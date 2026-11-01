package com.tewendelabs.investigator;

import java.util.*;
import java.time.LocalDate;
import java.sql.Connection;
import com.tewendelabs.investigator.investigation.InvestigationService.Create;

import org.junit.jupiter.api.*;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.CsvSource;
import org.junit.jupiter.params.provider.ValueSource;
import org.slf4j.LoggerFactory;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.ArgumentMatchers.anyList;
import static org.mockito.Mockito.when;
import static org.mockito.Mockito.reset;
import static org.mockito.Mockito.clearInvocations;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.times;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.any;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.mock.web.MockMultipartFile;
import org.springframework.ai.embedding.EmbeddingModel;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.testcontainers.containers.PostgreSQLContainer;
import org.testcontainers.utility.DockerImageName;
import com.tewendelabs.investigator.policy.*;
import com.tewendelabs.investigator.security.*;
import com.tewendelabs.investigator.ingestion.*;
import com.tewendelabs.investigator.api.ApiFailure;

@Tag("database")
@SpringBootTest(properties = {"app.worker.enabled=false", "app.investigation.worker-enabled=false", "meta.api.key=synthetic-test-marker", "app.embedding.verify-artifacts=false", "spring.ai.model.embedding=none", "app.embedding.revision=synthetic-test-v1"})
@AutoConfigureMockMvc(print = org.springframework.boot.webmvc.test.autoconfigure.MockMvcPrint.NONE)
class SecurityDatabaseTest {
    static final String OWNER_PASSWORD = UUID.randomUUID().toString(), APP_PASSWORD = UUID.randomUUID().toString();
    static final PostgreSQLContainer<?> POSTGRES = new PostgreSQLContainer<>(DockerImageName.parse("pgvector/pgvector:0.8.0-pg16").asCompatibleSubstituteFor("postgres"))
            .withDatabaseName("investigator_phase2_test").withUsername("postgres").withPassword(UUID.randomUUID().toString());
    static JdbcTemplate admin;

    @DynamicPropertySource
    static void database(DynamicPropertyRegistry props) throws Exception {
        POSTGRES.start();
        admin = new JdbcTemplate(new DriverManagerDataSource(POSTGRES.getJdbcUrl(), POSTGRES.getUsername(), POSTGRES.getPassword()));
        try (Connection c = admin.getDataSource().getConnection()) {
            try (var p = c.prepareStatement("select set_config('test.owner_password',?,false),set_config('test.app_password',?,false)")) {
                p.setString(1, OWNER_PASSWORD);
                p.setString(2, APP_PASSWORD);
                p.execute();
            }
            c.createStatement().execute("""
                    CREATE ROLE investigator_runtime NOLOGIN NOSUPERUSER NOBYPASSRLS;
                    DO $$ BEGIN
                      EXECUTE format('CREATE ROLE investigator_owner LOGIN NOSUPERUSER NOBYPASSRLS PASSWORD %L',current_setting('test.owner_password'));
                      EXECUTE format('CREATE ROLE investigator_app LOGIN NOSUPERUSER NOBYPASSRLS PASSWORD %L',current_setting('test.app_password'));
                    END $$;
                    GRANT investigator_runtime TO investigator_app;
                    ALTER DATABASE investigator_phase2_test OWNER TO investigator_owner;
                    ALTER SCHEMA public OWNER TO investigator_owner;
                    REVOKE CREATE ON SCHEMA public FROM PUBLIC;
                    CREATE EXTENSION vector;
                    CREATE EXTENSION pgcrypto;
                    """);
        } catch (Exception e) {
            throw new IllegalStateException("Isolated test database role initialization failed");
        }
        props.add("spring.datasource.url", POSTGRES::getJdbcUrl);
        props.add("spring.datasource.password", () -> APP_PASSWORD);
        props.add("spring.flyway.url", POSTGRES::getJdbcUrl);
        props.add("spring.flyway.password", () -> OWNER_PASSWORD);
        props.add("app.jwt.secret", () -> UUID.randomUUID().toString() + UUID.randomUUID());
        props.add("spring.datasource.hikari.maximum-pool-size", () -> 1);
    }

    @Autowired
    ScopedAccess scope;
    @Autowired
    PolicyService service;
    @Autowired
    PolicyRepository repository;
    @Autowired
    JdbcTemplate jdbc;
    @Autowired
    IngestionWorker worker;
    @Autowired
    PasswordEncoder passwords;
    @Autowired
    MockMvc mvc;
    @Autowired
    AuthController auth;
    @MockitoBean
    EmbeddingModel model;
    @MockitoBean
    com.tewendelabs.investigator.provider.MetaTransport metaTransport;
    @Autowired
    com.tewendelabs.investigator.investigation.InvestigationService investigationService;
    @Autowired
    com.tewendelabs.investigator.investigation.InvestigationWorker investigationWorker;
    UUID org, finance, hr, analyst, outsider, viewer;
    String loginPassword;

    @BeforeEach
    void setup() {
        admin.update("update demo_meta_budget set attempts=0,max_attempts=1000 where singleton");
        org = UUID.randomUUID();
        finance = UUID.randomUUID();
        hr = UUID.randomUUID();
        analyst = UUID.randomUUID();
        outsider = UUID.randomUUID();
        viewer = UUID.randomUUID();
        loginPassword = UUID.randomUUID().toString();
        admin.update("insert into organizations values(?,?)", org, "Synthetic organization");
        admin.update("insert into departments values(?,?,?),(?,?,?)", finance, org, "Finance", hr, org, "HR");
        for (UUID user : List.of(analyst, outsider, viewer))
            admin.update("insert into app_users(id,organization_id,email,password_hash) values(?,?,?,?)", user, org, user + "@test.invalid", passwords.encode(loginPassword));
        admin.update("insert into memberships values(?,?,?),(?,?,?),(?,?,?)", analyst, finance, "ANALYST", outsider, hr, "ANALYST", viewer, finance, "VIEWER");
        when(model.embed(anyList())).thenAnswer(inv -> {
            List<String> texts = inv.getArgument(0);
            return texts.stream().map(t -> {
                float[] v = new float[384];
                v[0] = 1;
                return v;
            }).toList();
        });
    }

    private PolicyService.Upload upload() throws Exception {
        return upload(analyst, finance);
    }

    private PolicyService.Upload upload(UUID actor, UUID department) throws Exception {
        return service.upload(actor, UUID.randomUUID(), null, department, "Incident policy", "POLICY", null, LocalDate.of(2026, 10, 26), "policy.pdf", PdfAndVectorTest.pdf("Report incidents in 24 hours."));
    }

    private void ingest(PolicyService.Upload result) {
        ingest(result, analyst);
    }

    private void ingest(PolicyService.Upload result, UUID actor) {
        // Claim this exact task without consuming tasks left by other tests.
        admin.update("update ingestion_tasks set created_at=now()-interval '1 year' where id=?", result.jobId());
        IngestionWorker.Lease lease = worker.claim();
        assertThat(lease.id()).isEqualTo(result.jobId());
        worker.process(lease);
        assertThat(service.job(actor, result.jobId()).get("status")).isEqualTo("COMPLETED");
    }

    @Test
    void deploymentChecksumsMatchActualFlywayHistory() throws Exception {
        var process = new ProcessBuilder("python3", "-B", "-c", """
                import pathlib,sys
                sys.path.insert(0,'scripts')
                from release_artifacts import flyway_checksum
                for p in sorted(pathlib.Path('src/main/resources/db/migration').glob('V*.sql')):
                    print(p.name + '\\t' + str(flyway_checksum(p.read_bytes())))
                """).redirectError(ProcessBuilder.Redirect.DISCARD).start();
        assertThat(process.waitFor(20, java.util.concurrent.TimeUnit.SECONDS)).isTrue();
        assertThat(process.exitValue()).isZero();
        var computed = process.inputReader().lines().map(line -> line.split("\\t"))
                .collect(java.util.stream.Collectors.toMap(parts -> parts[0], parts -> Integer.parseInt(parts[1])));
        var applied = admin.queryForList("select script,checksum,success from flyway_schema_history");
        assertThat(computed).hasSize(applied.size()).isNotEmpty();
        for (var row : applied) {
            assertThat(row.get("success")).isEqualTo(true);
            assertThat(computed.get(row.get("script"))).isEqualTo(row.get("checksum"));
        }
    }

    @Test
    void jdbcJpaAndConnectionReuseDenyOtherDepartment() throws Exception {
        var result = upload();
        assertThat(scope.as(analyst, () -> repository.findById(result.policyId()))).isPresent();
        assertThat(scope.as(outsider, () -> repository.findById(result.policyId()))).isEmpty();
        assertThat(scope.as(outsider, () -> jdbc.queryForList("select * from policy_versions"))).isEmpty();
        assertThat(jdbc.queryForList("select * from policies")).isEmpty(); // no actor after transaction
        assertThat(repository.findById(result.policyId())).isEmpty(); // JPA also has no actor
        assertThat(scope.as(viewer, () -> repository.findById(result.policyId()))).isPresent();
        assertThatThrownBy(() -> service.upload(viewer, UUID.randomUUID(), null, finance, "x", "POLICY", null, LocalDate.now(), "x.pdf", PdfAndVectorTest.pdf("x"))).hasMessage("NOT_FOUND");
    }

    @Test
    void workflowPreservesPdfPageEvidenceAndImmutableVersions() throws Exception {
        var initial = upload();
        ingest(initial);
        var evidence = service.search(analyst, initial.versionId(), "incident").getFirst();
        assertThat(evidence.get("page_number")).isEqualTo(1);
        assertThat(service.evidence(analyst, (UUID) evidence.get("id")).get("excerpt").toString()).contains("24 hours");
        var original = service.content(analyst, initial.policyId(), initial.versionId());
        assertThat(original).startsWith((byte) '%', (byte) 'P');
        var second = service.upload(analyst, UUID.randomUUID(), initial.policyId(), null, null, null, initial.versionId(), LocalDate.of(2026, 11, 1), "v2.pdf", PdfAndVectorTest.pdf("Report in 12 hours."));
        var history = service.versions(analyst, initial.policyId());
        assertThat(history).hasSize(2);
        assertThat(history.getFirst().get("job_id")).isEqualTo(initial.jobId());
        assertThat(history.getFirst().get("job_status")).isEqualTo("COMPLETED");
        assertThat(history.getLast().get("job_id")).isEqualTo(second.jobId());
        assertThat(service.content(analyst, initial.policyId(), initial.versionId())).isEqualTo(original);
        assertThatThrownBy(() -> scope.as(analyst, () -> jdbc.update("update policy_versions set filename='changed.pdf' where id=?", initial.versionId()))).isInstanceOf(RuntimeException.class);
        assertThatThrownBy(() -> service.evidence(outsider, (UUID) evidence.get("id"))).hasMessage("NOT_FOUND");
        assertThatThrownBy(() -> service.job(outsider, second.jobId())).hasMessage("NOT_FOUND");
    }

    @Test
    void revokedRequesterCannotIngestAndCannotReadPreviouslyCreatedContent() throws Exception {
        var initial = upload();
        admin.update("delete from memberships where user_id=?", analyst);
        admin.update("update ingestion_tasks set created_at=now()-interval '1 year' where id=?", initial.jobId());
        worker.process(worker.claim());
        assertThat(admin.queryForObject("select count(*) from chunks where version_id=?", Integer.class, initial.versionId())).isZero();
        assertThat(admin.queryForObject("select error_code from ingestion_tasks where id=?", String.class, initial.jobId())).isEqualTo("ACCESS_REVOKED");
        assertThatThrownBy(() -> service.content(analyst, initial.policyId(), initial.versionId())).hasMessage("NOT_FOUND");
    }

    @Test
    void explicitGrantWorksAndRevocationTakesEffectForJpaAndSql() throws Exception {
        var initial = upload();
        ingest(initial);
        admin.update("insert into policy_grants values(?,?,?)", initial.policyId(), hr, "READ");
        assertThat(service.get(outsider, initial.policyId()).getId()).isEqualTo(initial.policyId());
        assertThat(service.search(outsider, initial.versionId(), "incident")).isNotEmpty();
        assertThatThrownBy(() -> service.upload(outsider, UUID.randomUUID(), initial.policyId(), null, null, null, initial.versionId(), LocalDate.now(), "x.pdf", PdfAndVectorTest.pdf("x"))).hasMessage("NOT_FOUND");
        admin.update("delete from policy_grants where policy_id=?", initial.policyId());
        assertThatThrownBy(() -> service.get(outsider, initial.policyId())).hasMessage("NOT_FOUND");
        assertThatThrownBy(() -> service.search(outsider, initial.versionId(), "incident")).hasMessage("NOT_FOUND");
    }

    @Test
    void idempotencyAndLeaseRecoveryRejectDuplicatesAndStaleWorkers() throws Exception {
        UUID key = UUID.randomUUID();
        byte[] bytes = PdfAndVectorTest.pdf("same input");
        var first = service.upload(analyst, key, null, finance, "A", "POLICY", null, LocalDate.now(), "a.pdf", bytes);
        var replay = service.upload(analyst, key, null, finance, "A", "POLICY", null, LocalDate.now(), "a.pdf", bytes);
        assertThat(replay.versionId()).isEqualTo(first.versionId());
        assertThatThrownBy(() -> service.upload(analyst, key, null, finance, "B", "POLICY", null, LocalDate.now(), "a.pdf", bytes)).hasMessage("IDEMPOTENCY_CONFLICT");
        admin.update("update ingestion_tasks set created_at=now()-interval '1 year' where id=?", first.jobId());
        var stale = worker.claim();
        admin.update("update ingestion_tasks set lease_until=now()-interval '1 second' where id=?", first.jobId());
        var recovered = worker.claim();
        assertThat(recovered.token()).isNotEqualTo(stale.token());
        assertThat(jdbc.queryForObject("select finish_ingestion(?,?,null)", Boolean.class, stale.id(), stale.token())).isFalse();
        worker.process(recovered);
        assertThat(service.job(analyst, first.jobId()).get("status")).isEqualTo("COMPLETED");
    }

    @Test
    void realJwtAndHttpUploadEnforceCurrentAccountStatus() throws Exception {
        String token = (String) auth.login(new AuthController.Login(analyst + "@test.invalid", loginPassword)).get("token");
        mvc.perform(get("/api/auth/me").header("Authorization", "Bearer " + token)).andExpect(status().isOk());
        mvc.perform(multipart("/api/policies").file(new MockMultipartFile("file", "api.pdf", "application/pdf", PdfAndVectorTest.pdf("HTTP upload")))
                        .header("Authorization", "Bearer " + token).header("Idempotency-Key", UUID.randomUUID().toString())
                        .param("departmentId", finance.toString()).param("title", "API policy").param("effectiveDate", "2026-10-26"))
                .andExpect(status().isAccepted()).andExpect(jsonPath("$.jobId").exists());
        admin.update("update app_users set active=false where id=?", analyst);
        mvc.perform(get("/api/auth/me").header("Authorization", "Bearer " + token)).andExpect(status().isUnauthorized());
        mvc.perform(get("/api/policies")).andExpect(status().isUnauthorized());
    }

    @Test
    void runtimeCannotReadQueueCredentialsOrBypassImmutability() throws Exception {
        var initial = upload();
        assertThatThrownBy(() -> jdbc.queryForList("select * from app_users")).isInstanceOf(RuntimeException.class);
        assertThatThrownBy(() -> jdbc.queryForList("select * from ingestion_tasks")).isInstanceOf(RuntimeException.class);
        assertThatThrownBy(() -> scope.as(analyst, () -> jdbc.update("delete from policy_versions where id=?", initial.versionId()))).isInstanceOf(RuntimeException.class);
        assertThat(scope.as(outsider, () -> jdbc.queryForList("select * from policies"))).isEmpty();
    }

    @Test
    void unauthorizedSearchNeverReachesEmbeddingModel() throws Exception {
        var initial = upload();
        ingest(initial);
        clearInvocations(model);
        assertThatThrownBy(() -> service.search(outsider, initial.versionId(), "confidential")).hasMessage("NOT_FOUND");
        verifyNoInteractions(model);
    }

    @Test
    void revocationDuringEmbeddingRollsBackAllEvidence() throws Exception {
        var initial = upload();
        when(model.embed(anyList())).thenAnswer(inv -> {
            admin.update("delete from memberships where user_id=?", analyst);
            List<String> texts = inv.getArgument(0);
            return texts.stream().map(t -> {
                float[] v = new float[384];
                v[0] = 1;
                return v;
            }).toList();
        });
        admin.update("update ingestion_tasks set created_at=now()-interval '1 year' where id=?", initial.jobId());
        worker.process(worker.claim());
        assertThat(admin.queryForObject("select count(*) from chunks where version_id=?", Integer.class, initial.versionId())).isZero();
        assertThat(admin.queryForObject("select count(*) from document_pages where version_id=?", Integer.class, initial.versionId())).isZero();
        assertThat(admin.queryForObject("select error_code from ingestion_tasks where id=?", String.class, initial.jobId())).isEqualTo("ACCESS_REVOKED");
    }

    @Test
    void jpaWritesCannotCrossDepartmentBoundary() throws Exception {
        var initial = upload();
        assertThatThrownBy(() -> scope.as(outsider, () -> {
            repository.saveAndFlush(servicePolicy(initial.policyId()));
            return null;
        })).isInstanceOf(RuntimeException.class);
        assertThat(service.get(analyst, initial.policyId()).getDepartmentId()).isEqualTo(finance);
    }

    private Policy servicePolicy(UUID id) {
        // A detached entity deliberately constructed to test a hostile JPA write under another actor.
        try {
            var ctor = Policy.class.getDeclaredConstructor();
            ctor.setAccessible(true);
            Policy policy = ctor.newInstance();
            for (var pair : Map.<String, Object>of("id", id, "organizationId", org, "departmentId", finance, "title", "forged", "kind", "POLICY").entrySet()) {
                var field = Policy.class.getDeclaredField(pair.getKey());
                field.setAccessible(true);
                field.set(policy, pair.getValue());
            }
            return policy;
        } catch (ReflectiveOperationException e) {
            throw new IllegalStateException(e);
        }
    }

    @Test
    void deletedAccountCannotUseAnAlreadyIssuedJwt() throws Exception {
        String token = (String) auth.login(new AuthController.Login(outsider + "@test.invalid", loginPassword)).get("token");
        admin.update("delete from memberships where user_id=?", outsider);
        admin.update("delete from app_users where id=?", outsider);
        mvc.perform(get("/api/auth/me").header("Authorization", "Bearer " + token)).andExpect(status().isUnauthorized());
    }

    @Test
    void adminRoleAndMalformedCrossOrganizationGrantsDoNotBypassScope() throws Exception {
        var initial = upload();
        admin.update("update memberships set role='ADMIN' where user_id=?", outsider);
        assertThatThrownBy(() -> service.get(outsider, initial.policyId())).hasMessage("NOT_FOUND");
        UUID otherOrg = UUID.randomUUID(), otherDept = UUID.randomUUID();
        admin.update("insert into organizations values(?,?)", otherOrg, "Another synthetic organization");
        admin.update("insert into departments values(?,?,?)", otherDept, otherOrg, "Other department");
        admin.update("insert into memberships values(?,?,?)", outsider, otherDept, "ADMIN");
        admin.update("insert into policy_grants values(?,?,?)", initial.policyId(), otherDept, "WRITE");
        assertThatThrownBy(() -> service.get(outsider, initial.policyId())).hasMessage("NOT_FOUND");
    }

    @Test
    void forgedEvidenceCannotBeInsertedEvenByAnAuthorizedWriter() throws Exception {
        var initial = upload();
        float[] vector = new float[384];
        vector[0] = 1;
        assertThatThrownBy(() -> scope.as(analyst, () -> {
            jdbc.update("insert into document_pages(version_id,page_number,text) values(?,1,'source text')", initial.versionId());
            return jdbc.update("insert into chunks(id,version_id,page_number,start_offset,end_offset,content,embedding,embedding_revision) values(?,?,1,0,6,'forged',cast(? as vector),'synthetic-test-v1')",
                    UUID.randomUUID(), initial.versionId(), EmbeddingGateway.vectorLiteral(vector));
        })).hasRootCauseInstanceOf(org.postgresql.util.PSQLException.class);
        assertThat(admin.queryForObject("select count(*) from document_pages where version_id=?", Integer.class, initial.versionId())).isZero();
    }

    @Test
    void incompatibleEmbeddingRevisionCannotLookLikeAnEmptySearch() throws Exception {
        var initial = upload();
        ingest(initial);
        admin.update("update chunks set embedding_revision='old-model' where version_id=?", initial.versionId());
        assertThatThrownBy(() -> service.search(analyst, initial.versionId(), "incident")).hasMessage("EMBEDDING_REVISION_MISMATCH");
    }

    @Test
    void consentChangesRequireOwningDepartmentAdminInApiAndSql() throws Exception {
        var policy = upload();
        assertThatThrownBy(() -> investigationService.consent(analyst, policy.policyId(), true)).hasMessage("NOT_FOUND");
        assertThatThrownBy(() -> scope.as(analyst, () -> jdbc.update("update policies set external_processing_allowed=true where id=?", policy.policyId())))
                .hasRootCauseInstanceOf(org.postgresql.util.PSQLException.class);
        admin.update("update memberships set role='ADMIN' where user_id=? and department_id=?", analyst, finance);
        investigationService.consent(analyst, policy.policyId(), true);
        assertThat(scope.as(analyst, () -> jdbc.queryForObject("select external_processing_allowed from policies where id=?", Boolean.class, policy.policyId()))).isTrue();
    }

    @Test void totalDeadlineIsConfigurableAndNotResetDuringRecovery() throws Exception {
        var fixture=investigationFixture();
        admin.update("update investigation_jobs set created_at=now()-interval '1 year' where id=?",fixture.id());
        var first=jdbc.queryForList("select * from claim_investigation(30)").getFirst();
        assertThat(first.get("id")).isEqualTo(fixture.id());
        var deadline=((java.sql.Timestamp)first.get("deadline_at")).toInstant();
        assertThat(java.time.Duration.between(java.time.Instant.now(),deadline).toSeconds()).isBetween(27L,30L);
        admin.update("update investigation_jobs set lease_until=now()-interval '1 second' where id=?",fixture.id());
        var recovered=investigationLease(fixture.id());
        assertThat(recovered.deadline()).isEqualTo(deadline);
        admin.update("update investigation_jobs set deadline_at=now()-interval '1 second',lease_until=now()-interval '1 second' where id=?",fixture.id());
        investigationWorker.claim();
        assertThat(investigationService.progress(analyst,fixture.id()).get("state")).isEqualTo("PARTIAL");
        assertThat(investigationService.progress(analyst,fixture.id()).get("error_code")).isEqualTo("RECOVERY_OR_BUDGET_EXHAUSTED");
    }

    record InvestigationFixture(UUID id, UUID baseline, UUID replacement, UUID procedure) {
    }

    private InvestigationFixture investigationFixture() throws Exception {
        return investigationFixture(analyst, finance);
    }

    private InvestigationFixture investigationFixture(UUID actor, UUID department) throws Exception {
        var baseline = upload(actor, department);
        ingest(baseline, actor);
        var replacement = service.upload(actor, UUID.randomUUID(), baseline.policyId(), null, null, null, baseline.versionId(), LocalDate.of(2026, 10, 27), "new.pdf", PdfAndVectorTest.pdf("Training is mandatory before sensitive-system access."));
        ingest(replacement, actor);
        var procedure = service.upload(actor, UUID.randomUUID(), null, department, "HR access", "PROCEDURE", null, LocalDate.of(2026, 10, 26), "hr.pdf", PdfAndVectorTest.pdf("Access on day one; training within 30 days."));
        ingest(procedure, actor);
        admin.update("update policies set external_processing_allowed=true where id in (?,?)", baseline.policyId(), procedure.policyId());
        UUID id = investigationService.create(actor, UUID.randomUUID(), new com.tewendelabs.investigator.investigation.InvestigationService.Create(baseline.versionId(), replacement.versionId(), List.of(procedure.versionId()), LocalDate.of(2026, 10, 27)));
        return new InvestigationFixture(id, baseline.versionId(), replacement.versionId(), procedure.versionId());
    }

    private com.tewendelabs.investigator.investigation.InvestigationWorker.Lease investigationLease(UUID id) {
        admin.update("update investigation_jobs set created_at=now()-interval '1 year' where id=?", id);
        var lease = investigationWorker.claim();
        assertThat(lease.id()).isEqualTo(id);
        return lease;
    }

    private com.tewendelabs.investigator.provider.MetaTransport.Reply fixtureReply(String payload, InvestigationFixture fixture, boolean complete, boolean fabricated) {
        var json = com.tewendelabs.investigator.investigation.JsonContract.JSON;
        var envelope = json.readTree(payload);
        var input = json.readTree(envelope.path("messages").get(1).path("content").asString());
        List<Map<String, Object>> refs = new ArrayList<>();
        for (var src : input.path("sources"))
            refs.add(Map.of("sourceId", src.path("sourceId").asString(), "quote", src.path("excerpt").asString()));
        Object content;
        if (envelope.path("response_format").path("json_schema").path("name").asString().equals(
                com.tewendelabs.investigator.investigation.InvestigationSchemas.EXTRACTION.replace('-', '_'))) {
            var ref = refs.getFirst();
            var req = com.tewendelabs.investigator.investigation.StructuredValidationTest.requirement(fabricated ? UUID.randomUUID().toString() : (String) ref.get("sourceId"), (String) ref.get("quote"));
            List<String> sourceIds = refs.stream().map(r -> (String) r.get("sourceId")).toList();
            content = Map.of("requirements", List.of(req), "processedSourceIds", sourceIds, "complete", complete, "limitations", List.of());
        } else {
            String task = input.path("task").asString();
            var extracted = json.readTree(task.substring(task.indexOf("Extracted requirements by version: ") + 34));
            String old = extracted.path(fixture.baseline().toString()).path("requirements").get(0).path("id").asString();
            String current = extracted.path(fixture.replacement().toString()).path("requirements").get(0).path("id").asString();
            String proc = extracted.path(fixture.procedure().toString()).path("requirements").get(0).path("id").asString();
            var change = Map.of("baselineRequirementId", old, "replacementRequirementId", current, "changeType", "MODIFIED", "reason", "Changed timing", "sourceReferences", refs);
            var relevant = new ArrayList<Map<String, Object>>();
            for (var src : input.path("sources"))
                if (!src.path("versionId").asString().equals(fixture.baseline().toString()))
                    relevant.add(Map.of("sourceId", src.path("sourceId").asString(), "quote", src.path("excerpt").asString()));
            var assessment = Map.of("policyRequirementId", current, "procedureVersionId", fixture.procedure().toString(), "relatedProcedureRequirementIds", List.of(proc), "classification", "CONTRADICTION", "severity", "HIGH", "rationale", "Incompatible timing", "suggestedAction", "Review procedure", "scopeExplanation", "Same sensitive systems", "sourceReferences", relevant);
            content = Map.of("changes", List.of(change), "assessments", List.of(assessment), "complete", complete, "limitations", List.of());
        }
        return new com.tewendelabs.investigator.provider.MetaTransport.Reply(200, com.tewendelabs.investigator.investigation.JsonContract.encode(Map.of("model", "muse-spark-1.3", "choices", List.of(Map.of("finish_reason", "stop", "message", Map.of("content", com.tewendelabs.investigator.investigation.JsonContract.encode(content)))), "usage", Map.of("prompt_tokens", 5, "completion_tokens", 5, "total_tokens", 10))));
    }

    private void successfulTransport(InvestigationFixture fixture) {
        reset(metaTransport);
        when(metaTransport.send(anyString(), anyString(), any()))
                .thenAnswer(inv -> fixtureReply(inv.getArgument(1), fixture, true, false));
    }

    @Test
    void investigationCompletesWithValidatedRequirementsAndPendingHumanReview() throws Exception {
        var fixture = investigationFixture();
        successfulTransport(fixture);
        investigationWorker.process(investigationLease(fixture.id()));
        assertThat(investigationService.progress(analyst, fixture.id()).get("state")).isEqualTo("COMPLETED");
        assertThat(investigationService.extractions(analyst, fixture.id())).hasSize(3);
        var payload = (tools.jackson.databind.JsonNode) investigationService.findings(analyst, fixture.id()).get("payload");
        assertThat(payload.path("assessments").get(0).path("reviewStatus").asString()).isEqualTo("PENDING_REVIEW");
        assertThatThrownBy(() -> investigationService.findings(outsider, fixture.id())).hasMessage("NOT_FOUND");
    }

    @Test
    void fabricatedCitationFailsWithoutPublishingFindings() throws Exception {
        var fixture = investigationFixture();
        when(metaTransport.send(anyString(), anyString(), any())).thenAnswer(inv -> fixtureReply(inv.getArgument(1), fixture, true, true));
        investigationWorker.process(investigationLease(fixture.id()));
        assertThat(investigationService.progress(analyst, fixture.id()).get("error_code")).isEqualTo("UNVERIFIABLE_SOURCE_REFERENCE");
        assertThat(investigationService.extractions(analyst, fixture.id())).isEmpty();
        assertThat(investigationService.findings(analyst, fixture.id()).get("complete")).isEqualTo(false);
    }

    @ParameterizedTest
    @CsvSource({"false, INVALID_FORMAT", "true, INVALID_FORMAT", "false, INVALID_CALENDAR_DATE", "true, INVALID_CALENDAR_DATE"})
    void invalidDateIsMeteredWithoutRetryAndPreservesOnlyEarlierCheckpoints(boolean afterCheckpoint, String reason) throws Exception {
        var fixture = investigationFixture();
        var lease = investigationLease(fixture.id());
        int rejectedCall = afterCheckpoint ? 2 : 1;
        String invalidDate = reason.equals("INVALID_FORMAT") ? "synthetic-private-date\nforged=true" : "2025-02-29";
        var sent = new java.util.concurrent.atomic.AtomicInteger();
        var requests = new ArrayList<String>();
        when(metaTransport.send(anyString(), anyString(), any())).thenAnswer(inv -> {
            String request = inv.getArgument(1);
            requests.add(request);
            var reply = fixtureReply(request, fixture, true, false);
            if (sent.incrementAndGet() != rejectedCall) return reply;
            var envelope = com.tewendelabs.investigator.investigation.JsonContract.parse(reply.body());
            var message = (tools.jackson.databind.node.ObjectNode) envelope.path("choices").get(0).path("message");
            var content = com.tewendelabs.investigator.investigation.JsonContract.parse(message.path("content").asString());
            var requirements = (tools.jackson.databind.node.ArrayNode) content.path("requirements");
            var invalid = (tools.jackson.databind.node.ObjectNode) requirements.get(0).deepCopy();
            invalid.put("effectiveDate", invalidDate);
            invalid.set("unknownFields", com.tewendelabs.investigator.investigation.JsonContract.tree(List.of("condition", "exceptions")));
            requirements.add(invalid); // Index 1: the first requirement remains valid and unknown.
            message.put("content", com.tewendelabs.investigator.investigation.JsonContract.encode(content));
            return new com.tewendelabs.investigator.provider.MetaTransport.Reply(200,
                    com.tewendelabs.investigator.investigation.JsonContract.encode(envelope));
        });
        var logger = (ch.qos.logback.classic.Logger) LoggerFactory.getLogger(
                com.tewendelabs.investigator.investigation.InvestigationWorker.class);
        var previousLevel = logger.getLevel();
        var logs = new ch.qos.logback.core.read.ListAppender<ch.qos.logback.classic.spi.ILoggingEvent>();
        logs.start();
        logger.setLevel(ch.qos.logback.classic.Level.INFO);
        logger.addAppender(logs);
        try {
            investigationWorker.process(lease);
            assertThat(investigationService.progress(analyst, fixture.id()))
                    .containsEntry("state", afterCheckpoint ? "PARTIAL" : "FAILED")
                    .containsEntry("stage", "STOPPED").containsEntry("error_code", "INVALID_EFFECTIVE_DATE")
                    .containsEntry("calls", rejectedCall).containsEntry("metered_calls", rejectedCall)
                    .containsEntry("prompt_tokens", 5 * rejectedCall).containsEntry("completion_tokens", 5 * rejectedCall);
            verify(metaTransport, times(rejectedCall)).send(anyString(), anyString(), any());
            var extractions = investigationService.extractions(analyst, fixture.id());
            assertThat(extractions).hasSize(afterCheckpoint ? 1 : 0);
            if (afterCheckpoint) {
                assertThat(extractions.getFirst().get("version_id")).isEqualTo(fixture.baseline());
                var saved = (tools.jackson.databind.JsonNode) extractions.getFirst().get("payload");
                assertThat(saved.path("requirements").get(0).path("effectiveDate").isNull()).isTrue();
            }
            assertThat(admin.queryForObject("select count(*) from investigation_assessments where investigation_id=?", Integer.class, fixture.id())).isZero();
            assertThat(investigationService.findings(analyst, fixture.id()).get("complete")).isEqualTo(false);
            var events = logs.list.stream().filter(event -> event.getFormattedMessage().startsWith("effective_date_validation_rejected ")).toList();
            assertThat(events).hasSize(1);
            assertThat(events.getFirst().getFormattedMessage()).isEqualTo("effective_date_validation_rejected reason=" + reason
                    + " stage=" + (afterCheckpoint ? "EXTRACTING_REPLACEMENT" : "EXTRACTING_BASELINE")
                    + " investigation_id=" + fixture.id()
                    + " version_id=" + (afterCheckpoint ? fixture.replacement() : fixture.baseline()) + " requirement_index=1");
            for (var event : logs.list) {
                assertThat(event.getThrowableProxy()).isNull();
                assertThat(event.getFormattedMessage()).doesNotContain(invalidDate, "synthetic-private-date", "forged=true",
                        lease.token().toString(), lease.actor().toString(), "Report incidents", "Training is mandatory");
            }
            for (String request : requests) {
                var payload = com.tewendelabs.investigator.investigation.JsonContract.parse(request);
                var input = com.tewendelabs.investigator.investigation.JsonContract.parse(payload.path("messages").get(1).path("content").asString());
                assertThat(input.path("task").asString()).contains("never an effective-date fallback", "Never substitute metadata or the analysis date")
                        .doesNotContain("Document effective date:");
            }
        } finally {
            logger.detachAppender(logs);
            logs.stop();
            logger.setLevel(previousLevel);
        }
    }

    @ParameterizedTest
    @CsvSource({"UNKNOWN_SOURCE_ID,false", "BLANK_QUOTE,false", "NONLITERAL_QUOTE,false",
            "UNKNOWN_SOURCE_ID,true", "BLANK_QUOTE,true", "NONLITERAL_QUOTE,true"})
    void citationDiagnosticsPreserveStatesAndCheckpointsWithoutLoggingEvidence(String reason, boolean afterCheckpoint) throws Exception {
        var fixture = investigationFixture();
        var lease = investigationLease(fixture.id());
        var sent = new java.util.concurrent.atomic.AtomicInteger();
        when(metaTransport.send(anyString(), anyString(), any())).thenAnswer(inv -> {
            var reply = fixtureReply(inv.getArgument(1), fixture, true, false);
            if (sent.incrementAndGet() != (afterCheckpoint ? 2 : 1)) return reply;
            var envelope = com.tewendelabs.investigator.investigation.JsonContract.parse(reply.body());
            var message = (tools.jackson.databind.node.ObjectNode) envelope.path("choices").path(0).path("message");
            var content = com.tewendelabs.investigator.investigation.JsonContract.parse(message.path("content").asString());
            var reference = (tools.jackson.databind.node.ObjectNode) content.path("requirements").path(0).path("sourceReferences").path(0);
            switch (reason) {
                case "UNKNOWN_SOURCE_ID" -> reference.put("sourceId", "synthetic-private-source-id\nforged=true");
                case "BLANK_QUOTE" -> reference.put("quote", " \t\n");
                case "NONLITERAL_QUOTE" -> reference.put("quote", "synthetic-private-quote\nforged=true");
                default -> throw new AssertionError("Unknown synthetic rejection reason");
            }
            message.put("content", com.tewendelabs.investigator.investigation.JsonContract.encode(content));
            return new com.tewendelabs.investigator.provider.MetaTransport.Reply(200,
                    com.tewendelabs.investigator.investigation.JsonContract.encode(envelope));
        });
        var logger = (ch.qos.logback.classic.Logger) LoggerFactory.getLogger(
                com.tewendelabs.investigator.investigation.InvestigationWorker.class);
        var previousLevel = logger.getLevel();
        var logs = new ch.qos.logback.core.read.ListAppender<ch.qos.logback.classic.spi.ILoggingEvent>();
        logs.start();
        logger.setLevel(ch.qos.logback.classic.Level.INFO);
        logger.addAppender(logs);
        try {
            investigationWorker.process(lease);
            var progress = investigationService.progress(analyst, fixture.id());
            assertThat(progress.get("state")).isEqualTo(afterCheckpoint ? "PARTIAL" : "FAILED");
            assertThat(progress.get("stage")).isEqualTo("STOPPED");
            assertThat(progress.get("error_code")).isEqualTo("UNVERIFIABLE_SOURCE_REFERENCE");
            assertThat(progress.get("calls")).isEqualTo(afterCheckpoint ? 2 : 1);
            assertThat(progress.get("metered_calls")).isEqualTo(afterCheckpoint ? 2 : 1);
            assertThat(sent.get()).isEqualTo(afterCheckpoint ? 2 : 1);
            var extractions = investigationService.extractions(analyst, fixture.id());
            assertThat(extractions).hasSize(afterCheckpoint ? 1 : 0);
            if (afterCheckpoint) {
                assertThat(extractions.getFirst().get("version_id")).isEqualTo(fixture.baseline());
                var saved = (tools.jackson.databind.JsonNode) extractions.getFirst().get("payload");
                assertThat(saved.path("complete").asBoolean()).isTrue();
                assertThat(saved.path("requirements").size()).isEqualTo(1);
            }
            assertThat(admin.queryForObject("select count(*) from investigation_assessments where investigation_id=?", Integer.class, fixture.id())).isZero();
            assertThat(investigationService.findings(analyst, fixture.id()).get("complete")).isEqualTo(false);
            var events = logs.list.stream().filter(event -> event.getFormattedMessage().startsWith("citation_validation_rejected ")).toList();
            assertThat(events).hasSize(1);
            assertThat(events.getFirst().getFormattedMessage()).isEqualTo("citation_validation_rejected reason=" + reason
                    + " stage=" + (afterCheckpoint ? "EXTRACTING_REPLACEMENT" : "EXTRACTING_BASELINE")
                    + " investigation_id=" + fixture.id());
            assertThat(events.getFirst().getThrowableProxy()).isNull();
            for (var event : logs.list) {
                assertThat(event.getFormattedMessage()).doesNotContain("synthetic-private-source-id", "synthetic-private-quote",
                        "forged=true", lease.token().toString(), lease.actor().toString(),
                        fixture.baseline().toString(), fixture.replacement().toString(), fixture.procedure().toString(),
                        "Report incidents", "Training is mandatory", "Access on day one");
            }
        } finally {
            logger.detachAppender(logs);
            logs.stop();
            logger.setLevel(previousLevel);
        }
    }

    @Test
    void inaccessibleExistingCitationIsRejected() throws Exception {
        var fixture = investigationFixture();
        var hidden = service.upload(outsider, UUID.randomUUID(), null, hr, "Hidden synthetic procedure", "PROCEDURE", null, LocalDate.of(2026, 10, 26), "hidden.pdf", PdfAndVectorTest.pdf("Private synthetic requirement."));
        admin.update("update ingestion_tasks set created_at=now()-interval '1 year' where id=?", hidden.jobId());
        var hiddenLease = worker.claim();
        assertThat(hiddenLease.id()).isEqualTo(hidden.jobId());
        worker.process(hiddenLease);
        assertThat(service.job(outsider, hidden.jobId()).get("status")).isEqualTo("COMPLETED");
        UUID hiddenSource = admin.queryForObject("select id from chunks where version_id=? limit 1", UUID.class, hidden.versionId());
        when(metaTransport.send(anyString(), anyString(), any())).thenAnswer(inv -> {
            var reply = fixtureReply(inv.getArgument(1), fixture, true, false);
            var envelope = com.tewendelabs.investigator.investigation.JsonContract.parse(reply.body());
            var message = (tools.jackson.databind.node.ObjectNode) envelope.path("choices").get(0).path("message");
            var content = com.tewendelabs.investigator.investigation.JsonContract.parse(message.path("content").asString());
            ((tools.jackson.databind.node.ObjectNode) content.path("requirements").get(0).path("sourceReferences").get(0)).put("sourceId", hiddenSource.toString());
            message.put("content", com.tewendelabs.investigator.investigation.JsonContract.encode(content));
            return new com.tewendelabs.investigator.provider.MetaTransport.Reply(200, com.tewendelabs.investigator.investigation.JsonContract.encode(envelope));
        });
        investigationWorker.process(investigationLease(fixture.id()));
        assertThat(investigationService.progress(analyst, fixture.id()).get("error_code")).isEqualTo("UNVERIFIABLE_SOURCE_REFERENCE");
        assertThat(investigationService.extractions(analyst, fixture.id())).isEmpty();
    }

    @Test
    void malformedProviderOutputAndPermanentAuthenticationFailureDoNotRetry() throws Exception {
        var malformed = investigationFixture();
        when(metaTransport.send(anyString(), anyString(), any())).thenReturn(new com.tewendelabs.investigator.provider.MetaTransport.Reply(200, "not-json"));
        investigationWorker.process(investigationLease(malformed.id()));
        assertThat(investigationService.progress(analyst, malformed.id()).get("calls")).isEqualTo(1);
        assertThat(investigationService.findings(analyst, malformed.id()).get("complete")).isEqualTo(false);
        var denied = investigationFixture();
        reset(metaTransport);
        when(metaTransport.send(anyString(), anyString(), any())).thenReturn(new com.tewendelabs.investigator.provider.MetaTransport.Reply(401, ""));
        investigationWorker.process(investigationLease(denied.id()));
        assertThat(investigationService.progress(analyst, denied.id()).get("calls")).isEqualTo(1);
        assertThat(investigationService.progress(analyst, denied.id()).get("error_code")).isEqualTo("PROVIDER_AUTHENTICATION_FAILED");
    }

    @Test
    void consentRevokedDuringSuccessfulCallPreventsResultPersistence() throws Exception {
        var fixture = investigationFixture();
        when(metaTransport.send(anyString(), anyString(), any())).thenAnswer(inv -> {
            var reply = fixtureReply(inv.getArgument(1), fixture, true, false);
            admin.update("update policies set external_processing_allowed=false where id=(select policy_id from policy_versions where id=?)", fixture.replacement());
            return reply;
        });
        investigationWorker.process(investigationLease(fixture.id()));
        assertThat(investigationService.progress(analyst, fixture.id()).get("error_code")).isEqualTo("ACCESS_CONSENT_OR_LEASE_REVOKED");
        assertThat(investigationService.extractions(analyst, fixture.id())).isEmpty();
    }

    @Test
    void incompleteExtractionIsPartialAndNeverNoConflict() throws Exception {
        var fixture = investigationFixture();
        when(metaTransport.send(anyString(), anyString(), any())).thenAnswer(inv -> fixtureReply(inv.getArgument(1), fixture, false, false));
        investigationWorker.process(investigationLease(fixture.id()));
        assertThat(investigationService.progress(analyst, fixture.id()).get("state")).isEqualTo("PARTIAL");
        assertThat(investigationService.progress(analyst, fixture.id()).get("error_code")).isEqualTo("INCOMPLETE_EXTRACTION");
        assertThat(investigationService.findings(analyst, fixture.id()).get("assessments")).isEqualTo(List.of());
    }

    @Test
    void providerTimeoutRetriesAreBoundedAndConsentWithdrawalStopsDispatch() throws Exception {
        var fixture = investigationFixture();
        when(metaTransport.send(anyString(), anyString(), any())).thenThrow(new ApiFailure(504, "PROVIDER_TIMEOUT"));
        investigationWorker.process(investigationLease(fixture.id()));
        assertThat(investigationService.progress(analyst, fixture.id()).get("calls")).isEqualTo(3);
        assertThat(investigationService.progress(analyst, fixture.id()).get("error_code")).isEqualTo("PROVIDER_TIMEOUT");
        var denied = investigationFixture();
        clearInvocations(metaTransport);
        admin.update("update policies set external_processing_allowed=false where id=(select policy_id from policy_versions where id=?)", denied.replacement());
        investigationWorker.process(investigationLease(denied.id()));
        verifyNoInteractions(metaTransport);
        assertThat(investigationService.progress(analyst, denied.id()).get("state")).isEqualTo("FAILED");
    }

    @Test
    void permissionRevocationBetweenRetryAttemptsStopsPayloads() throws Exception {
        var fixture = investigationFixture();
        java.util.concurrent.atomic.AtomicInteger sent = new java.util.concurrent.atomic.AtomicInteger();
        when(metaTransport.send(anyString(), anyString(), any())).thenAnswer(inv -> {
            sent.incrementAndGet();
            admin.update("delete from memberships where user_id=?", analyst);
            throw new ApiFailure(503, "PROVIDER_UNAVAILABLE");
        });
        investigationWorker.process(investigationLease(fixture.id()));
        assertThat(sent.get()).isEqualTo(1);
        assertThat(admin.queryForObject("select count(*) from requirement_extractions where investigation_id=?", Integer.class, fixture.id())).isZero();
        assertThatThrownBy(() -> investigationService.progress(analyst, fixture.id())).hasMessage("NOT_FOUND");
    }

    @ParameterizedTest
    @ValueSource(booleans = {false, true})
    void restartRecoveryReusesExtractionCheckpointAndFencesStaleLease(boolean legacy) throws Exception {
        var fixture = investigationFixture();
        demoProfile(analyst, finance);
        java.util.concurrent.atomic.AtomicInteger sent = new java.util.concurrent.atomic.AtomicInteger();
        when(metaTransport.send(anyString(), anyString(), any())).thenAnswer(inv -> {
            if (sent.incrementAndGet() == 2) throw new AssertionError("simulated process crash");
            return fixtureReply(inv.getArgument(1), fixture, true, false);
        });
        var stale = investigationLease(fixture.id());
        assertThatThrownBy(() -> investigationWorker.process(stale)).isInstanceOf(AssertionError.class);
        assertThat(investigationService.extractions(analyst, fixture.id())).hasSize(1);
        if (legacy) admin.update("update requirement_extractions set prompt_version='policy-investigator-2026-10-27-v1',schema_version='requirements-v1' where investigation_id=?", fixture.id());
        var checkpoint = admin.queryForMap("select payload::text,source_hash,model,prompt_version,schema_version from requirement_extractions where investigation_id=?", fixture.id());
        admin.update("update investigation_jobs set lease_until=now()-interval '1 second' where id=?", fixture.id());
        var recovered = investigationLease(fixture.id());
        successfulTransport(fixture);
        investigationWorker.process(recovered);
        assertThat(investigationService.progress(analyst, fixture.id()).get("state")).isEqualTo("COMPLETED");
        assertThat(jdbc.queryForObject("select finish_investigation(?,?,'FAILED','STALE')", Boolean.class, stale.id(), stale.token())).isFalse();
        assertThat(investigationService.progress(analyst, fixture.id()).get("calls")).isEqualTo(5);
        assertThat(admin.queryForObject("select meta_attempts from demo_access where user_id=?", Long.class, analyst)).isEqualTo(5);
        assertThat(admin.queryForObject("select attempts from demo_meta_budget", Long.class)).isEqualTo(5);
        assertThat(admin.queryForMap("select payload::text,source_hash,model,prompt_version,schema_version from requirement_extractions where investigation_id=? and version_id=?", fixture.id(), fixture.baseline())).isEqualTo(checkpoint);
        var findings = (tools.jackson.databind.JsonNode) investigationService.findings(analyst, fixture.id()).get("payload");
        assertThat(findings.path("complete").asBoolean()).isTrue();
    }

    private String token(UUID actor) {
        return (String) auth.login(new AuthController.Login(actor + "@test.invalid", loginPassword)).get("token");
    }

    @Autowired
    com.tewendelabs.investigator.investigation.InvestigationDashboardService dashboard;

    @Test
    void graphUsesPersistedRequirementsAndVerifiedEvidenceAndDeniesRevocation() throws Exception {
        var fixture = investigationFixture();
        assertThat(dashboard.graph(analyst, fixture.id()).complete()).isFalse();
        assertThat(dashboard.graph(analyst, fixture.id()).nodes()).hasSize(3);
        successfulTransport(fixture);
        investigationWorker.process(investigationLease(fixture.id()));
        clearInvocations(metaTransport, model);
        var graph = dashboard.graph(analyst, fixture.id());
        verifyNoInteractions(metaTransport, model);
        assertThat(graph.complete()).isTrue();
        assertThat(graph.nodes()).hasSize(7);
        assertThat(graph.edges()).allSatisfy(e -> {
            assertThat(graph.nodes()).anyMatch(n -> n.id().equals(e.source()));
            assertThat(graph.nodes()).anyMatch(n -> n.id().equals(e.target()));
        });
        assertThat(graph.edges()).anyMatch(e -> e.type().equals("AFFECTS"));
        assertThatThrownBy(() -> dashboard.graph(outsider, fixture.id())).hasMessage("NOT_FOUND");
        mvc.perform(get("/api/investigations/" + fixture.id() + "/graph").header("Authorization", "Bearer " + token(analyst)))
                .andExpect(status().isOk()).andExpect(jsonPath("$.nodes.length()").value(7));
        admin.update("delete from memberships where user_id=?", analyst);
        assertThatThrownBy(() -> dashboard.graph(analyst, fixture.id())).hasMessage("NOT_FOUND");
    }

    @Test
    void reviewHistoryPreservesAiOutputRequiresReviewerAndCurrentDocumentAccess() throws Exception {
        var fixture = investigationFixture();
        successfulTransport(fixture);
        investigationWorker.process(investigationLease(fixture.id()));
        var original = (tools.jackson.databind.JsonNode) investigationService.findings(analyst, fixture.id()).get("payload");
        UUID finding = UUID.fromString(original.path("assessments").get(0).path("id").asString());
        var confirm = new com.tewendelabs.investigator.investigation.InvestigationDashboardService.ReviewRequest(
                com.tewendelabs.investigator.investigation.InvestigationDashboardService.ReviewAction.CONFIRM, "Checked source timing");
        assertThat(investigationService.findings(analyst, fixture.id()).get("canReview")).isEqualTo(false);
        assertThatThrownBy(() -> dashboard.review(analyst, fixture.id(), finding, confirm)).hasMessage("REVIEW_PERMISSION_REQUIRED");
        assertThatThrownBy(() -> scope.as(analyst, () -> jdbc.update(
                "insert into finding_reviews(id,investigation_id,finding_id,reviewer_id,action) values(?,?,?,?,'CONFIRM')",
                UUID.randomUUID(), fixture.id(), finding, analyst))).isInstanceOf(RuntimeException.class);
        admin.update("update memberships set role='REVIEWER' where user_id=? and department_id=?", analyst, finance);
        var state = dashboard.review(analyst, fixture.id(), finding, confirm);
        assertThat(state.status()).isEqualTo("CONFIRMED");
        assertThat(state.history().getFirst().reviewerId()).isEqualTo(analyst);
        assertThat(state.history().getFirst().createdAt()).isNotNull();
        String reviewRoute = "/api/investigations/" + fixture.id() + "/findings/" + finding + "/reviews";
        mvc.perform(post(reviewRoute).header("Authorization", "Bearer " + token(analyst)).contentType("application/json")
                .content("{\"action\":\"ADD_NOTE\",\"note\":\"Source owner contacted\"}"))
                .andExpect(status().isOk()).andExpect(jsonPath("$.status").value("CONFIRMED"))
                .andExpect(jsonPath("$.history.length()").value(2));
        var dismissed = dashboard.review(analyst, fixture.id(), finding,
                new com.tewendelabs.investigator.investigation.InvestigationDashboardService.ReviewRequest(
                        com.tewendelabs.investigator.investigation.InvestigationDashboardService.ReviewAction.DISMISS, "Approved exception"));
        assertThat(dismissed.status()).isEqualTo("DISMISSED");
        assertThat(dismissed.history()).hasSize(3);
        assertThat(investigationService.findings(analyst, fixture.id()).get("payload")).isEqualTo(original);
        assertThatThrownBy(() -> scope.as(analyst, () -> jdbc.update("delete from finding_reviews where investigation_id=?", fixture.id())))
                .isInstanceOf(RuntimeException.class);
        assertThatThrownBy(() -> scope.as(analyst, () -> jdbc.update("update finding_reviews set note='changed' where investigation_id=?", fixture.id())))
                .isInstanceOf(RuntimeException.class);
        assertThatThrownBy(() -> dashboard.review(analyst, fixture.id(), UUID.randomUUID(), confirm)).hasMessage("NOT_FOUND");
        assertThatThrownBy(() -> scope.as(analyst, () -> jdbc.update(
                "insert into finding_reviews(id,investigation_id,finding_id,reviewer_id,action) values(?,?,?,?,'CONFIRM')",
                UUID.randomUUID(), fixture.id(), UUID.randomUUID(), analyst))).isInstanceOf(RuntimeException.class);
        assertThatThrownBy(() -> dashboard.review(outsider, fixture.id(), finding, confirm)).hasMessage("NOT_FOUND");
        admin.update("insert into policy_grants select distinct policy_id,?,'READ' from policy_versions where id in (?,?,?)", hr, fixture.baseline(), fixture.replacement(), fixture.procedure());
        admin.update("update memberships set role='REVIEWER' where user_id=?", outsider);
        assertThat(investigationService.findings(outsider, fixture.id()).get("canReview")).isEqualTo(false);
        assertThatThrownBy(() -> dashboard.review(outsider, fixture.id(), finding, confirm)).hasMessage("REVIEW_PERMISSION_REQUIRED");
        admin.update("delete from policy_grants where department_id=?", hr);
        assertThatThrownBy(() -> dashboard.graph(outsider, fixture.id())).hasMessage("NOT_FOUND");
        admin.update("update memberships set role='VIEWER' where user_id=?", analyst);
        assertThatThrownBy(() -> dashboard.review(analyst, fixture.id(), finding, confirm)).hasMessage("REVIEW_PERMISSION_REQUIRED");
        assertThat(investigationService.findings(analyst, fixture.id()).get("reviews")).asList().hasSize(1);
        admin.update("delete from memberships where user_id=?", analyst);
        assertThatThrownBy(() -> dashboard.review(analyst, fixture.id(), finding, confirm)).hasMessage("NOT_FOUND");
        assertThat(scope.as(outsider, () -> jdbc.queryForList("select * from finding_reviews where investigation_id=?", fixture.id()))).isEmpty();
    }

    @Test
    void reviewRejectsInvalidInputAndGraphsRejectTamperedPersistedCitations() throws Exception {
        var fixture = investigationFixture();
        successfulTransport(fixture);
        investigationWorker.process(investigationLease(fixture.id()));
        var original = (tools.jackson.databind.JsonNode) investigationService.findings(analyst, fixture.id()).get("payload");
        UUID finding = UUID.fromString(original.path("assessments").get(0).path("id").asString());
        var invalid = new com.tewendelabs.investigator.investigation.InvestigationDashboardService.ReviewRequest(
                com.tewendelabs.investigator.investigation.InvestigationDashboardService.ReviewAction.ADD_NOTE, " ");
        assertThatThrownBy(() -> dashboard.review(analyst, fixture.id(), finding, invalid)).hasMessage("INVALID_REVIEW");
        mvc.perform(post("/api/investigations/" + fixture.id() + "/findings/" + finding + "/reviews")
                .header("Authorization", "Bearer " + token(analyst)).contentType("application/json")
                .content("{\"action\":\"INVALID\"}")).andExpect(status().isBadRequest());
        admin.update("update investigation_assessments set payload=jsonb_set(payload,'{assessments,0,sourceReferences,0,quote}','\"fabricated\"'::jsonb) where investigation_id=?", fixture.id());
        assertThatThrownBy(() -> dashboard.graph(analyst, fixture.id())).hasMessage("UNVERIFIED_GRAPH_DATA");
    }

    private void demoProfile(UUID actor, UUID department) {
        admin.update("""
                insert into demo_access(user_id,department_id,expires_at,max_imports,max_bytes,max_investigations,max_pending,max_meta_attempts)
                values(?,?,now()+interval '1 day',12,67108864,3,10,30)
                """, actor, department);
    }

    private com.tewendelabs.investigator.investigation.InvestigationService.Create scopeOf(InvestigationFixture fixture) {
        return new com.tewendelabs.investigator.investigation.InvestigationService.Create(
                fixture.baseline(), fixture.replacement(), List.of(fixture.procedure()), LocalDate.of(2026, 10, 27));
    }

    private Connection runtimeConnection(UUID actor) throws Exception {
        var connection = java.sql.DriverManager.getConnection(POSTGRES.getJdbcUrl(), "investigator_app", APP_PASSWORD);
        connection.setAutoCommit(false);
        try (var p = connection.prepareStatement("select set_config('app.user_id',?,true)")) {
            p.setString(1, actor.toString());
            p.execute();
        }
        return connection;
    }

    private void sqlImport(Connection c, UUID actor, UUID department) throws Exception {
        UUID policy = UUID.randomUUID(), version = UUID.randomUUID();
        try (var p = c.prepareStatement("insert into policies(id,organization_id,department_id,title,kind) values(?,?,?,'Synthetic concurrent policy','POLICY')")) {
            p.setObject(1, policy); p.setObject(2, org); p.setObject(3, department); p.executeUpdate();
        }
        try (var p = c.prepareStatement("insert into policy_versions(id,policy_id,sequence,effective_date,filename,sha256,original_pdf) values(?,?,1,current_date,'test.pdf',? ,?)")) {
            p.setObject(1, version); p.setObject(2, policy); p.setString(3, "0".repeat(64)); p.setBytes(4, "%PDF-test!".getBytes(java.nio.charset.StandardCharsets.US_ASCII)); p.executeUpdate();
        }
        try (var p = c.prepareStatement("select enqueue_ingestion(?,?,?,?)")) {
            p.setObject(1, UUID.randomUUID()); p.setObject(2, version); p.setObject(3, UUID.randomUUID()); p.setString(4, "test-digest"); p.execute();
        }
    }

    private void sqlInvestigation(Connection c, UUID actor, InvestigationFixture fixture) throws Exception {
        sqlInvestigation(c, actor, scopeOf(fixture));
    }

    private UUID sqlInvestigation(Connection c, UUID actor, Create request) throws Exception {
        UUID id = sqlInvestigationRow(c, actor, request);
        try (var p = c.prepareStatement("select schedule_investigation(?)")) { p.setObject(1, id); p.execute(); }
        return id;
    }

    private UUID sqlInvestigationRow(Connection c, UUID actor, Create request) throws Exception {
        UUID id = UUID.randomUUID();
        try (var p = c.prepareStatement("insert into investigations(id,requested_by,request_key,payload_digest,baseline_id,replacement_id,procedure_ids,analysis_date) values(?,?,?,'test-digest',?,?,?,?)")) {
            p.setObject(1, id); p.setObject(2, actor); p.setObject(3, UUID.randomUUID()); p.setObject(4, request.baselineVersionId()); p.setObject(5, request.replacementVersionId());
            p.setArray(6, c.createArrayOf("uuid", request.procedureVersionIds().toArray())); p.setObject(7, request.analysisDate()); p.executeUpdate();
        }
        return id;
    }

    private void shareWithJudge(InvestigationFixture fixture) {
        demoProfile(outsider, hr);
        admin.update("insert into policy_grants(policy_id,department_id,permission) select policy_id,?,'READ' from policy_versions where id in (?,?)",
                hr, fixture.replacement(), fixture.procedure());
    }

    private boolean runtimeBoolean(UUID actor, String sql, Object... parameters) throws Exception {
        try (var c = runtimeConnection(actor); var p = c.prepareStatement(sql)) {
            for (int n = 0; n < parameters.length; n++) p.setObject(n + 1, parameters[n]);
            try (var r = p.executeQuery()) { assertThat(r.next()).isTrue(); return r.getBoolean(1); }
        }
    }

    @Test
    void judgeReadonlySharedScopeRunsWithAdmissionAndMetaReservationsButWithoutContentWrite() throws Exception {
        var fixture = investigationFixture();
        shareWithJudge(fixture);
        admin.update("update demo_access set max_investigations=1,max_pending=1,max_meta_attempts=4 where user_id=?", outsider);
        UUID key = UUID.randomUUID();
        UUID own = investigationService.create(outsider, key, scopeOf(fixture));
        assertThat(investigationService.create(outsider, key, scopeOf(fixture))).isEqualTo(own);
        assertThatThrownBy(() -> investigationService.create(outsider, UUID.randomUUID(), scopeOf(fixture))).hasMessage("DEMO_PENDING_LIMIT");
        assertThat(runtimeBoolean(outsider, "select investigation_runnable(?)", own)).isTrue();
        // Read access to another requester's investigation never grants execution.
        assertThat(runtimeBoolean(outsider, "select investigation_runnable(?)", fixture.id())).isFalse();
        assertThat(runtimeBoolean(analyst, "select investigation_runnable(?)", own)).isFalse();
        assertThatThrownBy(() -> runtimeBoolean(analyst, "select schedule_investigation(?)", own))
                .isInstanceOf(java.sql.SQLException.class).extracting(e -> ((java.sql.SQLException) e).getSQLState()).isEqualTo("42501");
        for (UUID version : List.of(fixture.baseline(), fixture.replacement(), fixture.procedure())) {
            UUID policy = admin.queryForObject("select policy_id from policy_versions where id=?", UUID.class, version);
            assertThat(runtimeBoolean(outsider, "select can_analyze_policy(?)", policy)).isTrue();
            assertThat(runtimeBoolean(outsider, "select can_write_policy(?)", policy)).isFalse();
            assertThat(scope.as(outsider, () -> jdbc.update("update policies set title='forged' where id=?", policy))).isZero();
            assertThat(scope.as(outsider, () -> jdbc.update("update policy_versions set status=status where id=?", version))).isZero();
            assertThatThrownBy(() -> scope.as(outsider, () -> jdbc.update("insert into document_pages values(?,999,'forged')", version)))
                    .hasRootCauseInstanceOf(java.sql.SQLException.class);
            assertThatThrownBy(() -> service.upload(outsider, UUID.randomUUID(), policy, null, null, null, version,
                    LocalDate.now(), "forged.pdf", PdfAndVectorTest.pdf("Forged synthetic document."))).hasMessage("NOT_FOUND");
            assertThatThrownBy(() -> scope.as(outsider, () -> jdbc.queryForObject("select enqueue_ingestion(?,?,?,?)", Object.class,
                    UUID.randomUUID(), version, UUID.randomUUID(), "test-digest"))).hasRootCauseInstanceOf(java.sql.SQLException.class);
        }
        assertThat(jdbc.queryForObject("select investigation_runnable(?)", Boolean.class, own)).isFalse(); // actor cleared
        successfulTransport(fixture);
        var lease = investigationLease(own);
        assertThat(runtimeBoolean(analyst, "select checkpoint_investigation(?,?,'EXTRACTING')", own, lease.token())).isFalse();
        assertThat(runtimeBoolean(outsider, "select checkpoint_investigation(?,?,'EXTRACTING')", own, UUID.randomUUID())).isFalse();
        assertThat(runtimeBoolean(outsider, "select reserve_investigation_call(?,?)", own, UUID.randomUUID())).isFalse();
        assertThatThrownBy(() -> runtimeBoolean(analyst, "select reserve_investigation_call(?,?)", own, lease.token()))
                .isInstanceOf(java.sql.SQLException.class).extracting(e -> ((java.sql.SQLException) e).getSQLState()).isEqualTo("42501");
        investigationWorker.process(lease);
        assertThat(investigationService.progress(outsider, own)).containsEntry("state", "COMPLETED").containsEntry("calls", 4);
        assertThat(investigationService.extractions(outsider, own)).hasSize(3);
        assertThat(admin.queryForMap("select investigations,meta_attempts from demo_access where user_id=?", outsider))
                .containsEntry("investigations", 1).containsEntry("meta_attempts", 4L);
        assertThat(admin.queryForObject("select attempts from demo_meta_budget", Long.class)).isEqualTo(4);
        assertThatThrownBy(() -> investigationService.create(outsider, UUID.randomUUID(), scopeOf(fixture))).hasMessage("DEMO_INVESTIGATION_LIMIT");
        try (var c = runtimeConnection(outsider)) {
            assertThatThrownBy(() -> sqlInvestigation(c, outsider, fixture)).isInstanceOf(java.sql.SQLException.class)
                    .extracting(e -> ((java.sql.SQLException) e).getSQLState()).isEqualTo("P7503");
            c.rollback();
        }
        assertThat(admin.queryForObject("select count(*) from investigations where requested_by=?", Integer.class, outsider)).isEqualTo(1);
    }

    @ParameterizedTest
    @CsvSource({"NONE", "POLICY_ONLY", "PROCEDURE_ONLY", "EXPIRED", "INACTIVE", "CROSS_ORG", "NO_MEMBERSHIP"})
    void judgeReadonlyRejectsHiddenScopesEvenThroughDefinerScheduling(String reason) throws Exception {
        var fixture = investigationFixture();
        shareWithJudge(fixture);
        switch (reason) {
            case "NONE" -> admin.update("delete from policy_grants where department_id=?", hr);
            case "POLICY_ONLY" -> admin.update("delete from policy_grants where department_id=? and policy_id=(select policy_id from policy_versions where id=?)", hr, fixture.procedure());
            case "PROCEDURE_ONLY" -> admin.update("delete from policy_grants where department_id=? and policy_id=(select policy_id from policy_versions where id=?)", hr, fixture.replacement());
            case "EXPIRED" -> admin.update("update demo_access set expires_at=now()-interval '1 second' where user_id=?", outsider);
            case "INACTIVE" -> admin.update("update app_users set active=false where id=?", outsider);
            case "CROSS_ORG" -> {
                UUID otherOrg = UUID.randomUUID();
                admin.update("insert into organizations values(?,'Other synthetic organization')", otherOrg);
                admin.update("update app_users set organization_id=? where id=?", otherOrg, outsider);
                admin.update("update departments set organization_id=? where id=?", otherOrg, hr);
            }
            case "NO_MEMBERSHIP" -> admin.update("delete from memberships where user_id=?", outsider);
            default -> throw new AssertionError(reason);
        }
        assertThatThrownBy(() -> investigationService.create(outsider, UUID.randomUUID(), scopeOf(fixture)))
                .hasMessage(List.of("EXPIRED", "INACTIVE").contains(reason) ? "UNAUTHENTICATED" : "NOT_FOUND");
        try (var c = runtimeConnection(outsider)) {
            assertThatThrownBy(() -> sqlInvestigation(c, outsider, fixture)).isInstanceOf(java.sql.SQLException.class)
                    .extracting(e -> ((java.sql.SQLException) e).getSQLState()).isEqualTo("42501");
        }
        // Simulate an older/privileged row: knowing its UUID must not bypass source visibility.
        UUID forged;
        try (var c = admin.getDataSource().getConnection()) { forged = sqlInvestigationRow(c, outsider, scopeOf(fixture)); }
        assertThat(runtimeBoolean(outsider, "select investigation_runnable(?)", forged)).isFalse();
        try (var c = runtimeConnection(outsider); var p = c.prepareStatement("select schedule_investigation(?)")) {
            p.setObject(1, forged);
            assertThatThrownBy(p::execute).isInstanceOf(java.sql.SQLException.class)
                    .extracting(e -> ((java.sql.SQLException) e).getSQLState()).isEqualTo("42501");
        }
        assertThat(admin.queryForObject("select count(*) from investigation_jobs where requested_by=?", Integer.class, outsider)).isZero();
        assertThat(admin.queryForObject("select investigations from demo_access where user_id=?", Integer.class, outsider)).isZero();
        verifyNoInteractions(metaTransport);
    }

    @Test
    void ordinaryReadersStillNeedWritePermissionToAnalyze() throws Exception {
        var fixture = investigationFixture();
        admin.update("insert into policy_grants select policy_id,?,'READ' from policy_versions where id in (?,?)", hr, fixture.replacement(), fixture.procedure());
        UUID policy = admin.queryForObject("select policy_id from policy_versions where id=?", UUID.class, fixture.replacement());
        assertThat(runtimeBoolean(outsider, "select can_analyze_policy(?)", policy)).isFalse();
        assertThatThrownBy(() -> investigationService.create(outsider, UUID.randomUUID(), scopeOf(fixture))).hasMessage("NOT_FOUND");
        assertThatThrownBy(() -> investigationService.create(viewer, UUID.randomUUID(), scopeOf(fixture))).hasMessage("NOT_FOUND");
        try (var c = runtimeConnection(outsider)) {
            assertThatThrownBy(() -> sqlInvestigation(c, outsider, fixture)).isInstanceOf(java.sql.SQLException.class);
        }
        admin.update("update policy_grants set permission='WRITE' where department_id=? and policy_id=?", hr, policy);
        assertThat(runtimeBoolean(outsider, "select can_analyze_policy(?)", policy)).isTrue();
        UUID own = investigationService.create(outsider, UUID.randomUUID(), scopeOf(fixture));
        assertThat(runtimeBoolean(outsider, "select investigation_runnable(?)", own)).isTrue();
        assertThat(runtimeBoolean(analyst, "select investigation_runnable(?)", fixture.id())).isTrue();
    }

    @ParameterizedTest
    @CsvSource({"INVESTIGATION,P7503", "PENDING,P7504"})
    void judgeReadonlyConcurrentSqlAdmissionsKeepQuotaReservations(String limit, String denied) throws Exception {
        var fixture = investigationFixture();
        shareWithJudge(fixture);
        admin.update("update demo_access set max_investigations=?,max_pending=? where user_id=?",
                limit.equals("INVESTIGATION") ? 2 : 10, limit.equals("PENDING") ? 2 : 10, outsider);
        assertThat(race(6, n -> outsider, (c, n) -> sqlInvestigation(c, outsider, fixture)))
                .containsOnly("OK", denied).containsExactlyInAnyOrder("OK", "OK", denied, denied, denied, denied);
        assertThat(admin.queryForObject("select investigations from demo_access where user_id=?", Integer.class, outsider)).isEqualTo(2);
        assertThat(admin.queryForObject("select count(*) from investigations where requested_by=?", Integer.class, outsider)).isEqualTo(2);
    }

    @ParameterizedTest
    @CsvSource({"INDIVIDUAL,DEMO_META_LIMIT", "COLLECTIVE,DEMO_COLLECTIVE_META_LIMIT"})
    void judgeReadonlyMetaExhaustionStopsBeforeAnotherTransportCall(String limit, String code) throws Exception {
        var fixture = investigationFixture();
        shareWithJudge(fixture);
        UUID own = investigationService.create(outsider, UUID.randomUUID(), scopeOf(fixture));
        if (limit.equals("INDIVIDUAL")) admin.update("update demo_access set max_meta_attempts=1 where user_id=?", outsider);
        else admin.update("update demo_meta_budget set max_attempts=1 where singleton");
        successfulTransport(fixture);
        investigationWorker.process(investigationLease(own));
        verify(metaTransport, times(1)).send(anyString(), anyString(), any());
        assertThat(investigationService.progress(outsider, own)).containsEntry("state", "PARTIAL").containsEntry("calls", 1).containsEntry("error_code", code);
        assertThat(admin.queryForObject("select meta_attempts from demo_access where user_id=?", Long.class, outsider)).isEqualTo(1);
        assertThat(admin.queryForObject("select attempts from demo_meta_budget", Long.class)).isEqualTo(1);
    }

    @Test
    void judgeReadonlyScopeFailsClosedForNullUnknownAndDuplicateVersionIds() throws Exception {
        var fixture = investigationFixture();
        shareWithJudge(fixture);
        try (var c = runtimeConnection(outsider); var p = c.prepareStatement("select investigation_scope_analyzable(?,?,?,?)")) {
            for (UUID[] procedures : List.of(new UUID[]{fixture.procedure(), null}, new UUID[]{UUID.randomUUID()},
                    new UUID[]{fixture.procedure(), fixture.procedure()}, new UUID[]{},
                    new UUID[]{fixture.procedure(), UUID.randomUUID(), UUID.randomUUID(), UUID.randomUUID(), UUID.randomUUID()})) {
                p.setObject(1, fixture.baseline()); p.setObject(2, fixture.replacement());
                p.setArray(3, c.createArrayOf("uuid", procedures)); p.setObject(4, scopeOf(fixture).analysisDate());
                try (var r = p.executeQuery()) { assertThat(r.next()).isTrue(); assertThat(r.getObject(1)).isEqualTo(false); }
            }
            p.setArray(3, c.createArrayOf("uuid", new UUID[]{fixture.procedure()}));
            p.setNull(1, java.sql.Types.OTHER);
            try (var r = p.executeQuery()) { assertThat(r.next()).isTrue(); assertThat(r.getObject(1)).isEqualTo(false); }
            p.setObject(1, fixture.baseline()); p.setNull(4, java.sql.Types.DATE);
            try (var r = p.executeQuery()) { assertThat(r.next()).isTrue(); assertThat(r.getObject(1)).isEqualTo(false); }
        }
    }

    @Test
    void judgeAnalysisDefinerIsRestrictedAndUnsafeOwnershipBlocksStartup() {
        assertThat(jdbc.queryForObject("""
                select prosecdef and proconfig @> array['search_path=pg_catalog, public, pg_temp']
                 and not exists(select 1 from aclexplode(proacl) where grantee=0 and privilege_type='EXECUTE')
                from pg_proc where oid='can_analyze_policy(uuid)'::regprocedure
                """, Boolean.class)).isTrue();
        assertThat(jdbc.queryForObject("select not prosecdef from pg_proc where oid='investigation_scope_analyzable(uuid,uuid,uuid[],date)'::regprocedure", Boolean.class)).isTrue();
        assertThat(jdbc.queryForObject("select not prosecdef from pg_proc where oid='investigation_runnable(uuid)'::regprocedure", Boolean.class)).isTrue();
        var safety = new com.tewendelabs.investigator.security.DatabaseSafetyCheck(jdbc);
        safety.run(null);
        try {
            admin.execute("alter function can_analyze_policy(uuid) owner to postgres");
            assertThatThrownBy(() -> safety.run(null)).isInstanceOf(IllegalStateException.class)
                    .hasMessage("Database roles do not satisfy the RLS security boundary");
        } finally {
            admin.execute("alter function can_analyze_policy(uuid) owner to investigator_owner");
        }
        safety.run(null);
    }

    @ParameterizedTest
    @CsvSource({"LINEAGE,INVALID_POLICY_LINEAGE", "DUPLICATE,DUPLICATE_SCOPE_VERSION", "UNKNOWN,NOT_FOUND",
            "POLICY_AS_PROCEDURE,INVALID_PROCEDURE_SCOPE", "CONSENT,EXTERNAL_PROCESSING_DENIED",
            "FUTURE,VERSION_NOT_EFFECTIVE", "NOT_INDEXED,VERSION_NOT_INDEXED"})
    void judgeReadonlyScopeValidationAppliesToJavaRlsAndDefinerScheduling(String problem, String code) throws Exception {
        var fixture = investigationFixture();
        shareWithJudge(fixture);
        Create request = scopeOf(fixture);
        switch (problem) {
            case "LINEAGE" -> request = new Create(fixture.replacement(), fixture.baseline(), List.of(fixture.procedure()), request.analysisDate());
            case "DUPLICATE" -> request = new Create(fixture.baseline(), fixture.replacement(), List.of(fixture.procedure(), fixture.procedure()), request.analysisDate());
            case "UNKNOWN" -> request = new Create(fixture.baseline(), fixture.replacement(), List.of(UUID.randomUUID()), request.analysisDate());
            case "POLICY_AS_PROCEDURE", "NOT_INDEXED" -> {
                var invalid = service.upload(analyst, UUID.randomUUID(), null, finance, "Synthetic invalid scope",
                        problem.equals("POLICY_AS_PROCEDURE") ? "POLICY" : "PROCEDURE", null,
                        LocalDate.of(2026, 10, 26), "scope.pdf", PdfAndVectorTest.pdf("Synthetic requirement."));
                if (problem.equals("POLICY_AS_PROCEDURE")) ingest(invalid);
                admin.update("update policies set external_processing_allowed=true where id=?", invalid.policyId());
                admin.update("insert into policy_grants values(?,?,'READ')", invalid.policyId(), hr);
                request = new Create(fixture.baseline(), fixture.replacement(), List.of(invalid.versionId()), request.analysisDate());
            }
            case "CONSENT" -> admin.update("update policies set external_processing_allowed=false where id=(select policy_id from policy_versions where id=?)", fixture.procedure());
            case "FUTURE" -> request = new Create(fixture.baseline(), fixture.replacement(), List.of(fixture.procedure()), LocalDate.of(2026, 10, 26));
            default -> throw new AssertionError(problem);
        }
        final Create invalidRequest = request;
        assertThatThrownBy(() -> investigationService.create(outsider, UUID.randomUUID(), invalidRequest)).hasMessage(code);
        try (var c = runtimeConnection(outsider)) {
            assertThatThrownBy(() -> sqlInvestigation(c, outsider, invalidRequest)).isInstanceOf(java.sql.SQLException.class)
                    .extracting(e -> ((java.sql.SQLException) e).getSQLState()).isEqualTo("42501");
        }
        UUID older;
        try (var c = admin.getDataSource().getConnection()) { older = sqlInvestigationRow(c, outsider, invalidRequest); }
        assertThat(runtimeBoolean(outsider, "select investigation_runnable(?)", older)).isFalse();
        try (var c = runtimeConnection(outsider); var p = c.prepareStatement("select schedule_investigation(?)")) {
            p.setObject(1, older);
            assertThatThrownBy(p::execute).isInstanceOf(java.sql.SQLException.class)
                    .extracting(e -> ((java.sql.SQLException) e).getSQLState()).isEqualTo("42501");
        }
        assertThat(admin.queryForObject("select investigations from demo_access where user_id=?", Integer.class, outsider)).isZero();
        verifyNoInteractions(metaTransport);
    }

    @ParameterizedTest
    @CsvSource({"POLICY,false", "PROCEDURE,false", "EXPIRED,false", "CONSENT,false",
            "POLICY,true", "PROCEDURE,true", "EXPIRED,true", "CONSENT,true"})
    void judgeReadonlyRevocationStopsReservationsAndAsyncPersistence(String revoked, boolean duringCall) throws Exception {
        var fixture = investigationFixture();
        shareWithJudge(fixture);
        UUID own = investigationService.create(outsider, UUID.randomUUID(), scopeOf(fixture));
        var lease = investigationLease(own);
        Runnable revoke = () -> {
            switch (revoked) {
                case "POLICY", "PROCEDURE" -> admin.update("delete from policy_grants where department_id=? and policy_id=(select policy_id from policy_versions where id=?)",
                        hr, revoked.equals("POLICY") ? fixture.replacement() : fixture.procedure());
                case "EXPIRED" -> admin.update("update demo_access set expires_at=now()-interval '1 second' where user_id=?", outsider);
                case "CONSENT" -> admin.update("update policies set external_processing_allowed=false where id=(select policy_id from policy_versions where id=?)", fixture.procedure());
                default -> throw new AssertionError(revoked);
            }
        };
        if (duringCall) {
            when(metaTransport.send(anyString(), anyString(), any())).thenAnswer(inv -> {
                revoke.run();
                return fixtureReply(inv.getArgument(1), fixture, true, false);
            });
        } else {
            revoke.run();
            assertThat(runtimeBoolean(outsider, "select investigation_runnable(?)", own)).isFalse();
            assertThat(runtimeBoolean(outsider, "select checkpoint_investigation(?,?,'EXTRACTING')", own, lease.token())).isFalse();
            try (var c = runtimeConnection(outsider); var p = c.prepareStatement("select reserve_investigation_call(?,?)")) {
                p.setObject(1, own); p.setObject(2, lease.token());
                assertThatThrownBy(p::execute).isInstanceOf(java.sql.SQLException.class)
                        .extracting(e -> ((java.sql.SQLException) e).getSQLState()).isEqualTo(revoked.equals("EXPIRED") ? "P7507" : "42501");
            }
        }
        investigationWorker.process(lease);
        if (duringCall) verify(metaTransport, times(1)).send(anyString(), anyString(), any());
        else verifyNoInteractions(metaTransport);
        assertThat(admin.queryForObject("select count(*) from requirement_extractions where investigation_id=?", Integer.class, own)).isZero();
        assertThat(admin.queryForObject("select count(*) from investigation_assessments where investigation_id=?", Integer.class, own)).isZero();
        assertThat(admin.queryForObject("select state from investigation_jobs where id=?", String.class, own)).isEqualTo("FAILED");
        assertThat(admin.queryForObject("select investigations from demo_access where user_id=?", Integer.class, outsider)).isEqualTo(1);
        assertThat(admin.queryForObject("select meta_attempts from demo_access where user_id=?", Long.class, outsider)).isEqualTo(duringCall ? 1L : 0L);
        assertThat(admin.queryForObject("select attempts from demo_meta_budget", Long.class)).isEqualTo(duringCall ? 1L : 0L);
    }

    @FunctionalInterface
    interface SqlRace { void run(Connection c, int index) throws Exception; }

    private List<String> race(int count, java.util.function.IntFunction<UUID> actors, SqlRace operation) throws Exception {
        var executor = java.util.concurrent.Executors.newFixedThreadPool(count);
        var ready = new java.util.concurrent.CountDownLatch(count);
        var start = new java.util.concurrent.CountDownLatch(1);
        var futures = new ArrayList<java.util.concurrent.Future<String>>();
        try {
            for (int n = 0; n < count; n++) {
                final int index = n;
                futures.add(executor.submit(() -> {
                    try (var c = runtimeConnection(actors.apply(index))) {
                        ready.countDown();
                        if (!start.await(10, java.util.concurrent.TimeUnit.SECONDS)) throw new AssertionError("Race start timed out");
                        try { operation.run(c, index); c.commit(); return "OK"; }
                        catch (java.sql.SQLException rejected) { c.rollback(); return rejected.getSQLState(); }
                    }
                }));
            }
            assertThat(ready.await(10, java.util.concurrent.TimeUnit.SECONDS)).isTrue();
            start.countDown();
            var result = new ArrayList<String>();
            for (var f : futures) result.add(f.get(20, java.util.concurrent.TimeUnit.SECONDS));
            return result;
        } finally { start.countDown(); executor.shutdownNow(); }
    }

    @Test
    void demoImportsAndBytesArePersistentAndIdempotentAndRejectedTransactionsRollBack() throws Exception {
        demoProfile(analyst, finance);
        byte[] bytes = PdfAndVectorTest.pdf("Synthetic policy.");
        admin.update("update demo_access set max_imports=1,max_bytes=? where user_id=?", bytes.length, analyst);
        UUID key = UUID.randomUUID();
        var accepted = service.upload(analyst, key, null, finance, "Synthetic", "POLICY", null, LocalDate.now(), "test.pdf", bytes);
        var replay = service.upload(analyst, key, null, finance, "Synthetic", "POLICY", null, LocalDate.now(), "test.pdf", bytes);
        assertThat(replay.policyId()).isEqualTo(accepted.policyId());
        assertThat(replay.versionId()).isEqualTo(accepted.versionId());
        assertThat(replay.jobId()).isEqualTo(accepted.jobId());
        assertThatThrownBy(() -> service.upload(analyst, key, null, finance, "Different", "POLICY", null, LocalDate.now(), "test.pdf", bytes)).hasMessage("IDEMPOTENCY_CONFLICT");
        assertThatThrownBy(this::upload).hasMessage("DEMO_IMPORT_LIMIT");
        mvc.perform(multipart("/api/policies").file(new MockMultipartFile("file", "test.pdf", "application/pdf", bytes))
                .param("departmentId", finance.toString()).param("title", "Another").param("kind", "POLICY").param("effectiveDate", LocalDate.now().toString())
                .header("Idempotency-Key", UUID.randomUUID()).header("Authorization", "Bearer " + token(analyst)))
                .andExpect(status().isTooManyRequests()).andExpect(jsonPath("$.code").value("DEMO_IMPORT_LIMIT"));
        assertThat(admin.queryForMap("select imports,bytes from demo_access where user_id=?", analyst))
                .containsEntry("imports", 1).containsEntry("bytes", (long) bytes.length);
        assertThat(service.list(analyst, 0)).hasSize(1);
        demoProfile(outsider, hr);
        admin.update("update demo_access set max_bytes=1 where user_id=?", outsider);
        assertThatThrownBy(() -> upload(outsider, hr)).hasMessage("DEMO_BYTE_LIMIT");
        assertThat(service.list(outsider, 0)).isEmpty();
        assertThat(admin.queryForObject("select imports from demo_access where user_id=?", Integer.class, outsider)).isZero();
    }

    @Test
    void demoInvestigationReplayDoesNotConsumeAgainAndPendingCoversBothKindsOfWork() throws Exception {
        var fixture = investigationFixture();
        demoProfile(analyst, finance);
        admin.update("update demo_access set max_pending=1,max_investigations=1 where user_id=?", analyst);
        assertThatThrownBy(this::upload).hasMessage("DEMO_PENDING_LIMIT");
        assertThatThrownBy(() -> investigationService.create(analyst, UUID.randomUUID(), scopeOf(fixture))).hasMessage("DEMO_PENDING_LIMIT");
        admin.update("update investigation_jobs set state='FAILED' where id=?", fixture.id());
        UUID key = UUID.randomUUID();
        UUID accepted = investigationService.create(analyst, key, scopeOf(fixture));
        assertThat(investigationService.create(analyst, key, scopeOf(fixture))).isEqualTo(accepted);
        admin.update("update investigation_jobs set state='FAILED' where id=?", accepted);
        assertThatThrownBy(() -> investigationService.create(analyst, UUID.randomUUID(), scopeOf(fixture))).hasMessage("DEMO_INVESTIGATION_LIMIT");
        assertThat(admin.queryForObject("select investigations from demo_access where user_id=?", Integer.class, analyst)).isEqualTo(1);
        // A failed terminal job frees a pending slot, but never refunds the lifetime counter.
        assertThat(upload()).isNotNull();
    }

    @ParameterizedTest
    @CsvSource({"IMPORT,P7501", "BYTES,P7502", "INVESTIGATION,P7503", "PENDING,P7504"})
    void demoConcurrentAdmissionsCannotExceedPersistentLimits(String kind, String deniedState) throws Exception {
        var fixture = investigationFixture();
        admin.update("update investigation_jobs set state='FAILED' where id=?", fixture.id());
        demoProfile(analyst, finance);
        switch (kind) {
            case "IMPORT" -> admin.update("update demo_access set max_imports=2 where user_id=?", analyst);
            case "BYTES" -> admin.update("update demo_access set max_bytes=20 where user_id=?", analyst);
            case "INVESTIGATION" -> admin.update("update demo_access set max_investigations=2 where user_id=?", analyst);
            case "PENDING" -> admin.update("update demo_access set max_pending=2 where user_id=?", analyst);
        }
        var result = race(6, n -> analyst, (c, n) -> {
            if (kind.equals("INVESTIGATION") || kind.equals("PENDING") && n % 2 == 0) sqlInvestigation(c, analyst, fixture);
            else sqlImport(c, analyst, finance);
        });
        assertThat(result).containsOnly("OK", deniedState).filteredOn("OK"::equals).hasSize(2);
        var counters = admin.queryForMap("select imports,bytes,investigations from demo_access where user_id=?", analyst);
        assertThat(((Number) counters.get("imports")).intValue() + ((Number) counters.get("investigations")).intValue()).isEqualTo(2);
        assertThat(((Number) counters.get("bytes")).longValue()).isEqualTo(((Number) counters.get("imports")).longValue() * 10);
    }

    @Test
    void demoReservationRollsBackWithItsWorkAndRuntimeCannotAlterLimits() throws Exception {
        demoProfile(analyst, finance);
        try (var c = runtimeConnection(analyst)) { sqlImport(c, analyst, finance); c.rollback(); }
        assertThat(service.list(analyst, 0)).isEmpty();
        assertThat(admin.queryForObject("select imports from demo_access where user_id=?", Integer.class, analyst)).isZero();
        for (String sql : List.of("select * from demo_access", "update demo_access set max_imports=1000", "delete from demo_access",
                "select * from demo_meta_budget", "update demo_meta_budget set attempts=0", "select reserve_demo_work('IMPORT',1)")) {
            assertThatThrownBy(() -> scope.as(analyst, () -> { jdbc.execute(sql); return null; })).isInstanceOf(org.springframework.dao.DataAccessException.class);
        }
    }

    private void sqlMetaAttempt(Connection c, UUID id, UUID lease) throws Exception {
        try (var p = c.prepareStatement("select reserve_investigation_call(?,?)")) {
            p.setObject(1, id); p.setObject(2, lease);
            try (var r = p.executeQuery()) { assertThat(r.next()).isTrue(); assertThat(r.getBoolean(1)).isTrue(); }
        }
    }

    @Test
    void demoMetaIndividualBudgetIsAtomicAndInvalidLeaseDoesNotDebit() throws Exception {
        var fixture = investigationFixture();
        var lease = investigationLease(fixture.id());
        demoProfile(analyst, finance);
        admin.update("update demo_access set max_meta_attempts=2 where user_id=?", analyst);
        assertThat(scope.as(analyst, () -> jdbc.queryForObject("select reserve_investigation_call(?,?)", Boolean.class, fixture.id(), UUID.randomUUID()))).isFalse();
        assertThat(admin.queryForObject("select attempts from demo_meta_budget", Long.class)).isZero();
        var result = race(6, n -> analyst, (c, n) -> sqlMetaAttempt(c, fixture.id(), lease.token()));
        assertThat(result).containsOnly("OK", "P7505").filteredOn("OK"::equals).hasSize(2);
        assertThat(admin.queryForObject("select meta_attempts from demo_access where user_id=?", Long.class, analyst)).isEqualTo(2);
        assertThat(investigationService.progress(analyst, fixture.id()).get("calls")).isEqualTo(2);
        assertThat(admin.queryForObject("select attempts from demo_meta_budget", Long.class)).isEqualTo(2);
        verifyNoInteractions(metaTransport);
        admin.update("update investigation_jobs set state='FAILED' where id=?", fixture.id());
    }

    @Test
    void demoCollectiveMetaBudgetIsAtomicAcrossDifferentJudges() throws Exception {
        var first = investigationFixture();
        var firstLease = investigationLease(first.id());
        var second = investigationFixture(outsider, hr);
        var secondLease = investigationLease(second.id());
        demoProfile(analyst, finance); demoProfile(outsider, hr);
        admin.update("update demo_meta_budget set max_attempts=1 where singleton");
        var result = race(6, n -> n % 2 == 0 ? analyst : outsider, (c, n) ->
                sqlMetaAttempt(c, n % 2 == 0 ? first.id() : second.id(), n % 2 == 0 ? firstLease.token() : secondLease.token()));
        assertThat(result).containsOnly("OK", "P7506").filteredOn("OK"::equals).hasSize(1);
        assertThat(admin.queryForObject("select sum(meta_attempts) from demo_access where user_id in (?,?)", Long.class, analyst, outsider)).isEqualTo(1);
        assertThat(admin.queryForObject("select attempts from demo_meta_budget", Long.class)).isEqualTo(1);
        assertThat(((Number) investigationService.progress(analyst, first.id()).get("calls")).intValue()
                + ((Number) investigationService.progress(outsider, second.id()).get("calls")).intValue()).isEqualTo(1);
        verifyNoInteractions(metaTransport);
        admin.update("update investigation_jobs set state='FAILED' where id in (?,?)", first.id(), second.id());
    }

    @Test
    void demoRetriesConsumeAttemptsAndStopBeforeTheNextTransportCall() throws Exception {
        var fixture = investigationFixture();
        demoProfile(analyst, finance);
        admin.update("update demo_access set max_meta_attempts=2 where user_id=?", analyst);
        when(metaTransport.send(anyString(), anyString(), any())).thenThrow(new ApiFailure(504, "PROVIDER_TIMEOUT"));
        investigationWorker.process(investigationLease(fixture.id()));
        verify(metaTransport, times(2)).send(anyString(), anyString(), any());
        assertThat(investigationService.progress(analyst, fixture.id())).containsEntry("calls", 2).containsEntry("error_code", "DEMO_META_LIMIT");
        assertThat(admin.queryForObject("select meta_attempts from demo_access where user_id=?", Long.class, analyst)).isEqualTo(2);
        assertThat(admin.queryForObject("select attempts from demo_meta_budget", Long.class)).isEqualTo(2);
    }

    @Test
    void demoExpiryRejectsLoginExistingJwtSqlContentAndQueuedProcessing() throws Exception {
        var fixture = investigationFixture();
        String jwt = token(analyst);
        demoProfile(analyst, finance);
        admin.update("update demo_access set expires_at=now()-interval '1 second' where user_id=?", analyst);
        assertThatThrownBy(() -> auth.login(new AuthController.Login(analyst + "@test.invalid", loginPassword))).hasMessage("INVALID_CREDENTIALS");
        mvc.perform(get("/api/auth/me").header("Authorization", "Bearer " + jwt)).andExpect(status().isUnauthorized());
        mvc.perform(get("/api/policies").header("Authorization", "Bearer " + jwt)).andExpect(status().isUnauthorized());
        assertThatThrownBy(() -> service.list(analyst, 0)).hasMessage("UNAUTHENTICATED");
        try (var c = runtimeConnection(analyst)) {
            for (String table : List.of("policies", "policy_versions", "document_pages", "chunks", "investigations", "requirement_extractions", "investigation_assessments", "finding_reviews")) {
                try (var r = c.createStatement().executeQuery("select count(*) from " + table)) { r.next(); assertThat(r.getInt(1)).isZero(); }
            }
        }
        investigationWorker.process(investigationLease(fixture.id()));
        assertThat(admin.queryForObject("select error_code from investigation_jobs where id=?", String.class, fixture.id())).isEqualTo("ACCESS_OR_CONSENT_REVOKED");
        assertThat(admin.queryForObject("select attempts from demo_meta_budget", Long.class)).isZero();
        verifyNoInteractions(metaTransport);
    }

    @ParameterizedTest
    @CsvSource({"true", "false"})
    void demoExpiryDuringCallPreventsRetryOrCheckpointPersistence(boolean retry) throws Exception {
        var fixture = investigationFixture();
        demoProfile(analyst, finance);
        when(metaTransport.send(anyString(), anyString(), any())).thenAnswer(inv -> {
            admin.update("update demo_access set expires_at=now()-interval '1 second' where user_id=?", analyst);
            if (retry) throw new ApiFailure(504, "PROVIDER_TIMEOUT");
            return fixtureReply(inv.getArgument(1), fixture, true, false);
        });
        investigationWorker.process(investigationLease(fixture.id()));
        verify(metaTransport, times(1)).send(anyString(), anyString(), any());
        assertThat(admin.queryForObject("select count(*) from requirement_extractions where investigation_id=?", Integer.class, fixture.id())).isZero();
        assertThat(admin.queryForObject("select meta_attempts from demo_access where user_id=?", Long.class, analyst)).isEqualTo(1);
    }

    @Test
    void demoExpiryWhileWaitingForQuotaLockIsRecheckedAfterTheWait() throws Exception {
        demoProfile(analyst, finance);
        var executor = java.util.concurrent.Executors.newSingleThreadExecutor();
        var started = new java.util.concurrent.CountDownLatch(1);
        try (var lock = admin.getDataSource().getConnection()) {
            lock.setAutoCommit(false);
            try (var p = lock.prepareStatement("select * from demo_access where user_id=? for update")) { p.setObject(1, analyst); p.execute(); }
            var waiting = executor.submit(() -> {
                try (var c = runtimeConnection(analyst)) {
                    started.countDown();
                    try { sqlImport(c, analyst, finance); c.commit(); return "OK"; }
                    catch (java.sql.SQLException e) { c.rollback(); return e.getSQLState(); }
                }
            });
            assertThat(started.await(10, java.util.concurrent.TimeUnit.SECONDS)).isTrue();
            assertThatThrownBy(() -> waiting.get(200, java.util.concurrent.TimeUnit.MILLISECONDS)).isInstanceOf(java.util.concurrent.TimeoutException.class);
            try (var p = lock.prepareStatement("update demo_access set expires_at=clock_timestamp()-interval '1 second' where user_id=?")) { p.setObject(1, analyst); p.executeUpdate(); }
            lock.commit();
            assertThat(waiting.get(10, java.util.concurrent.TimeUnit.SECONDS)).isEqualTo("P7507");
        } finally { executor.shutdownNow(); }
        assertThat(admin.queryForObject("select imports from demo_access where user_id=?", Integer.class, analyst)).isZero();
    }

    @ParameterizedTest
    @CsvSource({"VERSION", "AGGREGATE", "LATER_PROCEDURE"})
    void entireContextIsCheckedBeforeAdmissionAndBeforeAnyMetaCall(String oversized) throws Exception {
        var fixture = investigationFixture();
        if (oversized.equals("AGGREGATE")) {
            admin.update("update chunks set content=repeat('x',7100) where version_id in (?,?,?)", fixture.baseline(), fixture.replacement(), fixture.procedure());
        } else {
            admin.update("update chunks set content=repeat('x',16001) where version_id=?", oversized.equals("VERSION") ? fixture.baseline() : fixture.procedure());
        }
        demoProfile(analyst, finance);
        String code = oversized.equals("AGGREGATE") ? "ASSESSMENT_CONTEXT_BUDGET_EXCEEDED" : "SOURCE_COVERAGE_BUDGET_EXCEEDED";
        assertThatThrownBy(() -> investigationService.create(analyst, UUID.randomUUID(), scopeOf(fixture))).hasMessage(code);
        assertThat(admin.queryForObject("select investigations from demo_access where user_id=?", Integer.class, analyst)).isZero();
        // Simulate a job admitted before this release: the worker must also preflight the whole scope.
        investigationWorker.process(investigationLease(fixture.id()));
        assertThat(investigationService.progress(analyst, fixture.id())).containsEntry("calls", 0).containsEntry("error_code", code);
        verifyNoInteractions(metaTransport);
    }

    private Map<String, Object> judgeManifest(InvestigationFixture fixture) {
        return new HashMap<>(Map.ofEntries(
                Map.entry("organization_id", org.toString()), Map.entry("operator_user_id", analyst.toString()),
                Map.entry("investigation_id", fixture.id().toString()), Map.entry("email", UUID.randomUUID() + "@test.invalid"),
                Map.entry("department", "Judge " + UUID.randomUUID()), Map.entry("password", UUID.randomUUID().toString()),
                Map.entry("expires_at", java.time.Instant.now().plusSeconds(3600).toString()), Map.entry("synthetic_data_confirmed", true),
                Map.entry("read_policy_ids", admin.queryForList("select distinct policy_id::text from policy_versions where id in (?,?,?) order by policy_id::text", String.class, fixture.baseline(), fixture.replacement(), fixture.procedure())),
                Map.entry("max_imports", 12), Map.entry("max_bytes", 67108864), Map.entry("max_investigations", 3),
                Map.entry("max_pending", 2), Map.entry("max_meta_attempts", 30), Map.entry("shared_meta_attempts", 1000)));
    }

    private UUID provisionJudge(Map<String, Object> data) throws Exception {
        var parts = java.nio.file.Files.readString(java.nio.file.Path.of("scripts/provision_judge.sql")).split("-- JUDGE_INPUT --", -1);
        assertThat(parts).hasSize(2);
        try (var c = admin.getDataSource().getConnection()) {
            c.createStatement().execute(parts[0]);
            c.unwrap(org.postgresql.PGConnection.class).getCopyAPI().copyIn("COPY pg_temp.judge_input FROM STDIN",
                    new java.io.StringReader(Base64.getEncoder().encodeToString(com.tewendelabs.investigator.investigation.JsonContract.encode(data).getBytes(java.nio.charset.StandardCharsets.UTF_8)) + "\n"));
            c.createStatement().execute(parts[1]);
        }
        return admin.queryForObject("select id from app_users where email=?", UUID.class, data.get("email"));
    }

    @Test
    void judgeProvisioningPreservesCompletedScenarioAndProvidesOnlyPrivateWriteAndTargetedRead() throws Exception {
        var fixture = investigationFixture();
        successfulTransport(fixture);
        investigationWorker.process(investigationLease(fixture.id()));
        admin.update("update memberships set role='ADMIN' where user_id=?", analyst);
        var manifest = judgeManifest(fixture);
        UUID judge = provisionJudge(manifest);
        var secondManifest = judgeManifest(fixture);
        UUID second = provisionJudge(secondManifest);
        UUID department = admin.queryForObject("select department_id from demo_access where user_id=?", UUID.class, judge);
        assertThat(passwords.matches((String) manifest.get("password"), admin.queryForObject("select password_hash from app_users where id=?", String.class, judge))).isTrue();
        assertThat(admin.queryForList("select role,department_id from memberships where user_id=?", judge))
                .containsExactly(Map.of("role", "ADMIN", "department_id", department));
        assertThat(admin.queryForList("select policy_id::text from policy_grants where department_id=? and permission='READ' order by policy_id::text", String.class, department))
                .containsExactlyElementsOf((List<String>) manifest.get("read_policy_ids"));
        clearInvocations(metaTransport);
        assertThat(investigationService.progress(judge, fixture.id()).get("state")).isEqualTo("COMPLETED");
        assertThat(investigationService.findings(judge, fixture.id()).get("canReview")).isEqualTo(false);
        assertThat(investigationService.extractions(judge, fixture.id())).hasSize(3);
        assertThat(dashboard.graph(judge, fixture.id()).complete()).isTrue();
        UUID source = admin.queryForObject("select id from chunks where version_id=? limit 1", UUID.class, fixture.baseline());
        assertThat(service.evidence(judge, source)).containsKey("excerpt");
        UUID policy = admin.queryForObject("select policy_id from policy_versions where id=?", UUID.class, fixture.baseline());
        assertThat(service.content(judge, policy, fixture.baseline())).isNotEmpty();
        assertThatThrownBy(() -> investigationService.consent(judge, policy, false)).hasMessage("NOT_FOUND");
        assertThatThrownBy(() -> service.upload(judge, UUID.randomUUID(), policy, null, null, null, fixture.replacement(), LocalDate.now(), "new.pdf", PdfAndVectorTest.pdf("Changed."))).hasMessage("NOT_FOUND");
        UUID sharedAnalysis = investigationService.create(judge, UUID.randomUUID(), scopeOf(fixture));
        assertThat(runtimeBoolean(judge, "select investigation_runnable(?)", sharedAnalysis)).isTrue();
        assertThat(admin.queryForObject("select investigations from demo_access where user_id=?", Integer.class, judge)).isEqualTo(1);
        UUID finding = UUID.fromString(((tools.jackson.databind.JsonNode) investigationService.findings(judge, fixture.id()).get("payload")).path("assessments").get(0).path("id").asString());
        assertThatThrownBy(() -> dashboard.review(judge, fixture.id(), finding, new com.tewendelabs.investigator.investigation.InvestigationDashboardService.ReviewRequest(
                com.tewendelabs.investigator.investigation.InvestigationDashboardService.ReviewAction.CONFIRM, null))).hasMessage("REVIEW_PERMISSION_REQUIRED");
        var privateUpload = upload(judge, department);
        ingest(privateUpload, judge);
        investigationService.consent(judge, privateUpload.policyId(), true);
        assertThatThrownBy(() -> service.get(second, privateUpload.policyId())).hasMessage("NOT_FOUND");
        UUID privateSource = admin.queryForObject("select id from chunks where version_id=? limit 1", UUID.class, privateUpload.versionId());
        assertThatThrownBy(() -> service.evidence(second, privateSource)).hasMessage("NOT_FOUND");
        assertThatThrownBy(() -> service.content(second, privateUpload.policyId(), privateUpload.versionId())).hasMessage("NOT_FOUND");
        assertThatThrownBy(() -> service.job(second, privateUpload.jobId())).hasMessage("NOT_FOUND");
        verifyNoInteractions(metaTransport);
        assertThat(admin.queryForObject("select meta_attempts from demo_access where user_id=?", Long.class, judge)).isZero();
        var ownReplacement = service.upload(judge, UUID.randomUUID(), privateUpload.policyId(), null, null, null, privateUpload.versionId(),
                LocalDate.now(), "v2.pdf", PdfAndVectorTest.pdf("Report incidents in 12 hours."));
        ingest(ownReplacement, judge);
        UUID ownId = investigationService.create(judge, UUID.randomUUID(), new com.tewendelabs.investigator.investigation.InvestigationService.Create(
                privateUpload.versionId(), ownReplacement.versionId(), List.of(fixture.procedure()), LocalDate.now()));
        var own = new InvestigationFixture(ownId, privateUpload.versionId(), ownReplacement.versionId(), fixture.procedure());
        successfulTransport(own);
        investigationWorker.process(investigationLease(ownId));
        assertThat(investigationService.progress(judge, ownId).get("state")).isEqualTo("COMPLETED");
        assertThatThrownBy(() -> investigationService.progress(second, ownId)).hasMessage("NOT_FOUND");
        assertThatThrownBy(() -> investigationService.extractions(second, ownId)).hasMessage("NOT_FOUND");
        assertThatThrownBy(() -> investigationService.findings(second, ownId)).hasMessage("NOT_FOUND");
        assertThatThrownBy(() -> dashboard.graph(second, ownId)).hasMessage("NOT_FOUND");
        assertThat(admin.queryForObject("select meta_attempts from demo_access where user_id=?", Long.class, judge)).isEqualTo(4);
        // Even an accidental extra ADMIN membership / WRITE grant cannot expand demo write scope.
        admin.update("insert into memberships values(?,?,'ADMIN')", judge, finance);
        admin.update("update policy_grants set permission='WRITE' where department_id=?", department);
        assertThatThrownBy(() -> investigationService.consent(judge, policy, true)).hasMessage("NOT_FOUND");
        assertThat(scope.as(judge, () -> jdbc.queryForObject("select can_write_policy(?)", Boolean.class, policy))).isFalse();
        assertThat(scope.as(judge, () -> jdbc.queryForList("select * from actor_memberships(?)", judge))).hasSize(1);
        // Removing one source grant hides the whole result and its checkpoints immediately.
        admin.update("delete from policy_grants where department_id=? and policy_id=?", department, policy);
        assertThatThrownBy(() -> investigationService.progress(judge, fixture.id())).hasMessage("NOT_FOUND");
        assertThatThrownBy(() -> investigationService.extractions(judge, fixture.id())).hasMessage("NOT_FOUND");
        assertThatThrownBy(() -> investigationService.findings(judge, fixture.id())).hasMessage("NOT_FOUND");
    }

    @ParameterizedTest
    @CsvSource({"UNCONFIRMED", "EXPIRED", "WRONG_ALLOWLIST", "INCOMPLETE", "EXISTING_EMAIL", "SHARED_BUDGET", "WRONG_ORG", "INVALID_LIMIT"})
    void judgeProvisioningRefusesUnsafeInputsWithoutPartialChanges(String problem) throws Exception {
        var fixture = investigationFixture();
        successfulTransport(fixture);
        investigationWorker.process(investigationLease(fixture.id()));
        admin.update("update memberships set role='ADMIN' where user_id=?", analyst);
        var data = judgeManifest(fixture);
        switch (problem) {
            case "UNCONFIRMED" -> data.put("synthetic_data_confirmed", false);
            case "EXPIRED" -> data.put("expires_at", java.time.Instant.now().minusSeconds(1).toString());
            case "WRONG_ALLOWLIST" -> data.put("read_policy_ids", List.of(UUID.randomUUID().toString()));
            case "INCOMPLETE" -> admin.update("update investigation_jobs set state='PARTIAL' where id=?", fixture.id());
            case "EXISTING_EMAIL" -> data.put("email", analyst + "@test.invalid");
            case "SHARED_BUDGET" -> data.put("shared_meta_attempts", 1001);
            case "WRONG_ORG" -> data.put("organization_id", UUID.randomUUID().toString());
            case "INVALID_LIMIT" -> {
                admin.update("update demo_meta_budget set max_attempts=0 where singleton");
                data.put("max_pending", 0);
            }
        }
        long users = admin.queryForObject("select count(*) from app_users", Long.class);
        long profiles = admin.queryForObject("select count(*) from demo_access", Long.class);
        long departments = admin.queryForObject("select count(*) from departments", Long.class);
        assertThatThrownBy(() -> provisionJudge(data)).hasMessageContaining("JUDGE_PROVISIONING_REFUSED");
        assertThat(admin.queryForObject("select count(*) from app_users", Long.class)).isEqualTo(users);
        assertThat(admin.queryForObject("select count(*) from demo_access", Long.class)).isEqualTo(profiles);
        assertThat(admin.queryForObject("select count(*) from departments", Long.class)).isEqualTo(departments);
        assertThat(admin.queryForObject("select max_attempts from demo_meta_budget", Long.class)).isEqualTo(problem.equals("INVALID_LIMIT") ? 0 : 1000);
    }

    private static final UUID DEMO_USER = UUID.fromString("d3000000-0000-4000-8000-000000000004");
    private static final UUID DEMO_SECURITY = UUID.fromString("d3000000-0000-4000-8000-000000000002");

    private void seedDemo(java.sql.Connection connection, String enabled, String environment, String password) throws Exception {
        String[] parts = java.nio.file.Files.readString(java.nio.file.Path.of("scripts/seed_demo.sql")).split("-- DEMO_INPUT --", -1);
        assertThat(parts).hasSize(2);
        connection.createStatement().execute(parts[0]);
        String encoded = Base64.getEncoder().encodeToString(password.getBytes(java.nio.charset.StandardCharsets.UTF_8));
        connection.unwrap(org.postgresql.PGConnection.class).getCopyAPI().copyIn(
                "COPY pg_temp.demo_seed_input FROM STDIN", new java.io.StringReader(enabled + "\t" + environment + "\t" + encoded + "\n"));
        connection.createStatement().execute(parts[1]);
    }

    private void seedDemo(String enabled, String environment, String password) throws Exception {
        try (var connection = admin.getDataSource().getConnection()) {
            seedDemo(connection, enabled, environment, password);
        }
    }

    @Test
    void demoOperatorSeedIsIdempotentAndUsesNormalJwtAndDepartmentAuthorization() throws Exception {
        String password = UUID.randomUUID().toString();
        seedDemo("true", "local", password);
        String hash = admin.queryForObject("select password_hash from app_users where id=?", String.class, DEMO_USER);
        seedDemo("true", "local", password);
        assertThat(admin.queryForObject("select password_hash from app_users where id=?", String.class, DEMO_USER)).isEqualTo(hash);
        assertThat(admin.queryForObject("select count(*) from app_users where email='demo@policy-investigator.local'", Integer.class)).isEqualTo(1);
        assertThat(passwords.matches(password, hash)).isTrue();
        assertThat(admin.queryForList("select role from memberships where user_id=?", DEMO_USER)).hasSize(2)
                .allSatisfy(row -> assertThat(row.get("role")).isEqualTo("ADMIN"));
        var response = mvc.perform(post("/api/auth/login").contentType("application/json")
                        .content(com.tewendelabs.investigator.investigation.JsonContract.encode(Map.of("email", "demo@policy-investigator.local", "password", password))))
                .andExpect(status().isOk()).andReturn().getResponse();
        String jwt = com.tewendelabs.investigator.investigation.JsonContract.parse(response.getContentAsString()).path("token").asString();
        mvc.perform(get("/api/auth/me").header("Authorization", "Bearer " + jwt))
                .andExpect(status().isOk()).andExpect(jsonPath("$.memberships.length()").value(2));
        var document = service.upload(DEMO_USER, UUID.randomUUID(), null, DEMO_SECURITY, "Synthetic demo policy", "POLICY", null,
                LocalDate.of(2026, 10, 27), "demo.pdf", PdfAndVectorTest.pdf("Training before access."));
        assertThat(scope.as(DEMO_USER, () -> repository.findById(document.policyId()))).isPresent();
        assertThat(scope.as(analyst, () -> repository.findById(document.policyId()))).isEmpty();
        assertThat(scope.as(DEMO_USER, () -> repository.findAll())).hasSize(1);
        // Same-password reseeding is stable; an explicit changed password rotates only the demo account.
        String rotated = UUID.randomUUID().toString();
        seedDemo("true", "local", rotated);
        assertThatThrownBy(() -> auth.login(new AuthController.Login("demo@policy-investigator.local", password))).hasMessage("INVALID_CREDENTIALS");
        assertThat(auth.login(new AuthController.Login("demo@policy-investigator.local", rotated))).containsKey("token");
    }

    @Test
    void demoSqlRefusesDisabledProductionAndUnrelatedIdentityCollisions() throws Exception {
        String password = UUID.randomUUID().toString();
        seedDemo("true", "local", password);
        String hash = admin.queryForObject("select password_hash from app_users where id=?", String.class, DEMO_USER);
        assertThatThrownBy(() -> seedDemo("false", "local", password)).hasMessageContaining("DEMO_SEED_DISABLED");
        assertThatThrownBy(() -> seedDemo("true", "production", password)).hasMessageContaining("DEMO_SEED_DISABLED");
        assertThatThrownBy(() -> seedDemo("true", "local", "short")).hasMessageContaining("DEMO_PASSWORD_INVALID");
        assertThat(admin.queryForObject("select password_hash from app_users where id=?", String.class, DEMO_USER)).isEqualTo(hash);
        try (var connection = admin.getDataSource().getConnection()) {
            connection.createStatement().execute("BEGIN");
            try (var statement = connection.prepareStatement("update app_users set organization_id=? where id=?")) {
                statement.setObject(1, org); statement.setObject(2, DEMO_USER); statement.executeUpdate();
            }
            assertThatThrownBy(() -> seedDemo(connection, "true", "local", UUID.randomUUID().toString())).hasMessageContaining("DEMO_IDENTITY_COLLISION");
            connection.createStatement().execute("ROLLBACK");
        }
        assertThat(admin.queryForObject("select password_hash from app_users where id=?", String.class, DEMO_USER)).isEqualTo(hash);
    }

}
