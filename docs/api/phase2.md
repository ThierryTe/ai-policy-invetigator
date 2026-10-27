# Phase 2 contracts

All routes except login and minimal health require a bearer JWT. Content responses
are scoped to current authorization. Inaccessible IDs return 404. Invalid/disabled
identities return 401. No JWT role/department claim is trusted as a permission grant.

| Method | Route | Input and result |
|---|---|---|
| POST | /api/auth/login | `{email,password}` → `{token,expiresIn:900,tokenType:"Bearer"}` |
| GET | /api/auth/me | `{user:{id,organizationId,email},memberships:[{department_id,department_name,role}]}` |
| POST | /api/policies | Multipart `file,title,kind,departmentId,effectiveDate`; kind POLICY/PROCEDURE; UUID Idempotency-Key → 202 `{policyId,versionId,jobId,status}` and Location job URL |
| POST | /api/policies/{id}/versions | Multipart `file,previousVersionId,effectiveDate`; UUID Idempotency-Key → same 202 response |
| GET | /api/policies?page=0 | Authorized array of at most 25 policy records; page must be 0–10000 |
| GET | /api/policies/{id} | JPA-backed authorized policy metadata |
| GET | /api/policies/{id}/versions | `{id,policy_id,sequence,previous_id,effective_date,filename,sha256,status,created_at,job_id,job_status,stage,error_code}[]` |
| GET | /api/policies/{id}/versions/{version}/content | Original PDF, attachment disposition, no-store |
| GET | /api/jobs/{id} | `{id,version_id,policy_id,status,stage,error_code,attempts}` |
| POST | /api/versions/{id}/search | `{query}` (1–2000 chars) → at most 10 `{id,version_id,page_number,start_offset,end_offset,excerpt,similarity}` records |
| GET | /api/evidence/{id} | `{id,version_id,policy_id,page_number,start_offset,end_offset,excerpt}` |

Dates use ISO YYYY-MM-DD. Offsets are zero-based Unicode code-point positions,
end-exclusive in the canonical page text. Page numbers are one-based. Excerpts
are source text, not model-generated quotations. Section heading detection is not
implemented. Similarity is a retrieval distance transformation, never confidence.

Jobs: QUEUED → RUNNING → COMPLETED/FAILED. Stages: QUEUED, EXTRACTING, EMBEDDING,
PERSISTING, COMPLETED, FAILED. The UI must not display invented percentages. Failed
jobs have stable safe error codes. An expired lease is reclaimed up to three attempts;
a stale worker cannot publish data. On access revocation, the job is failed and no
source content is published. Its version may remain QUEUED when permission no longer
allows a status update; job status is authoritative for ingestion progress. Version history includes the authorized job ID/state so polling can resume after a browser reload.

Idempotent replay requires the same actor, UUID key and exact request/PDF payload.
It returns the original IDs with status ACCEPTED; clients poll the job for current
state. Altered replays return 409. Original bytes are immutable; submit another
version to retry a terminal extraction failure. Replacement uploads require the
current latest predecessor, otherwise 409 STALE_PREDECESSOR.

Errors handled by the API use application/problem+json with `status`, `title`, and
`code`. Authentication failures can have an empty 401 response; the login throttle
returns 429 and Retry-After. Clients must branch on HTTP status before parsing a body.

## Future dashboard contracts (not implemented routes)

Phase 3/4 investigation requests will name baseline/new version IDs, procedure
version IDs and the analysis date. Responses will freeze this scope and return a job
ID with stage and completeness. Graph nodes reference policy/version IDs; edges
reference changed requirements and findings. Findings reference verified source IDs,
classification, severity, concise rationale, suggested action and review status.
Reviews contain decision/comment/expected revision. Reports and graph data require
current access to every contributing source. No placeholder findings or success
responses are served in Phase 2. Field casing of the new investigation DTOs will be
camelCase; the Angular API mapper can normalize the explicitly documented SQL views.

Search returns 409 EMBEDDING_REVISION_MISMATCH when a version was indexed with a different model revision; an empty result must not hide incompatible vectors.
