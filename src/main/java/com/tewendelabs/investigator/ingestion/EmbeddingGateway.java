package com.tewendelabs.investigator.ingestion;

import java.util.*;

import org.springframework.ai.embedding.EmbeddingModel;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;
import com.tewendelabs.investigator.api.ApiFailure;

@Component
public class EmbeddingGateway {
    public static final int DIMENSIONS = 384;
    private final EmbeddingModel model;
    private final TextCleaningService cleaning;
    public final String revision;

    public EmbeddingGateway(EmbeddingModel model, TextCleaningService cleaning, @Value("${app.embedding.revision}") String revision) {
        if (revision.isBlank() || revision.length() > 160)
            throw new IllegalArgumentException("Invalid embedding revision");
        this.model = model;
        this.cleaning = cleaning;
        this.revision = revision;
    }

    public List<float[]> embed(List<String> texts) {
        if (texts.size() > 32) throw new IllegalArgumentException("Embedding batch exceeds 32");
        try {
            List<float[]> result = model.embed(texts.stream().map(cleaning::clean).toList());
            if (result.size() != texts.size()) throw new IllegalArgumentException();
            result.forEach(EmbeddingGateway::vectorLiteral);
            return result;
        } catch (RuntimeException e) {
            throw new ApiFailure(503, "EMBEDDING_FAILED");
        }
    }

    public static String vectorLiteral(float[] vector) {
        if (vector.length != DIMENSIONS) throw new IllegalArgumentException("Unexpected embedding dimension");
        double norm = 0;
        StringJoiner out = new StringJoiner(",", "[", "]");
        for (float value : vector) {
            if (!Float.isFinite(value)) throw new IllegalArgumentException("Nonfinite vector");
            norm += (double) value * value;
            out.add(Float.toString(value));
        }
        if (norm == 0) throw new IllegalArgumentException("Zero vector");
        return out.toString();
    }
}
