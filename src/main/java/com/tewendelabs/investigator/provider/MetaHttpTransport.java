package com.tewendelabs.investigator.provider;

import java.net.URI;
import java.net.http.*;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.concurrent.*;

import org.springframework.stereotype.Component;
import com.tewendelabs.investigator.api.ApiFailure;

@Component
public class MetaHttpTransport implements MetaTransport {
    public static final URI ENDPOINT = URI.create("https://api.meta.ai/v1/chat/completions");
    private final HttpClient client;
    private final URI endpoint;

    public MetaHttpTransport() {
        this(ENDPOINT, HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(5)).followRedirects(HttpClient.Redirect.NEVER).build());
    }

    MetaHttpTransport(URI endpoint, HttpClient client) {
        this.endpoint = endpoint;
        this.client = client;
    }

    @jakarta.annotation.PreDestroy
    public void close() {
        client.shutdownNow();
    }

    @Override
    public Reply send(String key, String payload, Duration timeout) {
        long started = System.nanoTime();
        var request = HttpRequest.newBuilder(endpoint).timeout(timeout).header("Authorization", "Bearer " + key).header("Content-Type", "application/json")
                .POST(HttpRequest.BodyPublishers.ofString(payload)).build();
        var future = client.sendAsync(request, HttpResponse.BodyHandlers.ofInputStream());
        try {
            var response = future.get(timeout.toMillis(), TimeUnit.MILLISECONDS);
            // Read under the same absolute deadline; abort both request and body on timeout.
            var body = response.body();
            var read = CompletableFuture.supplyAsync(() -> {
                try (body) {
                    byte[] bytes = body.readNBytes(262145);
                    if (bytes.length > 262144) throw new ApiFailure(502, "PROVIDER_RESPONSE_TOO_LARGE");
                    return new String(bytes, StandardCharsets.UTF_8);
                } catch (java.io.IOException e) {
                    throw new ApiFailure(503, "PROVIDER_UNAVAILABLE");
                }
            });
            long remaining = Math.max(1, timeout.toMillis() - (System.nanoTime() - started) / 1_000_000);
            try {
                return new Reply(response.statusCode(), read.get(remaining, TimeUnit.MILLISECONDS));
            } catch (TimeoutException e) {
                try {
                    body.close();
                } catch (java.io.IOException ignored) {
                }
                read.cancel(true);
                throw e;
            }
        } catch (TimeoutException e) {
            future.cancel(true);
            throw new ApiFailure(504, "PROVIDER_TIMEOUT");
        } catch (InterruptedException e) {
            future.cancel(true);
            Thread.currentThread().interrupt();
            throw new ApiFailure(503, "PROVIDER_INTERRUPTED");
        } catch (ExecutionException e) {
            if (e.getCause() instanceof ApiFailure a) throw a;
            if (e.getCause() instanceof java.net.http.HttpTimeoutException)
                throw new ApiFailure(504, "PROVIDER_TIMEOUT");
            throw new ApiFailure(503, "PROVIDER_UNAVAILABLE");
        }
    }
}
