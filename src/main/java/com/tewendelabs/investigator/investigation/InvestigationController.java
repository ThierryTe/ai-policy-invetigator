package com.tewendelabs.investigator.investigation;

import java.net.URI;
import java.util.*;

import org.springframework.http.ResponseEntity;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.security.oauth2.jwt.Jwt;
import org.springframework.web.bind.annotation.*;

import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.Parameter;
import io.swagger.v3.oas.annotations.media.ArraySchema;
import io.swagger.v3.oas.annotations.media.Content;
import io.swagger.v3.oas.annotations.media.Schema;
import io.swagger.v3.oas.annotations.responses.ApiResponse;
import io.swagger.v3.oas.annotations.responses.ApiResponses;
import io.swagger.v3.oas.annotations.headers.Header;
import io.swagger.v3.oas.annotations.tags.Tag;
import com.tewendelabs.investigator.api.documentation.ApiDocumentation;

@ApiResponses({
        @ApiResponse(responseCode = "400", description = "Invalid request.", content = @Content(mediaType = "application/problem+json", schema = @Schema(implementation = ApiDocumentation.SafeProblem.class))),
        @ApiResponse(responseCode = "401", description = "Authentication missing, invalid, expired or no longer active. Body may be empty.", content = @Content(mediaType = "application/problem+json", schema = @Schema(implementation = ApiDocumentation.SafeProblem.class))),
        @ApiResponse(responseCode = "404", description = "Resource missing or inaccessible under current permissions.", content = @Content(mediaType = "application/problem+json", schema = @Schema(implementation = ApiDocumentation.SafeProblem.class))),
        @ApiResponse(responseCode = "409", description = "State, lineage, embedding revision or idempotency conflict.", content = @Content(mediaType = "application/problem+json", schema = @Schema(implementation = ApiDocumentation.SafeProblem.class))),
        @ApiResponse(responseCode = "500", description = "Safe internal failure; no raw exception detail.", content = @Content(mediaType = "application/problem+json", schema = @Schema(implementation = ApiDocumentation.SafeProblem.class)))
})
@Tag(name = "Investigations", description = "Findings require current access to every contributing document.")
@RestController
@RequestMapping("/api")
public class InvestigationController {
    private final InvestigationService service;

    public InvestigationController(InvestigationService service) {
        this.service = service;
    }

    @Operation(summary = "Start a policy-change investigation", description = "Requires indexed, effective and externally consented selected versions, baseline/replacement lineage, and current replacement write permission. Processing is asynchronous.")
    @ApiResponse(responseCode = "202", description = "Accepted; poll the investigation.", headers = @Header(name = "Location", description = "Relative investigation polling URL", schema = @Schema(type = "string")), content = @Content(mediaType = "application/json", schema = @Schema(implementation = ApiDocumentation.InvestigationAccepted.class)))
    @PostMapping("/investigations")
    public ResponseEntity<Map<String, Object>> create(@Parameter(hidden = true) @AuthenticationPrincipal Jwt jwt, @Parameter(description = "Required UUID idempotency key; replay requires identical scope.") @RequestHeader("Idempotency-Key") UUID key, @RequestBody InvestigationService.Create request) {
        UUID id = service.create(UUID.fromString(jwt.getSubject()), key, request);
        return ResponseEntity.accepted().location(URI.create("/api/investigations/" + id)).body(Map.of("id", id, "state", "QUEUED"));
    }

    @Operation(summary = "Poll investigation progress", description = "Persisted state and reported usage. PARTIAL or FAILED never means NO_CONFLICT.")
    @ApiResponse(responseCode = "200", description = "Successful response.", content = @Content(mediaType = "application/json", schema = @Schema(implementation = ApiDocumentation.InvestigationProgress.class)))
    @GetMapping("/investigations/{id}")
    public Map<String, Object> progress(@Parameter(hidden = true) @AuthenticationPrincipal Jwt jwt, @PathVariable UUID id) {
        return service.progress(UUID.fromString(jwt.getSubject()), id);
    }

    @Operation(summary = "Read extracted requirements", description = "May contain partial checkpoints; model, prompt and schema metadata are preserved.")
    @ApiResponse(responseCode = "200", description = "Successful response.", content = @Content(mediaType = "application/json", array = @ArraySchema(schema = @Schema(implementation = ApiDocumentation.RequirementExtraction.class))))
    @GetMapping("/investigations/{id}/requirements")
    public List<Map<String, Object>> requirements(@Parameter(hidden = true) @AuthenticationPrincipal Jwt jwt, @PathVariable UUID id) {
        return service.extractions(UUID.fromString(jwt.getSubject()), id);
    }

    @Operation(summary = "Read verified findings", description = "Complete and incomplete response variants differ. Actionable findings remain pending human review.")
    @ApiResponse(responseCode = "200", description = "Successful response.", content = @Content(mediaType = "application/json", schema = @Schema(oneOf = {ApiDocumentation.CompletedFindings.class, ApiDocumentation.IncompleteFindings.class})))
    @GetMapping("/investigations/{id}/findings")
    public Map<String, Object> findings(@Parameter(hidden = true) @AuthenticationPrincipal Jwt jwt, @PathVariable UUID id) {
        return service.findings(UUID.fromString(jwt.getSubject()), id);
    }

    public record Consent(boolean allowed) {
    }

    @Operation(summary = "Set external-processing consent", description = "Requires ADMIN membership in the owning department. Revocation prevents subsequent processing.")
    @ApiResponse(responseCode = "204", description = "Consent updated.", content = @Content)
    @PostMapping("/policies/{id}/external-processing")
    public ResponseEntity<Void> consent(@Parameter(hidden = true) @AuthenticationPrincipal Jwt jwt, @PathVariable UUID id, @RequestBody Consent request) {
        service.consent(UUID.fromString(jwt.getSubject()), id, request.allowed());
        return ResponseEntity.noContent().build();
    }
}
