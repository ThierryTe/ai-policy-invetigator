package com.tewendelabs.investigator.ingestion;

import java.util.*;
import java.util.concurrent.*;
import java.util.concurrent.atomic.AtomicInteger;

import jakarta.annotation.PreDestroy;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;
import io.micrometer.core.instrument.MeterRegistry;
import io.micrometer.core.instrument.Timer;
import com.tewendelabs.investigator.api.ApiFailure;
import com.tewendelabs.investigator.security.ScopedAccess;

@Component
public class IngestionWorker {
    public record Lease(UUID id, UUID versionId, UUID requestedBy, UUID token) { }

    private final JdbcTemplate jdbc;
    private final ScopedAccess scope;
    private final PdfExtractor extractor;
    private final SourceChunker chunker;
    private final EmbeddingGateway embeddings;
    private final MeterRegistry metrics;
    private final boolean enabled;
    private final com.tewendelabs.investigator.security.DatabaseSafetyCheck safety;
    private final ExecutorService executor = Executors.newFixedThreadPool(2);
    private final AtomicInteger active = new AtomicInteger();
    private volatile long lastSuccessfulPoll;

    public IngestionWorker(JdbcTemplate jdbc, ScopedAccess scope, PdfExtractor extractor, SourceChunker chunker, EmbeddingGateway embeddings, MeterRegistry metrics, @Value("${app.worker.enabled:true}") boolean enabled, com.tewendelabs.investigator.security.DatabaseSafetyCheck safety) {
        this.jdbc = jdbc;
        this.scope = scope;
        this.extractor = extractor;
        this.chunker = chunker;
        this.embeddings = embeddings;
        this.metrics = metrics;
        this.enabled = enabled;
        this.safety = safety;
    }

    @Scheduled(fixedDelay = 1000)
    public void dispatch() {
        if (!safety.ready() || !enabled || active.get() >= 2) return;
        Lease lease = claim();
        lastSuccessfulPoll = System.nanoTime();
        if (lease == null) return;
        active.incrementAndGet();
        try {
            executor.submit(() -> {
                try {
                    process(lease);
                } finally {
                    active.decrementAndGet();
                }
            });
        } catch (RejectedExecutionException e) {
            active.decrementAndGet(); /* lease will expire and recover */
        }
    }

    public Lease claim() {
        return jdbc.query("select * from claim_ingestion()", (r, n) -> new Lease(r.getObject("id", UUID.class), r.getObject("version_id", UUID.class), r.getObject("requested_by", UUID.class), r.getObject("lease_token", UUID.class)))
                .stream().findFirst().orElse(null);
    }

    public boolean operational() {
        // Allow the bounded PDF/embedding work to finish when both slots are busy.
        long grace = active.get() >= 2 ? 180L : 30L;
        return enabled && safety.ready() && !executor.isShutdown() && lastSuccessfulPoll != 0
                && System.nanoTime() - lastSuccessfulPoll < grace * 1_000_000_000L;
    }

    public void process(Lease lease) {
        Timer.Sample sample = Timer.start(metrics);
        String outcome = "completed";
        try {
            byte[] pdf = scope.as(lease.requestedBy(), () -> authorizedPdf(lease.versionId()));
            var pages = extractor.extract(pdf);
            var spans = chunker.chunk(pages);
            List<float[]> vectors = new ArrayList<>();
            long deadline = System.nanoTime() + 120_000_000_000L;
            for (int start = 0; start < spans.size(); start += 32) {
                if (System.nanoTime() > deadline) throw new ApiFailure(503, "PROCESSING_FAILED");
                scope.as(lease.requestedBy(), () -> {
                    requireWritable(lease.versionId());
                    return null;
                });
                heartbeat(lease, "EMBEDDING");
                var batch = spans.subList(start, Math.min(start + 32, spans.size()));
                vectors.addAll(embeddings.embed(batch.stream().map(SourceChunker.Span::text).toList()));
            }
            heartbeat(lease, "PERSISTING");
            scope.as(lease.requestedBy(), () -> {
                requireWritable(lease.versionId());
                for (var page : pages)
                    jdbc.update("insert into document_pages(version_id,page_number,text) values(?,?,?)", lease.versionId(), page.number(), page.text());
                for (int i = 0; i < spans.size(); i++) {
                    var span = spans.get(i);
                    jdbc.update("insert into chunks(id,version_id,page_number,start_offset,end_offset,content,embedding,embedding_revision) values(?,?,?,?,?,?,cast(? as vector),?)",
                            span.id(), lease.versionId(), span.page(), span.start(), span.end(), span.text(), EmbeddingGateway.vectorLiteral(vectors.get(i)), embeddings.revision);
                }
                if (jdbc.update("update policy_versions set status='INDEXED' where id=? and status='QUEUED'", lease.versionId()) != 1)
                    throw new ApiFailure(409, "PROCESSING_FAILED");
                if (!finish(lease, null))
                    throw new ApiFailure(409, "PROCESSING_FAILED"); // rollback every source/vector if lease lost
                return null;
            });
        } catch (RuntimeException e) {
            outcome = "failed";
            String code = e instanceof ApiFailure a ? switch (a.code) {
                case "NOT_FOUND", "UNAUTHENTICATED" -> "ACCESS_REVOKED";
                case "INVALID_PDF", "UNSUPPORTED_PDF", "EMPTY_TEXT", "EMBEDDING_FAILED" -> a.code;
                default -> "PROCESSING_FAILED";
            } : "PROCESSING_FAILED";
            try {
                // Mark version failed only under the original actor's current WRITE authorization.
                scope.as(lease.requestedBy(), () -> {
                    if (!finish(lease, code)) return null;
                    jdbc.update("update policy_versions set status='FAILED' where id=? and status='QUEUED'", lease.versionId());
                    return null;
                });
            } catch (RuntimeException revoked) {
                finish(lease, code);
            }
        } finally {
            sample.stop(Timer.builder("ingestion.duration").tag("outcome", outcome).register(metrics));
        }
    }

    private byte[] authorizedPdf(UUID version) {
        requireWritable(version);
        return jdbc.query("select original_pdf from policy_versions where id=?", (r, n) -> r.getBytes(1), version).stream().findFirst().orElseThrow(ApiFailure::missing);
    }

    private void requireWritable(UUID version) {
        Boolean allowed = jdbc.queryForObject("select exists(select 1 from policy_versions v where v.id=? and v.status='QUEUED' and can_write_policy(v.policy_id))", Boolean.class, version);
        if (!Boolean.TRUE.equals(allowed)) throw ApiFailure.missing();
    }

    private void heartbeat(Lease lease, String stage) {
        if (!Boolean.TRUE.equals(jdbc.queryForObject("select heartbeat_ingestion(?,?,?)", Boolean.class, lease.id(), lease.token(), stage)))
            throw new ApiFailure(409, "PROCESSING_FAILED");
    }

    private boolean finish(Lease lease, String code) {
        return Boolean.TRUE.equals(jdbc.queryForObject("select finish_ingestion(?,?,?)", Boolean.class, lease.id(), lease.token(), code));
    }

    @PreDestroy
    public void close() {
        executor.shutdownNow();
    }
}
