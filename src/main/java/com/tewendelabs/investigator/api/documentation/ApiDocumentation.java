package com.tewendelabs.investigator.api.documentation;

import java.net.URI;
import java.time.Instant;
import java.time.LocalDate;
import java.util.List;
import java.util.UUID;

import io.swagger.v3.oas.annotations.media.Schema;
import com.tewendelabs.investigator.security.IdentityService;

/**
 * Documentation views of existing map responses; never used for persistence or API execution.
 */
public final class ApiDocumentation {
    private ApiDocumentation() {
    }

    @Schema(name = "NewPolicyUpload")
    public record NewPolicyUpload(
            @Schema(requiredMode = Schema.RequiredMode.REQUIRED) UUID departmentId,
            @Schema(requiredMode = Schema.RequiredMode.REQUIRED, maxLength = 200) String title,
            @Schema(allowableValues = {"POLICY", "PROCEDURE"}, defaultValue = "POLICY") String kind,
            @Schema(requiredMode = Schema.RequiredMode.REQUIRED) LocalDate effectiveDate,
            @Schema(type = "string", format = "binary", requiredMode = Schema.RequiredMode.REQUIRED, description = "PDF file, at most 10 MiB.") String file) {
    }

    @Schema(name = "ReplacementPolicyUpload")
    public record ReplacementPolicyUpload(
            @Schema(requiredMode = Schema.RequiredMode.REQUIRED) UUID previousVersionId,
            @Schema(requiredMode = Schema.RequiredMode.REQUIRED) LocalDate effectiveDate,
            @Schema(type = "string", format = "binary", requiredMode = Schema.RequiredMode.REQUIRED, description = "PDF file, at most 10 MiB.") String file) {
    }

    @Schema(name = "LoginResponse")
    public record LoginResponse(
            @Schema(description = "Short-lived bearer token. No sample credential is provided.", accessMode = Schema.AccessMode.READ_ONLY) String token,
            @Schema(description = "Token lifetime in seconds.") int expiresIn, String tokenType) {
    }

    @Schema(name = "CurrentIdentity")
    public record CurrentIdentity(IdentityService.Identity user, List<Membership> memberships) {
    }

    public record Membership(UUID department_id, String department_name,
                             @Schema(allowableValues = {"VIEWER", "ANALYST", "REVIEWER", "ADMIN"}) String role) {
    }

    @Schema(name = "PolicyMetadata")
    public record PolicyMetadata(UUID id, UUID organizationId, UUID departmentId, String title,
                                 @Schema(allowableValues = {"POLICY", "PROCEDURE"}) String kind,
                                 boolean externalProcessingAllowed) {
    }

    @Schema(name = "PolicyVersion")
    public record PolicyVersion(UUID id, UUID policy_id, int sequence,
                                @Schema(nullable = true) UUID previous_id, LocalDate effective_date, String filename,
                                String sha256,
                                String status, Instant created_at, @Schema(nullable = true) UUID job_id,
                                @Schema(nullable = true) String job_status, @Schema(nullable = true) String stage,
                                @Schema(nullable = true) String error_code) {
    }

    @Schema(name = "IngestionProgress")
    public record IngestionProgress(UUID id, UUID version_id, UUID policy_id,
                                    @Schema(allowableValues = {"QUEUED", "RUNNING", "COMPLETED", "FAILED"}) String status,
                                    String stage, @Schema(nullable = true) String error_code, int attempts) {
    }

    @Schema(name = "SourceEvidence", description = "Persisted PDF source. Pages are one-based; offsets are zero-based Unicode code points, end-exclusive.")
    public record SourceEvidence(UUID id, UUID version_id, UUID policy_id, int page_number,
                                 int start_offset, int end_offset, String excerpt) {
    }

    @Schema(name = "SearchHit")
    public record SearchHit(UUID id, UUID version_id, int page_number, int start_offset, int end_offset,
                            String excerpt,
                            @Schema(description = "Retrieval similarity, not confidence in correctness.") double similarity) {
    }

    @Schema(name = "InvestigationAccepted")
    public record InvestigationAccepted(UUID id, @Schema(allowableValues = "QUEUED") String state) {
    }

    @Schema(name = "InvestigationProgress")
    public record InvestigationProgress(UUID id,
                                        @Schema(allowableValues = {"QUEUED", "RUNNING", "COMPLETED", "PARTIAL", "FAILED"}) String state,
                                        @Schema(allowableValues = {"QUEUED", "EXTRACTING", "ASSESSING", "COMPLETED", "STOPPED"}) String stage,
                                        @Schema(nullable = true, description = "Stable safe failure code; no provider body or document text.") String error_code,
                                        int attempts, int calls, int metered_calls, int prompt_tokens,
                                        int completion_tokens, long latency_ms) {
    }

    @Schema(name = "SourceReference", description = "Server-verified source ID and exact quote. Resolve page/offsets through the authorized evidence API.")
    public record SourceReference(UUID sourceId, @Schema(minLength = 1, maxLength = 2000) String quote) {
    }

    @Schema(name = "PolicyRequirement")
    public record PolicyRequirement(UUID id,
                                    @Schema(nullable = true) String actor, @Schema(nullable = true) String action,
                                    @Schema(nullable = true) String obligation,
                                    @Schema(nullable = true) String condition,
                                    @Schema(nullable = true) String scope, @Schema(nullable = true) String deadline,
                                    @Schema(nullable = true) List<String> exceptions,
                                    @Schema(nullable = true) LocalDate effectiveDate,
                                    List<String> unknownFields, List<SourceReference> sourceReferences) {
    }

    @Schema(name = "ExtractionPayload")
    public record ExtractionPayload(List<PolicyRequirement> requirements, List<UUID> processedSourceIds,
                                    @Schema(description = "Declared processing coverage; not proof of semantic correctness.") boolean complete,
                                    List<String> limitations) {
    }

    @Schema(name = "RequirementExtraction")
    public record RequirementExtraction(UUID version_id, ExtractionPayload payload, String model, String prompt_version,
                                        String schema_version) {
    }

    @Schema(name = "RequirementChange")
    public record RequirementChange(@Schema(nullable = true) UUID baselineRequirementId,
                                    @Schema(nullable = true) UUID replacementRequirementId,
                                    @Schema(allowableValues = {"ADDED", "REMOVED", "MODIFIED", "UNCHANGED"}) String changeType,
                                    String reason, List<SourceReference> sourceReferences) {
    }

    @Schema(name = "InvestigationFinding")
    public record InvestigationFinding(UUID id, UUID policyRequirementId, UUID procedureVersionId,
                                       List<UUID> relatedProcedureRequirementIds,
                                       @Schema(allowableValues = {"CONTRADICTION", "MISSING_REQUIREMENT", "AMBIGUITY", "NO_CONFLICT"}) String classification,
                                       @Schema(allowableValues = {"HIGH", "MEDIUM", "LOW", "NONE"}) String severity,
                                       String rationale, @Schema(nullable = true) String suggestedAction,
                                       String scopeExplanation,
                                       List<SourceReference> sourceReferences,
                                       @Schema(allowableValues = {"PENDING_REVIEW", "NOT_REQUIRED"}, description = "Original AI review requirement, unchanged by later review events.") String reviewStatus) {
    }

    @Schema(name = "AssessmentPayload")
    public record AssessmentPayload(List<RequirementChange> changes, List<InvestigationFinding> assessments,
                                    boolean complete, List<String> limitations) {
    }

    @Schema(name = "CompletedFindings")
    public record CompletedFindings(AssessmentPayload payload, String model, String prompt_version,
                                    String schema_version, boolean canReview,
                                    List<com.tewendelabs.investigator.investigation.InvestigationDashboardService.ReviewState> reviews) {
    }

    @Schema(name = "IncompleteFindings", description = "complete is false; changes/assessments are empty. Never interpret this as NO_CONFLICT.")
    public record IncompleteFindings(boolean complete, List<RequirementChange> changes,
                                     List<InvestigationFinding> assessments, InvestigationProgress progress, boolean canReview,
                                     List<com.tewendelabs.investigator.investigation.InvestigationDashboardService.ReviewState> reviews) {
    }

    @Schema(name = "SafeProblem", description = "Safe application problem details. Authentication/filter failures can instead have an empty body.")
    public record SafeProblem(URI type, String title, int status, @Schema(nullable = true) URI instance, String code) {
    }
}
