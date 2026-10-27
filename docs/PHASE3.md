# Phase 3 — verified Meta investigation workflow

The packaged Java backend completed a genuine `muse-spark-1.3` investigation on
October 27, 2026. Four synthetic PDFs passed through PDF ingestion, local ONNX
embeddings, structured Meta extraction, comparison, persistence and authorized
HTTP evidence lookup. No substitute reasoning provider was used for this run.

The final run found the applicable training-before-access contradiction and returned
NO_CONFLICT for a procedure withholding sensitive-system access until training.
Its five calls used 6,368 prompt and 8,200 completion tokens; aggregate provider
latency was 47,469 ms and investigation wall time was 48,732 ms. All
25 cited source/quote instances matched authorized persisted evidence. See
[phase3-demo.json](verification/phase3-demo.json); earlier successful runs are
retained in `verification/phase3-attempts/`. These numbers describe actual calls,
not estimates or general performance guarantees.

## Implementation

`PolicyReasoningProvider` separates reasoning from Spring AI local embeddings.
`MetaPolicyReasoningProvider` uses the actual authenticated contract established by
[the access preflight](verification/meta-api-preflight.json):
`POST https://api.meta.ai/v1/chat/completions`, bearer authentication, the verified
model, strict `response_format.json_schema`, low reasoning effort and a 4,096-token
completion limit. Production transport is pinned to that HTTPS endpoint and rejects
redirects. It verifies returned model, completion status, usage and structured JSON;
no OpenAI dependency or compatibility assumption is involved.

Extraction records actor, action, obligation, condition, scope, deadline, exceptions,
effective date, explicit null/unknown fields and exact source ID/quote pairs. The
server assigns requirement IDs; model IDs cannot introduce new evidence. Every
quote must be an exact substring of a supplied persisted chunk. Existing evidence
routes resolve its original version, page and canonical Unicode offsets. Each
checkpoint records model, prompt version, schema version and source hash. Recovery
rejects mismatched checkpoints, including a changed model configuration.

A small server-owned JSON Schema vocabulary is validated independently of Meta's
structured-output enforcement. Extra properties, wrong types, excessive sizes,
invalid dates, fabricated IDs/quotes, unknown-field inconsistencies and incomplete
source/requirement coverage are rejected. Citation validation proves source identity
and text correspondence; human review is still required to judge interpretation.

Investigations freeze a direct baseline/replacement lineage, analysis date and one
to four explicitly selected procedure versions. For this bounded MVP, all selected
authorized procedure requirements are compared rather than using semantic top-k
filtering that could omit a requirement. Automatic enterprise-wide discovery is
not implemented. The result aligns old/new requirements and returns one assessment
per replacement requirement and procedure: CONTRADICTION, MISSING_REQUIREMENT,
AMBIGUITY or NO_CONFLICT. Missing requirements refer only to the fully processed
selected scope. Null fields are preserved; a complete flag describes coverage and
never establishes correctness.

Actionable findings receive PENDING_REVIEW. They do not automatically change policy,
grant access or implement a suggestion. Review submission, dashboard controls,
graph aggregation and exported reports are not implemented in this increment.

## Security and durability

V3 adds immutable investigation scope, extraction and assessment tables with forced
RLS. An investigation is readable only while the caller can read every contributing
version. Its derived data inherits that rule. SQL, JPA and workers retain the Phase 2
`ScopedAccess` transaction/current-identity boundary. The runtime cannot directly
read private job tables. Security-definer helpers have a non-superuser owner and
locked search paths. Existing Phase 2 migration/evidence files were not rewritten.

Every provider attempt, including retries, checks active identity, current access to
every selected document, replacement write permission, external-processing consent,
actual source text and scope, lease and budgets. Checks occur after concurrency
acquisition and retry backoff. Responses are checked again before checkpoint/result
persistence. A consent change requires ADMIN membership in the owning department;
V4 enforces this for runtime SQL/JPA as well as the HTTP endpoint. V5 makes the
persisted first-claim deadline configurable; recovery retains the original deadline. An ADMIN role in
another department grants no global access. Consent withdrawal prevents subsequent
processing; it cannot retract content already transmitted in an earlier authorized
request. A network request and a concurrent permission change are not atomic.

Jobs persist QUEUED/RUNNING/COMPLETED/PARTIAL/FAILED and EXTRACTING/ASSESSING stages,
safe failure codes, attempt/call counters, reported usage and latency. An expired
lease can be reclaimed up to three attempts; fencing blocks stale commits. Stored
extractions are reused after restart. An incomplete response or provider failure
never becomes NO_CONFLICT, and incomplete assessments are not published as findings.

Limits: one investigation worker per instance; Meta semaphore defaults to two slots
(configurable 1–4), timeout 30 seconds (1–60), at most two retries with bounded
backoff, 256 KiB response limit, four-minute default total job deadline (configurable 30–600 seconds), 20 dispatched calls
and a 40,000 reported-token threshold before further dispatch. The last response
can cross that threshold. Timed-out calls may incur unreported provider usage.
Override provider settings with META_MODEL_ID, META_TIMEOUT_SECONDS,
META_MAX_RETRIES, META_CONCURRENCY and META_INVESTIGATION_BUDGET_SECONDS (Compose forwards these without logging them).
The complete HTTP header/body read shares one deadline. Sources are limited to
20 chunks/16,000 characters per version, 20,000 aggregate source characters and
32,000 encoded request characters. Over-budget processing fails explicitly.
Limits are deliberately conservative; there is no silent document truncation.

Logs contain job IDs and safe event codes, not document text, prompts, model bodies,
credentials or tokens. Progress exposes numeric token counts and latency only.

## Reproduce

Keep root `.env` private and populate MODEL_API_KEY through your editor. Existing
real process variables take precedence. Dotenv configuration and packaging evidence
remain in [dotenv-results.json](verification/dotenv-results.json). Production uses
runtime secrets with `SPRINGDOTENV_ENABLED=false` and the prod profile. Neither `.env`
nor `.local` is packaged or mounted into the backend.

With the dedicated local PostgreSQL database/model cache already initialized:

```sh
./mvnw -Pneural-embeddings,database-tests verify
python3 -m unittest discover -s scripts/tests -v
python3 scripts/verify_provenance.py
python3 scripts/smoke_investigation.py
```

The demo starts/stops the supplied nonroot Linux backend, uses real Meta credentials
from Compose environment files, creates isolated synthetic accounts/documents and
leaves that data in the dedicated local database. It also checks cross-department
404s, current membership revocation and every citation against the evidence API.
The input and expected outcomes are in [the golden cases](../evaluation/phase3-golden.json).
Use [Phase 3 API contracts](api/phase3.md) for manual requests.

## Verification and limits

[phase3-results.json](verification/phase3-results.json) records the actual final
build/tests, preservation checks, provenance and demo result. Controlled transport
fixtures test failures without contacting Meta; they are not accuracy evidence.
The separate real run uses Meta and the actual local embedding model.

The golden set has one positive and one negative procedure case. Its procedure-level
precision/recall and exact-quote citation correctness are smoke measurements only.
Broader exceptions, ambiguity, missing requirements, large-document quality,
multitenant load, distributed throttling, cancel/resume UX and production operations
remain unverified or deferred. Model reasoning is advisory even when citations match.

No new reference code was imported in Phase 3. The four Phase 2 allowlisted imports
and original repositories remain unchanged. New and changed paths are listed in
[phase3-files.csv](provenance/phase3-files.csv); the session-specific list is
[phase3-implementation-files.csv](provenance/phase3-implementation-files.csv).
Phase 4 and Angular implementation require separate approval.
