package com.tewendelabs.investigator.config;

import java.util.List;
import com.tewendelabs.investigator.ingestion.EmbeddingGateway;
import com.tewendelabs.investigator.ingestion.IngestionWorker;
import com.tewendelabs.investigator.investigation.InvestigationWorker;
import com.tewendelabs.investigator.security.DatabaseSafetyCheck;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.boot.health.contributor.Status;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

class WorkersHealthIndicatorTest {
    private final IngestionWorker ingestion = mock(IngestionWorker.class);
    private final InvestigationWorker investigation = mock(InvestigationWorker.class);
    private final EmbeddingGateway embeddings = mock(EmbeddingGateway.class);
    private final DatabaseSafetyCheck safety = mock(DatabaseSafetyCheck.class);

    @BeforeEach void ready() {
        when(safety.ready()).thenReturn(true);
        when(ingestion.operational()).thenReturn(true);
        when(investigation.operational()).thenReturn(true);
    }

    private WorkersHealthIndicator indicator(String key) {
        return new WorkersHealthIndicator(ingestion, investigation, embeddings, safety, key);
    }

    @Test void upRequiresRealLocalEmbeddingAndCachesIt() {
        when(embeddings.embed(anyList())).thenReturn(List.of(new float[384]));
        var health = indicator("synthetic-key");
        assertThat(health.health().getStatus()).isEqualTo(Status.UP);
        assertThat(health.health().getStatus()).isEqualTo(Status.UP);
        verify(embeddings, times(1)).embed(List.of("Worker readiness probe"));
    }

    @Test void missingMetaKeyDoesNotProbeOrCallAnyProvider() {
        assertThat(indicator(" ").health().getStatus()).isEqualTo(Status.DOWN);
        verifyNoInteractions(embeddings);
    }

    @Test void disabledStaleOrFailedWorkerAndUnsafeDatabaseAreDown() {
        when(ingestion.operational()).thenReturn(false);
        assertThat(indicator("synthetic-key").health().getStatus()).isEqualTo(Status.DOWN);
        when(ingestion.operational()).thenReturn(true);
        when(investigation.operational()).thenReturn(false);
        assertThat(indicator("synthetic-key").health().getStatus()).isEqualTo(Status.DOWN);
        when(investigation.operational()).thenReturn(true);
        when(safety.ready()).thenReturn(false);
        assertThat(indicator("synthetic-key").health().getStatus()).isEqualTo(Status.DOWN);
        verifyNoInteractions(embeddings);
    }

    @Test void failedEmbeddingIsDownWithoutLeakingExceptionDetails() {
        when(embeddings.embed(anyList())).thenThrow(new IllegalStateException("synthetic-private-value"));
        var result = indicator("synthetic-key").health();
        assertThat(result.getStatus()).isEqualTo(Status.DOWN);
        assertThat(result.getDetails()).isEmpty();
    }

    @Test void emptyEmbeddingResultIsDown() {
        when(embeddings.embed(anyList())).thenReturn(List.of());
        assertThat(indicator("synthetic-key").health().getStatus()).isEqualTo(Status.DOWN);
    }
}
