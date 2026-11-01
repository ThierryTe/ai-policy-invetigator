package com.tewendelabs.investigator.investigation;

import java.util.*;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.EnumSource;
import org.junit.jupiter.params.provider.ValueSource;
import org.junit.jupiter.params.provider.CsvSource;

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

    private static Map<String, Object> datedRequirement(String source, String quote, String date) {
        var req = requirement(source, quote);
        req.put("effectiveDate", date);
        if (date != null) req.put("unknownFields", List.of("condition", "exceptions"));
        return req;
    }

    @ParameterizedTest
    @ValueSource(strings = {"2025-01-01", "2026-12-01", "2024-02-29", "2000-02-29", "9999-12-31"})
    void acceptsCompleteIsoDatesWithoutChangingThem(String date) {
        UUID version = UUID.randomUUID(), source = UUID.randomUUID();
        String quote = "Policy effective from " + date + ".";
        var sources = List.of(new Source(source, version, quote));
        var output = JsonContract.tree(Map.of("requirements", List.of(datedRequirement(source.toString(), quote, date)),
                "processedSourceIds", List.of(source.toString()), "complete", true, "limitations", List.of()));
        var validated = EvidenceValidator.extraction(output, sources, UUID.randomUUID(), version);
        assertThat(validated.path("requirements").get(0).path("effectiveDate").asString()).isEqualTo(date);
    }

    @ParameterizedTest
    @ValueSource(strings = {"January 1, 2025", "01/02/2025", "2025", "2025-01", "2025-1-1", "20250101",
            "2025-01-01T00:00:00Z", "2025-01-01 ", " 2025-01-01", "", "+10000-01-01", "-0001-01-01",
            "２０２５-０１-０１", "synthetic-private-date\nforged=true"})
    void rejectsTextualAmbiguousPartialAndNoncanonicalDates(String date) {
        assertInvalidDate(date, EvidenceValidator.DateRejectionReason.INVALID_FORMAT);
    }

    @ParameterizedTest
    @ValueSource(strings = {"2025-02-29", "1900-02-29", "2026-04-31", "2026-13-01", "2026-00-01", "2026-01-00", "2026-01-32"})
    void rejectsImpossibleCalendarDatesWithoutSmartResolution(String date) {
        assertInvalidDate(date, EvidenceValidator.DateRejectionReason.INVALID_CALENDAR_DATE);
    }

    private static void assertInvalidDate(String date, EvidenceValidator.DateRejectionReason reason) {
        UUID version = UUID.randomUUID(), source = UUID.randomUUID();
        String quote = "Synthetic private source.";
        var sources = List.of(new Source(source, version, quote));
        var output = JsonContract.tree(Map.of("requirements", List.of(
                datedRequirement(source.toString(), quote, "2025-01-01"), datedRequirement(source.toString(), quote, date)),
                "processedSourceIds", List.of(source.toString()), "complete", true, "limitations", List.of()));
        // A structurally valid response still requires independent Java format and calendar validation.
        JsonContract.validate(output, InvestigationSchemas.schema(InvestigationSchemas.EXTRACTION));
        assertThatThrownBy(() -> EvidenceValidator.extraction(output, sources, UUID.randomUUID(), version))
                .isInstanceOf(EvidenceValidator.InvalidEffectiveDate.class).hasMessage("INVALID_EFFECTIVE_DATE").hasNoCause()
                .satisfies(error -> {
                    var rejection = (EvidenceValidator.InvalidEffectiveDate) error;
                    assertThat(rejection.status).isEqualTo(502);
                    assertThat(rejection.reason()).isEqualTo(reason);
                    assertThat(rejection.version()).isEqualTo(version);
                    assertThat(rejection.requirementIndex()).isEqualTo(1);
                    assertThat(rejection.toString()).isEqualTo(EvidenceValidator.InvalidEffectiveDate.class.getName() + ": INVALID_EFFECTIVE_DATE");
                });
        assertThat(output.path("requirements").get(1).path("effectiveDate").asString()).isEqualTo(date);
    }

    @ParameterizedTest
    @ValueSource(strings = {"No effective date is stated.", "Effective: 01/02/2025.", "Effective: February 30, 2025."})
    void preservesExplicitlyUnknownDatesWithLimitations(String quote) {
        UUID version = UUID.randomUUID(), source = UUID.randomUUID();
        var output = JsonContract.tree(Map.of("requirements", List.of(datedRequirement(source.toString(), quote, null)),
                "processedSourceIds", List.of(source.toString()), "complete", true,
                "limitations", List.of("The effective date is unknown, ambiguous or invalid.")));
        var validated = EvidenceValidator.extraction(output, List.of(new Source(source, version, quote)), UUID.randomUUID(), version);
        assertThat(validated.path("requirements").get(0).path("effectiveDate").isNull()).isTrue();
        assertThat(EvidenceValidator.values(validated.path("requirements").get(0).path("unknownFields"))).contains("effectiveDate");
        assertThat(validated.path("limitations")).isEqualTo(output.path("limitations"));
    }

    @ParameterizedTest
    @ValueSource(booleans = {false, true})
    void keepsNotificationDeadlineSeparateFromEffectiveDate(boolean hasEffectiveDate) {
        UUID version = UUID.randomUUID(), source = UUID.randomUUID();
        String quote = "Notify employees by November 15, 2026." + (hasEffectiveDate ? " Policy takes effect on December 1, 2026." : "");
        var req = datedRequirement(source.toString(), quote, hasEffectiveDate ? "2026-12-01" : null);
        req.put("deadline", "November 15, 2026");
        var output = JsonContract.tree(Map.of("requirements", List.of(req), "processedSourceIds", List.of(source.toString()),
                "complete", true, "limitations", List.of()));
        var validated = EvidenceValidator.extraction(output, List.of(new Source(source, version, quote)), UUID.randomUUID(), version);
        var saved = validated.path("requirements").get(0);
        assertThat(saved.path("deadline").asString()).isEqualTo("November 15, 2026");
        if (hasEffectiveDate) assertThat(saved.path("effectiveDate").asString()).isEqualTo("2026-12-01");
        else assertThat(saved.path("effectiveDate").isNull()).isTrue();
    }

    @ParameterizedTest
    @CsvSource({"policy-investigator-2026-10-27-v1, requirements-v1, true",
            "policy-investigator-2026-11-02-v2, requirements-v2, true",
            "policy-investigator-2026-10-27-v1, requirements-v2, false",
            "policy-investigator-2026-11-02-v2, requirements-v1, false",
            "unknown-prompt, requirements-v1, false", "policy-investigator-2026-10-27-v1, requirements-v99, false",
            ", requirements-v1, false", "policy-investigator-2026-10-27-v1, , false"})
    void checkpointCompatibilityAllowsOnlyKnownPairs(String prompt, String schema, boolean compatible) {
        assertThat(InvestigationSchemas.compatibleExtractionCheckpoint(prompt, schema)).isEqualTo(compatible);
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
