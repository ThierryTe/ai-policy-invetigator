package com.tewendelabs.investigator;

import java.util.*;
import java.time.LocalDate;
import java.sql.Connection;

import org.junit.jupiter.api.*;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.ArgumentMatchers.anyList;
import static org.mockito.Mockito.when;
import static org.mockito.Mockito.reset;
import static org.mockito.Mockito.clearInvocations;
import static org.mockito.Mockito.verifyNoInteractions;
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
        return service.upload(analyst, UUID.randomUUID(), null, finance, "Incident policy", "POLICY", null, LocalDate.of(2026, 10, 26), "policy.pdf", PdfAndVectorTest.pdf("Report incidents in 24 hours."));
    }

    private void ingest(PolicyService.Upload result) {
        // Claim this exact task without consuming tasks left by other tests.
        admin.update("update ingestion_tasks set created_at=now()-interval '1 year' where id=?", result.jobId());
        IngestionWorker.Lease lease = worker.claim();
        assertThat(lease.id()).isEqualTo(result.jobId());
        worker.process(lease);
        assertThat(service.job(analyst, result.jobId()).get("status")).isEqualTo("COMPLETED");
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
        var baseline = upload();
        ingest(baseline);
        var replacement = service.upload(analyst, UUID.randomUUID(), baseline.policyId(), null, null, null, baseline.versionId(), LocalDate.of(2026, 10, 27), "new.pdf", PdfAndVectorTest.pdf("Training is mandatory before sensitive-system access."));
        ingest(replacement);
        var procedure = service.upload(analyst, UUID.randomUUID(), null, finance, "HR access", "PROCEDURE", null, LocalDate.of(2026, 10, 26), "hr.pdf", PdfAndVectorTest.pdf("Access on day one; training within 30 days."));
        ingest(procedure);
        admin.update("update policies set external_processing_allowed=true where id in (?,?)", baseline.policyId(), procedure.policyId());
        UUID id = investigationService.create(analyst, UUID.randomUUID(), new com.tewendelabs.investigator.investigation.InvestigationService.Create(baseline.versionId(), replacement.versionId(), List.of(procedure.versionId()), LocalDate.of(2026, 10, 27)));
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
        if (envelope.path("response_format").path("json_schema").path("name").asString().equals("requirements_v1")) {
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

    @Test
    void restartRecoveryReusesExtractionCheckpointAndFencesStaleLease() throws Exception {
        var fixture = investigationFixture();
        java.util.concurrent.atomic.AtomicInteger sent = new java.util.concurrent.atomic.AtomicInteger();
        when(metaTransport.send(anyString(), anyString(), any())).thenAnswer(inv -> {
            if (sent.incrementAndGet() == 2) throw new AssertionError("simulated process crash");
            return fixtureReply(inv.getArgument(1), fixture, true, false);
        });
        var stale = investigationLease(fixture.id());
        assertThatThrownBy(() -> investigationWorker.process(stale)).isInstanceOf(AssertionError.class);
        assertThat(investigationService.extractions(analyst, fixture.id())).hasSize(1);
        admin.update("update investigation_jobs set lease_until=now()-interval '1 second' where id=?", fixture.id());
        var recovered = investigationLease(fixture.id());
        successfulTransport(fixture);
        investigationWorker.process(recovered);
        assertThat(investigationService.progress(analyst, fixture.id()).get("state")).isEqualTo("COMPLETED");
        assertThat(jdbc.queryForObject("select finish_investigation(?,?,'FAILED','STALE')", Boolean.class, stale.id(), stale.token())).isFalse();
        assertThat(investigationService.progress(analyst, fixture.id()).get("calls")).isEqualTo(5);
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
