package com.tewendelabs.investigator.config;

import java.nio.file.*;
import java.util.*;
import java.util.concurrent.TimeUnit;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import static org.assertj.core.api.Assertions.*;

class DotenvConfigurationTest {
    @TempDir Path directory;

    private void verify(String expected, boolean file, Map<String,String> environment) throws Exception {
        Files.writeString(directory.resolve("application.properties"), "meta.api.key=${MODEL_API_KEY:}\nspringdotenv.enabled=false\nspringdotenv.ignore-if-missing=true\nspringdotenv.export-to-system-properties=false\n");
        if (file) Files.writeString(directory.resolve(".env"), "MODEL_API_KEY=dotenv-test-marker\n");
        String classpath = Arrays.stream(System.getProperty("java.class.path").split(java.io.File.pathSeparator))
                .map(p -> Path.of(p).toAbsolutePath().toString()).collect(java.util.stream.Collectors.joining(java.io.File.pathSeparator));
        Path output = directory.resolve("result.log");
        ProcessBuilder builder = new ProcessBuilder(Path.of(System.getProperty("java.home"),"bin","java").toString(),
                "-cp",classpath,DotenvProbeFixture.class.getName(),expected).directory(directory.toFile())
                .redirectErrorStream(true).redirectOutput(output.toFile());
        builder.environment().keySet().removeIf(k -> k.equals("MODEL_API_KEY") || k.startsWith("SPRINGDOTENV_") || k.startsWith("SPRING_CONFIG_") || k.equals("SPRING_PROFILES_ACTIVE"));
        if (expected.equals("file") || expected.equals("process") || environment.containsKey("MODEL_API_KEY"))
            builder.environment().put("SPRINGDOTENV_ENABLED", "true");
        builder.environment().putAll(environment);
        Process child = builder.start();
        try {
            assertThat(child.waitFor(30,TimeUnit.SECONDS)).isTrue();
            assertThat(child.exitValue()).isZero();
            assertThat(Files.readString(output)).contains("CONFIGURATION_CHECK_PASSED");
        } finally { if (child.isAlive()) child.destroyForcibly(); }
    }
    @Test void loadsRootDotenvThroughSpringBoot4() throws Exception { verify("file",true,Map.of()); }
    @Test void realProcessEnvironmentOverridesDotenv() throws Exception { verify("process",true,Map.of("MODEL_API_KEY","process-test-marker")); }
    @Test void deliberatelyEmptyProcessVariableDoesNotFallBackToDotenv() throws Exception { verify("absent",true,Map.of("MODEL_API_KEY","")); }
    @Test void productionEnvironmentCanDisableDotenv() throws Exception { verify("absent",true,Map.of("SPRINGDOTENV_ENABLED","false")); }
    @Test void secureDefaultDoesNotReadLocalDotenv() throws Exception { verify("absent",true,Map.of()); }
    @Test void missingDotenvDoesNotBreakProductionConfiguration() throws Exception { verify("absent",false,Map.of()); }
    @Test void localOptInAllowsMissingOptionalDotenv() throws Exception { verify("absent",false,Map.of("SPRINGDOTENV_ENABLED","true")); }
}
