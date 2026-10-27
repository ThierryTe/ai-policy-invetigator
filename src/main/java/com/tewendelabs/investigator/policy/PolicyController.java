package com.tewendelabs.investigator.policy;

import java.io.IOException;
import java.net.URI;
import java.time.LocalDate;
import java.util.*;

import org.springframework.http.*;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.security.oauth2.jwt.Jwt;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.multipart.MultipartFile;
import com.tewendelabs.investigator.api.ApiFailure;

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
@Tag(name = "Policies and evidence", description = "Current document access is required for every source and result.")
@RestController
@RequestMapping("/api")
public class PolicyController {
    private final PolicyService service;

    public PolicyController(PolicyService service) {
        this.service = service;
    }

    private UUID user(Jwt jwt) {
        return UUID.fromString(jwt.getSubject());
    }

    @Operation(summary = "Upload a policy or procedure PDF", description = "Creates an immutable initial version and asynchronous ingestion job. Requires department write permission.")
    @ApiResponse(responseCode = "202", description = "Accepted; poll the ingestion job.", headers = @Header(name = "Location", description = "Relative ingestion-job polling URL", schema = @Schema(type = "string")), content = @Content(mediaType = "application/json", schema = @Schema(implementation = PolicyService.Upload.class)))
    @io.swagger.v3.oas.annotations.parameters.RequestBody(required = true, content = @Content(mediaType = "multipart/form-data", schema = @Schema(implementation = ApiDocumentation.NewPolicyUpload.class)))
    @ApiResponse(responseCode = "413", description = "PDF or multipart request exceeds the upload limit.", content = @Content(mediaType = "application/problem+json", schema = @Schema(implementation = ApiDocumentation.SafeProblem.class)))
    @ApiResponse(responseCode = "415", description = "PDF required.", content = @Content(mediaType = "application/problem+json", schema = @Schema(implementation = ApiDocumentation.SafeProblem.class)))
    @PostMapping(value = "/policies", consumes = MediaType.MULTIPART_FORM_DATA_VALUE)
    public ResponseEntity<PolicyService.Upload> create(@Parameter(hidden = true) @AuthenticationPrincipal Jwt jwt, @Parameter(description = "Required UUID idempotency key; replay requires identical payload.") @RequestHeader("Idempotency-Key") UUID key,
                                                       @Parameter(hidden = true) @RequestParam UUID departmentId, @Parameter(hidden = true) @RequestParam String title, @Parameter(hidden = true) @RequestParam(defaultValue = "POLICY") String kind, @Parameter(hidden = true) @RequestParam @org.springframework.format.annotation.DateTimeFormat(iso = org.springframework.format.annotation.DateTimeFormat.ISO.DATE) LocalDate effectiveDate, @Parameter(hidden = true) @RequestPart MultipartFile file) throws IOException {
        return accepted(service.upload(user(jwt), key, null, departmentId, title, kind, null, effectiveDate, file.getOriginalFilename(), file.getBytes()));
    }

    @Operation(summary = "Upload a replacement PDF version", description = "Requires current policy write permission and the latest predecessor. Prior bytes remain immutable.")
    @ApiResponse(responseCode = "202", description = "Accepted; poll the ingestion job.", headers = @Header(name = "Location", description = "Relative ingestion-job polling URL", schema = @Schema(type = "string")), content = @Content(mediaType = "application/json", schema = @Schema(implementation = PolicyService.Upload.class)))
    @io.swagger.v3.oas.annotations.parameters.RequestBody(required = true, content = @Content(mediaType = "multipart/form-data", schema = @Schema(implementation = ApiDocumentation.ReplacementPolicyUpload.class)))
    @ApiResponse(responseCode = "413", description = "PDF or multipart request exceeds the upload limit.", content = @Content(mediaType = "application/problem+json", schema = @Schema(implementation = ApiDocumentation.SafeProblem.class)))
    @ApiResponse(responseCode = "415", description = "PDF required.", content = @Content(mediaType = "application/problem+json", schema = @Schema(implementation = ApiDocumentation.SafeProblem.class)))
    @PostMapping(value = "/policies/{id}/versions", consumes = MediaType.MULTIPART_FORM_DATA_VALUE)
    public ResponseEntity<PolicyService.Upload> version(@Parameter(hidden = true) @AuthenticationPrincipal Jwt jwt, @Parameter(description = "Required UUID idempotency key; replay requires identical payload.") @RequestHeader("Idempotency-Key") UUID key,
                                                        @PathVariable UUID id, @Parameter(hidden = true) @RequestParam UUID previousVersionId, @Parameter(hidden = true) @RequestParam @org.springframework.format.annotation.DateTimeFormat(iso = org.springframework.format.annotation.DateTimeFormat.ISO.DATE) LocalDate effectiveDate, @Parameter(hidden = true) @RequestPart MultipartFile file) throws IOException {
        return accepted(service.upload(user(jwt), key, id, null, null, null, previousVersionId, effectiveDate, file.getOriginalFilename(), file.getBytes()));
    }

    private ResponseEntity<PolicyService.Upload> accepted(PolicyService.Upload result) {
        return ResponseEntity.accepted().location(URI.create("/api/jobs/" + result.jobId())).body(result);
    }

    @Operation(summary = "List authorized policies", description = "At most 25 entries. Page must be between 0 and 10000.")
    @ApiResponse(responseCode = "200", description = "Successful response.", content = @Content(mediaType = "application/json", array = @ArraySchema(schema = @Schema(implementation = ApiDocumentation.PolicyMetadata.class))))
    @GetMapping("/policies")
    public List<Policy> list(@Parameter(hidden = true) @AuthenticationPrincipal Jwt jwt, @RequestParam(defaultValue = "0") int page) {
        if (page < 0 || page > 10000) throw new ApiFailure(400, "INVALID_PAGE");
        return service.list(user(jwt), page);
    }

    @Operation(summary = "Read policy metadata", description = "Current role, department and explicit grants apply.")
    @ApiResponse(responseCode = "200", description = "Successful response.", content = @Content(mediaType = "application/json", schema = @Schema(implementation = ApiDocumentation.PolicyMetadata.class)))
    @GetMapping("/policies/{id}")
    public Policy get(@Parameter(hidden = true) @AuthenticationPrincipal Jwt jwt, @PathVariable UUID id) {
        return service.get(user(jwt), id);
    }

    @Operation(summary = "Read immutable version history", description = "Includes authorized ingestion progress for each version.")
    @ApiResponse(responseCode = "200", description = "Successful response.", content = @Content(mediaType = "application/json", array = @ArraySchema(schema = @Schema(implementation = ApiDocumentation.PolicyVersion.class))))
    @GetMapping("/policies/{id}/versions")
    public List<Map<String, Object>> versions(@Parameter(hidden = true) @AuthenticationPrincipal Jwt jwt, @PathVariable UUID id) {
        return service.versions(user(jwt), id);
    }

    @Operation(summary = "Download the original PDF", description = "Returns original bytes with attachment disposition and no-store caching.")
    @ApiResponse(responseCode = "200", description = "Successful response.", content = @Content(mediaType = "application/pdf", schema = @Schema(type = "string", format = "binary")))
    @GetMapping("/policies/{id}/versions/{version}/content")
    public ResponseEntity<byte[]> content(@Parameter(hidden = true) @AuthenticationPrincipal Jwt jwt, @PathVariable UUID id, @PathVariable UUID version) {
        return ResponseEntity.ok().contentType(MediaType.APPLICATION_PDF).header("Content-Disposition", "attachment; filename=policy.pdf").header("Cache-Control", "no-store").body(service.content(user(jwt), id, version));
    }

    @Operation(summary = "Poll document ingestion", description = "Job status is authoritative; failed or incomplete ingestion is not searchable.")
    @ApiResponse(responseCode = "200", description = "Successful response.", content = @Content(mediaType = "application/json", schema = @Schema(implementation = ApiDocumentation.IngestionProgress.class)))
    @GetMapping("/jobs/{id}")
    public Map<String, Object> job(@Parameter(hidden = true) @AuthenticationPrincipal Jwt jwt, @PathVariable UUID id) {
        return service.job(user(jwt), id);
    }

    @Operation(summary = "Read source evidence", description = "Rechecks current access and returns the persisted excerpt, version, page and offsets.")
    @ApiResponse(responseCode = "200", description = "Successful response.", content = @Content(mediaType = "application/json", schema = @Schema(implementation = ApiDocumentation.SourceEvidence.class)))
    @GetMapping("/evidence/{id}")
    public Map<String, Object> evidence(@Parameter(hidden = true) @AuthenticationPrincipal Jwt jwt, @PathVariable UUID id) {
        return service.evidence(user(jwt), id);
    }

    public record Search(
            @Schema(minLength = 1, maxLength = 2000, requiredMode = Schema.RequiredMode.REQUIRED) String query) {
    }

    @Operation(summary = "Search within an authorized version", description = "Uses local embeddings. Similarity does not establish correctness.")
    @ApiResponse(responseCode = "200", description = "Successful response.", content = @Content(mediaType = "application/json", array = @ArraySchema(schema = @Schema(implementation = ApiDocumentation.SearchHit.class))))
    @PostMapping("/versions/{id}/search")
    public List<Map<String, Object>> search(@Parameter(hidden = true) @AuthenticationPrincipal Jwt jwt, @PathVariable UUID id, @RequestBody Search request) {
        return service.search(user(jwt), id, request.query());
    }
}
