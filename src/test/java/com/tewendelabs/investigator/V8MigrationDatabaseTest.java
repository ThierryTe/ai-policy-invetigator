package com.tewendelabs.investigator;

import java.sql.Connection;
import java.time.LocalDate;
import java.util.*;
import java.util.concurrent.*;

import org.flywaydb.core.Flyway;
import org.junit.jupiter.api.*;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.ai.embedding.EmbeddingModel;
import org.testcontainers.containers.PostgreSQLContainer;
import org.testcontainers.utility.DockerImageName;

import com.tewendelabs.investigator.investigation.*;
import com.tewendelabs.investigator.policy.PolicyService;
import com.tewendelabs.investigator.provider.*;
import com.tewendelabs.investigator.provider.PolicyReasoningProvider.Source;
import com.tewendelabs.investigator.security.ScopedAccess;

import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;
import static org.mockito.ArgumentMatchers.*;

/** Upgrade qualification only: isolated PG16, synthetic data, no HTTP transport. */
@Tag("database")
@TestMethodOrder(MethodOrderer.OrderAnnotation.class)
@SpringBootTest(properties = {"app.worker.enabled=false", "app.investigation.worker-enabled=false",
        "app.investigation.budget-seconds=600", "meta.api.key=synthetic-upgrade-only",
        "app.embedding.verify-artifacts=false", "spring.ai.model.embedding=none",
        "app.embedding.revision=synthetic-upgrade-v1"})
class V8MigrationDatabaseTest {
    static final String OWNER = UUID.randomUUID().toString(), APP = UUID.randomUUID().toString();
    static final PostgreSQLContainer<?> POSTGRES = new PostgreSQLContainer<>(
            DockerImageName.parse("pgvector/pgvector:0.8.0-pg16").asCompatibleSubstituteFor("postgres"))
            .withDatabaseName("investigator_v8_qualification").withUsername("postgres")
            .withPassword(UUID.randomUUID().toString());
    static JdbcTemplate admin;
    static Map<String, String> before;
    static List<Map<String, Object>> historyV7;
    static Fixture completed, queued, running, judgePrivate, judgeShared, revoked, inFlight;
    static UUID oldLease;
    static final String TEXT = "Complete training before access.";
    static final LocalDate DATE = LocalDate.of(2026, 10, 27);

    record Fixture(UUID actor, UUID department, UUID id, UUID policy, UUID procedurePolicy,
                   UUID baseline, UUID replacement, UUID procedure) {
        List<UUID> versions() { return List.of(baseline, replacement, procedure); }
    }

    @DynamicPropertySource
    static void database(DynamicPropertyRegistry props) throws Exception {
        POSTGRES.start();
        admin = new JdbcTemplate(new DriverManagerDataSource(POSTGRES.getJdbcUrl(), "postgres", POSTGRES.getPassword()));
        try (Connection c = admin.getDataSource().getConnection()) {
            try (var p = c.prepareStatement("select set_config('test.owner',?,false),set_config('test.app',?,false)")) {
                p.setString(1, OWNER); p.setString(2, APP); p.execute();
            }
            c.createStatement().execute("""
                    CREATE ROLE investigator_runtime NOLOGIN NOSUPERUSER NOBYPASSRLS;
                    CREATE ROLE qualification_untrusted NOLOGIN NOSUPERUSER NOBYPASSRLS;
                    DO $$ BEGIN
                     EXECUTE format('CREATE ROLE investigator_owner LOGIN NOSUPERUSER NOBYPASSRLS PASSWORD %L',current_setting('test.owner'));
                     EXECUTE format('CREATE ROLE investigator_app LOGIN NOSUPERUSER NOBYPASSRLS PASSWORD %L',current_setting('test.app'));
                    END $$;
                    GRANT investigator_runtime TO investigator_app;
                    ALTER DATABASE investigator_v8_qualification OWNER TO investigator_owner;
                    ALTER SCHEMA public OWNER TO investigator_owner;
                    REVOKE CREATE ON SCHEMA public FROM PUBLIC;
                    CREATE EXTENSION vector;
                    CREATE EXTENSION pgcrypto;
                    """);
        }
        var v7 = flyway(POSTGRES.getJdbcUrl(), "7");
        assertThat(v7.migrate().migrationsExecuted).isEqualTo(7);
        POSTGRES.copyFileToContainer(org.testcontainers.utility.MountableFile.forHostPath(
                "scripts/qualification_v8_preflight.sql"), "/tmp/qualification.sql");
        assertThat(preflight(7)).isZero();
        completed = fixture(false, false);
        queued = fixture(false, false);
        running = fixture(false, false);
        judgePrivate = fixture(true, false);
        judgeShared = fixture(true, true);
        revoked = fixture(false, false);
        inFlight = fixture(true, true);
        // Persist valid V7 output, not just empty placeholder rows.
        for (UUID v : completed.versions()) checkpoint(completed, v);
        var assessment = JsonContract.tree(assessment(completed));
        EvidenceValidator.assessment(assessment,
                new InvestigationService.Snapshot(completed.id(), completed.actor(), completed.baseline(),
                        completed.replacement(), List.of(completed.procedure()), DATE),
                extracted(completed), sources(completed));
        admin.update("insert into investigation_assessments values(?,?,?::jsonb,?,?,?)", UUID.randomUUID(),
                completed.id(), JsonContract.encode(assessment), "muse-spark-1.3", InvestigationSchemas.PROMPT, InvestigationSchemas.ASSESSMENT);
        admin.update("update investigation_jobs set state='COMPLETED',stage='COMPLETED',calls=4,metered_calls=4 where id=?", completed.id());
        admin.update("insert into finding_reviews(id,investigation_id,finding_id,reviewer_id,action) values(?,?,?,?,'CONFIRM')",
                UUID.randomUUID(), completed.id(), UUID.fromString(assessment.path("assessments").get(0).path("id").asString()), completed.actor());
        checkpoint(running, running.baseline());
        oldLease = UUID.randomUUID();
        admin.update("update investigation_jobs set state='RUNNING',stage='EXTRACTING',attempts=1,calls=1,metered_calls=1,lease_token=?,lease_until=now()+interval '5 minutes',deadline_at=now()+interval '10 minutes' where id=?", oldLease, running.id());
        historyV7 = admin.queryForList("select * from flyway_schema_history order by installed_rank");
        before = snapshot(admin);
        var dump = POSTGRES.execInContainer("pg_dump", "-U", "postgres", "-d", POSTGRES.getDatabaseName(),
                "-Fc", "-f", "/tmp/qualification-v7.dump");
        assertThat(dump.getExitCode()).isZero();
        props.add("spring.datasource.url", POSTGRES::getJdbcUrl);
        props.add("spring.datasource.password", () -> APP);
        props.add("spring.flyway.url", POSTGRES::getJdbcUrl);
        props.add("spring.flyway.password", () -> OWNER);
        props.add("app.jwt.secret", () -> UUID.randomUUID().toString() + UUID.randomUUID());
    }

    static Flyway flyway(String url, String target) {
        return Flyway.configure().dataSource(url, "investigator_owner", OWNER).target(target).load();
    }

    static int preflight(int version) throws Exception {
        return POSTGRES.execInContainer("psql", "-X", "-U", "postgres", "-d", POSTGRES.getDatabaseName(),
                "-v", "expected_database=" + POSTGRES.getDatabaseName(), "-v", "target_version=" + version,
                "-f", "/tmp/qualification.sql").getExitCode();
    }

    static Fixture fixture(boolean judge, boolean shared) throws Exception {
        UUID org = UUID.randomUUID(), dept = UUID.randomUUID(), actor = UUID.randomUUID();
        UUID policy = UUID.randomUUID(), procPolicy = UUID.randomUUID();
        var f = new Fixture(actor, dept, UUID.randomUUID(), policy, procPolicy,
                UUID.randomUUID(), UUID.randomUUID(), UUID.randomUUID());
        admin.update("insert into organizations values(?,'Synthetic V7 upgrade')", org);
        admin.update("insert into departments values(?,?,'Synthetic source department')", dept, org);
        admin.update("insert into app_users(id,organization_id,email,password_hash) values(?,?,?,'non-login-synthetic')", actor, org, actor + "@test.invalid");
        admin.update("insert into memberships values(?,?,'ADMIN')", actor, dept);
        admin.update("insert into policies values(?,?,?,'Policy','POLICY',true),(?,?,?,'Procedure','PROCEDURE',true)", policy, org, dept, procPolicy, org, dept);
        byte[] pdf = PdfAndVectorTest.pdf(TEXT);
        for (int n = 0; n < 3; n++) {
            UUID v = f.versions().get(n);
            admin.update("insert into policy_versions(id,policy_id,sequence,previous_id,effective_date,filename,sha256,original_pdf,status) values(?,?,?,?,?,'synthetic.pdf',?,?,'QUEUED')",
                    v, n == 2 ? procPolicy : policy, n == 1 ? 2 : 1, n == 1 ? f.baseline() : null,
                    DATE, PolicyService.sha256(pdf), pdf);
            admin.update("insert into document_pages values(?,1,?)", v, TEXT);
            admin.update("insert into chunks values(?,?,1,0,?,?,?::vector,'synthetic-upgrade-v1')",
                    UUID.randomUUID(), v, TEXT.length(), TEXT, "[1," + "0,".repeat(382) + "0]");
            admin.update("update policy_versions set status='INDEXED' where id=?", v);
        }
        if (judge) {
            admin.update("update demo_meta_budget set max_attempts=1000 where singleton");
            admin.update("insert into demo_access(user_id,department_id,expires_at,max_imports,max_bytes,max_investigations,max_pending,max_meta_attempts) values(?,?,now()+interval '1 day',10,100000,10,10,100)", actor, dept);
        }
        // Admission and quota reservation run through the real V7 runtime login.
        try (var c = runtime(actor)) {
            try (var p = c.prepareStatement("insert into investigations values(?,?,?,?,?,?,?,?)")) {
                p.setObject(1, f.id()); p.setObject(2, actor); p.setObject(3, UUID.randomUUID()); p.setString(4, "synthetic-v7-digest");
                p.setObject(5, f.baseline()); p.setObject(6, f.replacement());
                p.setArray(7, c.createArrayOf("uuid", new UUID[]{f.procedure()})); p.setObject(8, DATE);
                p.executeUpdate();
            }
            try (var p = c.prepareStatement("select schedule_investigation(?)")) { p.setObject(1, f.id()); p.execute(); }
            c.commit();
        }
        if (shared) {
            // An already admitted V7 request loses WRITE, retaining targeted READ.
            UUID privateDept = UUID.randomUUID();
            admin.update("insert into departments values(?,?,'Judge private department')", privateDept, org);
            admin.update("delete from memberships where user_id=?", actor);
            admin.update("insert into memberships values(?,?,'ADMIN')", actor, privateDept);
            admin.update("update demo_access set department_id=? where user_id=?", privateDept, actor);
            admin.update("insert into policy_grants values(?,?,'READ'),(?,?,'READ')", policy, privateDept, procPolicy, privateDept);
        }
        return f;
    }

    static Connection runtime(UUID actor) throws Exception {
        var c = java.sql.DriverManager.getConnection(POSTGRES.getJdbcUrl(), "investigator_app", APP);
        c.setAutoCommit(false);
        try (var p = c.prepareStatement("select set_config('app.user_id',?,true)")) { p.setString(1, actor.toString()); p.execute(); }
        return c;
    }

    static Map<String, String> snapshot(JdbcTemplate db) {
        var result = new TreeMap<String, String>();
        for (String table : db.queryForList("select tablename from pg_tables where schemaname='public' and tablename<>'flyway_schema_history' order by tablename", String.class)) {
            assertThat(table).matches("[a-z_]+");
            result.put(table, db.queryForObject("select count(*)::text||':'||md5(coalesce(string_agg(to_jsonb(t)::text,E'\\n' order by to_jsonb(t)::text),'')) from public.\"" + table + "\" t", String.class));
        }
        return result;
    }

    static List<Source> sources(Fixture f) {
        return f.versions().stream().map(v -> new Source(
                admin.queryForObject("select id from chunks where version_id=?", UUID.class, v), v, TEXT)).toList();
    }

    static tools.jackson.databind.JsonNode extraction(Fixture f, UUID version) {
        var source = sources(f).stream().filter(s -> s.versionId().equals(version)).findFirst().orElseThrow();
        return EvidenceValidator.extraction(JsonContract.tree(Map.of("requirements", List.of(
                com.tewendelabs.investigator.investigation.StructuredValidationTest.requirement(source.sourceId().toString(), TEXT)),
                "processedSourceIds", List.of(source.sourceId().toString()), "complete", true, "limitations", List.of())), List.of(source), f.id(), version);
    }

    static Map<UUID, tools.jackson.databind.JsonNode> extracted(Fixture f) {
        var rows = new LinkedHashMap<UUID, tools.jackson.databind.JsonNode>();
        for (UUID v : f.versions()) rows.put(v, extraction(f, v));
        return rows;
    }

    static void checkpoint(Fixture f, UUID version) {
        var src = sources(f).stream().filter(s -> s.versionId().equals(version)).toList();
        String hash = PolicyService.sha256(JsonContract.encode(src).getBytes(java.nio.charset.StandardCharsets.UTF_8));
        admin.update("insert into requirement_extractions values(?,?,?::jsonb,?,?,?,?)", f.id(), version,
                JsonContract.encode(extraction(f, version)), hash, "muse-spark-1.3", InvestigationSchemas.PROMPT, InvestigationSchemas.EXTRACTION);
    }

    static Map<String, Object> assessment(Fixture f) {
        var data = extracted(f);
        var refs = sources(f).stream().map(s -> Map.of("sourceId", s.sourceId().toString(), "quote", TEXT)).toList();
        var relevant = sources(f).stream().filter(s -> !s.versionId().equals(f.baseline()))
                .map(s -> Map.of("sourceId", s.sourceId().toString(), "quote", TEXT)).toList();
        String old = data.get(f.baseline()).path("requirements").get(0).path("id").asString();
        String current = data.get(f.replacement()).path("requirements").get(0).path("id").asString();
        String proc = data.get(f.procedure()).path("requirements").get(0).path("id").asString();
        return Map.of("changes", List.of(Map.of("baselineRequirementId", old, "replacementRequirementId", current,
                "changeType", "UNCHANGED", "reason", "Same synthetic requirement", "sourceReferences", refs)),
                "assessments", List.of(Map.of("policyRequirementId", current, "procedureVersionId", f.procedure().toString(),
                        "relatedProcedureRequirementIds", List.of(proc), "classification", "NO_CONFLICT", "severity", "LOW",
                        "rationale", "Matching requirements", "suggestedAction", "Review", "scopeExplanation", "Same scope", "sourceReferences", relevant)),
                "complete", true, "limitations", List.of());
    }

    @Autowired JdbcTemplate jdbc;
    @Autowired ScopedAccess scope;
    @Autowired InvestigationService service;
    @Autowired InvestigationWorker worker;
    @MockitoBean MetaTransport transport;
    @MockitoBean EmbeddingModel embeddings;

    @Test @Order(1)
    void upgradePreservesEveryExistingRowAndV7History() {
        assertThat(admin.queryForObject("show server_version_num", Integer.class)).isBetween(160000, 169999);
        assertThat(snapshot(admin)).isEqualTo(before);
        assertThat(admin.queryForList("select * from flyway_schema_history where version<>'8' order by installed_rank")).isEqualTo(historyV7);
        assertThat(admin.queryForList("select version from flyway_schema_history where success order by installed_rank", String.class))
                .containsExactly("1", "2", "3", "4", "5", "6", "7", "8");
        assertThat(service.progress(completed.actor(), completed.id())).containsEntry("state", "COMPLETED");
        assertThat(service.extractions(completed.actor(), completed.id())).hasSize(3);
        assertThat(service.findings(completed.actor(), completed.id()).get("reviews").toString()).contains("CONFIRMED");
        verifyNoInteractions(transport);
    }

    @Test @Order(2)
    void backupRestoresV7AndFailedV8RollsBackBeforeSuccessfulRetry() throws Exception {
        admin.execute("create database qualification_restore owner investigator_owner");
        var restore = POSTGRES.execInContainer("pg_restore", "-U", "postgres", "-d", "qualification_restore", "--exit-on-error", "/tmp/qualification-v7.dump");
        assertThat(restore.getExitCode()).isZero();
        String url = POSTGRES.getJdbcUrl().replace(POSTGRES.getDatabaseName(), "qualification_restore");
        var restored = new JdbcTemplate(new DriverManagerDataSource(url, "postgres", POSTGRES.getPassword()));
        assertThat(snapshot(restored)).isEqualTo(before);
        assertThat(restored.queryForList("select * from flyway_schema_history order by installed_rank")).isEqualTo(historyV7);
        flyway(url, "7").validate();
        restored.execute("alter policy investigation_create on investigations rename to qualification_failure");
        assertThatThrownBy(() -> flyway(url, "8").migrate()).isInstanceOf(org.flywaydb.core.api.FlywayException.class);
        assertThat(restored.queryForObject("select to_regprocedure('can_analyze_policy(uuid)') is null", Boolean.class)).isTrue();
        assertThat(restored.queryForObject("select count(*) from flyway_schema_history where version='8'", Integer.class)).isZero();
        assertThat(snapshot(restored)).isEqualTo(before);
        restored.execute("alter policy qualification_failure on investigations rename to investigation_create");
        assertThat(flyway(url, "8").migrate().migrationsExecuted).isEqualTo(1);
        flyway(url, "8").validate();
        assertThat(flyway(url, "8").migrate().migrationsExecuted).isZero();
        assertThat(snapshot(restored)).isEqualTo(before);
    }

    @Test @Order(3)
    void effectiveRolesFunctionAclsAndForcedRlsAreSafe() throws Exception {
        assertThat(preflight(8)).isZero();
        assertThat(jdbc.queryForObject("select current_user", String.class)).isEqualTo("investigator_app");
        assertThat(admin.queryForObject("select bool_and(not rolsuper and not rolbypassrls) from pg_roles where rolname in ('investigator_app','investigator_owner','investigator_runtime')", Boolean.class)).isTrue();
        assertThat(admin.queryForObject("select pg_has_role('investigator_app','investigator_owner','MEMBER')", Boolean.class)).isFalse();
        for (String signature : List.of("can_analyze_policy(uuid)", "investigation_scope_analyzable(uuid,uuid,uuid[],date)", "investigation_runnable(uuid)")) {
            assertThat(jdbc.queryForObject("select has_function_privilege(current_user,?,'EXECUTE') and not has_function_privilege('qualification_untrusted',?,'EXECUTE')", Boolean.class, signature, signature)).isTrue();
            assertThat(admin.queryForObject("select r.rolname='investigator_owner' and not r.rolsuper and not r.rolbypassrls and p.proconfig @> array['search_path=pg_catalog, public, pg_temp'] from pg_proc p join pg_roles r on r.oid=p.proowner where p.oid=?::regprocedure", Boolean.class, signature)).isTrue();
        }
        assertThat(jdbc.queryForObject("select prosecdef from pg_proc where oid='can_analyze_policy(uuid)'::regprocedure", Boolean.class)).isTrue();
        assertThat(jdbc.queryForObject("select bool_and(not prosecdef) from pg_proc where oid in ('investigation_runnable(uuid)'::regprocedure,'investigation_scope_analyzable(uuid,uuid,uuid[],date)'::regprocedure)", Boolean.class)).isTrue();
        for (String table : List.of("policies", "policy_versions", "document_pages", "chunks", "investigations", "requirement_extractions", "investigation_assessments", "finding_reviews")) {
            assertThat(admin.queryForObject("select relrowsecurity and relforcerowsecurity from pg_class where oid=?::regclass", Boolean.class, table)).isTrue();
        }
        try (var c = java.sql.DriverManager.getConnection(POSTGRES.getJdbcUrl(), "investigator_owner", OWNER)) {
            try (var r = c.createStatement().executeQuery("select count(*) from policies")) { r.next(); assertThat(r.getInt(1)).isZero(); }
        }
        scope.as(judgeShared.actor(), () -> {
            assertThat(jdbc.queryForObject("select can_analyze_policy(?) and not can_write_policy(?)", Boolean.class, judgeShared.policy(), judgeShared.policy())).isTrue();
            assertThat(jdbc.update("update policies set title='forged' where id=?", judgeShared.policy())).isZero();
            return null;
        });
        assertThat(jdbc.queryForObject("select has_table_privilege(current_user,'demo_access','SELECT,INSERT,UPDATE,DELETE,TRUNCATE') or has_table_privilege(current_user,'demo_meta_budget','SELECT,INSERT,UPDATE,DELETE,TRUNCATE') or has_function_privilege(current_user,'reserve_demo_work(text,bigint)','EXECUTE')", Boolean.class)).isFalse();
        try {
            admin.execute("alter table policies no force row level security");
            assertThat(preflight(8)).isNotZero();
        } finally { admin.execute("alter table policies force row level security"); }
        try {
            admin.execute("alter role investigator_owner bypassrls");
            assertThat(preflight(8)).isNotZero();
        } finally { admin.execute("alter role investigator_owner nobypassrls"); }
        assertThat(preflight(8)).isZero();
    }

    void successfulTransport(Fixture f) {
        when(transport.send(anyString(), anyString(), any())).thenAnswer(inv -> reply(inv.getArgument(1), f));
    }

    MetaTransport.Reply reply(String payload, Fixture f) {
            var envelope = JsonContract.parse(payload);
            var input = JsonContract.parse(envelope.path("messages").get(1).path("content").asString());
            Object content;
            if (envelope.path("response_format").path("json_schema").path("name").asString().equals("requirements_v1")) {
                var src = input.path("sources").get(0);
                content = Map.of("requirements", List.of(StructuredValidationTest.requirement(src.path("sourceId").asString(), TEXT)),
                        "processedSourceIds", List.of(src.path("sourceId").asString()), "complete", true, "limitations", List.of());
            } else content = assessment(f);
            return new MetaTransport.Reply(200, JsonContract.encode(Map.of("model", "muse-spark-1.3", "choices", List.of(Map.of("finish_reason", "stop", "message", Map.of("content", JsonContract.encode(content)))),
                    "usage", Map.of("prompt_tokens", 5, "completion_tokens", 5, "total_tokens", 10))));
    }

    InvestigationWorker.Lease claim(Fixture f) {
        admin.update("update investigation_jobs set created_at=now()-interval '1 year' where id=?", f.id());
        var lease = worker.claim();
        assertThat(lease.id()).isEqualTo(f.id());
        return lease;
    }

    @Test @Order(4)
    void pendingV7WorkCompletesAsynchronouslyIncludingPrivateAndReadonlyJudges() throws Exception {
        for (var f : List.of(queued, judgePrivate, judgeShared)) {
            reset(transport);
            successfulTransport(f);
            var lease = claim(f);
            CompletableFuture.runAsync(() -> worker.process(lease)).get(30, TimeUnit.SECONDS);
            assertThat(service.progress(f.actor(), f.id())).containsEntry("state", "COMPLETED").containsEntry("calls", 4);
            verify(transport, times(4)).send(anyString(), anyString(), any());
            if (f != queued) assertThat(admin.queryForMap("select investigations,meta_attempts from demo_access where user_id=?", f.actor()))
                    .containsEntry("investigations", 1).containsEntry("meta_attempts", 4L);
        }
        assertThat(admin.queryForObject("select attempts from demo_meta_budget", Integer.class)).isEqualTo(8);
    }

    @Test @Order(5)
    void runningV7LeaseIsNotStolenThenRecoversItsCheckpointWithoutDoubleBilling() throws Exception {
        reset(transport);
        successfulTransport(running);
        // The unexpired lease cannot be claimed by the new process.
        admin.update("update investigation_jobs set created_at=now()-interval '2 years' where id=?", running.id());
        try (var c = runtime(running.actor()); var p = c.prepareStatement("select id from claim_investigation(600)")) {
            try (var r = p.executeQuery()) { while (r.next()) assertThat(r.getObject(1)).isNotEqualTo(running.id()); }
            c.rollback();
        }
        String checkpoint = admin.queryForObject("select payload::text from requirement_extractions where investigation_id=?", String.class, running.id());
        var deadline = admin.queryForObject("select deadline_at from investigation_jobs where id=?", java.sql.Timestamp.class, running.id());
        admin.update("update investigation_jobs set lease_until=now()-interval '1 second' where id=?", running.id());
        var lease = claim(running);
        assertThat(lease.token()).isNotEqualTo(oldLease);
        assertThat(lease.deadline()).isEqualTo(deadline.toInstant());
        assertThat(jdbc.queryForObject("select finish_investigation(?,?,'COMPLETED',null)", Boolean.class, running.id(), oldLease)).isFalse();
        CompletableFuture.runAsync(() -> worker.process(lease)).get(30, TimeUnit.SECONDS);
        assertThat(service.progress(running.actor(), running.id())).containsEntry("state", "COMPLETED").containsEntry("calls", 4).containsEntry("attempts", 2);
        assertThat(admin.queryForObject("select payload::text from requirement_extractions where investigation_id=? and version_id=?", String.class, running.id(), running.baseline())).isEqualTo(checkpoint);
        verify(transport, times(3)).send(anyString(), anyString(), any());
    }

    @Test @Order(6)
    void queuedV7RevocationAndConcurrentRevocationBlockTransportAndPersistence() throws Exception {
        reset(transport);
        admin.update("delete from memberships where user_id=?", revoked.actor());
        var revokedLease = claim(revoked);
        CompletableFuture.runAsync(() -> worker.process(revokedLease)).get(30, TimeUnit.SECONDS);
        verifyNoInteractions(transport);
        assertThat(admin.queryForMap("select state,calls from investigation_jobs where id=?", revoked.id()))
                .containsEntry("state", "FAILED").containsEntry("calls", 0);
        var entered = new CountDownLatch(1);
        var release = new CountDownLatch(1);
        when(transport.send(anyString(), anyString(), any())).thenAnswer(inv -> {
            entered.countDown();
            assertThat(release.await(15, TimeUnit.SECONDS)).isTrue();
            return reply(inv.getArgument(1), inFlight);
        });
        var lease = claim(inFlight);
        var processing = CompletableFuture.runAsync(() -> worker.process(lease));
        try {
            assertThat(entered.await(15, TimeUnit.SECONDS)).isTrue();
            admin.update("delete from policy_grants where policy_id=?", inFlight.procedurePolicy());
        } finally { release.countDown(); }
        processing.get(30, TimeUnit.SECONDS);
        verify(transport, times(1)).send(anyString(), anyString(), any());
        assertThat(admin.queryForObject("select count(*) from requirement_extractions where investigation_id=?", Integer.class, inFlight.id())).isZero();
        assertThat(admin.queryForObject("select count(*) from investigation_assessments where investigation_id=?", Integer.class, inFlight.id())).isZero();
        assertThat(admin.queryForMap("select state,calls from investigation_jobs where id=?", inFlight.id())).containsEntry("state", "FAILED").containsEntry("calls", 1);
        assertThat(admin.queryForObject("select meta_attempts from demo_access where user_id=?", Integer.class, inFlight.actor())).isEqualTo(1);
    }
}
