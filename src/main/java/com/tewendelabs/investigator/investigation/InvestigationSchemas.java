package com.tewendelabs.investigator.investigation;

import java.util.*;

import tools.jackson.databind.JsonNode;

import static com.tewendelabs.investigator.investigation.JsonContract.*;

public final class InvestigationSchemas {
    public static final String EXTRACTION = "requirements-v1", ASSESSMENT = "impact-v1", PROMPT = "policy-investigator-2026-10-27-v1";

    public static JsonNode schema(String version) {
        var reference = object(Map.of("sourceId", text(), "quote", Map.of("type", "string", "minLength", 1, "maxLength", 2000)));
        var refs = array(reference, 1, 12);
        Map<String, Object> fields = new LinkedHashMap<>();
        for (String name : List.of("actor", "action", "obligation", "condition", "scope", "deadline", "effectiveDate"))
            fields.put(name, nullable());
        fields.put("exceptions", Map.of("type", List.of("array", "null"), "items", text(), "maxItems", 20));
        fields.put("unknownFields", strings());
        fields.put("sourceReferences", refs);
        if (EXTRACTION.equals(version))
            return tree(object(Map.of("requirements", array(object(fields), 0, 16), "processedSourceIds", strings(), "complete", Map.of("type", "boolean"), "limitations", strings())));
        if (ASSESSMENT.equals(version)) {
            var change = object(Map.of("baselineRequirementId", nullable(), "replacementRequirementId", nullable(), "changeType", choice("ADDED", "REMOVED", "MODIFIED", "UNCHANGED"), "reason", text(), "sourceReferences", refs));
            var assessment = object(Map.of("policyRequirementId", text(), "procedureVersionId", text(), "relatedProcedureRequirementIds", strings(), "classification", choice("CONTRADICTION", "MISSING_REQUIREMENT", "AMBIGUITY", "NO_CONFLICT"), "severity", choice("HIGH", "MEDIUM", "LOW", "NONE"), "rationale", text(), "suggestedAction", nullable(), "scopeExplanation", text(), "sourceReferences", refs));
            return tree(object(Map.of("changes", array(change, 0, 32), "assessments", array(assessment, 0, 64), "complete", Map.of("type", "boolean"), "limitations", strings())));
        }
        throw new IllegalArgumentException("Unknown server schema");
    }
}
