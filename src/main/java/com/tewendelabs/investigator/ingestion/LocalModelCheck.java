package com.tewendelabs.investigator.ingestion;

import java.util.List;
import java.util.Map;
import org.springframework.ai.embedding.EmbeddingModel;

/** Offline diagnostic uses fixed synthetic sentences only; never receives application documents. */
public final class LocalModelCheck {

    public static void run(String modelUri, String tokenizerUri) throws Exception {
        Class<?> type = Class.forName("org.springframework.ai.transformers.TransformersEmbeddingModel");
        Object model = type.getConstructor().newInstance();
        type.getMethod("setModelResource", String.class).invoke(model, modelUri);
        type.getMethod("setTokenizerResource", String.class).invoke(model, tokenizerUri);
        type.getMethod("setTokenizerOptions", Map.class).invoke(model, Map.of("padding", "true"));
        try {
            type.getMethod("afterPropertiesSet").invoke(model);
            var vectors = ((EmbeddingModel) model).embed(List.of("Report security incidents within 24 hours.", "Travel meals are reimbursed."));
            for (var vector : vectors) EmbeddingGateway.vectorLiteral(vector);
            System.out.println("Local embedding check passed: " + vectors.size() + " vectors with 384 dimensions.");
        } finally { ((AutoCloseable) model).close(); }
    }
}
