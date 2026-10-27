package com.tewendelabs.investigator.investigation;

import java.util.*;

import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.*;

import com.tewendelabs.investigator.provider.PolicyReasoningProvider.Source;

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
}
