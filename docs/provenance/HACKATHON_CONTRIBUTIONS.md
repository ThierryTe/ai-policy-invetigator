# Work developed for AI Policy Investigator

Entries are chronological snapshots. The latest completed increment below supersedes
earlier pending/blocked status descriptions; historical verification is preserved.

Phase 2 implementation dates: October 26–27, 2026. A new file is not necessarily a new
product capability; see PRE_EXISTING.md and adaptations.json.

New domain/security work: immutable policy/version lineage and original bytes;
source spans tied to canonical page text; Unicode-compatible evidence offsets;
current membership and explicit grants; PostgreSQL forced RLS; one scoped JPA/JDBC
transaction boundary; active-account rejection and issuer/audience JWT validation;
durable identifier-only ingestion queue with leases and fenced atomic persistence;
PDF child-process resource limits; content-free metrics and safe failures; fresh
local credentials/database setup; embedding artifact checks and provider isolation.

New tests exercise these contracts, including a separate mandatory database profile.
The final run passed 22 tests, including 14 PostgreSQL integration tests. A separate
container HTTP smoke passed with the pinned real ONNX model. See the report for limits.
See ../PHASE2.md for actual verification status.

The Meta reasoning implementation, structured requirement extraction, contradiction
classification, change-impact reports, human reviews, relationship graph and Angular
investigation dashboard are not built yet and must not be presented as completed.

For future commits: put selective imports and subsequent adaptations in separately
reviewable commits; include source hashes and destination paths. Record import commit
IDs only when commits actually exist. No Git history/commits have been created by
this implementation session.

## Phase 3 access preflight — October 27, 2026

New work: a standard-library, synthetic-only Meta API verification command and four
local validation tests. The access check is blocked by a missing `MODEL_API_KEY`;
no authenticated API request or Meta investigation has succeeded. No Java provider,
requirement engine or comparison functionality is claimed as implemented. Phase 2
verification evidence is preserved. See `docs/PHASE3.md` and
`docs/provenance/phase3-files.csv` for exact scope and status.

## Dotenv configuration and successful Meta access — October 27, 2026

Added the official Boot 4 dotenv module/BOM 5.1.0, root-file placeholders/example,
production opt-out, process-precedence tests, packaging exclusions, and configuration
verification modes. Existing owner-supplied root `.env` content was preserved; no
real credentials were generated or logged. The root key is now available through
Spring. Authenticated model discovery and strict synthetic JSON inference succeeded
against Meta's official API with `muse-spark-1.3`; usage and latency are recorded in
`docs/verification/meta-api-preflight.json`. The previous blocked attempt is archived.
This is real access verification, not a completed requirement/investigation engine.

## Phase 3 investigation engine — October 27, 2026

Newly written during this increment: a bounded real Meta HTTP/provider adapter behind
PolicyReasoningProvider; independent structured schema/source validation; extracted
requirement and change/comparison contracts; forced-RLS investigation/extraction/result
storage; durable async jobs, scoped dispatch gates, leases, recovery checkpoints,
configurable persisted total deadlines,
usage/progress, safe failures and owning-department consent controls including SQL
and JPA enforcement. Existing local Spring AI embeddings remain separate.

The real packaged demo extracted four synthetic versions and compared two procedures.
Meta identified the training/access contradiction and returned NO_CONFLICT for the
compatible procedure. Actual evidence, usage and timings are recorded in
`docs/verification/phase3-demo.json`, with prior runs retained. Controlled transport
fixtures cover failure/revocation/recovery; their outputs are not real model results.
The small golden dataset is new synthetic material, not imported/private policies.

No new code was copied from either reference repository. The four Phase 2 allowlisted
files and their hashes are unchanged. Existing dotenv configuration/preflight and
Phase 2 evidence are preserved. The per-increment exact file inventory is
`docs/provenance/phase3-implementation-files.csv`; the cumulative Phase 3 inventory is
`docs/provenance/phase3-files.csv`. All implementation entries are newly authored or
adaptations of this new repository, not claims that reused infrastructure was built
at the event. No new Git histories or source commits were imported/created.

Actionable findings are pending human review. Human review submission, Angular,
exported impact reports, graph endpoints and broad evaluation remain deferred.
Phase 4 requires separate approval. See `docs/PHASE3.md` for verified scope and limits.

## Post-Phase 3 documentation and repository audit

Updated the English README, audited Python tooling/evaluation/CI/bootstrap/deployment,
and strengthened Git/Docker secret and generated-file exclusions. No application
capability, migration, deployment service, golden case or reference import changed.
No Git command was run; all repository operations remain with the owner. Candidate
commit files and actual local verification are recorded in
`docs/provenance/commit-ready-files.csv` and
`docs/verification/repository-audit.json`. Phase 3 evidence remains unchanged;
this documentation increment does not begin Phase 4.


## Follow-up: Lombok and local OpenAPI documentation

New follow-up work adds Boot-managed Lombok processing for two assignment-only
service constructors and Springdoc 3.2.0 documentation for existing APIs. Existing
API request records, JPA entity behavior, domain/security logic, provider contract,
RLS migrations and golden data are preserved. Documentation-only response records,
local profile/Compose opt-in, production documentation denial and database-backed
verification were added. No reference code was imported and no Git command was run.
This adds no Phase 4 investigation, frontend or production deployment feature.
See `docs/verification/lombok-openapi-results.json` and the refreshed candidate-file
manifest for actual paths, compatibility evidence and executed checks.


## Follow-up: environment/property organization

Grouped existing application properties and externalized operational settings into
named environment mappings. Preserved fixed security/profile guards, existing secrets,
API/provider behavior and earlier verification evidence. Updated the placeholder
example, Compose forwarding and English local-configuration instructions. Added two
isolated-JVM tests of actual property mappings and real-environment precedence.
No new credential or model request was created. The private `.env` remains excluded;
no reference code import, Git operation or Phase 4 work was performed.


## Follow-up: consolidate Spring configuration

Removed the local/prod application property files and kept one application.properties
with environment controls and safe defaults. Explicit local dotenv opt-in is handled
by the existing local launcher; production Compose pins production mode and disables
dotenv/docs. Local Compose no longer needs a Spring profile. Retained prior prod-profile
documentation denial as a backward-compatible safety veto. Updated tests preserve
local loading, process precedence, optional-file behavior and forced-flag production
denial. Existing credentials and previous evidence remain unchanged. No Git operation,
reference import, model inference or Phase 4 work was performed.


## Follow-up: Docker-managed pinned embedding artifacts

Added reproducible model bootstrap and backend Docker image builds, using observed
immutable public base-image digests. Reused the exact previously verified MiniLM
revision/bytes and 384 dimensions, strengthening tokenizer download verification to
the already recorded SHA-256. Added named model/native-cache volumes, read-only backend
model access, initialization gating and readiness checking. The existing fetcher still
supports host tooling. No reference code, model variant, credentials or Git history
was imported, and no model weights are committed. Deployment tests use real artifact
downloads and ONNX inference; controlled Python fixtures test failure paths separately.
See docs/verification/model-volume-results.json for actual checks and scope.

## Phase 4 hackathon MVP — October 27, 2026

Authorized after the owner's first commit/push. Newly authored work: an
investigation-scoped persisted graph projection, append-only human review events
and forced-RLS migration V6, review role/current-access checks, additive findings
review state, OpenAPI contracts, ten synthetic golden cases, a real-provider
API evaluation runner and scoring safety tests. The graph rechecks stored citations
and emits only persisted version/requirement/alignment/assessment relationships.
Human actions preserve original AI classifications, source evidence and prior decisions.

No further code was imported from either reference repository. The existing four
allowlisted imports and source commit records remain unchanged. Deployment files,
provider/model configuration, embeddings, old migrations and historical verification
records were preserved. Real evaluation failures are retained alongside targeted
retries; no fixture-provider result is claimed as real inference. See
`docs/PHASE4.md`, `docs/verification/phase4-results.json` and
`docs/provenance/phase4-files.csv` for actual outcomes and paths. No Git command
was run; the owner retains all Git operations. Angular/Phase 5 has not started.

## Explicit local demo login — October 28, 2026

Added an operator-only, opt-in demo provisioner and transactional SQL seed using the
existing psql/pgcrypto provisioning approach. New work supplies stable isolated demo
identities, idempotence/password rotation/collision protection, COPY-based secret
transport, environment/password validation, reproducible export of the existing
synthetic golden PDFs, tests and local instructions. Existing fixture-generation
utilities and JWT/BCrypt/current-role mechanisms are reused, not claimed as new.
No registration endpoint, application startup seed, runtime privileges, security
filter, production configuration or frontend source was changed. No code was
imported from the original reference repositories and no Git command was run.
Private demo credentials are ignored, never printed and excluded from artifacts.
See `docs/DEMO.md`, `docs/verification/demo-setup-results.json` and
`docs/provenance/demo-setup-files.csv` for actual scope, evidence and changed files.


## Phase 6A — Docker audit and deployment preparation — October 28, 2026

New work in this increment: restart policies for PostgreSQL/Spring Boot, a dedicated
project-scoped database bridge, a minimal frontend access-log privacy patch, audit
evidence and deployment instructions. The frontend patch is delivered for owner
application because that repository is outside this session's writable workspace;
it was verified in a temporary build, not applied to the frontend working copy.
Existing Dockerfiles, model initializer, pinned artifacts, authentication, domain,
Angular implementation, provider behavior and database migrations are pre-existing
and are not claimed as new. No reference repository code, credentials or Git history
was imported. No Git command, VPS deployment or new Meta inference was performed.
See `docs/PHASE6A.md`, `docs/verification/phase6a-results.json` and
`docs/provenance/phase6a-files.csv`.


## Phase 6B — Confirmed NPM integration preparation — October 28, 2026

Newly authored work: production backend/frontend Compose overlays with no published
ports, dedicated internal application/database networks, unique frontend NPM DNS alias,
configuration verification/negative tests, operator-only empty-identity-store initial
ADMIN provisioning with COPY secret transport and BCrypt/atomic-refusal tests, and
NPM/environment/backup/restore/image-rollback instructions. The frontend overlay is
backend-owned integration configuration referencing the independent frontend checkout;
no frontend application source or Git history is copied into this repository.
The earlier Nginx access-log fix is already present and is not claimed as new Phase 6B work.

Existing Dockerfiles, model initializer/revision/hash/dimensions, PostgreSQL volume,
application authentication/authorization, domain/provider code, migrations and frontend
Signals implementation remain unchanged. No reference code, production credentials
or model artifacts were imported. No Git operation, SSH, Compose application startup,
Docker network creation, NPM/firewall change or new Meta inference was performed.
PostgreSQL tests use disposable test containers; no existing application identity
store was seeded and no production backup/restore was executed. See
`docs/PHASE6B.md`, `docs/verification/phase6b-results.json` and
`docs/provenance/phase6b-files.csv` for the exact scope and evidence.


## Phase 6C — Minimal CI and optional GHCR publication — October 28, 2026

New work: scoped develop/main CI, read-only normal-job permissions, pinned official
actions, Java/PostgreSQL/Python/Compose/Docker checks, frontend Node/npm/test/build
workflow files, main-only manual full-SHA GHCR publishers and digest-image deployment
overlays/documentation. Frontend workflow files are delivered under docs/ci/frontend
for owner installation; direct frontend writes were rejected by workspace policy.
They were validated against a temporary frontend workspace, not installed in its Git
working copy. No external reference application code or Git history was imported.

The only cross-project snapshot is the new frontend's existing compose.yaml, copied
as a reviewed non-secret CI contract into .ci/frontend with its source URL, inspected
commit context and exact worktree SHA-256. It is pre-existing configuration and is not
claimed as new infrastructure. Original reference repositories remain untouched. The
existing topology tests gained only an explicit CI fixture directory selection and
a local source/fixture drift check. Domain, authorization, schema, provider, model
initializer and existing production topology files remain unchanged. No Git command,
hosted workflow dispatch, registry publication, real Meta request or VPS deployment
was performed. See docs/PHASE6C.md and the Phase 6C evidence/file inventory.
