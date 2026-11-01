package com.tewendelabs.investigator.config;

import java.util.List;
import com.tewendelabs.investigator.ingestion.*;
import com.tewendelabs.investigator.investigation.*;
import com.tewendelabs.investigator.provider.PolicyReasoningProvider;
import com.tewendelabs.investigator.security.*;
import io.micrometer.core.instrument.simple.SimpleMeterRegistry;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;

class WorkerPollingTest {
    @Test void ingestionRequiresSuccessfulQueuePollAndEnabledExecutor() throws Exception {
        JdbcTemplate jdbc = mock(JdbcTemplate.class);
        DatabaseSafetyCheck safety = mock(DatabaseSafetyCheck.class);
        when(safety.ready()).thenReturn(true);
        when(jdbc.query(anyString(), org.mockito.ArgumentMatchers.<RowMapper<IngestionWorker.Lease>>any())).thenReturn(List.of());
        var worker = new IngestionWorker(jdbc, mock(ScopedAccess.class), mock(PdfExtractor.class), mock(SourceChunker.class),
                mock(EmbeddingGateway.class), new SimpleMeterRegistry(), true, safety);
        try {
            assertThat(worker.operational()).isFalse();
            worker.dispatch();
            assertThat(worker.operational()).isTrue();
            var poll = IngestionWorker.class.getDeclaredField("lastSuccessfulPoll");
            poll.setAccessible(true);
            poll.setLong(worker, System.nanoTime() - 31_000_000_000L);
            assertThat(worker.operational()).isFalse();
            worker.dispatch();
            worker.close();
            assertThat(worker.operational()).isFalse();
        } finally { worker.close(); }
    }

    @Test void investigationPollFailuresNeverBecomeReady() throws Exception {
        JdbcTemplate jdbc = mock(JdbcTemplate.class);
        DatabaseSafetyCheck safety = mock(DatabaseSafetyCheck.class);
        when(safety.ready()).thenReturn(true);
        when(jdbc.query(anyString(), org.mockito.ArgumentMatchers.<RowMapper<InvestigationWorker.Lease>>any(), eq(240)))
                .thenThrow(new IllegalStateException("synthetic queue failure")).thenReturn(List.of());
        var worker = new InvestigationWorker(jdbc, mock(ScopedAccess.class), mock(InvestigationService.class),
                mock(PolicyReasoningProvider.class), safety, true, 240);
        try {
            worker.dispatch();
            assertThat(worker.operational()).isFalse();
            worker.dispatch();
            assertThat(worker.operational()).isTrue();
            var poll = InvestigationWorker.class.getDeclaredField("lastSuccessfulPoll");
            poll.setAccessible(true);
            poll.setLong(worker, System.nanoTime() - 31_000_000_000L);
            assertThat(worker.operational()).isFalse();
        } finally { worker.close(); }
    }

    @Test void disabledWorkersDoNotClaimWorkOrReportReady() {
        JdbcTemplate jdbc = mock(JdbcTemplate.class);
        DatabaseSafetyCheck safety = mock(DatabaseSafetyCheck.class);
        when(safety.ready()).thenReturn(true);
        var ingestion = new IngestionWorker(jdbc, mock(ScopedAccess.class), mock(PdfExtractor.class), mock(SourceChunker.class),
                mock(EmbeddingGateway.class), new SimpleMeterRegistry(), false, safety);
        var investigation = new InvestigationWorker(jdbc, mock(ScopedAccess.class), mock(InvestigationService.class),
                mock(PolicyReasoningProvider.class), safety, false, 240);
        try {
            ingestion.dispatch();
            investigation.dispatch();
            assertThat(ingestion.operational()).isFalse();
            assertThat(investigation.operational()).isFalse();
            verifyNoInteractions(jdbc);
        } finally { ingestion.close(); investigation.close(); }
    }
}
