# Phase 2 implementation and verification

Completed backend implementation and local verification on October 27, 2026.
Implementation began October 26. No Angular dashboard or Meta reasoning engine was
started. The source repositories remain unchanged; the frontend retains its
pre-existing uncommitted README modification.

## Delivered workflow

A provisioned analyst authenticates, uploads a PDF policy baseline, polls durable
ingestion, uploads a replacement and related procedure, retrieves version history
with resumable job progress, searches authorized vectors, opens exact page evidence
and downloads the unchanged original PDF. Every source access uses current database
permissions. The real HTTP smoke performs this complete Phase 2 workflow with local
ONNX embeddings and verifies cross-department denial and membership revocation.

## Actual files and origin

The complete [file inventory](provenance/files.csv) lists every intended project file
created in this phase, including hidden build/configuration files. All were absent
from the original workspace, which contained only IDE metadata. Generated `target/`,
private `.local/`, IDE state, dependency caches and temporary logs are excluded.

Four physical imports are recorded in [allowlist.json](provenance/allowlist.json):

- `mvnw`, `mvnw.cmd`, `.mvn/wrapper/maven-wrapper.properties`: unchanged imports.
- `ingestion/TextCleaningService.java`: imported with package rename, used only on
  embedding input; canonical evidence text is never normalized with this utility.

The source is `https://github.com/ThierryTe/spring-ai-rag` at
`c22f3b1e0f690aa195e85e0ea37c98d8ffe43cb1`. Source and destination SHA-256 hashes
were rechecked after implementation. [adaptations.json](provenance/adaptations.json)
records source-informed designs whose implementation was newly written, including
login, parameterized retrieval, validation, batching and bounded workers. No frontend
files, credentials, old migrations, RAG prompts, OpenAI reasoning code, private data,
Git histories or generated reference-project artifacts were imported.

New work comprises:

- Identity/JWT security, scoped JPA/JDBC transactions, database startup checks.
- Two Flyway migrations for the domain, forced RLS, immutable evidence, lease queue,
  and authorized version/job progress.
- Policy/version/upload/evidence/search/job APIs and stable problem codes.
- Page-aware resource-limited PDF child process, Unicode offsets and source-span validation.
- Local embedding adapter, pinned artifacts, hash checks and explicit revision mismatch errors.
- Durable worker dispatch/recovery, stale-lease fencing, atomic indexing and safe metrics.
- Fresh Compose database, Linux runtime profile, provisioning/run/fetch/smoke scripts.
- Unit/integration tests, CI definition, API and provenance documentation.

See [pre-existing work](provenance/PRE_EXISTING.md) and
[event contributions](provenance/HACKATHON_CONTRIBUTIONS.md). Importing existing
login/search concepts is not described as inventing those features during the event.

## Architectural decisions

PostgreSQL 16 remains the database target. Ordinary policy metadata uses Spring Data
JPA; explicit retrieval/indexing uses JDBC. `ScopedAccess` starts a new transaction,
sets a transaction-local principal and clears the JPA persistence context. Both APIs
share the JPA transaction manager's connection. Tests deliberately use one pooled
connection to expose retained principal/context problems.

Forced RLS evaluates active accounts, current department memberships and explicit
read/write grants. ADMIN is scoped rather than globally privileged. Runtime cannot
read credential or queue tables directly and cannot update/delete source pages or
chunks. Security-definer functions have a locked search path and non-superuser owner.
Startup refuses privileged runtime identities, unsafe owners or disabled/absent RLS.
Workers and content endpoints are gated until startup checks finish.

PDF parsing has a 30-second timeout and 128 MiB child heap. Child environments contain
no inherited application secrets. Byte, page and text limits apply; page text remains
canonical and source offsets use Unicode code points matching PostgreSQL substring.
Original bytes and all version fields except ingestion status are immutable.

The queue persists requester IDs and input version IDs. Worker count is bounded at
two per application instance. Expired leases can be reclaimed up to three attempts;
only the current lease can publish source data. Authorization is checked before
reading, between embedding batches and immediately before atomic persistence.

The reasoning interface is present but has no implementation and makes no external
calls. Real local embeddings use the pinned Apache-2.0 MiniLM ONNX artifacts recorded
in [embedding-model.json](provenance/embedding-model.json). This is independent of
future Meta reasoning integration.

## Checks actually run

| Check | Result |
|---|---|
| `./mvnw -B -o -Pneural-embeddings,database-tests verify` | PASS: executable JAR, 22 tests, 0 failures/errors/skips |
| JWT tests | PASS: issuer/audience/subject/expiry/signature/weak-key rejection |
| Login throttle test | PASS: spoofed forwarding headers cannot reset socket-peer quota |
| PDF/vector tests | PASS: child JVM, distinct pages, malformed/empty/mixed PDFs, Unicode spans, vector/name validation |
| PostgreSQL integration suite | PASS: 14 tests on fresh PostgreSQL 16.10/pgvector 0.8.0 |
| `python3 scripts/smoke_workflow.py --container` | PASS: actual HTTP + packaged Java app + real local ONNX + dedicated Compose database |
| Fixed-sentence model diagnostic | PASS: two finite nonzero 384-dimensional vectors in Linux x86_64 |
| `python3 scripts/verify_provenance.py` | PASS: all four source/destination hashes |
| Python parsing and shell syntax | PASS |
| Generated-secret scan of intended source/config/docs | PASS: no generated runtime secret copied into intended project files |
| Maven wrapper startup | PASS: Maven 3.9.16 on Java 21.0.11 |
| Remote GitHub Actions | NOT RUN; workflow supplied, no remote success claimed |

Machine-readable evidence and individual test names are in
[phase2-results.json](verification/phase2-results.json).

The database tests verify JDBC/JPA reads and JPA writes, cross-department isolation,
connection reuse without a principal, immutable version updates/deletes, original
PDF retention, verified source locations, denied reads without embedding calls,
explicit grants and revocation, worker revocation before/during embedding, duplicate
submissions, lease recovery/fencing, HTTP upload/JWT behavior, inactive/deleted users,
scoped ADMIN and cross-organization grant defense, forged source-span rejection,
and embedding revision mismatch handling.

The database suite uses deterministic vectors so security assertions do not depend on
model quality. The separate real-model smoke verifies one semantic ranking example;
it does not establish precision/recall for investigations or a broad retrieval benchmark.

## Resolved environment failures

The shell sandbox could not access Docker or fetch uncached dependencies. The
connected IDE terminal provided authorized Docker/network access, and all mandatory
checks above subsequently ran there. Context7's Spring AI lookup also succeeded
through that terminal after the initial shell escalation was rejected.

The neural profile initially lacked cached dependencies; normal dependency resolution
then succeeded. Intel macOS native tokenizer initialization failed (`Unexpected flavor:
cpu`). The verified deployment path is Linux x86_64 in Compose. Its first real embedding
attempt exhausted a small temporary filesystem while DJL downloaded native PyTorch
pooling libraries. A separate ignored dependency cache resolved that failure. The
final model diagnostic and full HTTP smoke both passed after this correction.

## Remaining limits and Phase 3 prerequisites

- Meta account access, model entitlement, request schema and processing terms have
  not been verified. Start Phase 3 with synthetic-input live API verification before
  implementing model-dependent reasoning. No credentials are requested in chat.
- OCR, complex table reconstruction and section-heading hierarchy extraction are
  absent. PDFs with any empty extracted page are conservatively rejected, including
  intentional blank separators. Page evidence is verified; extraction quality for
  arbitrary enterprise PDFs is not established.
- The local neural runtime requires Linux x86_64 for the tested path and approximately
  452 MiB of native cache in addition to the 86 MiB model. First setup downloads public
  runtime dependencies. Host macOS neural execution is unsupported by this baseline.
- Provisioning/grant administration uses operator SQL. There is no signup, refresh
  token, password recovery or management UI. JWTs expire after 15 minutes.
- Lease/concurrency bounds are per process. Multi-replica global throttling, richer
  observability and distributed scheduling are deferred.
- A failed/revoked or retry-exhausted task may leave immutable-version processing
  status QUEUED because queue failure updates are independent of content writes. Job state is
  authoritative and included in version history; no INDEXED result is published.
- Only synthetic documents were used. No policy contradiction accuracy, requirement
  extraction quality or human-review workflow is claimed in Phase 2.

The smoke stops its backend container. The dedicated local PostgreSQL service and
synthetic smoke data remain available; no reference-project database was touched.
Phase 3 requires the user's explicit phase approval.
