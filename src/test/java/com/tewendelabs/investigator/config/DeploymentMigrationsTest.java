package com.tewendelabs.investigator.config;

import org.flywaydb.core.Flyway;
import org.flywaydb.core.api.MigrationInfo;
import org.flywaydb.core.api.MigrationInfoService;
import org.flywaydb.core.api.MigrationState;
import org.junit.jupiter.api.Test;
import static org.assertj.core.api.Assertions.*;
import static org.mockito.Mockito.*;

class DeploymentMigrationsTest {
    @Test
    void validatesExistingSchemaWithoutEverMigrating() {
        Flyway flyway = mock(Flyway.class);
        MigrationInfoService info = mock(MigrationInfoService.class);
        MigrationInfo migration = mock(MigrationInfo.class);
        when(flyway.info()).thenReturn(info);
        when(info.current()).thenReturn(migration);
        when(info.pending()).thenReturn(new MigrationInfo[0]);
        when(info.all()).thenReturn(new MigrationInfo[]{migration});
        when(migration.getState()).thenReturn(MigrationState.SUCCESS);
        new DeploymentMigrations().validateExistingSchema().migrate(flyway);
        verify(flyway).validate();
        verify(flyway, never()).migrate();
    }

    @Test
    void rejectsEmptyPendingFailedAndFutureSchemas() {
        for (MigrationState state : new MigrationState[]{MigrationState.PENDING, MigrationState.FAILED, MigrationState.FUTURE_SUCCESS}) {
            Flyway flyway = mock(Flyway.class);
            MigrationInfoService info = mock(MigrationInfoService.class);
            MigrationInfo migration = mock(MigrationInfo.class);
            when(flyway.info()).thenReturn(info);
            when(info.current()).thenReturn(migration);
            when(info.pending()).thenReturn(new MigrationInfo[0]);
            when(info.all()).thenReturn(new MigrationInfo[]{migration});
            when(migration.getState()).thenReturn(state);
            assertThatThrownBy(() -> new DeploymentMigrations().validateExistingSchema().migrate(flyway))
                    .isInstanceOf(IllegalStateException.class);
            verify(flyway, never()).migrate();
        }
        Flyway flyway = mock(Flyway.class);
        when(flyway.info()).thenReturn(mock(MigrationInfoService.class));
        assertThatThrownBy(() -> new DeploymentMigrations().validateExistingSchema().migrate(flyway))
                .isInstanceOf(IllegalStateException.class);
        verify(flyway, never()).migrate();
    }

    @Test
    void validationFailureStopsBeforeAnyMigrationOrInfo() {
        Flyway flyway = mock(Flyway.class);
        doThrow(new IllegalStateException("synthetic checksum failure")).when(flyway).validate();
        assertThatThrownBy(() -> new DeploymentMigrations().validateExistingSchema().migrate(flyway))
                .isInstanceOf(IllegalStateException.class);
        verify(flyway, never()).migrate();
        verify(flyway, never()).info();
    }
}
