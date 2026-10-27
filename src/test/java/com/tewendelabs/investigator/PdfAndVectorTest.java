package com.tewendelabs.investigator;

import java.io.*;
import java.util.*;

import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.*;

import org.apache.pdfbox.pdmodel.*;
import org.apache.pdfbox.pdmodel.font.*;
import com.tewendelabs.investigator.ingestion.*;
import com.tewendelabs.investigator.policy.PolicyService;

class PdfAndVectorTest {
    static byte[] pdf(String... texts) throws IOException {
        try (PDDocument doc = new PDDocument(); ByteArrayOutputStream out = new ByteArrayOutputStream()) {
            for (String text : texts) {
                PDPage page = new PDPage();
                doc.addPage(page);
                try (PDPageContentStream cs = new PDPageContentStream(doc, page)) {
                    cs.beginText();
                    cs.setFont(new PDType1Font(Standard14Fonts.FontName.HELVETICA), 12);
                    cs.newLineAtOffset(50, 700);
                    cs.showText(text);
                    cs.endText();
                }
            }
            doc.save(out);
            return out.toByteArray();
        }
    }

    @Test
    void childJvmPreservesDistinctPageTextAndLocations() throws Exception {
        var pages = new PdfExtractor().extract(pdf("Report incidents within 24 hours.", "Finance retains reports for five years."));
        assertThat(pages).hasSize(2);
        assertThat(pages.get(0).number()).isEqualTo(1);
        assertThat(pages.get(1).text()).contains("five years").doesNotContain("24 hours");
    }

    @Test
    void rejectsMalformedAndEmptyPdf() throws Exception {
        assertThatThrownBy(() -> new PdfExtractor().extract("%PDF-invalid".getBytes())).hasMessage("INVALID_PDF");
        assertThatThrownBy(() -> new PdfExtractor().extract(pdf(""))).hasMessage("EMPTY_TEXT");
    }

    @Test
    void unicodeOffsetsRoundTripWithoutSplittingCharacters() {
        String text = "🧾 policy requirement. ".repeat(150);
        var spans = new SourceChunker().chunk(List.of(new PdfExtractor.Page(2, text)));
        assertThat(spans).hasSizeGreaterThan(1);
        for (var span : spans) {
            assertThat(span.end() - span.start()).isLessThanOrEqualTo(1200);
            assertThat(span.text()).isEqualTo(text.substring(text.offsetByCodePoints(0, span.start()), text.offsetByCodePoints(0, span.end())));
        }
        assertThat(spans.getLast().end()).isEqualTo(text.codePointCount(0, text.length()));
    }

    @Test
    void rejectsUnsafeNamesAndInvalidVectors() {
        assertThatThrownBy(() -> PolicyService.validatePdf("../x.pdf", "%PDF-".getBytes())).hasMessage("INVALID_FILENAME");
        assertThatThrownBy(() -> EmbeddingGateway.vectorLiteral(new float[384])).isInstanceOf(IllegalArgumentException.class);
        float[] vector = new float[384];
        vector[0] = Float.NaN;
        assertThatThrownBy(() -> EmbeddingGateway.vectorLiteral(vector)).isInstanceOf(IllegalArgumentException.class);
        vector[0] = 1;
        assertThat(EmbeddingGateway.vectorLiteral(vector)).startsWith("[1.0,");
    }
    @Test void refusesMixedEmptyPagesInsteadOfClaimingCompleteExtraction() throws Exception {
        assertThatThrownBy(() -> new PdfExtractor().extract(pdf("A requirement", ""))).hasMessage("UNSUPPORTED_PDF");
    }

}
