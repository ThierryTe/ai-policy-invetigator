# AI Policy Investigator

Built for the Meta Global AI Developer Hackathon 2026.

A Java backend for investigating policy changes against enterprise procedures.
An analyst uploads a replacement policy, selects a baseline and procedure versions,
and receives source-backed potential conflicts from a durable investigation job.
There is no generic chat endpoint.

**Backend implemented through the Phase 4 MVP.** Persisted impact graphs, append-only
human reviews and a ten-case synthetic evaluation extend the verified Phase 3 pipeline.
The approved Phase 5 Angular application is implemented in the separate
[frontend repository](https://github.com/ThierryTe/ai-policy-investigator-frontend).
Phase 6B prepares Nginx Proxy Manager integration and locally validated VPS
configuration. Phase 6C adds CI and optional manual GHCR publication; no VPS
deployment or hosted workflow execution has been performed. Exported report files remain
outside the MVP. AI classifications and evidence remain immutable; human decisions are separate, and no changes are applied automatically.

## Implemented capabilities

| Area | Current behavior |
|---|---|
| Documents | PDF upload, immutable versions and original bytes, effective dates, page-aware chunks and exact source locations |
| Retrieval | PostgreSQL/pgvector search with pinned local ONNX embeddings and embedding-revision checks |
| Authorization | JWT authentication, current roles/departments/grants, forced RLS, shared scoped JDBC/JPA access and worker permission checks |
| Requirements | Actor, action, obligation, condition, scope, deadline, exceptions, effective date, null/unknown fields and verified citations |
| Investigations | Baseline/replacement alignment and comparison against 1–4 explicitly selected procedure versions; durable jobs and polling |
| Findings | CONTRADICTION, MISSING_REQUIREMENT, AMBIGUITY or NO_CONFLICT; model/prompt/schema metadata and mandatory pending review for actionable findings |
| Impact graph | Authorized selected versions, extracted requirements, persisted alignment and finding relationships; no inference on graph reads |
| Human review | Confirm, Dismiss and Add Note; current owning-department REVIEWER/ADMIN permission, append-only identity/timestamp history |
| Reliability | Configurable timeouts/deadline/concurrency, bounded retries, checkpoints, lease fencing, safe failure codes and reported usage |

The bounded MVP compares all requirements in the selected authorized procedure
scope. It does not automatically discover every affected procedure across an
enterprise. An incomplete result, missing evidence or provider error never counts
as `NO_CONFLICT`. Matching a quotation proves its source correspondence, not the
correctness of the model's interpretation.

## Stack and architecture

- Java 21, Spring Boot 4.1.1, Spring AI 2.0.1.
- PostgreSQL 16, pgvector 0.8.0, Spring Data JPA and parameterized JDBC.
- Spring Security resource-server JWT authentication; PDFBox 3.0.8.
- Local `all-MiniLM-L6-v2` ONNX embeddings, separate from reasoning.
- Meta Model API through `PolicyReasoningProvider` and the Java HTTP client.
- Verified reasoning model: `muse-spark-1.3` at
  `https://api.meta.ai/v1/chat/completions`.

The production request path is Java. Python scripts provide setup, validation and
synthetic demonstrations; there is no Python API server or Python inference service.
Strict server-owned schemas and server-side evidence validation are independent of
Meta's structured-output enforcement. Source IDs must belong to supplied authorized
chunks, and quotations must match their text exactly. Evidence resolves to the
original version, page and Unicode offsets.

## Lombok and OpenAPI documentation

The follow-up before the first manual commit uses:

| Dependency | Version and scope |
|---|---|
| `org.projectlombok:lombok` | 1.18.46, managed by Boot 4.1.1; provided/optional and explicitly excluded from the runtime JAR |
| `org.springdoc:springdoc-openapi-starter-webmvc-ui` | 3.2.0; OpenAPI 3 generation and packaged Swagger UI |

The official [Springdoc matrix](https://springdoc.org/)
lists Boot 4.1.x with Springdoc 3.1–3.2. Lombok's
[Maven configuration](https://projectlombok.org/setup/maven) and
[changelog](https://projectlombok.org/changelog) establish the processor setup and
Java 21 support. This project keeps Boot's managed Lombok version rather than
independently upgrading it. Both CI and neural-runtime Maven profiles passed 50 tests each, including
30 PostgreSQL-backed tests. Packaged Linux HTTP checks passed for local documentation
and production denial. Actual results are recorded
in [the follow-up results](docs/verification/lombok-openapi-results.json).

`PolicyService`, `InvestigationService` and the new `InvestigationDashboardService` use `@RequiredArgsConstructor`,
replacing dependency-assignment constructors with the same parameter order and
visibility. Validating/resource-initializing constructors and security services remain
explicit. The JPA entity has no Lombok annotations; no `@Data` is used. API request
records remain records. Documentation-only response records describe existing map
payloads without changing API serialization or persistence.

Maven's existing Java 21/release/parameter-name setup is retained. The compiler has
an explicit Lombok annotation-processor path; no other processor was configured in
the original project. Future processors must be added to that list explicitly.
Lombok is not a runtime dependency and no MapStruct/JPA metamodel processor was added.

Documentation is **disabled by default**. To opt into loopback local documentation
using the existing Docker setup:

```sh
docker compose --env-file .env -f compose.yaml -f compose.local.yaml --profile app up -d --wait
```

Alternatively, on a compatible host after packaging:

```sh
python3 scripts/run_local.py
```

Then open `http://127.0.0.1:18080/swagger-ui.html` (container) or the corresponding
host server port. The specification is `/v3/api-docs`, YAML is `/v3/api-docs.yaml`,
and the Swagger configuration is `/v3/api-docs/swagger-config`. The local override
sets `APP_ENVIRONMENT=local` and the local documentation flags; it does not
publish additional ports or change API permissions. No Spring profile is required.
Normal jobs still run when you start this local environment.

Local documentation metadata is public; API operations retain JWT/current-access
checks. The spec declares HTTP bearer/JWT authentication, excludes the authenticated
principal from input schemas, provides no credential examples, and documents existing
multipart requests, errors, evidence and complete/incomplete finding variants. Swagger
uses the same origin and does not persist authorization. Try-it-out is not initially
active; explicitly executing an authorized investigation can incur real Meta usage.
Merely loading documentation does not invoke an API operation, query document content
or dispatch a provider request.

Production is the default mode (`APP_ENVIRONMENT=production`). Its independent
security rule denies documentation and Swagger assets even if documentation flags
are forced on. Base Compose pins production mode, disables dotenv and turns both
documentation flags off; the local override is an explicit development choice.
An existing `prod` Spring profile remains an additional denial safeguard for backward
compatibility, but no profile or profile-specific property file is needed.

## Verified Phase 3 result

The recorded real Meta demonstration found the contradiction between training
**before sensitive-system access** and a procedure granting access on day one while
allowing training within 30 days. The compatible procedure, which withholds sensitive
access until training, returned `NO_CONFLICT`.

- Five real Meta calls; 48,732 ms investigation elapsed, 47,469 ms summed provider latency.
- 6,368 prompt tokens and 8,200 completion tokens reported by Meta.
- All 25 cited source/quote instances matched persisted evidence.
- Cross-department denial and current membership revocation passed.

These are historical Phase 3 measurements, not a new live request made by the
subsequent documentation audit. The dataset contains one positive and one negative
procedure case; its precision/recall results do not establish general accuracy.

See [real investigation evidence](docs/verification/phase3-demo.json),
[Phase 3 implementation and verification](docs/PHASE3.md),
[Phase 3 test results](docs/verification/phase3-results.json), and the preserved
[Phase 2 report](docs/PHASE2.md). The original documentation/security audit is recorded
separately in [repository audit](docs/REPOSITORY_AUDIT.md) and
[audit verification](docs/verification/repository-audit.json).

## Phase 4 MVP verification

The persisted graph and human review APIs are implemented and verified. The final
Java build passed **57 tests** (34 PostgreSQL-backed); Python tooling passed **15 tests**.
See [Phase 4 report](docs/PHASE4.md), [Angular API contracts](docs/api/phase4.md) and
[actual verification evidence](docs/verification/phase4-results.json).

The real `muse-spark-1.3` evaluation used ten synthetic cases. The initial run matched
6/10; a four-procedure exception comparison produced incomplete output, leaving four
cases as errors. A separately recorded retry with two procedures per investigation
completed those four cases: 3 matched and 1 disagreed with the golden NO_CONFLICT label.
Muse treated the stricter training gate as contradicting a permitted emergency exception.
The expected label is unchanged; this is a false positive against the golden dataset
and needs human adjudication. Nine distinct cases ultimately matched after the retry,
including a safe incomplete-evidence abstention. This is not a single-run 90% accuracy claim.

Across both recorded runs: **31 real calls**, **296,572 ms** summed metered provider
latency, **38,359 prompt / 68,141 completion tokens**, and **119/119** source/quote
instances verified. Initial errors remain visible and their usage is included.
Citation correspondence does not establish semantic correctness. The dataset is too
small and selected to estimate general accuracy. Keep comparison scopes small under
the existing completion limit; an incomplete result must remain visibly partial.

## Docker Compose deployment: local machine or VPS

The backend and Angular frontend remain separate repositories. The current production
runbook is [Phase 6B](docs/PHASE6B.md), which supersedes Phase 6A's proxy/host-port
instructions. Configuration is prepared and tested locally; **actual deployment needs
separate approval**. No VPS, NPM setting or existing service was changed.

Production uses the existing `nginx-proxy-manager_default` network. Only the frontend
joins it, under unique DNS alias **`ai-policy-investigator-web:8080`**. NPM forwards the
whole chosen HTTPS origin there. Frontend Nginx proxies `/api/` to the actual `backend`
service, qualified as `backend.ai-policy-investigator_application:8080` to avoid
shared-network DNS collisions. PostgreSQL has a separate internal database network;
Spring Boot retains separate outbound connectivity for Meta/native dependencies.
**No frontend, backend or PostgreSQL host ports are published in production.**

Apply backend `compose.production.yaml` after its base Compose file. Apply
`deploy/frontend/compose.production.yaml` after the separate frontend's base file,
using its actual checkout as the project directory. The runbook pins project names
to preserve PostgreSQL/model/native-cache volumes and cross-repository DNS names.
The existing base local workflow and its loopback ports are unchanged.

Required private environment variables are `POSTGRES_ADMIN_PASSWORD`,
`OWNER_DB_PASSWORD`, `APP_DB_PASSWORD`, `JWT_SECRET` and `MODEL_API_KEY`. Keep the
production env file outside both checkouts; never use placeholders or print resolved
configuration. Production disables dotenv, Swagger/OpenAPI and documentation access.
No secrets belong in frontend variables or image build arguments.

From the backend checkout, validate the complete topology without deploying:

```sh
python3 scripts/verify_production_compose.py --frontend-directory ../ai-policy-investigator-frontend
```

The [runbook](docs/PHASE6B.md) provides exact per-project config/build/start/health
commands, NPM Proxy Host settings, first-admin bootstrap, backup, restore and image
rollback procedures. A real public domain/certificate and owner approval remain
required. Database restore and the new VPS topology have not been exercised on the VPS.

Docker builds need no host Java/Maven/Node, prebuilt JAR or preinstalled model. Operator
verification/bootstrap helpers use host Python 3, standard library only. Existing
[Phase 6A runtime evidence](docs/verification/phase6a-results.json) is preserved; current
[Phase 6B checks](docs/verification/phase6b-results.json) distinguish static topology
validation/builds/regressions from later live networking verification.

### Pinned model download and persistence

The initializer downloads exactly the previously verified Apache-2.0
`sentence-transformers/all-MiniLM-L6-v2` artifacts from revision
`1110a243fdf4706b3f48f1d95db1a4f5529b4d41`:

| Artifact | Size | SHA-256 |
|---|---:|---|
| `onnx/model.onnx` | 90,405,214 bytes | `6fd5d72fe4589f189f8ebc006442dbb529bb7ce38f8082112682524616046452` |
| `tokenizer.json` | 466,247 bytes | `be50c3628f2bf5bb5e3a7f17b1f74611b2561a3a27eeab05e5aa30f411572037` |

The model and **384 embedding dimensions are unchanged**. See
[existing model provenance](docs/provenance/embedding-model.json) and
[deployment verification](docs/verification/model-volume-results.json).

The project-scoped `embedding_models` named volume holds the files. Its default
Docker name is `ai-policy-investigator_embedding_models`; Spring Boot mounts it
**read-only** at `/models` and uses:

```text
EMBEDDING_MODEL_URI=file:/models/model.onnx
EMBEDDING_TOKENIZER_URI=file:/models/tokenizer.json
```

Compose supplies the exact existing model/tokenizer hash pair as `EMBEDDING_REVISION`;
no VPS-side env-file generation or manually copied host revision is needed. The
application's existing startup integrity check remains enabled.

The initializer verifies size and SHA-256 before atomically publishing each file.
A valid cached file is reused without network access. Download retries are bounded;
corrupt/oversized downloads are removed, and an invalid existing cache fails rather
than being silently replaced. A lock serializes initializers sharing the volume.

A second persistent named volume, `native_cache`, stores public DJL/PyTorch native
dependencies. The initializer prepares it for backend UID/GID 10001. Initial backend
startup may download those dependencies too; later starts reuse them. No `.local`
model directory or host cache permission setup is needed for Docker.

### Restart, verification and download failures

After deployment approval, use the `backend_compose` function defined in the
[Phase 6B runbook](docs/PHASE6B.md). A normal subsequent startup reuses both volumes:

```sh
backend_compose up -d --wait --wait-timeout 300
```

To explicitly recheck the model cache without starting dependencies:

```sh
backend_compose run --rm --no-deps model-init
```

`backend_compose restart backend` reuses the mounts; the application also checks its
artifact fingerprint on startup. Initializer errors such as
`INVALID_CACHED_ARTIFACT (model.onnx)`, `DOWNLOADED_ARTIFACT_INTEGRITY_FAILED`, or
`DOWNLOAD_NETWORK_OR_IO_FAILED` produce a nonzero exit and block backend startup.
Inspect `logs model-init`, fix network/storage access and rerun `up`. For a corrupt
cache, investigate and move only the invalid artifact aside before reinitializing.
Never remove the database volume to repair a model download. Ordinary stop/down
preserves named volumes; volume-deleting commands also delete their persisted data.

### Optional host development

Host Java development still uses Java 21, the Maven wrapper and Python 3.11+ tooling.
`scripts/init_local.py` can generate ignored local credentials, and
`scripts/fetch_embeddings.py` can fetch the same pinned artifacts into `.local/models`
and write `.local/embeddings.env`. These are optional host helpers; the VPS Docker
path above needs neither. Host-native tokenization on the Intel Mac failed with the
verified dependency combination; the Linux container path is verified.


The actual database initializer is **`deploy/postgres/init.sh`**; there is no
`deploy/init.sh`. It creates separate owner and runtime login roles, a non-login
runtime grant role, and the vector/pgcrypto extensions on a fresh volume. Flyway
then runs migrations as the non-superuser owner. Existing PostgreSQL data directories
are not reinitialized; this script is not an upgrade or password-rotation utility.

For a working local login, follow [Demo credentials and end-to-end walkthrough](docs/DEMO.md).
The explicitly enabled `scripts/setup_demo.py` command provisions
`demo@policy-investigator.local` using an environment-supplied private password and
exports the existing four synthetic PDFs. It does not run during application startup,
change JWT/security configuration, or require frontend source changes.

For other synthetic local users after migrations, see `scripts/provision_user.sql` and
its environment inputs. It uses a fixed synthetic organization and is not a general
production account-provisioning tool. Membership/grant administration currently
requires operator SQL; there is no public signup or administration UI.
For a fresh production identity store, the explicit operator-only
`scripts/provision_initial_admin.py` bootstrap creates one department ADMIN using
existing BCrypt/JWT authorization. It refuses existing identities and never runs
at application startup; see [secure initial provisioning](docs/PHASE6B.md#secure-first-application-administrator--owner-runs-after-deployment-approval).

## Environment configuration

There is one application configuration file: `src/main/resources/application.properties`.
The former local/prod property files were removed. It retains database, JWT, Meta,
ONNX, worker, logging and security settings without duplicate declarations.

`me.paulschwarz:springboot4-dotenv:5.1.0` remains installed. Dotenv loading is disabled
by default so production cannot silently read a development file. The local launcher
explicitly enables it while honoring an existing `SPRINGDOTENV_ENABLED=false` process
setting. For direct Maven/Java launches, set `SPRINGDOTENV_ENABLED=true` in the process.
Putting that switch only inside a disabled `.env` cannot enable its own loading.

The private local `.env` declares `APP_ENVIRONMENT=local` and existing local values.
Real process variables take precedence over file values, including intentionally
empty variables. Production injects values through its runtime with
`APP_ENVIRONMENT=production` and `SPRINGDOTENV_ENABLED=false`; no local file is required.

| Variables | Purpose |
|---|---|
| `APP_ENVIRONMENT` | Default `production`; explicit `local` allows opted-in developer documentation |
| `SPRINGDOTENV_ENABLED` | Default false; the local launcher enables it unless the process overrides it |
| `MODEL_API_KEY` | Real Meta bearer credential; supplied privately |
| `DB_URL`, `APP_DB_USERNAME`, `APP_DB_PASSWORD` | Runtime JDBC connection; default user `investigator_app` |
| `OWNER_DB_USERNAME`, `OWNER_DB_PASSWORD` | Flyway owner connection; default user `investigator_owner` |
| `JWT_SECRET` | Private signing secret; see `.env.example` |
| `POSTGRES_ADMIN_PASSWORD` | Dedicated local PostgreSQL bootstrap administrator |
| `EMBEDDING_MODEL_URI`, `EMBEDDING_TOKENIZER_URI`, `EMBEDDING_REVISION` | Local artifact locations and verified hashes |
| `META_MODEL_ID` | Verified default `muse-spark-1.3`; confirm account availability before changing |
| `META_TIMEOUT_SECONDS` | Default 30, range 1–60 per attempt |
| `META_MAX_RETRIES` | Default 2, range 0–2 |
| `META_CONCURRENCY` | Default 2, range 1–4, per instance |
| `META_INVESTIGATION_BUDGET_SECONDS` | Default 240, range 30–600; persisted on first claim and retained after restart |

Runtime settings resolve through named environment placeholders. The single property
file groups those mappings by database, JWT, workers/uploads, embeddings, Meta and
local documentation. Non-secret fallbacks preserve the previous defaults for CI and
production without a local file; passwords and the signing secret have no fake defaults.

Additional controls are `DB_POOL_MAX_SIZE`, `JWT_ISSUER`, `JWT_AUDIENCE`,
`UPLOAD_MAX_FILE_SIZE`, `UPLOAD_MAX_REQUEST_SIZE`, `APP_WORKER_ENABLED`,
`APP_INVESTIGATION_WORKER_ENABLED`, `LOCAL_OPENAPI_ENABLED`,
`LOCAL_SWAGGER_UI_ENABLED` and `SWAGGER_TRY_IT_OUT_ENABLED`. Compose forwards these
explicitly. It retains its internal database URL and `/models` mount paths, so host
Java paths from `.env` are not accidentally used inside the container.

Security invariants remain fixed in the property file: schema validation, disabled
JPA caches/open-in-view, redacted errors/health, SQL/bind logging off, and production
dotenv/documentation opt-out. The model-specific local embedding implementation and
padding remain fixed too. The refactor does not make these safeguards tuning knobs.
Two isolated-JVM tests exercise the actual application mappings and process precedence.
The preceding environment refactor passed 52 Java tests; the single-file follow-up
passed 54 Java tests (31 PostgreSQL-backed) and four Python tests. See
[single-file configuration verification](docs/verification/single-config-results.json);
the [earlier environment result](docs/verification/environment-refactor-results.json) is preserved.

A compatible host can run the packaged JAR or `scripts/run_local.py`. The helper
uses `.local` configuration as fallbacks, respects real environment values and yields
to keys declared in root `.env`. Build with `neural-embeddings` first. Host-native
inference on the Intel Mac remains unsupported by the verified dependency combination.

From the repository root, the following configuration-only command prints booleans
and does not start a database, web server or model:

```sh
SPRINGDOTENV_ENABLED=true java -jar target/ai-policy-investigator-0.1.0-SNAPSHOT.jar --verify-configuration
```

For an intentional live synthetic preflight:

```sh
SPRINGDOTENV_ENABLED=true java -jar target/ai-policy-investigator-0.1.0-SNAPSHOT.jar --verify-meta-access
```

The second command needs Python and the repository scripts on the host. It passes
Spring's resolved key to the child through its environment, never command arguments;
missing/example keys stop before dispatch. It archives prior preflight evidence.
The JRE-only backend container does not include this Python tooling, and normal
Java investigations do not require it.

## End-to-end API workflow

1. `POST /api/auth/login`; retain the short-lived bearer token in memory.
2. `GET /api/auth/me` to identify current permitted departments.
3. Upload baseline/replacement PDFs and procedure PDFs; poll their ingestion jobs.
4. An owning-department ADMIN explicitly enables external processing for each
   contributing policy/procedure with `POST /api/policies/{id}/external-processing`.
5. `POST /api/investigations` with a UUID `Idempotency-Key`, baselineVersionId,
   replacementVersionId, procedureVersionIds and analysisDate.
6. Poll `GET /api/investigations/{id}` and fetch `/requirements` and `/findings`.
7. Resolve cited source IDs through `GET /api/evidence/{id}` before human assessment.
8. Fetch `GET /api/investigations/{id}/graph` and submit review events through
   `POST /api/investigations/{id}/findings/{findingId}/reviews`.

The replacement must directly follow the baseline in the same policy. All selected
versions must be indexed, effective, readable and externally consented; the requester
must retain replacement write permission. Findings require access to every contributing
version. See exact fields, state transitions and failure handling in the
[document APIs](docs/api/phase2.md), [investigation APIs](docs/api/phase3.md), and
[exact Angular dashboard contracts](docs/api/phase4.md).

## Scripts, evaluation and tests

Python is local tooling. The scripts below use the standard library and are audited
in [detail](docs/REPOSITORY_AUDIT.md); their side effects differ.

| Script | Purpose and side effects |
|---|---|
| `scripts/init_local.py` | Generates ignored local-only credentials; refuses overwrite; creates cache directories |
| `scripts/verify_production_compose.py` | Offline production topology guard using synthetic Compose interpolation; no deployment or network creation |
| `scripts/provision_initial_admin.py` | Explicit empty-store initial ADMIN bootstrap; secret COPY transport, no default credentials or startup hook |
| `scripts/setup_demo.py` | Explicit local-only idempotent demo account provisioning and export of existing synthetic PDFs; reads DEMO_PASSWORD from the environment, never prints credentials, makes no model calls |
| `scripts/fetch_embeddings.py` | Shared integrity-checked model initializer; Docker volume mode or optional host artifact/configuration setup |
| `scripts/run_local.py` | Starts the packaged Java application with optional local configuration fallbacks |
| `scripts/verify_meta_access.py` | Live synthetic discovery/inference; writes sanitized preflight evidence/history; standalone configuration differs from the Spring wrapper |
| `scripts/verify_provenance.py` | Checks four allowlisted imports using read-only Git source reads and destination hashes; requires the reference backend checkout |
| `scripts/smoke_workflow.py` | Creates synthetic SQL fixtures, runs real local embeddings and HTTP checks, then stops its backend |
| `scripts/smoke_investigation.py` | Creates synthetic fixtures, runs real Meta extraction/comparison, verifies citations/isolation and writes evidence/history |
| `scripts/evaluate_phase4.py` | Runs ten synthetic cases through real PDF ingestion, consent, Meta investigations, graph/review APIs and citation checks; creates isolated synthetic SQL fixtures, disables fixture accounts on exit, writes sanitized results/history |
| `scripts/tests/test_phase4_evaluation.py` | Guards scoring of provider failures, abstentions, false positives and dataset coverage; no provider calls |
| `scripts/tests/test_verify_meta_access.py` | Four local validation tests; no real provider call |

`evaluation/phase3-golden.json` contains the synthetic training/access baseline,
replacement and two expected procedure outcomes. The demo is coupled to those two
case positions and fixed dates; it is not a generic benchmark runner.
`evaluation/phase4-golden.json` adds ten independently specified cases in four bounded
investigations, covering contradictions, compatible gates, exceptions, different
scopes, ambiguity, missing requirements and insufficient evidence. The runner uses
real `muse-spark-1.3` through the existing authorization/consent gates, not a substitute.
Provider/validation failures are reported as errors, not successful abstentions.

To reproduce on the **dedicated local demo database** with populated `.env` and
`.local/runtime.env` from the existing local setup:

```sh
python3 scripts/evaluate_phase4.py --start-backend
```

This builds/starts the existing Compose backend and stops it afterward. Without
`--start-backend`, it uses an already running backend without changing its lifecycle.
Do not run this fixture-creating evaluator on a shared VPS database. It uses local
operator SQL only to provision synthetic identities; document/model/review operations
use authenticated APIs and real consent. Results and prior attempts are retained in
`docs/verification/phase4-evaluation.json` and `phase4-attempts/`. The runner defaults
to two procedures per comparison to keep output within the existing token bound.
Use `--group explicit-exception --max-procedures 2` for a targeted exception retry;
it writes a separate `phase4-explicit-exception-evaluation.json`. No secret values
are recorded. The ten-case run is a targeted demonstration, not general accuracy.

```sh
python3 -B -m unittest discover -s scripts/tests -v
./mvnw -Pdatabase-tests verify
# Include the embedding backend to produce a locally runnable artifact:
./mvnw -Pneural-embeddings,database-tests verify
```

The Maven database profile requires Docker and fails rather than silently skipping
PostgreSQL security tests. Tests use synthetic credentials and controlled provider/
embedding fixtures; those results do not establish real model accuracy. The default
Maven build omits production embedding dependencies, so package/run with the neural
profile when starting the real backend.

The [Phase 6C workflows](docs/PHASE6C.md) run on develop pushes and PRs targeting main.
Backend CI uses Java 21/Maven wrapper 3.9.16, the existing database test profile, all
Python tests, the production Compose verifier and a production Docker build. No real
Meta request, production secrets or model-weight download is needed. A reviewed
frontend Compose snapshot avoids private cross-repository access tokens; local tests
still verify the actual sibling frontend contract.

Frontend CI and manual publisher files are prepared at `docs/ci/frontend/` for owner
installation into the separate repository; workspace policy prevented direct writes.
They use Node 22, npm 11.8.0, npm ci, all 29 tests and production and Docker builds.
Manual publishers run only on main, use GITHUB_TOKEN packages permission and tag images
with full commit SHAs; deployments pin actual registry digests. Image-only release
overlays preserve the Phase 6B topology and volumes. See the runbook for exact commands.
Local equivalent checks are recorded in [Phase 6C evidence](docs/verification/phase6c-results.json);
no hosted Actions run, GHCR publication, SSH or VPS deployment is claimed.

Optional **local dedicated-environment** demonstrations:

```sh
python3 scripts/smoke_workflow.py --container
python3 scripts/smoke_investigation.py
```

Run these sequentially. They write synthetic database records, create temporary
accounts, revoke fixture memberships, stop the backend and leave fixture data behind.
They are not production healthchecks. The Meta demo incurs real usage and changes
verification files; it was not rerun for the documentation-only audit. The provenance
utility also was not executed during this audit because Git operations are reserved
for the owner; its four destination hashes were checked directly instead.

## VPS and Docker Compose compatibility

Use [Phase 6B](docs/PHASE6B.md) for the confirmed Nginx Proxy Manager deployment.
It replaces the earlier host-loopback proxy guidance for production. The owner-provided
NPM container/network and unrelated services remain unchanged. Only the frontend joins
the shared proxy network; no service publishes a host port. Spring Boot/PostgreSQL are
kept off that shared network, with internal application/database networks and unchanged
named volumes, initialization and model hashes. Keep current secure isolation overlays
when rolling application images back.

This increment validates configuration, builds and relevant tests without running
Compose `up`, creating Docker networks, contacting the VPS or changing NPM/firewall
settings. Domain/certificate selection, live network/egress verification, account
provisioning, a backup/restore rehearsal and actual deployment require the owner's
next approval. The existing shared-peer login limiter remains unchanged. Actual VPS
architecture, capacity, HTTPS and runtime networking are not yet verified.

## Secrets and commit readiness

`.gitignore` excludes `.env`, environment variants, `*.env` files, `.local`, generated
build/cache files, Python bytecode, private-key and keystore file patterns. Only the
placeholder `.env.example` is allowed as a dotenv example. `.dockerignore` uses a
`pom.xml`/`src` allowlist with final dotenv/key/keystore exclusions. Maven additionally
excludes dotenv resource patterns. These safeguards do not detect a secret pasted
into an otherwise legitimate source file, or every arbitrary local resource filename.

The audit scanned candidate files and own packaged classes/resources for known
local credential values and private-key markers, and inspected a scratch Docker
build context with synthetic exclusion probes. Actual credentials were not printed
or copied. The earlier pre-commit audit had no `.git` directory and used ripgrep's Gitignore
reader. Phase 6A additionally inspected both current Git indexes read-only: no
dotenv, private fixture, key or keystore paths were tracked. It also checked both
actual Docker build contexts, packaged application resources and known local
credential values; see the current [verification record](docs/verification/phase6a-results.json).
These checks do not prove that arbitrary unknown secrets never existed in history.

The [pre-first-commit candidate manifest](docs/provenance/commit-ready-files.csv) and
[repository audit](docs/REPOSITORY_AUDIT.md) remain historical records. Review the
[new Phase 4 file inventory](docs/provenance/phase4-files.csv) for this increment.
Private `.env`/`.local` files, caches, model weights, logs and built artifacts are
excluded from that manifest. No Git commands, commits, pushes, tags or history edits
were performed during the audit. All Git operations remain with the owner.

## Attribution and phase boundaries

Selected infrastructure comes from [AI Compliance Copilot backend](https://github.com/ThierryTe/spring-ai-rag).
The [frontend reference](https://github.com/ThierryTe/spring-ai-rag-frontend) was
inspected and has not been imported. The [allowlist](docs/provenance/allowlist.json)
records the four exact imports, source commits, paths and hashes;
[adaptations](docs/provenance/adaptations.json),
[pre-existing capabilities](docs/provenance/PRE_EXISTING.md), and
[event contributions](docs/provenance/HACKATHON_CONTRIBUTIONS.md) distinguish reuse
from new work. Reference repositories remain unchanged by this project work.

Phase 4 was explicitly approved after the owner's first commit and push. Its additions
are the persisted graph projection, append-only review migration/API, ten synthetic
evaluation cases and frontend API contracts. No reference code was imported in this
phase. The working deployment and model/provider configuration remain unchanged.
Phase 5 was subsequently approved and implemented in the separate Angular repository.
Phase 6A audits Docker deployment and prepares local verification; Phase 6B finalizes the secure NPM configuration; actual VPS deployment still
requires explicit approval. The [Phase 6A report](docs/PHASE6A.md) records
what is applied, what remains pending and which checks were actually executed.
