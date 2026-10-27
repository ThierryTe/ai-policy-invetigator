package com.tewendelabs.investigator.provider;

import java.net.*;
import java.net.http.HttpClient;
import java.time.Duration;

import com.sun.net.httpserver.HttpServer;
import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.*;

/**
 * Controlled transport tests only; no provider success claim and no actual credential.
 */
class MetaHttpTransportTest {
    @Test
    void bodyReadSharesTheRequestDeadline() throws Exception {
        HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/slow", exchange -> {
            try {
                exchange.sendResponseHeaders(200, 10);
                Thread.sleep(600);
                exchange.getResponseBody().write("0123456789".getBytes());
            } catch (Exception ignored) {
            } finally {
                exchange.close();
            }
        });
        server.start();
        var transport = new MetaHttpTransport(URI.create("http://127.0.0.1:" + server.getAddress().getPort() + "/slow"), HttpClient.newHttpClient());
        long start = System.nanoTime();
        try {
            assertThatThrownBy(() -> transport.send("test-marker", "{}", Duration.ofMillis(150))).hasMessage("PROVIDER_TIMEOUT");
            assertThat(Duration.ofNanos(System.nanoTime() - start)).isLessThan(Duration.ofSeconds(2));
        } finally {
            server.stop(0);
            transport.close();
        }
    }

    @Test
    void credentialsAreNeverFollowedAcrossRedirects() throws Exception {
        HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/redirect", exchange -> {
            exchange.getResponseHeaders().add("Location", "http://127.0.0.1:1/never");
            exchange.sendResponseHeaders(302, -1);
            exchange.close();
        });
        server.start();
        var transport = new MetaHttpTransport(URI.create("http://127.0.0.1:" + server.getAddress().getPort() + "/redirect"), HttpClient.newBuilder().followRedirects(HttpClient.Redirect.NEVER).build());
        try {
            assertThat(transport.send("test-marker", "{}", Duration.ofSeconds(2)).status()).isEqualTo(302);
        } finally {
            server.stop(0);
            transport.close();
        }
    }
}
