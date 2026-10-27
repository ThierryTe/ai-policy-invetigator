# Phase 3 API contracts

All routes require the Phase 2 bearer JWT. Permissions come from current database
memberships/grants, not token role claims. An inaccessible investigation or source
returns 404. Failure bodies use the existing safe problem-details contract.

| Method | Route | Input and result |
|---|---|---|
| POST | /api/policies/{id}/external-processing | `{allowed:true}` → 204; owning-department ADMIN required; false revokes consent |
| POST | /api/investigations | UUID Idempotency-Key and scope below → 202 `{id,state:"QUEUED"}` with Location |
| GET | /api/investigations/{id} | `{id,state,stage,error_code,attempts,calls,metered_calls,prompt_tokens,completion_tokens,latency_ms}` |
| GET | /api/investigations/{id}/requirements | `[{version_id,payload,model,prompt_version,schema_version}]` |
| GET | /api/investigations/{id}/findings | Complete: `{payload,model,prompt_version,schema_version}`; otherwise `{complete:false,changes:[],assessments:[],progress}` |
| GET | /api/evidence/{sourceId} | Existing authorized original excerpt, version, policy, page and offsets |

```json
{
  "baselineVersionId": "<UUID>",
  "replacementVersionId": "<UUID>",
  "procedureVersionIds": ["<UUID>"],
  "analysisDate": "2026-10-27"
}
```

All versions must be indexed, authorized, externally consented and effective by the
analysis date. The baseline must be the replacement's immediate predecessor in the
same POLICY. Procedure versions must have kind PROCEDURE. IDs must be distinct;
select 1–4 procedures. Creation requires replacement write permission. Replay with
the same actor/key/payload returns the existing investigation; changed payload is 409.
No source text is accepted in this API request.

Extraction payload: `{requirements,processedSourceIds,complete,limitations}`.
Requirements contain server-generated `id`, actor, action, obligation, condition,
scope, deadline, exceptions, effectiveDate, unknownFields and sourceReferences.
Unknown scalars/exception lists remain null and are named in unknownFields.
Source references contain `sourceId` and a verified verbatim `quote`; resolve page
and offset via the evidence endpoint. Never render source text as trusted HTML.

Complete assessment payload: `{changes,assessments,complete:true,limitations}`.
Changes contain baselineRequirementId/replacementRequirementId (nullable for
added/removed rules), changeType ADDED/REMOVED/MODIFIED/UNCHANGED, reason and evidence.
Assessments contain server `id`, policyRequirementId, procedureVersionId,
relatedProcedureRequirementIds, classification, severity, rationale, suggestedAction,
scopeExplanation, sourceReferences and reviewStatus. Classification is one of
CONTRADICTION/MISSING_REQUIREMENT/AMBIGUITY/NO_CONFLICT; severity is HIGH/MEDIUM/LOW/NONE.
Actionable results are PENDING_REVIEW; NO_CONFLICT is NOT_REQUIRED.

States and stages are actual persisted progress, not a fabricated percentage.
Only COMPLETED plus `payload.complete=true` is a finished assessment. PARTIAL/FAILED,
empty results and provider errors cannot be presented as NO_CONFLICT. Extraction
checkpoints may be available during partial processing; they are not findings.
Metered calls count responses with validated usage; calls also include failed and
retried dispatches. Latency is summed successful, metered provider elapsed time,
not investigation wall time. A final dispatch can exceed the reported-token budget.

Safe errors include EXTERNAL_PROCESSING_DENIED, ACCESS_OR_CONSENT_REVOKED,
UNVERIFIABLE_SOURCE_REFERENCE, INVALID_MODEL_SCHEMA, INCOMPLETE_EXTRACTION,
INCOMPLETE_ASSESSMENT, PROVIDER_TIMEOUT, PROVIDER_AUTHENTICATION_FAILED,
INVESTIGATION_BUDGET_OR_LEASE_EXHAUSTED and SOURCE_COVERAGE_BUDGET_EXCEEDED.
See source for the exhaustive set; clients should handle unknown safe codes generically.

The future dashboard can map requirements/version IDs to graph nodes and assessments
to edges while resolving evidence on selection. There is no graph aggregate, review
submission, single-finding route, export or Angular dashboard in this phase. Pending
review is a mandatory state, not a completed human approval.
