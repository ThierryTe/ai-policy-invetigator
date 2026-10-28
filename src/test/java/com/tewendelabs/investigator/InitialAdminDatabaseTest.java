package com.tewendelabs.investigator;

import java.io.StringReader;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.sql.Connection;
import java.sql.DriverManager;
import java.util.Base64;
import java.util.Map;
import java.util.UUID;

import com.tewendelabs.investigator.investigation.JsonContract;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Tag;
import org.junit.jupiter.api.Test;
import org.postgresql.PGConnection;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.testcontainers.containers.PostgreSQLContainer;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;
import org.testcontainers.utility.DockerImageName;

import static org.assertj.core.api.Assertions.*;

/** Disposable operations tests only; no Compose deployment or custom network creation. */
@Tag("database")
@Testcontainers
class InitialAdminDatabaseTest {
    @Container
    static final PostgreSQLContainer<?> POSTGRES = new PostgreSQLContainer<>(
            DockerImageName.parse("pgvector/pgvector:0.8.0-pg16").asCompatibleSubstituteFor("postgres"))
            .withDatabaseName("initial_admin_test").withUsername("postgres").withPassword(UUID.randomUUID().toString());

    Connection connection() throws Exception {
        return DriverManager.getConnection(POSTGRES.getJdbcUrl(), POSTGRES.getUsername(), POSTGRES.getPassword());
    }

    @BeforeEach
    void emptyIdentityStore() throws Exception {
        try (var c = connection()) {
            c.createStatement().execute("CREATE EXTENSION IF NOT EXISTS pgcrypto; DROP TABLE IF EXISTS memberships,app_users,departments,organizations CASCADE;");
            String migration = Files.readString(Path.of("src/main/resources/db/migration/V1__policy_foundation.sql"));
            c.createStatement().execute(migration.substring(0, migration.indexOf("CREATE TABLE policies")));
        }
    }

    void seed(String password) throws Exception {
        String template = Files.readString(Path.of("deploy/postgres/provision-initial-admin.sql"));
        String[] parts = template.split("-- INITIAL_ADMIN_INPUT --", -1);
        String payload = JsonContract.encode(Map.of("email", "initial-admin@test.invalid", "password", password,
                "organization", "Synthetic operator test", "department", "Policy analysis"));
        try (var c = connection()) {
            c.createStatement().execute(parts[0]);
            c.unwrap(PGConnection.class).getCopyAPI().copyIn("COPY pg_temp.initial_admin_input FROM STDIN",
                    new StringReader(Base64.getEncoder().encodeToString(payload.getBytes(StandardCharsets.UTF_8)) + "\n"));
            c.createStatement().execute(parts[1]);
        }
    }

    String hash() throws Exception {
        try (var c = connection(); var rs = c.createStatement().executeQuery("SELECT password_hash FROM app_users")) {
            assertThat(rs.next()).isTrue();
            return rs.getString(1);
        }
    }

    @Test
    void createsOnlyAnActiveDepartmentAdminWithSpringCompatiblePassword() throws Exception {
        String password = UUID.randomUUID().toString();
        seed(password);
        assertThat(new BCryptPasswordEncoder().matches(password, hash())).isTrue();
        try (var c = connection(); var rs = c.createStatement().executeQuery("""
                SELECT u.active,m.role,u.organization_id=d.organization_id AS same_org,
                       (SELECT count(*) FROM app_users) AS users,(SELECT count(*) FROM memberships) AS memberships
                FROM app_users u JOIN memberships m ON m.user_id=u.id JOIN departments d ON d.id=m.department_id
                """)) {
            assertThat(rs.next()).isTrue();
            assertThat(rs.getBoolean("active")).isTrue();
            assertThat(rs.getString("role")).isEqualTo("ADMIN");
            assertThat(rs.getBoolean("same_org")).isTrue();
            assertThat(rs.getInt("users")).isEqualTo(1);
            assertThat(rs.getInt("memberships")).isEqualTo(1);
        }
    }

    @Test
    void refusesExistingIdentityStoreWithoutChangingCredentials() throws Exception {
        seed(UUID.randomUUID().toString());
        String before = hash();
        assertThatThrownBy(() -> seed(UUID.randomUUID().toString())).hasMessageContaining("INITIAL_ADMIN_REQUIRES_EMPTY_IDENTITY_STORE");
        assertThat(hash()).isEqualTo(before);
    }

    @Test
    void invalidInputRollsBackWithoutCreatingAnyIdentity() throws Exception {
        assertThatThrownBy(() -> seed("short")).hasMessageContaining("INITIAL_ADMIN_INPUT_INVALID");
        try (var c = connection(); var rs = c.createStatement().executeQuery("SELECT count(*) FROM organizations")) {
            assertThat(rs.next()).isTrue();
            assertThat(rs.getInt(1)).isZero();
        }
    }
}
