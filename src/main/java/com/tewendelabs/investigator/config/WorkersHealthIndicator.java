package com.tewendelabs.investigator.config;

import java.util.List;
import com.tewendelabs.investigator.ingestion.EmbeddingGateway;
import com.tewendelabs.investigator.ingestion.IngestionWorker;
import com.tewendelabs.investigator.investigation.InvestigationWorker;
import com.tewendelabs.investigator.security.DatabaseSafetyCheck;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.boot.health.contributor.Health;
import org.springframework.boot.health.contributor.HealthIndicator;
import org.springframework.stereotype.Component;

/** Included in the existing private health endpoint. Never calls the paid provider. */
@Component("workers")
@ConditionalOnProperty(name = "app.worker-health.enabled", havingValue = "true")
public class WorkersHealthIndicator implements HealthIndicator {
    private final IngestionWorker ingestion;
    private final InvestigationWorker investigation;
    private final EmbeddingGateway embeddings;
    private final DatabaseSafetyCheck safety;
    private final boolean providerConfigured;
    private long checkedAt;
    private boolean embeddingReady;

    public WorkersHealthIndicator(IngestionWorker ingestion, InvestigationWorker investigation,
            EmbeddingGateway embeddings, DatabaseSafetyCheck safety, @Value("${meta.api.key:}") String key) {
        this.ingestion = ingestion;
        this.investigation = investigation;
        this.embeddings = embeddings;
        this.safety = safety;
        this.providerConfigured = !key.isBlank();
    }

    @Override
    public synchronized Health health() {
        if (!safety.ready() || !providerConfigured || !ingestion.operational() || !investigation.operational())
            return Health.down().build();
        long now = System.nanoTime();
        if (checkedAt == 0 || now - checkedAt > (embeddingReady ? 60L : 10L) * 1_000_000_000L) {
            embeddingReady = false;
            try {
                var vectors = embeddings.embed(List.of("Worker readiness probe"));
                embeddingReady = vectors.size() == 1;
            } catch (RuntimeException ignored) {
                // Health details and exceptions must never expose configuration or document data.
            }
            checkedAt = System.nanoTime();
        }
        return (embeddingReady ? Health.up() : Health.down()).build();
    }
}
