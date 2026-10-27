package com.tewendelabs.investigator.config;

import java.util.Map;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.WebApplicationType;
import org.springframework.context.annotation.Configuration;

/** Resolves real Spring configuration without starting a web server, database or model. */
public final class ConfigurationCheck {
    @Configuration(proxyBeanMethods = false)
    public static class MinimalConfiguration {}

    public static int run(boolean verifyMeta) throws Exception {

        SpringApplication app = new SpringApplication(MinimalConfiguration.class);
        app.setWebApplicationType(WebApplicationType.NONE);
        app.setLogStartupInfo(false);
        app.setDefaultProperties(Map.of("spring.main.banner-mode", "off", "logging.level.root", "ERROR"));

        try (var context = app.run()) {
            String key = context.getEnvironment().getProperty("meta.api.key", "");
            boolean configured = !key.isBlank() && !key.startsWith("replace-with-");
            System.out.println("MODEL_API_KEY available to Spring: " + configured);
            System.out.println("Root dotenv file detected: " + java.nio.file.Files.isRegularFile(java.nio.file.Path.of(".env")));
            System.out.println("MODEL_API_KEY property present: " + context.getEnvironment().containsProperty("MODEL_API_KEY"));
            System.out.println("Application properties loaded: " + "ai-policy-investigator".equals(context.getEnvironment().getProperty("spring.application.name")));
            if (verifyMeta && configured) {
                // Pass the exact Spring-resolved value in the child's environment, never argv or stdout.
                // This avoids introducing a second dotenv parser with different precedence/quoting rules.
                ProcessBuilder probe = new ProcessBuilder("python3", "-B", "scripts/verify_meta_access.py").inheritIO();
                probe.environment().put("MODEL_API_KEY", key);
                String model = context.getEnvironment().getProperty("META_MODEL_ID");
                if (model != null) probe.environment().put("META_MODEL_ID", model);
                return probe.start().waitFor();
            }
            return configured ? 0 : 2;
        }
    }
}
