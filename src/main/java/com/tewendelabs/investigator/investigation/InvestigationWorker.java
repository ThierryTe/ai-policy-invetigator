package com.tewendelabs.investigator.investigation;

import java.time.*;
import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicBoolean;

import jakarta.annotation.PreDestroy;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;
import org.slf4j.LoggerFactory;
import com.tewendelabs.investigator.api.ApiFailure;
import com.tewendelabs.investigator.security.*;
import com.tewendelabs.investigator.provider.PolicyReasoningProvider;
import com.tewendelabs.investigator.provider.PolicyReasoningProvider.*;
import com.tewendelabs.investigator.policy.PolicyService;
import tools.jackson.databind.JsonNode;

@Component
public class InvestigationWorker {
    public record Lease(UUID id, UUID actor, UUID token, Instant deadline) {
    }

    private final JdbcTemplate jdbc;
    private final ScopedAccess access;
    private final InvestigationService service;
    private final PolicyReasoningProvider provider;
    private final DatabaseSafetyCheck safety;
    private final boolean enabled;
    private final int budgetSeconds;
    private final ExecutorService executor = Executors.newSingleThreadExecutor();
    private final AtomicBoolean active = new AtomicBoolean();

    public InvestigationWorker(JdbcTemplate jdbc, ScopedAccess access, InvestigationService service, PolicyReasoningProvider provider, DatabaseSafetyCheck safety, @Value("${app.investigation.worker-enabled:true}") boolean enabled, @Value("${app.investigation.budget-seconds:240}") int budgetSeconds) {
        if(budgetSeconds<30 || budgetSeconds>600)throw new IllegalArgumentException("Invalid investigation deadline budget");
        this.jdbc = jdbc;
        this.access = access;
        this.service = service;
        this.provider = provider;
        this.safety = safety;
        this.enabled = enabled;
        this.budgetSeconds = budgetSeconds;
    }

    @Scheduled(fixedDelay = 1000)
    public void dispatch() {
        if (!enabled || !safety.ready() || !active.compareAndSet(false, true)) return;
        try {
            Lease lease = claim();
            if (lease == null) {
                active.set(false);
                return;
            }
            executor.submit(() -> {
                try {
                    process(lease);
                } finally {
                    active.set(false);
                }
            });
        } catch (RuntimeException e) {
            active.set(false);
        }
    }

    public Lease claim() {
        return jdbc.query("select * from claim_investigation(?)", (r, n) -> new Lease(r.getObject("id", UUID.class), r.getObject("requested_by", UUID.class), r.getObject("lease_token", UUID.class), r.getTimestamp("deadline_at").toInstant()),budgetSeconds).stream().findFirst().orElse(null);
    }

    public void process(Lease lease) {
        boolean checkpointed = false;
        try {
            var snapshot = service.snapshot(lease.actor(), lease.id());
            Map<UUID, JsonNode> extracted = new LinkedHashMap<>();
            List<Source> allSources = new ArrayList<>();
            for (UUID version : snapshot.versions()) {
                service.requireRunnable(lease.actor(), lease.id());
                List<Source> sources = service.sources(lease.actor(), lease.id(), version);
                if (sources.isEmpty() || sources.size() > 20 || sources.stream().mapToInt(s -> s.excerpt().length()).sum() > 16000)
                    throw new ApiFailure(422, "SOURCE_COVERAGE_BUDGET_EXCEEDED");
                allSources.addAll(sources);
                String hash = PolicyService.sha256(JsonContract.encode(sources).getBytes(java.nio.charset.StandardCharsets.UTF_8));
                var prior = access.as(lease.actor(), () -> jdbc.queryForList("select payload::text,source_hash,model,prompt_version,schema_version from requirement_extractions where investigation_id=? and version_id=?", lease.id(), version));
                JsonNode data;
                if (!prior.isEmpty()) {
                    var row = prior.getFirst();
                    if (!hash.equals(row.get("source_hash")) || !provider.modelId().equals(row.get("model")) || !InvestigationSchemas.PROMPT.equals(row.get("prompt_version")) || !InvestigationSchemas.EXTRACTION.equals(row.get("schema_version")))
                        throw new ApiFailure(409, "EXTRACTION_CHECKPOINT_MISMATCH");
                    data = JsonContract.parse((String) row.get("payload"));
                } else {
                    String task = "Extract every explicit normative requirement in these sources. Fields not explicitly stated must be null and listed in unknownFields. Obligation uses MUST, MUST_NOT, SHOULD, or MAY. Preserve all exceptions and applicability. Copy each supplied sourceId into processedSourceIds after covering its entire excerpt. Analysis date: " + snapshot.date() + ". Document effective date: " + effectiveDate(lease, version) + ". The document date is metadata and may be used only if a requirement has no more specific effective date.";
                    Result result = provider.reason(request(lease, InvestigationSchemas.EXTRACTION, task, sources));
                    data = EvidenceValidator.extraction(result.content(), sources, lease.id(), version);
                    final JsonNode saved = data;
                    access.as(lease.actor(), () -> {
                        fence(lease, "EXTRACTING");
                        jdbc.update("insert into requirement_extractions(investigation_id,version_id,payload,source_hash,model,prompt_version,schema_version) values(?,?,cast(? as jsonb),?,?,?,?)", lease.id(), version, JsonContract.encode(saved), hash, result.model(), result.promptVersion(), result.schemaVersion());
                        return null;
                    });
                }
                checkpointed = true;
                if (!data.path("complete").asBoolean()) throw new ApiFailure(422, "INCOMPLETE_EXTRACTION");
                extracted.put(version, data);
            }
            if (allSources.stream().mapToInt(s -> s.excerpt().length()).sum() > 20000)
                throw new ApiFailure(422, "ASSESSMENT_CONTEXT_BUDGET_EXCEEDED");
            service.requireRunnable(lease.actor(), lease.id());
            access.as(lease.actor(), () -> {
                fence(lease, "ASSESSING");
                return null;
            });
            String task = "Compare baseline " + snapshot.baseline() + " with replacement " + snapshot.replacement() + ". Align ALL baseline/replacement requirement IDs and assess EVERY replacement requirement against EVERY selected procedure version " + snapshot.procedures() + ". Return one assessment per pair. Relevant authorized procedure requirements are retrieved in full for this bounded scope. Evaluate applicability at " + snapshot.date() + ". Extracted requirements by version: " + JsonContract.encode(extracted);
            Result result = provider.reason(request(lease, InvestigationSchemas.ASSESSMENT, task, allSources));
            EvidenceValidator.assessment(result.content(), snapshot, extracted, allSources);
            if (!result.content().path("complete").asBoolean()) throw new ApiFailure(422, "INCOMPLETE_ASSESSMENT");
            access.as(lease.actor(), () -> {
                fence(lease, "ASSESSING");
                jdbc.update("insert into investigation_assessments(id,investigation_id,payload,model,prompt_version,schema_version) values(?,?,cast(? as jsonb),?,?,?)", UUID.randomUUID(), lease.id(), JsonContract.encode(result.content()), result.model(), result.promptVersion(), result.schemaVersion());
                if (!finish(lease, "COMPLETED", null)) throw new ApiFailure(409, "LEASE_LOST");
                return null;
            });
        } catch (RuntimeException e) {
            String code = e instanceof ApiFailure a ? a.code : "INVESTIGATION_FAILED";
            if (code.equals("NOT_FOUND") || code.equals("UNAUTHENTICATED")) code = "ACCESS_OR_CONSENT_REVOKED";
            finish(lease, checkpointed ? "PARTIAL" : "FAILED", code);
        }
        LoggerFactory.getLogger(getClass()).info("investigation_event job_id={} event=attempt_finished", lease.id());
    }

    private java.sql.Date effectiveDate(Lease lease, UUID version) {
        return access.as(lease.actor(), () -> jdbc.queryForObject("select effective_date from policy_versions where id=?", java.sql.Date.class, version));
    }

    private Request request(Lease lease, String schema, String task, List<Source> sources) {
        Duration remaining = Duration.between(Instant.now(), lease.deadline());
        if (remaining.isNegative() || remaining.isZero()) throw new ApiFailure(504, "INVESTIGATION_DEADLINE_EXCEEDED");
        return new Request(lease.actor(), lease.id(), lease.token(), schema, task, sources, remaining);
    }

    private void fence(Lease lease, String stage) {
        if (!Boolean.TRUE.equals(jdbc.queryForObject("select checkpoint_investigation(?,?,?)", Boolean.class, lease.id(), lease.token(), stage)))
            throw new ApiFailure(403, "ACCESS_CONSENT_OR_LEASE_REVOKED");
    }

    private boolean finish(Lease lease, String state, String code) {
        return Boolean.TRUE.equals(jdbc.queryForObject("select finish_investigation(?,?,?,?)", Boolean.class, lease.id(), lease.token(), state, code));
    }

    @PreDestroy
    public void close() {
        executor.shutdownNow();
    }
}
