package com.tewendelabs.investigator.provider;

import java.time.Duration;
import java.util.List;
import java.util.UUID;

import tools.jackson.databind.JsonNode;

/**
 * Meta reasoning is independent of local embeddings. Every attempt requires a current authorization gate.
 */
public interface PolicyReasoningProvider {
    record Source(UUID sourceId, UUID versionId, String excerpt) {
    }

    record Request(UUID actorId, UUID investigationId, UUID leaseToken, String schemaVersion, String task,
                   List<Source> sources, Duration timeout) {
        public Request {
            sources = List.copyOf(sources);
        }
    }

    record Result(JsonNode content, String model, String promptVersion, String schemaVersion, int promptTokens,
                  int completionTokens, long latencyMs) {
    }

    Result reason(Request request);

    String modelId();
}
