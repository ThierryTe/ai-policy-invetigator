package com.tewendelabs.investigator.investigation;

import java.util.*;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.EnumSource;

import static org.assertj.core.api.Assertions.*;

import com.tewendelabs.investigator.provider.PolicyReasoningProvider.Source;
import com.tewendelabs.investigator.api.ApiFailure;

public class StructuredValidationTest {
    public static Map<String, Object> requirement(String id, String quote) {
        Map<String, Object> fields = new LinkedHashMap<>();
        fields.put("actor", "Employees");
        fields.put("action", "Complete training");
        fields.put("obligation", "MUST");
        fields.put("scope", "Sensitive systems");
        fields.put("deadline", "Before access");
        for (String key : List.of("condition", "effectiveDate", "exceptions")) fields.put(key, null);
        fields.put("unknownFields", List.of("condition", "effectiveDate", "exceptions"));
        fields.put("sourceReferences", List.of(Map.of("sourceId", id, "quote", quote)));
        return fields;
    }

    @Test
    void rejectsMalformedJsonAndUndeclaredFields() {
        assertThatThrownBy(() -> JsonContract.parse("not json")).hasMessage("MALFORMED_MODEL_OUTPUT");
        var raw = JsonContract.tree(Map.of("requirements", List.of(), "processedSourceIds", List.of(), "complete", true, "limitations", List.of(), "confidence", 1));
        assertThatThrownBy(() -> JsonContract.validate(raw, InvestigationSchemas.schema(InvestigationSchemas.EXTRACTION))).hasMessage("INVALID_MODEL_SCHEMA");
    }

    @Test
    void fabricatedSourceOrQuoteCannotPass() {
        UUID version = UUID.randomUUID(), source = UUID.randomUUID();
        var sources = List.of(new Source(source, version, "Training before access."));
        for (var refs : List.of(List.of(Map.of("sourceId", UUID.randomUUID().toString(), "quote", "Training")), List.of(Map.of("sourceId", source.toString(), "quote", "Training within 30 days"))))
            assertThatThrownBy(() -> EvidenceValidator.references(JsonContract.tree(refs), sources, Set.of(version))).hasMessage("UNVERIFIABLE_SOURCE_REFERENCE");
    }

    @Test
    void preservesUnknownsAndAssignsIdsOnlyOnServer() {
        UUID version = UUID.randomUUID(), source = UUID.randomUUID();
        var sources = List.of(new Source(source, version, "Training before access."));
        var output = JsonContract.tree(Map.of("requirements", List.of(requirement(source.toString(), "Training before access.")), "processedSourceIds", List.of(source.toString()), "complete", true, "limitations", List.of()));
        var validated = EvidenceValidator.extraction(output, sources, UUID.randomUUID(), version);
        assertThat(validated.path("requirements").get(0).path("condition").isNull()).isTrue();
        assertThatCode(() -> UUID.fromString(validated.path("requirements").get(0).path("id").asString())).doesNotThrowAnyException();
    }

    @Test
    void completeRequiresAllSourceIds() {
        UUID version = UUID.randomUUID(), source = UUID.randomUUID();
        var output = JsonContract.tree(Map.of("requirements", List.of(), "processedSourceIds", List.of(), "complete", true, "limitations", List.of()));
        assertThatThrownBy(() -> EvidenceValidator.extraction(output, List.of(new Source(source, version, "Training")), UUID.randomUUID(), version)).hasMessage("INCOMPLETE_SOURCE_COVERAGE");
    }

    @ParameterizedTest
    @EnumSource(EvidenceValidator.ReferenceRejectionReason.class)
    void citationDiagnosticPreservesPublicFailureAndContainsNoEvidence(EvidenceValidator.ReferenceRejectionReason reason) {
        UUID version = UUID.randomUUID(), source = UUID.randomUUID();
        String privateSourceId = "synthetic-private-source-id\nforged=true";
        String privateQuote = "synthetic-private-quote\nforged=true";
        String id = reason == EvidenceValidator.ReferenceRejectionReason.UNKNOWN_SOURCE_ID ? privateSourceId : source.toString();
        String quote = reason == EvidenceValidator.ReferenceRejectionReason.BLANK_QUOTE ? " \t\n" : privateQuote;
        var sources = List.of(new Source(source, version, "Training before access."));
        var output = JsonContract.tree(Map.of("requirements", List.of(requirement(id, quote)),
                "processedSourceIds", List.of(source.toString()), "complete", true, "limitations", List.of()));

        assertThatThrownBy(() -> EvidenceValidator.extraction(output, sources, UUID.randomUUID(), version))
                .isInstanceOf(EvidenceValidator.UnverifiableReference.class)
                .hasMessage("UNVERIFIABLE_SOURCE_REFERENCE")
                .hasNoCause()
                .satisfies(error -> {
                    var rejection = (EvidenceValidator.UnverifiableReference) error;
                    assertThat(rejection.reason()).isEqualTo(reason);
                    assertThat(rejection.status).isEqualTo(502);
                    assertThat(rejection.code).isEqualTo("UNVERIFIABLE_SOURCE_REFERENCE");
                    assertThat(rejection.toString()).doesNotContain(privateSourceId, privateQuote, source.toString());
                });
    }

    @Test
    void unknownSourceStillTakesPrecedenceOverBlankQuote() {
        var references = JsonContract.tree(List.of(Map.of("sourceId", "unknown", "quote", " ")));
        assertThatThrownBy(() -> EvidenceValidator.references(references, List.of(), Set.of()))
                .isInstanceOf(EvidenceValidator.UnverifiableReference.class)
                .satisfies(error -> assertThat(((EvidenceValidator.UnverifiableReference) error).reason())
                        .isEqualTo(EvidenceValidator.ReferenceRejectionReason.UNKNOWN_SOURCE_ID));
    }

    @Test
    void blankQuoteStillFailsEvenWhenItIsALiteralSubstring() {
        UUID version = UUID.randomUUID(), source = UUID.randomUUID();
        var references = JsonContract.tree(List.of(Map.of("sourceId", source.toString(), "quote", " ")));
        assertThatThrownBy(() -> EvidenceValidator.references(references,
                List.of(new Source(source, version, "Training before access.")), Set.of(version)))
                .isInstanceOf(EvidenceValidator.UnverifiableReference.class)
                .satisfies(error -> assertThat(((EvidenceValidator.UnverifiableReference) error).reason())
                        .isEqualTo(EvidenceValidator.ReferenceRejectionReason.BLANK_QUOTE));
    }

    @Test
    void schemaAndCoverageFailuresRetainTheirOwnCodes() {
        UUID version = UUID.randomUUID(), source = UUID.randomUUID();
        var sources = List.of(new Source(source, version, "Training before access."));
        assertThatThrownBy(() -> EvidenceValidator.extraction(JsonContract.tree(Map.of()), sources, UUID.randomUUID(), version))
                .isExactlyInstanceOf(ApiFailure.class).hasMessage("INVALID_MODEL_SCHEMA");
        var output = JsonContract.tree(Map.of("requirements", List.of(requirement("unknown", " ")),
                "processedSourceIds", List.of(), "complete", true, "limitations", List.of()));
        assertThatThrownBy(() -> EvidenceValidator.extraction(output, sources, UUID.randomUUID(), version))
                .isExactlyInstanceOf(ApiFailure.class).hasMessage("INCOMPLETE_SOURCE_COVERAGE");
        assertThatThrownBy(() -> EvidenceValidator.references(
                JsonContract.tree(List.of(Map.of("sourceId", source.toString(), "quote", "Training"))),
                sources, Set.of(UUID.randomUUID())))
                .isExactlyInstanceOf(ApiFailure.class).hasMessage("INSUFFICIENT_CITATION_COVERAGE");
    }
}
