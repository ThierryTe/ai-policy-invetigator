package com.tewendelabs.investigator.ingestion;

import java.util.*;

import org.springframework.stereotype.Component;

@Component
public class SourceChunker {
    public record Span(UUID id, int page, int start, int end, String text) {
    }

    /**
     * Offsets count Unicode code points, matching PostgreSQL substring(), not UTF-16 code units.
     */
    public List<Span> chunk(List<PdfExtractor.Page> pages) {
        List<Span> spans = new ArrayList<>();
        for (var page : pages) {
            String text = page.text();
            int count = text.codePointCount(0, text.length());
            for (int start = 0; start < count; ) {
                int end = Math.min(start + 1200, count);
                String excerpt = text.substring(text.offsetByCodePoints(0, start), text.offsetByCodePoints(0, end));
                if (!excerpt.isBlank()) spans.add(new Span(UUID.randomUUID(), page.number(), start, end, excerpt));
                if (end == count) break;
                start = end - 150;
            }
        }
        return List.copyOf(spans);
    }
}
