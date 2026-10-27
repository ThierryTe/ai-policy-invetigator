# Repository audit after Phase 3

This report preserves the original repository audit and includes a subsequent
Lombok/OpenAPI addendum. The initial audit updated the English README and exclusion
rules. The follow-up adds targeted constructor generation, API documentation,
local profile configuration and documentation-path security checks. Business logic,
JPA entities, migrations, golden cases, the CI workflow and base deployment services
remain unchanged. No Git command was executed. Phase 4 has not started.

## Python tooling

| File | Role and inputs | Side effects and audit conclusion |
|---|---|---|
| `scripts/init_local.py` | Fresh local setup; uses cryptographic randomness and this repository's path | Writes four local DB/JWT values through exclusive creation at mode 0600; refuses overwrite. Creates owner-only `.local` and a 0777 public native cache inside it. Appropriate for local bootstrap; use explicit UID/GID ownership for a shared VPS cache. Not executed during this audit. |
| `scripts/fetch_embeddings.py` | Pinned public MiniLM revision and model/tokenizer integrity metadata | Bounded-size temporary downloads, verification, atomic rename, cleanup; refuses an invalid existing artifact. Writes public paths/hashes to `.local/embeddings.env`. Reuses valid cached files. Both existing artifacts were checked without downloading or rewriting configuration. |
| `scripts/run_local.py` | Root `.env` key names, real environment and optional local fallback files | Replaces itself with the packaged Java process. Environment wins; fallback values do not override `.env` declarations. Its small key-name reader is not the Spring dotenv parser; use the documented simple assignments. A copied example containing placeholders suppresses useful fallback values. Not started during this audit. |
| `scripts/verify_meta_access.py` | Official Meta catalog and strict synthetic connectivity inference | Real, credentialed outbound requests; sanitized evidence/history writes. Standalone reads process variables and legacy `.local/meta.env`, not root `.env`. The Java wrapper supplies Spring's resolved key and screens missing/example keys. Never run it merely to inspect configuration. Not executed during this audit. |
| `scripts/verify_provenance.py` | Allowlist plus `../spring-ai-rag` source objects | Invokes read-only `git show` and compares recorded source/destination hashes. Requires the reference checkout; not portable as a self-contained VPS healthcheck. Not executed under the owner-only Git restriction; all four destination hashes were checked directly. |
| `scripts/smoke_workflow.py` | Local dedicated Compose PostgreSQL, packaged backend and actual ONNX model | Uses privileged operator SQL only for synthetic fixture creation/revocation, exercises JWT/upload/version/search/evidence APIs, and stops its backend. Leaves synthetic rows behind. Local integration tool, not a VPS healthcheck. No rerun was needed for documentation/exclusion changes; prior verified evidence is preserved. |
| `scripts/smoke_investigation.py` | Two golden cases, dedicated local stack and real Meta access | Explicit consent, real extraction/comparison, citation lookup and authorization checks. Starts/stops the backend; creates accounts/documents and writes current/history evidence. Incurs real provider usage. Not rerun by this audit. |
| `scripts/tests/test_verify_meta_access.py` | Controlled response dictionaries and missing-key validation | Four standard-library tests; no live API call or evidence-file replacement. All four passed again. |

Python is supporting tooling, not part of the Java backend's production request
path. AST parsing passed for all eight Python source files. Init/run utilities were
not imported or executed because their top-level code has side effects.

The preflight utility's urllib socket timeout and deadline checks are not equivalent
to the Java transport's hard shared header/body deadline. It validates the response
model's shape but does not itself assert equality to the selected catalog model.
The production Java provider does enforce model equality and the full response
contract. These are tooling limitations to address in a later authorized change;
the existing successful preflight records show the same selected/returned model.

## Evaluation directory

`evaluation/phase3-golden.json` contains synthetic text only: one baseline, its
replacement, one conflicting HR procedure and one compatible procedure. No private
PDFs, embeddings, model weights, credentials or enterprise data are present.

The recorded real run matched both expected procedure-level outcomes and verified
25 citation instances. This is a smoke measurement on two cases. It does not establish
broad precision/recall, source interpretation correctness or missing-requirement
accuracy. Unknown/ambiguous fields and failure handling have controlled Java tests;
that is different from broad real-model evaluation.

The current demo reads case texts by array position and hardcodes its dates, expected
classifications and top-level model label. It does not generically iterate the
fixture's `expected` values. Keep this fixture/model baseline unchanged when comparing
recorded runs; a future generic evaluator, additional cases and benchmark expansion
belong to the separately approved next phase. The dataset/evidence hashes are unchanged.

## GitHub Actions

`.github/workflows/verify.yml` currently:

- Is named `Verify Phase 2`, although current Maven discovery includes Phase 3 tests.
- Runs on push and pull request with `contents: read`.
- Uses `ubuntu-latest`, `actions/checkout@v4`, `actions/setup-java@v4`, Temurin 21 and
  Maven dependency caching.
- Runs `./mvnw -B -Pdatabase-tests verify`, including mandatory Docker/PostgreSQL tests.
- Has no deployment, registry publication, real Meta request or production credential
  reference. It does not run Python validation or the live demonstration.

The same Maven profile passed locally with `-o` for cached dependencies: 45 tests,
25 of them PostgreSQL integration tests, zero failures/errors/skips. This is not a
remote GitHub Actions result. The workflow was inspected and left unchanged.

Recommended future maintenance: rename the workflow, add the four Python tests, and
validate/package with the neural profile before publishing any runnable artifact.
The current default package deliberately lacks production embedding dependencies.
Pin action revisions and release image digests under the owner's update policy;
no versions or commit IDs were invented here. The provenance utility also needs an
explicit reference-source strategy before adding it to CI.

## PostgreSQL initializer

The requested `deploy/init.sh` does not exist. The real file is
`deploy/postgres/init.sh`, mounted at
`/docker-entrypoint-initdb.d/01-investigator.sh` in the PostgreSQL service.

It uses `set -eu`, psql error-stop behavior and quoted psql environment variables.
It creates `investigator_runtime` (non-login, non-superuser, no RLS bypass), owner/app
login roles with separate credentials, grants runtime privileges to the app login,
assigns database/schema ownership, revokes public schema creation, and installs
vector/pgcrypto. Migration functions are subsequently created by the non-superuser
owner, not PostgreSQL's bootstrap superuser.

`sh -n` passed. The initializer was not rerun against the existing volume. It is a
first-empty-volume bootstrap, not idempotent provisioning, a migration runner or
password rotation. Partial bootstrap failures require operator diagnosis; it must
not be aimed at an existing reference project's database. Flyway migrations V1–V5
and the original verification evidence were preserved byte-for-byte.

## Docker and VPS recommendation

Current Compose behavior is suitable for a dedicated local/demo stack:

| Existing choice | VPS compatibility and remaining work |
|---|---|
| PostgreSQL 16 + pgvector 0.8.0, dedicated named volume | Keep a separate project/database/volume. Establish backup/restore operations for originals, evidence and durable jobs. Changing env files does not rotate stored passwords. |
| JRE image and read-only host JAR mount | Build with `neural-embeddings`. A staging bind mount is possible; prefer an immutable release image for production. No Dockerfile, published app image or production override currently exists. |
| Models and native cache under `.local` | Replace developer paths with VPS paths/volumes and UID/GID 10001 access. Model/native cache is public and replaceable; DB data is not. Initial native downloads require egress. |
| Backend nonroot, read-only root, executable bounded tmpfs, 1536 MiB limit | Retain these constraints and confirm VPS architecture/capacity. Linux x86_64 is verified; VPS/ARM operation is not. |
| Loopback ports 18080/5546 | Host proxy can use backend loopback. A proxy container needs an explicitly shared proxy network and unique backend alias. Keep PostgreSQL on the private application network. |
| No restart policy or backend Compose healthcheck | Add explicit restart/readiness/shutdown settings in the VPS configuration. `up --wait` alone currently confirms backend running state, not API health. |
| Explicit environment forwarding; dotenv disabled in container | Inject production values outside the checkout. A production override must explicitly forward the prod profile; unspecified host variables are not automatically inherited. No automatic `_FILE`/Compose-secret-file binding exists in the app. |
| Flyway and runtime in one Java process | Preserve owner/app role separation and RLS checks. The process still holds the migration-owner credential; separate migration execution is a future hardening option. |

Keep the existing VPS proxy and Compose deployment style. No broker, Kubernetes or
separate Python service is required. Prefer an owner-maintained production override
for paths, ports, runtime secrets, monitoring and restart policy. Configure HTTPS,
one frontend/API origin and proxy upload/header behavior before public access.
A proxy running in another container cannot reach this backend through its own
`127.0.0.1`. Do not place PostgreSQL on a shared public proxy network.

This advice follows [Docker's production Compose guidance](https://docs.docker.com/compose/how-tos/production)
and its [multiple-file merge documentation](https://docs.docker.com/compose/how-tos/multiple-compose-files/merge).
Compose file-secret mounts require application binding; see Docker's
[implementation](https://github.com/docker/compose/blob/main/pkg/compose/create.go).
No secret mounts, override, deployment, proxy changes or VPS access were performed.

## Secrets, exclusions and manual commit review

The audit found missing Python cache and general `*.env` exclusions. `.gitignore`
now covers these, environment variants, virtualenvs, private keys and common keystore
extensions; `.env.example` remains allowed. `.dockerignore` retains its narrow
pom/source allowlist and now also excludes generic environment variants and private
key/keystore extensions within otherwise allowed source directories.

Verification used ten temporary synthetic dotenv/key/keystore probes and a control
file. Ripgrep's Gitignore reader excluded every private probe while retaining the
control and root `.env.example`. An actual scratch Docker build/export confirmed
the same exclusion from its context, with normal source/control files present.
Temporary source probes and Docker inspection objects were removed afterward.

Candidate files and own packaged classes/resources passed checks for known private
local values and private-key markers. Root `.env` remains mode 0600. Values were
never printed, copied into this report or supplied as command arguments. Maven
resource filters exclude `.env`, `.env.*` and `*.env`; arbitrary ignored resources
are not universally protected by those filters. In particular, building a JAR locally
and bind-mounting it bypasses Docker build-context filtering. Keep private material
outside source resources and inspect the release artifact, as this audit did.

No `.git` metadata exists in the inspected workspace. There is no tracked/staged
index or history to inspect. Gitignore checks used ripgrep with `--no-require-git`;
no Git command was executed, including the provenance utility's read-only commands.
Ignore rules do not remove a previously tracked secret; the owner must inspect the
files selected for the first commit. The scan checks known values/markers, not every
possible unknown secret or all historical external copies.

[commit-ready-files.csv](provenance/commit-ready-files.csv) enumerates candidate
project files, including source/tests, Maven wrapper/configuration, workflow,
deployment initializer, scripts, synthetic evaluation, placeholder env example,
documentation, attribution and sanitized verification/history. It excludes `.env`,
`.local`, `.idea`, model weights, caches, bytecode, logs and build artifacts. It is a
review manifest, not a Git status or proof of a staged commit. The initial audit
changed no application code; the limited follow-up scope is listed below. Neither
reference repository was modified.

## Actual verification and remaining concerns

See [repository-audit.json](verification/repository-audit.json) for commands, test
counts, preserved hashes and exact changed paths. The audit passed local Maven
verification, neural packaging, Python tests/syntax, shell syntax, Compose quiet
validation, existing model integrity, destination provenance, exclusion probes and
known-secret scans. Existing genuine Meta results were preserved, not rerun or
presented as a new live test.

Before a VPS rollout: prepare production paths/release artifact and secret injection,
proxy networking/TLS, restart/readiness, writable-cache ownership, backups/restoration,
and an account-provisioning procedure. Remote CI, the VPS, ARM compatibility,
production load and a release-image build remain unverified. Review submission,
exports, Angular and broader evaluation remain unimplemented. Phase 4 is not started.

## Follow-up: targeted Lombok and OpenAPI

Boot-managed Lombok 1.18.46 is now provided/optional with an explicit compiler
processor path and executable-JAR exclusion. Only the two assignment-only service
constructors in PolicyService and InvestigationService were replaced. Constructor
order remains the same; no entity, security-service or validation constructor was
converted. Existing immutable API request records remain records. Documentation-only
response records describe current payloads rather than refactoring runtime maps.

Springdoc 3.2.0 is within the official Boot 4.1 compatibility matrix and resolved
from Maven Central. It documents existing routes and safe schemas/errors with global
JWT bearer security and an explicitly public login operation. Principal parameters,
source content, credentials and implementation security details are not examples.
The local-profile metadata configurer performs no service invocation or provider call.

The new `compose.local.yaml` is an explicit local-profile opt-in only. Base Compose
services and the PostgreSQL initializer are unchanged. Documentation is disabled
by default and in prod. Security denies its routes outside `local & !prod`, including
when flags are forced true or local/prod are combined. Existing endpoint permissions
still apply to any deliberate Swagger API execution. VPS deployment should exclude
the local override and explicitly select prod; no production override was created.

Additional database-backed tests cover specification/schema correctness, local UI
assets/configuration, no provider invocation, continued RLS isolation and production/
default denial. Packaged Linux HTTP checks and complete final test outcomes are
recorded in [lombok-openapi-results.json](verification/lombok-openapi-results.json).
The initial audit JSON remains historical evidence. The candidate-file manifest is
refreshed for the owner; it is not a staged Git state.

## Follow-up: centralized local environment configuration

Application property files now group operational environment mappings while retaining
fixed security/bootstrap invariants. Root `.env` is populated privately with existing
project-local credentials/artifact metadata and previous non-secret defaults; its
existing Meta key is preserved. No credential was generated, rotated or copied from
a reference repository. `.env.example` contains safe defaults and placeholders only.
Compose explicitly forwards the added settings but preserves its internal database
URL/model mount paths. Production still disables dotenv/docs and uses runtime secrets.

The actual property mappings and process-variable precedence are tested in isolated
JVMs. Current verification is recorded separately in
[environment-refactor-results.json](verification/environment-refactor-results.json);
earlier audit, Phase 3 and Lombok/OpenAPI results remain historical evidence.

## Follow-up: single application.properties

The latest configuration uses only `src/main/resources/application.properties`.
The local/prod property files have been removed; the sections above describe earlier
snapshots. `APP_ENVIRONMENT` defaults to production. Dotenv and documentation default
to disabled, with process/environment controls for development. The local launcher
explicitly enables dotenv and still yields to an explicit process false value.

Base Compose pins production mode, disables dotenv and documentation. The local
Compose override selects local mode/flags without Spring profile activation. An
optional legacy prod-profile documentation veto remains for compatibility, without
requiring any profile-specific file. API permissions and database/provider/embedding/
worker settings remain unchanged. Current checks are recorded in
[single-config-results.json](verification/single-config-results.json).

## Follow-up: self-contained model-volume deployment

The current Compose deployment builds the backend image and runs one short-lived
model-init job before backend startup. Exact existing MiniLM revision, ONNX/tokenizer
SHA-256 values and 384 dimensions are preserved. Named volumes replace host model,
native-cache and JAR mount prerequisites. The backend reads models through a read-only
mount; native cache ownership is prepared for UID/GID 10001. A backend healthcheck now
supports readiness waiting. Earlier mount/Dockerfile observations above are historical.

The shared fetcher provides bounded downloads, size/hash checks, atomic publication,
serialized initialization, verified offline cache reuse and clear nonzero failures.
It never receives database/JWT/Meta credentials. Docker context still uses a narrow
allowlist, extended only for Maven wrapper files and the public bootstrap script.
The backend build skips tests; independently executed regression and fresh/cache/
corruption/real-ONNX checks are recorded in
[model-volume-results.json](verification/model-volume-results.json). No actual VPS
rollout, Git command, reasoning-model call or unrelated feature was performed.
