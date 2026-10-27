package com.tewendelabs.investigator.documentation;

import java.sql.Connection;
import java.time.Instant;
import java.util.List;
import java.util.UUID;

import org.junit.jupiter.api.Tag;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.security.oauth2.jose.jws.MacAlgorithm;
import org.springframework.security.oauth2.jwt.*;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.ai.embedding.EmbeddingModel;
import org.testcontainers.containers.PostgreSQLContainer;
import org.testcontainers.utility.DockerImageName;
import com.tewendelabs.investigator.provider.MetaTransport;

@Tag("database")
@SpringBootTest(properties = {"app.worker.enabled=false", "app.investigation.worker-enabled=false",
        "meta.api.key=documentation-fixture-only", "app.embedding.verify-artifacts=false",
        "spring.ai.model.embedding=none", "app.embedding.revision=synthetic-docs-v1"})
@AutoConfigureMockMvc(print = org.springframework.boot.webmvc.test.autoconfigure.MockMvcPrint.NONE)
abstract class DocumentationDatabaseSupport {
    private static final String OWNER = UUID.randomUUID().toString(), APP = UUID.randomUUID().toString(), JWT = UUID.randomUUID() + UUID.randomUUID().toString();
    private static final PostgreSQLContainer<?> POSTGRES = new PostgreSQLContainer<>(DockerImageName.parse("pgvector/pgvector:0.8.0-pg16").asCompatibleSubstituteFor("postgres"))
            .withDatabaseName("investigator_documentation_test").withPassword(UUID.randomUUID().toString());
    private static boolean initialized;
    static JdbcTemplate admin;
    @Autowired
    MockMvc mvc;
    @Autowired
    JwtEncoder encoder;
    @MockitoBean
    MetaTransport metaTransport;
    @MockitoBean
    EmbeddingModel embeddings;

    @DynamicPropertySource
    static synchronized void database(DynamicPropertyRegistry props) throws Exception {
        if (!initialized) {
            POSTGRES.start();
            admin = new JdbcTemplate(new DriverManagerDataSource(POSTGRES.getJdbcUrl(), POSTGRES.getUsername(), POSTGRES.getPassword()));
            try (Connection c = admin.getDataSource().getConnection()) {
                try (var p = c.prepareStatement("select set_config('test.owner_password',?,false),set_config('test.app_password',?,false)")) {
                    p.setString(1, OWNER);
                    p.setString(2, APP);
                    p.execute();
                }
                c.createStatement().execute("""
                        CREATE ROLE investigator_runtime NOLOGIN NOSUPERUSER NOBYPASSRLS;
                        DO $$ BEGIN
                         EXECUTE format('CREATE ROLE investigator_owner LOGIN NOSUPERUSER NOBYPASSRLS PASSWORD %L',current_setting('test.owner_password'));
                         EXECUTE format('CREATE ROLE investigator_app LOGIN NOSUPERUSER NOBYPASSRLS PASSWORD %L',current_setting('test.app_password'));
                        END $$;
                        GRANT investigator_runtime TO investigator_app;
                        ALTER DATABASE investigator_documentation_test OWNER TO investigator_owner;
                        ALTER SCHEMA public OWNER TO investigator_owner;
                        REVOKE CREATE ON SCHEMA public FROM PUBLIC;
                        CREATE EXTENSION vector;
                        CREATE EXTENSION pgcrypto;
                        """);
            } catch (Exception e) {
                throw new IllegalStateException("Isolated documentation database initialization failed");
            }
            initialized = true;
        }
        props.add("spring.datasource.url", POSTGRES::getJdbcUrl);
        props.add("spring.datasource.password", () -> APP);
        props.add("spring.flyway.url", POSTGRES::getJdbcUrl);
        props.add("spring.flyway.password", () -> OWNER);
        props.add("app.jwt.secret", () -> JWT);
    }

    record Actor(String token, UUID hiddenPolicy, String hiddenTitle) {
    }

    Actor actor() {
        UUID organization = UUID.randomUUID(), department = UUID.randomUUID(), other = UUID.randomUUID(), user = UUID.randomUUID(), hidden = UUID.randomUUID();
        String hiddenTitle = "Private fixture " + UUID.randomUUID();
        admin.update("insert into organizations values(?,?)", organization, "Synthetic documentation fixture");
        admin.update("insert into departments values(?,?,?),(?,?,?)", department, organization, "Reader", other, organization, "Hidden");
        admin.update("insert into app_users(id,organization_id,email,password_hash) values(?,?,?,?)", user, organization, user + "@test.invalid", "non-login-fixture");
        admin.update("insert into memberships values(?,?,'VIEWER')", user, department);
        admin.update("insert into policies(id,organization_id,department_id,title,kind) values(?,?,?,?,'POLICY')", hidden, organization, other, hiddenTitle);
        var claims = JwtClaimsSet.builder().issuer("ai-policy-investigator").audience(List.of("policy-api")).subject(user.toString()).issuedAt(Instant.now()).expiresAt(Instant.now().plusSeconds(120)).build();
        String token = encoder.encode(JwtEncoderParameters.from(JwsHeader.with(MacAlgorithm.HS256).build(), claims)).getTokenValue();
        return new Actor(token, hidden, hiddenTitle);
    }
}
