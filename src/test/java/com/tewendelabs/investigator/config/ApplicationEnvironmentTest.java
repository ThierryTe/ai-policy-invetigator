package com.tewendelabs.investigator.config;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Arrays;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.TimeUnit;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import static org.assertj.core.api.Assertions.assertThat;

/** Exercises actual application mappings in isolated JVMs using synthetic values only. */
class ApplicationEnvironmentTest {
    @TempDir Path directory;

    private void verify(String mode, Map<String,String> overrides) throws Exception {
        Files.copy(Path.of("src/main/resources/application.properties"),directory.resolve("application.properties"));
        String fixture="""
                MODEL_API_KEY=dotenv-test-marker
                DB_URL=jdbc:postgresql://localhost:6543/synthetic_config
                APP_DB_USERNAME=runtime-fixture
                APP_DB_PASSWORD=dotenv-runtime-marker
                OWNER_DB_USERNAME=owner-fixture
                OWNER_DB_PASSWORD=dotenv-owner-marker
                DB_POOL_MAX_SIZE=3
                JWT_SECRET=dotenv-jwt-marker-at-least-32-characters
                JWT_ISSUER=fixture-issuer
                JWT_AUDIENCE=fixture-audience
                UPLOAD_MAX_FILE_SIZE=7MB
                UPLOAD_MAX_REQUEST_SIZE=8MB
                APP_WORKER_ENABLED=false
                APP_INVESTIGATION_WORKER_ENABLED=false
                META_MODEL_ID=fixture-model
                META_TIMEOUT_SECONDS=12
                META_MAX_RETRIES=1
                META_CONCURRENCY=1
                META_INVESTIGATION_BUDGET_SECONDS=180
                """;
        Files.writeString(directory.resolve(".env"),fixture);
        Set<String> keys=fixture.lines().filter(line->line.contains("=")).map(line->line.split("=",2)[0]).collect(java.util.stream.Collectors.toSet());
        String classpath=Arrays.stream(System.getProperty("java.class.path").split(java.io.File.pathSeparator)).map(p->Path.of(p).toAbsolutePath().toString()).collect(java.util.stream.Collectors.joining(java.io.File.pathSeparator));
        Path output=directory.resolve("result.log");
        ProcessBuilder builder=new ProcessBuilder(Path.of(System.getProperty("java.home"),"bin","java").toString(),"-cp",classpath,DotenvProbeFixture.class.getName(),"file",mode)
                .directory(directory.toFile()).redirectErrorStream(true).redirectOutput(output.toFile());
        builder.environment().keySet().removeIf(key->keys.contains(key)||key.startsWith("SPRINGDOTENV_")||key.startsWith("SPRING_CONFIG_")||key.startsWith("SPRING_PROFILES_"));
        builder.environment().put("SPRINGDOTENV_ENABLED","true");
        builder.environment().putAll(overrides);
        Process child=builder.start();
        try {
            assertThat(child.waitFor(30,TimeUnit.SECONDS)).isTrue();
            assertThat(child.exitValue()).isZero();
            assertThat(Files.readString(output)).contains("CONFIGURATION_CHECK_PASSED");
        } finally {if(child.isAlive())child.destroyForcibly();}
    }

    @Test void actualApplicationPropertiesResolveRootDotenvSettings() throws Exception {verify("file-settings",Map.of());}
    @Test void processValuesOverrideFileForCredentialsAndOperationalSettings() throws Exception {
        verify("process-settings",Map.of("APP_DB_PASSWORD","process-runtime-marker","DB_POOL_MAX_SIZE","4","JWT_AUDIENCE","process-audience","META_TIMEOUT_SECONDS","15"));
    }
}
