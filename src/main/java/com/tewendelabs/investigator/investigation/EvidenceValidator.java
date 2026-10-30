package com.tewendelabs.investigator.investigation;

import java.util.*;
import java.time.LocalDate;

import tools.jackson.databind.JsonNode;
import tools.jackson.databind.node.ObjectNode;
import com.tewendelabs.investigator.provider.PolicyReasoningProvider.Source;
import com.tewendelabs.investigator.api.ApiFailure;

public final class EvidenceValidator {
    private static final Set<String> FIELDS = Set.of("actor", "action", "obligation", "condition", "scope", "deadline", "exceptions", "effectiveDate");

    enum ReferenceRejectionReason { UNKNOWN_SOURCE_ID, BLANK_QUOTE, NONLITERAL_QUOTE }

    /** Internal diagnostic only; the public status/code and persisted error remain unchanged. */
    static final class UnverifiableReference extends ApiFailure {
        private final ReferenceRejectionReason reason;

        private UnverifiableReference(ReferenceRejectionReason reason) {
            super(502, "UNVERIFIABLE_SOURCE_REFERENCE");
            this.reason = reason;
        }

        ReferenceRejectionReason reason() { return reason; }
    }

    public static void references(JsonNode references, List<Source> sources, Set<UUID> requiredVersions) {
        Map<String, Source> catalog = new HashMap<>();
        for (var s : sources) catalog.put(s.sourceId().toString(), s);
        Set<UUID> cited = new HashSet<>();
        for (var ref : references) {
            Source source = catalog.get(ref.path("sourceId").asString());
            String quote = ref.path("quote").asString("");
            if (source == null) throw new UnverifiableReference(ReferenceRejectionReason.UNKNOWN_SOURCE_ID);
            if (quote.isBlank()) throw new UnverifiableReference(ReferenceRejectionReason.BLANK_QUOTE);
            if (!source.excerpt().contains(quote)) throw new UnverifiableReference(ReferenceRejectionReason.NONLITERAL_QUOTE);
            cited.add(source.versionId());
        }
        if (!cited.containsAll(requiredVersions)) throw new ApiFailure(502, "INSUFFICIENT_CITATION_COVERAGE");
    }

    public static JsonNode extraction(JsonNode output, List<Source> sources, UUID investigation, UUID version) {
        JsonContract.validate(output, InvestigationSchemas.schema(InvestigationSchemas.EXTRACTION));
        Set<String> supplied = new HashSet<>();
        for (var source : sources) supplied.add(source.sourceId().toString());
        Set<String> processed = values(output.path("processedSourceIds"));
        if (!supplied.containsAll(processed) || output.path("complete").asBoolean() && !supplied.equals(processed))
            throw new ApiFailure(502, "INCOMPLETE_SOURCE_COVERAGE");
        int index = 0;
        for (var req : output.path("requirements")) {
            references(req.path("sourceReferences"), sources, Set.of(version));
            Set<String> unknown = values(req.path("unknownFields"));
            if (!FIELDS.containsAll(unknown)) throw new ApiFailure(502, "UNKNOWN_FIELD_INVALID");
            for (String field : FIELDS)
                if (req.path(field).isNull() != unknown.contains(field))
                    throw new ApiFailure(502, "UNKNOWN_FIELD_INVALID");
            if (!req.path("effectiveDate").isNull()) try {
                LocalDate.parse(req.path("effectiveDate").asString());
            } catch (RuntimeException e) {
                throw new ApiFailure(502, "INVALID_EFFECTIVE_DATE");
            }
            ((ObjectNode) req).put("id", UUID.nameUUIDFromBytes((investigation + ":" + version + ":" + (index++)).getBytes(java.nio.charset.StandardCharsets.UTF_8)).toString());
        }
        return output;
    }

    public static void assessment(JsonNode output, InvestigationService.Snapshot scope, Map<UUID, JsonNode> extracted, List<Source> sources) {
        JsonContract.validate(output, InvestigationSchemas.schema(InvestigationSchemas.ASSESSMENT));
        Set<String> baseline = ids(extracted.get(scope.baseline())), replacement = ids(extracted.get(scope.replacement()));
        Set<String> seenBase = new HashSet<>(), seenNew = new HashSet<>();
        for (var change : output.path("changes")) {
            String old = change.path("baselineRequirementId").isNull() ? null : change.path("baselineRequirementId").asString();
            String next = change.path("replacementRequirementId").isNull() ? null : change.path("replacementRequirementId").asString();
            if (old != null && !baseline.contains(old) || next != null && !replacement.contains(next) || old == null && next == null)
                throw new ApiFailure(502, "INVALID_REQUIREMENT_REFERENCE");
            String type = change.path("changeType").asString();
            if (type.equals("ADDED") && (old != null || next == null) || type.equals("REMOVED") && (old == null || next != null)
                    || Set.of("MODIFIED", "UNCHANGED").contains(type) && (old == null || next == null))
                throw new ApiFailure(502, "INVALID_CHANGE_ALIGNMENT");
            if (old != null) seenBase.add(old);
            if (next != null) seenNew.add(next);
            Set<UUID> expected = new HashSet<>();
            if (old != null) expected.add(scope.baseline());
            if (next != null) expected.add(scope.replacement());
            references(change.path("sourceReferences"), sources, expected);
        }
        if (output.path("complete").asBoolean() && (!seenBase.equals(baseline) || !seenNew.equals(replacement)))
            throw new ApiFailure(502, "INCOMPLETE_CHANGE_COVERAGE");
        Set<String> pairs = new HashSet<>();
        for (var assessment : output.path("assessments")) {
            String req = assessment.path("policyRequirementId").asString();
            UUID procedure;
            try {
                procedure = UUID.fromString(assessment.path("procedureVersionId").asString());
            } catch (RuntimeException e) {
                throw new ApiFailure(502, "INVALID_REQUIREMENT_REFERENCE");
            }
            if (!replacement.contains(req) || !scope.procedures().contains(procedure) || !pairs.add(req + ":" + procedure))
                throw new ApiFailure(502, "INVALID_REQUIREMENT_REFERENCE");
            if (!ids(extracted.get(procedure)).containsAll(values(assessment.path("relatedProcedureRequirementIds"))))
                throw new ApiFailure(502, "INVALID_REQUIREMENT_REFERENCE");
            references(assessment.path("sourceReferences"), sources.stream().filter(s -> s.versionId().equals(scope.replacement()) || s.versionId().equals(procedure)).toList(), Set.of(scope.replacement(), procedure));
            String classification = assessment.path("classification").asString();
            if (classification.equals("CONTRADICTION") && assessment.path("relatedProcedureRequirementIds").isEmpty())
                throw new ApiFailure(502, "INVALID_REQUIREMENT_REFERENCE");
            ((ObjectNode) assessment).put("id", UUID.randomUUID().toString());
            ((ObjectNode) assessment).put("reviewStatus", classification.equals("NO_CONFLICT") ? "NOT_REQUIRED" : "PENDING_REVIEW");
        }
        if (output.path("complete").asBoolean() && pairs.size() != replacement.size() * scope.procedures().size())
            throw new ApiFailure(502, "INCOMPLETE_ASSESSMENT_COVERAGE");
    }

    public static Set<String> ids(JsonNode extraction) {
        Set<String> out = new HashSet<>();
        for (var req : extraction.path("requirements")) out.add(req.path("id").asString());
        return out;
    }

    public static Set<String> values(JsonNode array) {
        Set<String> out = new HashSet<>();
        for (var value : array) if (!out.add(value.asString())) throw new ApiFailure(502, "DUPLICATE_MODEL_REFERENCE");
        return out;
    }
}
