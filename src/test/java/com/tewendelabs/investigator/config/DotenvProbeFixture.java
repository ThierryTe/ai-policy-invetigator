package com.tewendelabs.investigator.config;

import java.util.Map;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.WebApplicationType;

/** Child-process fixture: fixed test markers only, never real credentials. */
public final class DotenvProbeFixture {
    public static void main(String[] args) {
        SpringApplication app = new SpringApplication(ConfigurationCheck.MinimalConfiguration.class);
        app.setWebApplicationType(WebApplicationType.NONE);
        app.setLogStartupInfo(false);
        app.setDefaultProperties(Map.of("spring.config.location", "optional:file:./application.properties",
                "spring.main.banner-mode", "off", "logging.level.root", "ERROR"));
        try (var context = app.run()) {
            String expected = switch (args[0]) {
                case "file" -> "dotenv-test-marker";
                case "process" -> "process-test-marker";
                default -> "";
            };
            boolean matches = expected.equals(context.getEnvironment().getProperty("meta.api.key", ""));
            if (args.length > 1) matches &= operationalSettings(context.getEnvironment(), args[1]);
            boolean notExported = System.getProperty("MODEL_API_KEY") == null
                    && System.getProperty("APP_DB_PASSWORD") == null && System.getProperty("JWT_SECRET") == null;
            System.out.println(matches && notExported ? "CONFIGURATION_CHECK_PASSED" : "CONFIGURATION_CHECK_FAILED");
            System.exit(matches && notExported ? 0 : 3);
        }
    }

    private static boolean operationalSettings(org.springframework.core.env.Environment environment, String mode) {
        var expected = new java.util.LinkedHashMap<>(Map.ofEntries(
                Map.entry("spring.datasource.url", "jdbc:postgresql://localhost:6543/synthetic_config"),
                Map.entry("spring.datasource.username", "runtime-fixture"),
                Map.entry("spring.datasource.password", "dotenv-runtime-marker"),
                Map.entry("spring.flyway.user", "owner-fixture"),
                Map.entry("spring.flyway.password", "dotenv-owner-marker"),
                Map.entry("spring.datasource.hikari.maximum-pool-size", "3"),
                Map.entry("app.jwt.secret", "dotenv-jwt-marker-at-least-32-characters"),
                Map.entry("app.jwt.issuer", "fixture-issuer"),
                Map.entry("app.jwt.audience", "fixture-audience"),
                Map.entry("spring.servlet.multipart.max-file-size", "7MB"),
                Map.entry("spring.servlet.multipart.max-request-size", "8MB"),
                Map.entry("app.worker.enabled", "false"),
                Map.entry("app.investigation.worker-enabled", "false"),
                Map.entry("app.investigation.budget-seconds", "180"),
                Map.entry("meta.model", "fixture-model"),
                Map.entry("meta.timeout-seconds", "12"),
                Map.entry("meta.max-retries", "1"),
                Map.entry("meta.concurrency", "1"),
                Map.entry("spring.jpa.open-in-view", "false"),
                Map.entry("server.error.include-message", "never"),
                Map.entry("springdoc.api-docs.enabled", "false"),
                Map.entry("logging.level.org.hibernate.orm.jdbc.bind", "OFF")));
        if (mode.equals("process-settings")) {
            expected.put("spring.datasource.password", "process-runtime-marker");
            expected.put("spring.datasource.hikari.maximum-pool-size", "4");
            expected.put("app.jwt.audience", "process-audience");
            expected.put("meta.timeout-seconds", "15");
        }
        return expected.entrySet().stream().allMatch(entry -> entry.getValue().equals(environment.getProperty(entry.getKey())));
    }
}
