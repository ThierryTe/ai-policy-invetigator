package com.tewendelabs.investigator.ingestion;

import java.net.URI;
import java.nio.file.*;
import java.io.InputStream;
import java.security.MessageDigest;
import java.util.HexFormat;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Component;

@Component
@ConditionalOnProperty(name = "app.embedding.verify-artifacts", havingValue = "true", matchIfMissing = true)
public class EmbeddingArtifactCheck implements ApplicationRunner {
    private final String model, tokenizer, revision;

    public EmbeddingArtifactCheck(@Value("${spring.ai.embedding.transformer.onnx.model-uri}") String model,
                                  @Value("${spring.ai.embedding.transformer.tokenizer.uri}") String tokenizer, @Value("${app.embedding.revision}") String revision) {
        this.model = model;
        this.tokenizer = tokenizer;
        this.revision = revision;
    }

    @Override
    public void run(ApplicationArguments args) throws Exception {
        String fingerprint = hash(model) + ":" + hash(tokenizer);
        if (!fingerprint.equals(revision))
            throw new IllegalStateException("Embedding artifact hashes do not match the configured revision");
    }

    private String hash(String uri) throws Exception {
        URI location = URI.create(uri);
        if (!"file".equals(location.getScheme()))
            throw new IllegalStateException("Embedding artifacts must be local files");
        MessageDigest digest = MessageDigest.getInstance("SHA-256");
        try (InputStream in = Files.newInputStream(Path.of(location))) {
            byte[] buffer = new byte[65536];
            int count;
            while ((count = in.read(buffer)) != -1) digest.update(buffer, 0, count);
        }
        return HexFormat.of().formatHex(digest.digest());
    }
}
