package com.tewendelabs.investigator.investigation;

import java.util.*;

import tools.jackson.databind.JsonNode;

import static com.tewendelabs.investigator.investigation.JsonContract.*;

public final class InvestigationSchemas {
    public static final String EXTRACTION = "requirements-v4", ASSESSMENT = "impact-v1", PROMPT = "policy-investigator-2026-11-02-v4";
    static final List<String> REQUIREMENT_FIELDS = List.of("actor", "action", "obligation", "condition", "scope", "deadline", "exceptions", "effectiveDate");
    public static final String UNKNOWN_FIELDS_CONTRACT = "unknownFields must be an array of distinct, exact, case-sensitive field names drawn only from "
            + String.join(", ", REQUIREMENT_FIELDS) + ". Include a field if and only if its value is JSON null; list every null field and no non-null field. "
            + "Use field names, never values, descriptions, paths or the string null. Use [] when no fields are null. "
            + "For exceptions, use null and list exceptions when unknown; use [] only when the source explicitly establishes no exceptions, and do not list exceptions then. "
            + "Before returning, check all eight final JSON values: every null field must be listed exactly once, and every non-null field must be absent from unknownFields. "
            + "A non-null effectiveDate must never be listed in unknownFields. If its date is unknown, ambiguous or invalid, return JSON null and list effectiveDate instead. "
            + "unknownFields describes the final JSON null values, not earlier draft values or general uncertainty. "
            + "Do not invent or discard a source-grounded value to make the list match, or remove uncertainty from limitations. "
            + "Illustrative fragments follow; other required fields are omitted here and assumed non-null. In the actual response, emit all required properties and preserve all evidence and coverage rules. "
            + "The example date is valid only if explicitly grounded in the supplied source; exceptions: [] is valid only if that source explicitly establishes no exceptions. Never copy example values as evidence.\n"
            + "VALID {\"effectiveDate\":\"2025-01-01\",\"unknownFields\":[]}\n"
            + "INVALID {\"effectiveDate\":\"2025-01-01\",\"unknownFields\":[\"effectiveDate\"]}\n"
            + "VALID {\"effectiveDate\":null,\"unknownFields\":[\"effectiveDate\"]}\n"
            + "INVALID {\"effectiveDate\":null,\"unknownFields\":[]}\n"
            + "VALID {\"exceptions\":[],\"unknownFields\":[]}\n"
            + "INVALID {\"exceptions\":[],\"unknownFields\":[\"exceptions\"]}";
    public static final String EXTRACTION_CONTRACT = "When extracting requirements, obligation must be MUST, MUST_NOT, SHOULD or MAY, or JSON null when the source does not establish an unambiguous modality. "
            + "Return at most 16 requirements, at most 20 exceptions per requirement, 1 to 12 sourceReferences per requirement, and at most 30 limitations. "
            + "Every output string must fit within 2000 UTF-16 code units (a supplementary Unicode character uses two units), contain no U+0000 and contain no unpaired surrogate. "
            + "Each sourceReferences entry must copy a supplied sourceId, not a versionId or document ID, and quote a nonblank, exact, contiguous substring of that source's excerpt. "
            + "Choose a short literal quote that supports the requirement; never trim, normalize, paraphrase or fabricate evidence to make it fit. "
            + "processedSourceIds must contain at most 20 distinct supplied sourceId values only, and only after fully covering each entire excerpt. "
            + "When complete=true, processedSourceIds must contain every supplied sourceId exactly once, even when there are no requirements. "
            + "An empty requirements array is valid when no explicit normative requirements are present; unknown field values alone do not make processing incomplete. "
            + "If all requirements, exceptions or evidence cannot be represented faithfully within these bounds, return only faithfully represented requirements, complete=false and explain the processing limitation in limitations. "
            + "Never omit or truncate requirements or exceptions and claim complete coverage. Do not emit requirement IDs or server provenance metadata; the server assigns them.";

    /** Previously validated v1/v2/v3 checkpoints remain immutable and reusable under the same model and source hash. */
    static boolean compatibleExtractionCheckpoint(String prompt, String schema) {
        return PROMPT.equals(prompt) && EXTRACTION.equals(schema)
                || "policy-investigator-2026-11-02-v3".equals(prompt) && "requirements-v3".equals(schema)
                || "policy-investigator-2026-11-02-v2".equals(prompt) && "requirements-v2".equals(schema)
                || "policy-investigator-2026-10-27-v1".equals(prompt) && "requirements-v1".equals(schema);
    }

    public static JsonNode schema(String version) {
        var reference = object(Map.of("sourceId", text(), "quote", Map.of("type", "string", "minLength", 1, "maxLength", 2000)));
        var refs = array(reference, 1, 12);
        Map<String, Object> fields = new LinkedHashMap<>();
        for (String name : List.of("actor", "action", "condition", "scope"))
            fields.put(name, nullable());
        fields.put("obligation", Map.of("type", List.of("string", "null"), "enum", Arrays.asList("MUST", "MUST_NOT", "SHOULD", "MAY", null),
                "description", "Explicit normative modality only; null when unknown or ambiguous and then include obligation in unknownFields."));
        fields.put("deadline", Map.of("type", List.of("string", "null"), "maxLength", 2000,
                "description", "The requirement's deadline or relative timing, not its effective date."));
        fields.put("effectiveDate", Map.of("type", List.of("string", "null"), "maxLength", 2000,
                "description", "A complete, valid calendar date in ISO YYYY-MM-DD (four-digit year, two-digit month and day), grounded in explicit source text. Convert an explicit textual date only when unambiguous. If non-null, effectiveDate must be absent from unknownFields. If unknown, ambiguous or invalid, return null, include effectiveDate in unknownFields and explain in limitations. Never substitute the analysis date or document metadata. Do not confuse a deadline with an effective date."));
        fields.put("exceptions", Map.of("type", List.of("array", "null"), "items", text(), "maxItems", 20));
        fields.put("unknownFields", Map.of("type", "array", "items", choice(REQUIREMENT_FIELDS.toArray(String[]::new)),
                "minItems", 0, "maxItems", REQUIREMENT_FIELDS.size(), "description", UNKNOWN_FIELDS_CONTRACT));
        fields.put("sourceReferences", refs);
        if (EXTRACTION.equals(version)) {
            var extraction = new LinkedHashMap<String, Object>(object(Map.of("requirements", array(object(fields), 0, 16),
                    "processedSourceIds", array(text(), 0, 20), "complete", Map.of("type", "boolean"), "limitations", strings())));
            extraction.put("description", EXTRACTION_CONTRACT);
            return tree(extraction);
        }
        if (ASSESSMENT.equals(version)) {
            var change = object(Map.of("baselineRequirementId", nullable(), "replacementRequirementId", nullable(), "changeType", choice("ADDED", "REMOVED", "MODIFIED", "UNCHANGED"), "reason", text(), "sourceReferences", refs));
            var assessment = object(Map.of("policyRequirementId", text(), "procedureVersionId", text(), "relatedProcedureRequirementIds", strings(), "classification", choice("CONTRADICTION", "MISSING_REQUIREMENT", "AMBIGUITY", "NO_CONFLICT"), "severity", choice("HIGH", "MEDIUM", "LOW", "NONE"), "rationale", text(), "suggestedAction", nullable(), "scopeExplanation", text(), "sourceReferences", refs));
            return tree(object(Map.of("changes", array(change, 0, 32), "assessments", array(assessment, 0, 64), "complete", Map.of("type", "boolean"), "limitations", strings())));
        }
        throw new IllegalArgumentException("Unknown server schema");
    }
}
