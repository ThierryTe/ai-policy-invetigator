package com.tewendelabs.investigator.config;

import org.flywaydb.core.api.MigrationState;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.boot.flyway.autoconfigure.FlywayMigrationStrategy;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/** Routine image deployments validate the existing schema without modifying it. */
@Configuration
@ConditionalOnProperty(name = "app.migrations.validate-only", havingValue = "true")
public class DeploymentMigrations {
    @Bean
    FlywayMigrationStrategy validateExistingSchema() {
        return flyway -> {
            flyway.validate();
            var info = flyway.info();
            if (info.current() == null || info.pending().length != 0
                    || java.util.Arrays.stream(info.all()).anyMatch(m -> m.getState() != MigrationState.SUCCESS)) {
                throw new IllegalStateException("Schema changes require a separately reviewed migration; deployment only validates");
            }
        };
    }
}
