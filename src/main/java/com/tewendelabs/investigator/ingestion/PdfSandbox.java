package com.tewendelabs.investigator.ingestion;

import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;

import org.apache.pdfbox.Loader;
import org.apache.pdfbox.pdmodel.PDDocument;
import org.apache.pdfbox.text.PDFTextStripper;

/**
 * Runs in a child JVM with a fixed heap. No application context, database or provider access.
 */
public final class PdfSandbox {
    public static void main(String[] args) throws Exception {
        try (PDDocument document = Loader.loadPDF(Path.of(args[0]).toFile());
             DataOutputStream out = new DataOutputStream(Files.newOutputStream(Path.of(args[1])))) {
            if (document.isEncrypted() || document.getNumberOfPages() < 1 || document.getNumberOfPages() > 100)
                System.exit(2);
            out.writeInt(document.getNumberOfPages());
            int total = 0;
            for (int page = 1; page <= document.getNumberOfPages(); page++) {
                final long started = System.nanoTime();
                PDFTextStripper stripper = new PDFTextStripper() {
                    private int count;

                    @Override
                    protected void writeString(String text) throws IOException {
                        count += text.length();
                        if (count > 100000 || System.nanoTime() - started > 10_000_000_000L)
                            throw new IOException("TEXT_LIMIT");
                        super.writeString(text);
                    }
                };
                stripper.setStartPage(page);
                stripper.setEndPage(page);
                stripper.setSortByPosition(true);
                String text = stripper.getText(document);
                total += text.length();
                if (text.length() > 100000 || total > 1_000_000) System.exit(3);
                byte[] bytes = text.getBytes(StandardCharsets.UTF_8);
                out.writeInt(bytes.length);
                out.write(bytes);
            }
        } catch (Exception e) {
            System.exit(2);
        }
    }
}
