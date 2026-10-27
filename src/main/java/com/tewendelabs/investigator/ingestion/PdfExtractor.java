package com.tewendelabs.investigator.ingestion;

import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;
import java.util.concurrent.TimeUnit;
import java.util.jar.JarFile;

import org.springframework.stereotype.Component;
import com.tewendelabs.investigator.api.ApiFailure;

@Component
public class PdfExtractor {
    public record Page(int number, String text) { }

    public List<Page> extract(byte[] bytes) {
        Path dir = null;
        Process child = null;
        try {
            dir = Files.createTempDirectory("policy-pdf-");
            Path input = dir.resolve("input.pdf"), output = dir.resolve("pages.bin");
            Files.write(input, bytes);
            List<String> command = new ArrayList<>(List.of(Path.of(System.getProperty("java.home"), "bin", "java").toString(), "-Xmx128m", "-XX:+ExitOnOutOfMemoryError"));
            String cp = System.getProperty("java.class.path");
            boolean bootJar = false;
            if (!cp.contains(File.pathSeparator) && cp.endsWith(".jar")) {
                try (JarFile jar = new JarFile(cp)) {
                    bootJar = jar.getManifest().getMainAttributes().getValue("Spring-Boot-Version") != null;
                }
            }
            if (bootJar) command.addAll(List.of("-jar", cp, "--extract-pdf"));
            else command.addAll(List.of("-cp", cp, PdfSandbox.class.getName()));
            command.add(input.toString());
            command.add(output.toString());
            ProcessBuilder builder = new ProcessBuilder(command).redirectOutput(ProcessBuilder.Redirect.DISCARD).redirectError(ProcessBuilder.Redirect.DISCARD);
            // Child receives neither signing material nor database/provider credentials.
            builder.environment().clear();
            child = builder.start();
            if (!child.waitFor(30, TimeUnit.SECONDS)) throw new ApiFailure(422, "INVALID_PDF");
            if (child.exitValue() != 0 || !Files.exists(output) || Files.size(output) > 4_100_000)
                throw new ApiFailure(422, "INVALID_PDF");
            try (DataInputStream in = new DataInputStream(Files.newInputStream(output))) {
                int count = in.readInt();
                if (count < 1 || count > 100) throw new IOException();
                List<Page> pages = new ArrayList<>();
                for (int i = 1; i <= count; i++) {
                    int length = in.readInt();
                    if (length < 0 || length > 400000) throw new IOException();
                    byte[] text = in.readNBytes(length);
                    if (text.length != length) throw new IOException();
                    pages.add(new Page(i, new String(text, StandardCharsets.UTF_8)));
                }
                if (pages.stream().allMatch(p -> p.text().isBlank())) throw new ApiFailure(422, "EMPTY_TEXT");
                if (pages.stream().anyMatch(p -> p.text().isBlank())) throw new ApiFailure(422, "UNSUPPORTED_PDF");
                return List.copyOf(pages);
            }
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw new ApiFailure(422, "PROCESSING_FAILED");
        } catch (IOException e) {
            throw new ApiFailure(422, "INVALID_PDF");
        } finally {
            if (child != null && child.isAlive()) {
                child.destroyForcibly();
                try {
                    child.waitFor(5, TimeUnit.SECONDS);
                } catch (InterruptedException e) {
                    Thread.currentThread().interrupt();
                }
            }
            if (dir != null) {
                try (var files = Files.list(dir)) {
                    for (Path p : files.toList()) Files.deleteIfExists(p);
                    Files.deleteIfExists(dir);
                } catch (IOException ignored) { /* private OS temporary directory; no paths/content logged */ }
            }
        }
    }
}
