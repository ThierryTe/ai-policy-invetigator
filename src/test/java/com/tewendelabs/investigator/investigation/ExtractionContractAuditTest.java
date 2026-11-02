package com.tewendelabs.investigator.investigation;

import java.util.*;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.node.ObjectNode;
import com.tewendelabs.investigator.provider.PolicyReasoningProvider.Source;

import static org.assertj.core.api.Assertions.*;

/** Every fixture is synthetic. No Spring context, database or provider connection. */
class ExtractionContractAuditTest {
    private final UUID source = UUID.randomUUID(), version = UUID.randomUUID(), investigation = UUID.randomUUID();
    private final String quote = "Employees must complete training before access.";
    private final List<Source> sources = List.of(new Source(source, version, quote));
    private final JsonNode schema = InvestigationSchemas.schema(InvestigationSchemas.EXTRACTION);

    private ObjectNode requirement() {
        return (ObjectNode) JsonContract.tree(StructuredValidationTest.requirement(source.toString(), quote));
    }

    private ObjectNode output(ObjectNode req) {
        return (ObjectNode) JsonContract.tree(Map.of("requirements", List.of(req), "processedSourceIds", List.of(source.toString()),
                "complete", true, "limitations", List.of()));
    }

    private void validate(JsonNode content) {
        EvidenceValidator.extraction(content, sources, investigation, version);
    }

    @ParameterizedTest
    @ValueSource(strings = {"actor", "action", "obligation", "condition", "scope", "deadline", "exceptions", "effectiveDate", "unknownFields", "sourceReferences"})
    void everyRequirementFieldIsRequiredAndRejectsScalarTypeConfusion(String field) {
        var req = requirement();
        req.remove(field);
        assertThatThrownBy(() -> validate(output(req))).hasMessage("INVALID_MODEL_SCHEMA");
        for (Object wrong : List.of(1, true, Map.of())) {
            req.set(field, JsonContract.tree(wrong));
            assertThatThrownBy(() -> validate(output(req))).as(field + "=" + wrong).hasMessage("INVALID_MODEL_SCHEMA");
        }
    }

    @ParameterizedTest
    @ValueSource(strings = {"requirements", "processedSourceIds", "complete", "limitations"})
    void everyRootFieldIsRequiredAndNonNullable(String field) {
        var content = output(requirement());
        content.remove(field);
        assertThatThrownBy(() -> validate(content)).hasMessage("INVALID_MODEL_SCHEMA");
        content.putNull(field);
        assertThatThrownBy(() -> validate(content)).hasMessage("INVALID_MODEL_SCHEMA");
        content.set(field, JsonContract.tree(Map.of()));
        assertThatThrownBy(() -> validate(content)).hasMessage("INVALID_MODEL_SCHEMA");
    }

    @ParameterizedTest
    @ValueSource(strings = {"MUST", "MUST_NOT", "SHOULD", "MAY"})
    void modalityEnumIsExactAndNullable(String modality) {
        var req = requirement();
        req.put("obligation", modality);
        assertThatCode(() -> validate(output(req))).doesNotThrowAnyException();
        req.putNull("obligation");
        req.set("unknownFields", JsonContract.tree(List.of("condition", "exceptions", "effectiveDate", "obligation")));
        assertThatCode(() -> validate(output(req))).doesNotThrowAnyException();
    }

    @ParameterizedTest
    @ValueSource(strings = {"", "must", "MUST NOT", "REQUIRED", " MUST", "MAY ", "null"})
    void noncanonicalModalitiesAreRejectedBySchema(String modality) {
        var req = requirement();
        req.put("obligation", modality);
        assertThatThrownBy(() -> validate(output(req))).hasMessage("INVALID_MODEL_SCHEMA");
    }

    @ParameterizedTest
    @ValueSource(strings = {"actor", "action", "condition", "scope", "deadline"})
    void nullableFreeTextRetainsExistingEmptyAndLengthSemantics(String field) {
        var req = requirement();
        var unknown = new ArrayList<>(EvidenceValidator.values(req.path("unknownFields")));
        unknown.remove(field);
        req.set("unknownFields", JsonContract.tree(unknown));
        for (String allowed : List.of("", " ", "a".repeat(2000), "😀".repeat(1000))) {
            req.put(field, allowed);
            assertThatCode(() -> validate(output(req))).doesNotThrowAnyException();
        }
        for (String rejected : List.of("a".repeat(2001), "😀".repeat(1001))) {
            req.put(field, rejected);
            assertThatThrownBy(() -> validate(output(req))).hasMessage("INVALID_MODEL_SCHEMA");
        }
        req.putNull(field);
        unknown.add(field);
        req.set("unknownFields", JsonContract.tree(unknown));
        assertThatCode(() -> validate(output(req))).doesNotThrowAnyException();
    }

    @Test
    void exceptionsCanBeEmptyButCannotExceedItemOrTextBounds() {
        var req = requirement();
        req.set("unknownFields", JsonContract.tree(List.of("condition", "effectiveDate")));
        for (int size : List.of(0, 20)) {
            req.set("exceptions", JsonContract.tree(Collections.nCopies(size, "a".repeat(2000))));
            assertThatCode(() -> validate(output(req))).doesNotThrowAnyException();
        }
        for (Object invalid : List.of(Collections.nCopies(21, "exception"), List.of("a".repeat(2001)), List.of(1), "exception")) {
            req.set("exceptions", JsonContract.tree(invalid));
            assertThatThrownBy(() -> validate(output(req))).hasMessage("INVALID_MODEL_SCHEMA");
        }
    }

    @Test
    void requirementsAndLimitationsRetainTheirArrayBounds() {
        var content = output(requirement());
        content.set("requirements", JsonContract.tree(List.of()));
        assertThatCode(() -> validate(content)).doesNotThrowAnyException();
        content.set("requirements", JsonContract.tree(Collections.nCopies(16, requirement())));
        assertThatCode(() -> validate(content)).doesNotThrowAnyException();
        content.set("requirements", JsonContract.tree(Collections.nCopies(17, requirement())));
        assertThatThrownBy(() -> validate(content)).hasMessage("INVALID_MODEL_SCHEMA");
        content.set("requirements", JsonContract.tree(List.of()));
        content.set("limitations", JsonContract.tree(Collections.nCopies(30, "a".repeat(2000))));
        assertThatCode(() -> validate(content)).doesNotThrowAnyException();
        for (Object invalid : List.of(Collections.nCopies(31, "limit"), List.of("a".repeat(2001)), List.of(1))) {
            content.set("limitations", JsonContract.tree(invalid));
            assertThatThrownBy(() -> validate(content)).hasMessage("INVALID_MODEL_SCHEMA");
        }
    }

    @Test
    void referencesHaveExactCardinalityAndObjectShape() {
        var req = requirement();
        Object reference = Map.of("sourceId", source.toString(), "quote", quote);
        req.set("sourceReferences", JsonContract.tree(Collections.nCopies(12, reference)));
        assertThatCode(() -> validate(output(req))).doesNotThrowAnyException(); // Duplicate citations are not forbidden by the contract.
        for (Object invalid : List.of(List.of(), Collections.nCopies(13, reference), List.of(Map.of("sourceId", source.toString())),
                List.of(Map.of("sourceId", source.toString(), "quote", quote, "versionId", version.toString())),
                List.of(Map.of("sourceId", source.toString(), "quote", "")), List.of(Map.of("sourceId", source.toString(), "quote", "a".repeat(2001))))) {
            req.set("sourceReferences", JsonContract.tree(invalid));
            assertThatThrownBy(() -> validate(output(req))).hasMessage("INVALID_MODEL_SCHEMA");
        }
    }

    @ParameterizedTest
    @ValueSource(strings = {"unknown_source", "version_id", "blank_quote", "unicode_blank_quote", "paraphrase", "trimmed_quote"})
    void structurallyValidCitationsStillRequireAuthorizedLiteralEvidence(String fault) {
        var req = requirement();
        String id = fault.equals("unknown_source") ? UUID.randomUUID().toString() : fault.equals("version_id") ? version.toString() : source.toString();
        String citation = switch (fault) {
            case "blank_quote" -> " \t\n";
            case "unicode_blank_quote" -> "\u2003";
            case "paraphrase" -> "Employees must be trained before access.";
            case "trimmed_quote" -> quote + " ";
            default -> quote;
        };
        req.set("sourceReferences", JsonContract.tree(List.of(Map.of("sourceId", id, "quote", citation))));
        var content = output(req);
        JsonContract.validate(content, schema);
        assertThatThrownBy(() -> validate(content)).hasMessage("UNVERIFIABLE_SOURCE_REFERENCE");
    }

    @Test
    void suppliedReferenceStillHasToCoverTheExpectedVersion() {
        var content = output(requirement());
        JsonContract.validate(content, schema);
        assertThatThrownBy(() -> EvidenceValidator.extraction(content,
                List.of(new Source(source, UUID.randomUUID(), quote)), investigation, version)).hasMessage("INSUFFICIENT_CITATION_COVERAGE");
    }

    @Test
    void processedSourcesHaveSubsetUniquenessAndCompleteCoverageRules() {
        for (boolean complete : List.of(false, true)) {
            var content = output(requirement());
            content.put("complete", complete);
            for (Object invalid : List.of(List.of(version.toString()), List.of(source.toString(), UUID.randomUUID().toString()))) {
                content.set("processedSourceIds", JsonContract.tree(invalid));
                JsonContract.validate(content, schema);
                assertThatThrownBy(() -> validate(content)).hasMessage("INCOMPLETE_SOURCE_COVERAGE");
            }
            content.set("processedSourceIds", JsonContract.tree(List.of(source.toString(), source.toString())));
            JsonContract.validate(content, schema);
            assertThatThrownBy(() -> validate(content)).hasMessage("DUPLICATE_MODEL_REFERENCE");
            content.set("processedSourceIds", JsonContract.tree(List.of()));
            if (complete) assertThatThrownBy(() -> validate(content)).hasMessage("INCOMPLETE_SOURCE_COVERAGE");
            else assertThatCode(() -> validate(content)).doesNotThrowAnyException();
        }
        var content = output(requirement());
        content.set("processedSourceIds", JsonContract.tree(Collections.nCopies(21, source.toString())));
        assertThatThrownBy(() -> validate(content)).hasMessage("INVALID_MODEL_SCHEMA");
    }

    @Test
    void allTwentySuppliedSourcesCanBeCompletelyProcessedWithoutRequirements() {
        var supplied = new ArrayList<Source>();
        for (int i = 0; i < 20; i++) supplied.add(new Source(UUID.randomUUID(), version, "Informational synthetic excerpt."));
        var content = JsonContract.tree(Map.of("requirements", List.of(), "processedSourceIds", supplied.stream().map(s -> s.sourceId().toString()).toList(),
                "complete", true, "limitations", List.of()));
        assertThatCode(() -> EvidenceValidator.extraction(content, supplied, investigation, version)).doesNotThrowAnyException();
    }

    @ParameterizedTest
    @ValueSource(strings = {"nul", "high_surrogate", "low_surrogate", "high_followed_by_text"})
    void unpersistableUnicodeIsRejectedWithoutRewritingOrLeakingIt(String shape) {
        String value = "synthetic-private-text" + switch (shape) {
            case "nul" -> Character.toString((char) 0);
            case "high_surrogate" -> Character.toString((char) 0xD800);
            case "low_surrogate" -> Character.toString((char) 0xDC00);
            default -> Character.toString((char) 0xD800) + "x";
        };
        var content = output(requirement());
        content.set("limitations", JsonContract.tree(List.of(value)));
        var parsed = JsonContract.parse(JsonContract.encode(content)); // Valid JSON syntax is not a jsonb storage guarantee.
        assertThatThrownBy(() -> validate(parsed)).hasMessage("UNPERSISTABLE_MODEL_TEXT").hasNoCause()
                .satisfies(error -> assertThat(error.toString()).doesNotContain("synthetic-private-text"));
        assertThat(parsed).isEqualTo(content);
    }

    @Test
    void validUnicodeAndEscapedControlsArePreservedRatherThanSanitized() {
        String value = "é e\u0301 😀 \t\n\r" + Character.toString((char) 1);
        var content = output(requirement());
        content.set("limitations", JsonContract.tree(List.of(value)));
        var parsed = JsonContract.parse(JsonContract.encode(content));
        validate(parsed);
        assertThat(parsed.path("limitations").get(0).asString()).isEqualTo(value);
    }

    @Test
    void serverMetadataCannotBeSuppliedByTheModel() {
        for (String field : List.of("id", "model", "promptVersion", "schemaVersion", "confidence")) {
            var req = requirement();
            req.put(field, "model-supplied");
            assertThatThrownBy(() -> validate(output(req))).hasMessage("INVALID_MODEL_SCHEMA");
        }
    }

    @Test
    void schemaBoundsDoNotPromiseTheGlobalRawJsonBudget() {
        var req = requirement();
        req.put("action", "a".repeat(2000));
        req.set("exceptions", JsonContract.tree(Collections.nCopies(20, "e".repeat(2000))));
        req.set("unknownFields", JsonContract.tree(List.of("condition", "effectiveDate")));
        var content = output(req);
        content.set("requirements", JsonContract.tree(Collections.nCopies(3, req)));
        JsonContract.validate(content, schema);
        String encoded = JsonContract.encode(content);
        assertThat(encoded.length()).isGreaterThan(100000);
        assertThatThrownBy(() -> JsonContract.parse(encoded)).hasMessage("MALFORMED_MODEL_OUTPUT");
    }
}
