package com.tewendelabs.investigator.provider;

import java.time.Duration;
import java.util.*;

import ch.qos.logback.classic.Level;
import ch.qos.logback.classic.Logger;
import ch.qos.logback.classic.spi.ILoggingEvent;
import ch.qos.logback.core.read.ListAppender;
import org.junit.jupiter.api.*;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.slf4j.LoggerFactory;
import org.springframework.context.annotation.AnnotationConfigApplicationContext;
import org.springframework.context.support.PropertySourcesPlaceholderConfigurer;
import org.springframework.core.env.PropertiesPropertySource;
import org.springframework.core.env.StandardEnvironment;
import org.springframework.core.env.SystemEnvironmentPropertySource;

import com.tewendelabs.investigator.investigation.InvestigationSchemas;
import com.tewendelabs.investigator.investigation.JsonContract;
import com.tewendelabs.investigator.provider.PolicyReasoningProvider.Request;
import com.tewendelabs.investigator.provider.PolicyReasoningProvider.Source;
import tools.jackson.databind.node.ObjectNode;

import static org.assertj.core.api.Assertions.*;

/** Synthetic transport and authorization fixtures only; no network, database or dotenv access. */
class MetaPolicyReasoningProviderTest {
    private static final String MODEL = "muse-spark-1.3";
    private static final String KEY = "synthetic-key-must-not-be-logged";
    private static final String PRIVATE_TEXT = "synthetic-private-text-must-not-be-logged";
    private final RecordingTransport transport = new RecordingTransport();
    private final RecordingGate gate = new RecordingGate();
    private final Request request = new Request(UUID.randomUUID(), UUID.randomUUID(), UUID.randomUUID(),
            InvestigationSchemas.EXTRACTION, PRIVATE_TEXT,
            List.of(new Source(UUID.randomUUID(), UUID.randomUUID(), PRIVATE_TEXT)), Duration.ofSeconds(5));
    private final Logger logger = (Logger) LoggerFactory.getLogger(MetaPolicyReasoningProvider.class);
    private final ListAppender<ILoggingEvent> logs = new ListAppender<>();
    private Level previousLevel;

    @BeforeEach
    void captureProviderLogs() {
        previousLevel = logger.getLevel();
        logger.setLevel(Level.INFO);
        logs.start();
        logger.addAppender(logs);
    }

    @AfterEach
    void restoreLogger() {
        logger.detachAppender(logs);
        logs.stop();
        logger.setLevel(previousLevel);
    }

    private MetaPolicyReasoningProvider provider(int limit) {
        return new MetaPolicyReasoningProvider(transport, gate, KEY, MODEL, 30, 2, 2, limit);
    }

    private ObjectNode envelope(String reason, String content) {
        var choice = new LinkedHashMap<String, Object>();
        if (reason != null) choice.put("finish_reason", reason);
        choice.put("message", Map.of("content", content));
        return (ObjectNode) JsonContract.tree(Map.of("model", MODEL, "choices", List.of(choice),
                "usage", Map.of("prompt_tokens", 1224, "completion_tokens", 4096, "total_tokens", 5320)));
    }

    private String completeContent() {
        return JsonContract.encode(Map.of("requirements", List.of(), "processedSourceIds", List.of(),
                "complete", true, "limitations", List.of(PRIVATE_TEXT)));
    }

    private void reply(ObjectNode envelope) {
        transport.reply = new MetaTransport.Reply(200, JsonContract.encode(envelope));
    }

    private String onlyLog() {
        assertThat(logs.list).hasSize(1);
        String message = logs.list.getFirst().getFormattedMessage();
        assertThat(message).contains("meta_provider_event job_id=" + request.investigationId(),
                "attempt=1", "prompt_tokens=1224", "completion_tokens=4096", "total_tokens=5320", "latency_ms=");
        assertThat(message).doesNotContain(KEY, PRIVATE_TEXT, MODEL, request.leaseToken().toString());
        assertThat(logs.list.getFirst().getThrowableProxy()).isNull();
        assertThat(transport.calls).isEqualTo(1);
        assertThat(gate.reservations).isEqualTo(1);
        assertThat(gate.metered).isEqualTo(1);
        assertThat(gate.prompt).isEqualTo(1224);
        assertThat(gate.completion).isEqualTo(4096);
        return message;
    }

    @ParameterizedTest
    @ValueSource(ints = {4096, 6144, 8192})
    void sendsConfiguredBudgetAndPreservesStrictLowReasoning(int limit) {
        reply(envelope("stop", completeContent()));
        provider(limit).reason(request);
        var payload = JsonContract.parse(transport.payload);
        assertThat(payload.path("max_completion_tokens").asInt()).isEqualTo(limit);
        assertThat(payload.path("reasoning_effort").asString()).isEqualTo("low");
        var format = payload.path("response_format");
        assertThat(format.path("type").asString()).isEqualTo("json_schema");
        assertThat(format.path("json_schema").path("strict").asBoolean()).isTrue();
        assertThat(format.path("json_schema").path("schema")).isEqualTo(InvestigationSchemas.schema(request.schemaVersion()));
        assertThat(onlyLog()).contains("finish_reason=stop refusal=false", "max_completion_tokens=" + limit);
    }

    @ParameterizedTest
    @ValueSource(ints = {Integer.MIN_VALUE, -1, 0, 4095, 8193, Integer.MAX_VALUE})
    void rejectsBudgetsOutsideApplicationBounds(int limit) {
        assertThatIllegalArgumentException().isThrownBy(() -> provider(limit))
                .withMessage("meta.max-completion-tokens must be between 4096 and 8192");
        assertThat(transport.calls).isZero();
        assertThat(gate.reservations).isZero();
    }

    @Test
    void rejectsOversizedSerializedContextBeforeReservingAnAttempt() {
        var oversized = new Request(request.actorId(), request.investigationId(), request.leaseToken(),
                request.schemaVersion(), "x".repeat(32001), request.sources(), request.timeout());
        assertThatThrownBy(() -> provider(4096).reason(oversized)).hasMessage("CONTEXT_BUDGET_EXCEEDED");
        assertThat(gate.reservations).isZero();
        assertThat(transport.calls).isZero();
        assertThat(logs.list).isEmpty();
    }

    @Test
    void lengthIsMeteredAndLoggedWithoutRetryingOrParsingTruncatedContent() {
        reply(envelope("length", PRIVATE_TEXT + "{"));
        assertThatThrownBy(() -> provider(8192).reason(request)).hasMessage("INCOMPLETE_PROVIDER_OUTPUT");
        assertThat(onlyLog()).contains("finish_reason=length refusal=false", "max_completion_tokens=8192");
    }

    @ParameterizedTest
    @ValueSource(strings = {"", PRIVATE_TEXT})
    void refusalsRemainRejectedAndOnlyTheirPresenceIsLogged(String refusal) {
        var envelope = envelope("stop", completeContent());
        ((ObjectNode) envelope.path("choices").path(0).path("message")).put("refusal", refusal);
        reply(envelope);
        assertThatThrownBy(() -> provider(4096).reason(request)).hasMessage("INCOMPLETE_PROVIDER_OUTPUT");
        assertThat(onlyLog()).contains("finish_reason=stop refusal=true");
    }

    @Test
    void nullRefusalDoesNotRejectACompleteResponse() {
        var envelope = envelope("stop", completeContent());
        ((ObjectNode) envelope.path("choices").path(0).path("message")).putNull("refusal");
        reply(envelope);
        provider(4096).reason(request);
        assertThat(onlyLog()).contains("finish_reason=stop refusal=false");
    }

    @ParameterizedTest
    @ValueSource(strings = {"content_filter", "tool_calls", "function_call"})
    void otherKnownFinishReasonsAreLoggedAndNeverRetried(String reason) {
        reply(envelope(reason, PRIVATE_TEXT));
        assertThatThrownBy(() -> provider(4096).reason(request)).hasMessage("INCOMPLETE_PROVIDER_OUTPUT");
        assertThat(onlyLog()).contains("finish_reason=" + reason + " refusal=false");
    }

    @ParameterizedTest
    @ValueSource(strings = {"stop\n" + PRIVATE_TEXT, "STOP", " stop ", PRIVATE_TEXT})
    void unknownFinishReasonsCannotInjectLogsOrBecomeAccepted(String reason) {
        reply(envelope(reason, completeContent()));
        assertThatThrownBy(() -> provider(4096).reason(request)).hasMessage("INCOMPLETE_PROVIDER_OUTPUT");
        assertThat(onlyLog()).contains("finish_reason=other refusal=false").doesNotContain("\n", "\r");
    }

    @ParameterizedTest
    @ValueSource(strings = {"missing", "null", "number", "object", "no_choices"})
    void missingAndInvalidFinishReasonsUseFixedLogVocabulary(String shape) {
        var envelope = envelope(null, completeContent());
        var choice = (ObjectNode) envelope.path("choices").path(0);
        switch (shape) {
            case "null" -> choice.putNull("finish_reason");
            case "number" -> choice.put("finish_reason", 123);
            case "object" -> choice.set("finish_reason", JsonContract.tree(Map.of("text", PRIVATE_TEXT)));
            case "no_choices" -> envelope.set("choices", JsonContract.tree(List.of()));
        }
        reply(envelope);
        assertThatThrownBy(() -> provider(4096).reason(request)).hasMessage("INCOMPLETE_PROVIDER_OUTPUT");
        assertThat(onlyLog()).contains("finish_reason=" + (Set.of("number", "object").contains(shape) ? "other" : "missing"));
    }

    @Test
    void malformedContentStillFailsAfterStopIsLogged() {
        reply(envelope("stop", PRIVATE_TEXT));
        assertThatThrownBy(() -> provider(4096).reason(request)).hasMessage("MALFORMED_MODEL_OUTPUT");
        assertThat(onlyLog()).contains("finish_reason=stop refusal=false");
    }

    @Test
    void invalidSchemaStillFailsAfterStopIsLogged() {
        reply(envelope("stop", "{}"));
        assertThatThrownBy(() -> provider(4096).reason(request)).hasMessage("INVALID_MODEL_SCHEMA");
        onlyLog();
    }

    @ParameterizedTest
    @ValueSource(strings = {"default", "4096", "8192", "4095", "8193", "not-an-integer", ""})
    void springResolvesActualEnvironmentMappingAndRejectsInvalidConfiguration(String setting) throws Exception {
        // Only the provider is registered: no Boot startup, dotenv loader, database or HTTP client.
        try (var context = new AnnotationConfigApplicationContext()) {
            var environment = new StandardEnvironment();
            environment.getPropertySources().remove(StandardEnvironment.SYSTEM_ENVIRONMENT_PROPERTY_SOURCE_NAME);
            environment.getPropertySources().remove(StandardEnvironment.SYSTEM_PROPERTIES_PROPERTY_SOURCE_NAME);
            environment.getPropertySources().addFirst(new SystemEnvironmentPropertySource("synthetic-process",
                    setting.equals("default") ? Map.of() : Map.of("META_MAX_COMPLETION_TOKENS", setting)));
            var properties = new Properties();
            try (var input = java.nio.file.Files.newInputStream(java.nio.file.Path.of("src/main/resources/application.properties"))) {
                properties.load(input);
            }
            environment.getPropertySources().addLast(new PropertiesPropertySource("application", properties));
            context.setEnvironment(environment);
            context.registerBean(PropertySourcesPlaceholderConfigurer.class);
            context.registerBean(MetaTransport.class, () -> transport);
            context.registerBean(ProviderGate.class, () -> gate);
            context.registerBean(MetaPolicyReasoningProvider.class);
            if (Set.of("default", "4096", "8192").contains(setting)) {
                context.refresh();
                assertThat(environment.getProperty("meta.max-completion-tokens")).isEqualTo(setting.equals("default") ? "4096" : setting);
            } else {
                assertThatThrownBy(context::refresh).isInstanceOf(org.springframework.beans.BeansException.class);
            }
        }
    }

    private static final class RecordingTransport implements MetaTransport {
        int calls;
        String payload;
        Reply reply;

        @Override
        public Reply send(String key, String payload, Duration timeout) {
            calls++;
            this.payload = payload;
            return reply;
        }
    }

    private static final class RecordingGate extends ProviderGate {
        int reservations, metered, prompt, completion;

        RecordingGate() { super(null, null, null); }

        @Override public void beforeAttempt(Request request) { reservations++; }

        @Override public void usage(Request request, int prompt, int completion, long latency) {
            metered++;
            this.prompt = prompt;
            this.completion = completion;
        }
    }
}
