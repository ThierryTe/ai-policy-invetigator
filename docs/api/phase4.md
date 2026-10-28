# Phase 4 Angular dashboard contract

All `/api/**` routes below require `Authorization: Bearer <JWT>` and current identity.
Use the same origin via the eventual Angular reverse proxy. No CORS change is needed
for that setup. Resource absence and inaccessible scope both return 404. Never cache
evidence across logout, membership changes or users. Render excerpts/notes as text,
not HTML. Production OpenAPI/Swagger remains denied.

Existing upload, version, ingestion and login contracts are unchanged:
[Phase 2](phase2.md), [Phase 3](phase3.md). The local generated `/v3/api-docs`
also includes the two new routes. No graph/review request invokes Meta or embeddings.

## Dashboard request sequence

1. `POST /api/auth/login` → `{token}`; `GET /api/auth/me` supplies current identity
   and memberships. Keep tokens in memory; authentication examples contain no secrets.
2. `GET /api/policies?page=0` and `GET /api/policies/{id}/versions` provide selectors.
   Upload replacement PDFs using the existing multipart route; poll `/api/jobs/{id}`.
3. `POST /api/investigations` with UUID `Idempotency-Key` and
   `{baselineVersionId,replacementVersionId,procedureVersionIds,analysisDate}` → 202
   `{id,state:"QUEUED"}`. Procedure list length is 1–4. The replacement must directly
   follow the baseline. This MVP investigates an explicit scope, not enterprise-wide discovery.
4. Poll `GET /api/investigations/{id}` about once per second. Its fields are
   `{id,state,stage,error_code,attempts,calls,metered_calls,prompt_tokens,completion_tokens,latency_ms}`.
   `state`: QUEUED, RUNNING, COMPLETED, PARTIAL, FAILED. `stage`: QUEUED, EXTRACTING,
   ASSESSING, COMPLETED, STOPPED. Stop polling at a terminal state; offer a new
   investigation after a safe failure. A terminal incomplete state never means NO_CONFLICT.
5. Fetch `/requirements`, `/findings`, `/graph`. Retrieve individual quoted chunks
   using `GET /api/evidence/{sourceId}` when a finding is selected. Recheck 404 at
   every read; clear the view if access has been revoked.
6. Submit reviews using the route below. Update review state from its returned value
   or refetch findings. Reviews never alter the AI classification or evidence.

All routes require current read access to **every** selected version, including
baseline and every procedure. Partial filtering would reveal hidden relationships;
the server instead returns 404 for the entire investigation if any document is revoked.
External-processing consent is checked for every model attempt. Viewing existing
results or reviewing them does not send documents to a provider and does not require
new external-processing consent.

## GET `/api/investigations/{id}/findings`

Existing completed response plus two additive fields:

```ts
type Classification = 'CONTRADICTION' | 'MISSING_REQUIREMENT' | 'AMBIGUITY' | 'NO_CONFLICT';
type ReviewAction = 'CONFIRM' | 'DISMISS' | 'ADD_NOTE';
interface Reference { sourceId: string; quote: string }
interface Finding {
  id: string; policyRequirementId: string; procedureVersionId: string;
  relatedProcedureRequirementIds: string[];
  classification: Classification; severity: 'HIGH' | 'MEDIUM' | 'LOW' | 'NONE';
  rationale: string; suggestedAction: string | null; scopeExplanation: string;
  sourceReferences: Reference[];
  reviewStatus: 'PENDING_REVIEW' | 'NOT_REQUIRED'; // immutable initial AI requirement
}
interface ReviewEvent {
  id: string; findingId: string; reviewerId: string;
  action: ReviewAction; note: string | null; createdAt: string; // ISO UTC timestamp
}
interface ReviewState {
  findingId: string;
  status: 'PENDING_REVIEW' | 'NOT_REQUIRED' | 'CONFIRMED' | 'DISMISSED';
  history: ReviewEvent[]; // persisted sequence order; latest decision wins
}
// Completed:
interface CompletedFindings {
  payload: {
    changes: { baselineRequirementId: string | null; replacementRequirementId: string | null;
               changeType: 'ADDED' | 'REMOVED' | 'MODIFIED' | 'UNCHANGED';
               reason: string; sourceReferences: Reference[] }[];
    assessments: Finding[]; complete: true; limitations: string[];
  };
  model: string; prompt_version: string; schema_version: string;
  canReview: boolean; reviews: ReviewState[];
}
// No published assessment (queued, running, partial or failed):
// {complete:false,changes:[],assessments:[],progress:<poll response>,canReview:boolean,reviews:[]}
```

Join `reviews` to findings by `findingId`; display the overlay `status`, and keep
`reviewStatus` as the original AI requirement. An added note does not change a
confirmed/dismissed decision. Notes and previous decisions stay visible after later
decisions. Reviewer UUIDs are audit identities; email addresses are not exposed.
`canReview` reflects current role and complete document scope; enforcement occurs
again on every POST, independent of UI visibility.

`GET /requirements` remains
`[{version_id,payload:{requirements,processedSourceIds,complete,limitations},model,prompt_version,schema_version}]`.
Requirements contain server-issued `id`, actor, action, obligation, condition, scope,
deadline, exceptions, effectiveDate, unknownFields and sourceReferences. Nullable
fields remain unknown; the UI must not convert null to a negative assertion.

## GET `/api/investigations/{id}/graph`

```ts
interface ImpactGraph {
  investigationId: string;
  complete: boolean; // false before a complete, persisted assessment exists
  nodes: {
    id: string; // version UUID, server-issued requirement UUID or finding UUID
    type: 'BASELINE' | 'REPLACEMENT' | 'PROCEDURE' | 'REQUIREMENT' | 'FINDING';
    label: string;
    versionId: string;
    classification: Classification | null; // FINDING only
    severity: 'HIGH' | 'MEDIUM' | 'LOW' | 'NONE' | null; // FINDING only
  }[];
  edges: {
    source: string; target: string; // existing node IDs
    type: 'REPLACED_BY' | 'CONTAINS' | 'MODIFIED' |
          'UNCHANGED' | 'ASSESSED_AS' | 'AFFECTS' | 'SUPPORTED_BY';
  }[];
}
```

Edges: baseline → replacement `REPLACED_BY`; version → requirement `CONTAINS`;
aligned baseline requirement → replacement requirement `MODIFIED`/`UNCHANGED`;
replacement requirement → finding `ASSESSED_AS`; finding → procedure `AFFECTS`;
finding → cited related procedure requirement `SUPPORTED_BY`. Added/removed
requirements have no counterpart, so appear through CONTAINS and assessments rather
than an invented counterpart edge. ADDED/REMOVED details are in `payload.changes`.
AFFECTS means the pair was assessed, including NO_CONFLICT; it is not a claim that
an action is needed. Filter or color findings using classification/severity.

Only selected persisted versions appear. During extraction, the graph may contain
only version lineage or partial requirement checkpoints. No inferred similarity or
unpersisted provider output creates an edge. The server rechecks each stored source
reference against currently readable chunk text. Invalid persisted references yield
409 `UNVERIFIED_GRAPH_DATA`; an incomplete graph is not evidence of no impact.
Graph node IDs let Angular select an item in the already loaded findings/requirements.

## POST `/api/investigations/{id}/findings/{findingId}/reviews`

JSON body: `{ "action": "CONFIRM" | "DISMISS" | "ADD_NOTE", "note": string | null }`.
`note` is optional for decisions; required/nonblank for ADD_NOTE; maximum 2,000
Java characters. Blank optional notes normalize to null, other notes are trimmed.
Returns **200** `ReviewState` for the selected finding, including the appended event.
The server sets reviewer UUID, event UUID and UTC timestamp; clients cannot supply them.

Requires REVIEWER or ADMIN membership in the replacement policy's owning department
**and** read access to every contributing version. ANALYST and VIEWER alone cannot
review. A reviewer's membership in another department, even with READ grants to
all documents, is insufficient. All authorized readers can see the review history.
Runtime SQL grants allow SELECT/INSERT only and forced RLS independently enforces
reviewer identity, scope, role and existence of the finding inside that investigation.
There is no update/delete endpoint and no mutation grant for review history.

- 400 `INVALID_REVIEW` or safe invalid-request response: unknown action, blank note,
  missing action or overlong note.
- 401: missing/invalid/expired/inactive identity.
- 403 `REVIEW_PERMISSION_REQUIRED`: scope is readable but review role is absent.
- 404 `NOT_FOUND`: missing/inaccessible investigation or finding not in that investigation.
- 500: safe internal failure; no exception text.

Disable the submit button while a review is in flight. This MVP appends one event
per successful POST; it does not deduplicate retried POSTs. Concurrent decisions are
serialized per investigation and last persisted decision wins; both remain audited.
Confirming is human acknowledgement, not automatic remediation or proof of correctness.

## Verified citation detail and dashboard KPIs

`GET /api/evidence/{sourceId}` returns the existing snake-case source fields:
`{id,version_id,policy_id,page_number,start_offset,end_offset,excerpt}`.
Offsets locate the stored chunk in normalized page text (Unicode code points), not
PDF pixel coordinates. A finding's exact `quote` is a verbatim substring of that
excerpt. Retain version and page alongside both displayed source excerpts; more
than two citations are possible. The full PDF is available through the existing
version-content route under the same authorization rules.

For a completed investigation: Rules Analyzed = replacement requirements count;
Potential Conflicts = CONTRADICTION assessments count; Missing Requirements =
MISSING_REQUIREMENT count. These are requirement/procedure pairs, not unique policies.
Evidence Coverage can display the fraction of published assessments with verified
policy and procedure citations, with a label explaining that this measures citation
coverage, not model correctness. Incomplete processing must show a partial/unknown
indicator instead of a green 100% or zero-conflicts summary. No extra KPI endpoint
is needed for this bounded scope.
