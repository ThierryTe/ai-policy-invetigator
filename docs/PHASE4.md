# Phase 4 — minimum investigation dashboard backend

Scope: persisted impact graph, human review, a small real Meta evaluation and exact
Angular API contracts. No frontend, automatic enterprise-wide procedure discovery,
exported report generator, infrastructure service or unrelated refactor was added.

## Implemented

- `GET /api/investigations/{id}/graph` projects stored version lineage, extracted
  requirements, verified requirement alignments and assessment relationships.
  Reads recheck current scope authorization and source quotations; no provider or
  embedding request is made. Partial checkpoints remain visibly incomplete.
- `POST /api/investigations/{id}/findings/{findingId}/reviews` accepts CONFIRM,
  DISMISS and ADD_NOTE. Events record reviewer UUID, server UTC timestamp and notes.
  Existing findings responses include additive `canReview` and `reviews` fields.
  Original AI classification, evidence and initial review requirement are untouched.
- New migration V6 enables and forces RLS on append-only `finding_reviews`.
  Current access to every selected version is required to read history. Writing
  requires REVIEWER/ADMIN in the replacement policy's owning department, matching
  current actor and an actual finding inside that investigation. Runtime roles have
  no review UPDATE/DELETE privileges. The startup safety check now verifies eight
  protected tables. JPA and JDBC retain the existing shared scoped transaction boundary.
- Ten independently authored synthetic cases and a real-model evaluator exercise
  the upload → ingestion → consent → durable investigation → citations → graph →
  review path. Fixture identities are disabled when the runner exits; synthetic
  documents/results remain in the dedicated demo database for audit.

The graph uses selected scope, not an automatically discovered network. AFFECTS
links include assessed NO_CONFLICT pairs; classification determines the visual
status. A matching citation establishes textual correspondence, not semantic truth.
All actionable AI findings still require human review.

## Frontend contracts

See [exact dashboard contracts](api/phase4.md), including TypeScript-shaped payloads,
review overlays, node/edge meanings, errors, evidence resolution, polling and KPI
calculations. Existing upload/status/requirement/evidence APIs remain compatible.
The two new routes are documented in local OpenAPI; production documentation remains
denied independently of Springdoc flags.

Use one origin behind the eventual VPS reverse proxy. Angular has no blocker for
these investigation detail APIs. A global investigation-history/list endpoint and
automated scope discovery are outside this increment; preserve the created
investigation ID or deep-link it. Human review controls must use `canReview` rather
than infer rights from stale JWT claims. Do not auto-retry review POSTs: each success
appends a new event. Concurrent decisions retain both events and the last persisted
decision wins.

## Verification and limits

The full command `./mvnw -B -o -Pneural-embeddings,database-tests verify` passed
**57 tests**, including **34 PostgreSQL-backed tests**, with no failures/errors/skips.
`python3 -B -m unittest discover -s scripts/tests -v` passed **15 tests**.

Coverage includes graph source verification, dangling-edge checks, SQL review RLS,
forged finding IDs, cross-department denial, wrong-department reviewers with READ
grants, viewer/analyst rejection, role and membership revocation, immutable AI output,
append-only history, invalid input, local OpenAPI and production denial. Existing
JDBC/JPA authorization, provider malformed-output/timeouts/retries, consent revocation,
restart recovery, dotenv and PDF provenance regression tests still pass. Controlled
transport fixtures are separate from the real evaluation evidence.

Two preliminary Java runs failed documentation assertions: first the expected path
list needed the new routes, then the new routes needed explicit 200 OpenAPI response
annotations. These were fixed; no production authorization test was relaxed.

Earlier migration files, provider/model limits, embeddings, Compose/Docker files,
application properties, all four reference imports and historical evidence were
hash-checked unchanged. No configured long secret value was found in changed public
files; the built JAR contains no dotenv files or credential-file entries. This is
not a claim about the owner's Git index/history: no Git command was run.

The initial real run matched 6/10 cases and had four errors from one exception
comparison stopping with INCOMPLETE_PROVIDER_OUTPUT. A targeted retry with two
procedures per investigation completed those four cases: three matched and one
produced a contradiction against the golden NO_CONFLICT label. Muse interpreted
an optional emergency exception as something the stricter procedure must permit.
The golden label is unchanged. Treat this disagreement as a false positive against
the dataset, with human adjudication still needed. Nine of ten distinct cases
ultimately matched across the initial run and targeted retry, including safe abstention
for missing evidence. This is not a single-run accuracy claim.

Both runs together made 31 real model calls: 38,359 prompt tokens, 68,141 completion
tokens and 296,572 ms summed metered provider latency. All 119 citation instances
matched stored source text; both real runs also passed graph, review-history,
original-AI immutability and current permission-revocation checks.

The actual per-group outcomes, errors, latency and usage are recorded below. The initial ten-case run is preserved independently of targeted
retries. Incomplete model output never becomes NO_CONFLICT or a published assessment.
The existing 4,096 completion-token cap can stop larger comparison scopes; keep
comparisons small rather than infer that missing output is safe. The evaluator now
defaults to two procedures per investigation. The original incomplete response's raw
body/finish reason was not retained, so output truncation is a suspected cause rather
than a separately verified transport fact.

- [Initial ten-case real run](verification/phase4-evaluation.json)
- [Targeted exception retry](verification/phase4-explicit-exception-evaluation.json)
- [Verification and results summary](verification/phase4-results.json)
- [Exact changed-file attribution](provenance/phase4-files.csv)

Model-generated interpretations remain fallible. Ten synthetic cases and targeted
retries do not estimate general accuracy. Reported provider latency/usage covers
metered responses, not unmetered failed attempts; group elapsed times also include
result/citation/review API verification. No secrets, raw provider credentials or
private policy data are in these reports.

Phase 5 has not started. The owner manages all Git operations; explicit approval is
required before the Angular implementation.
