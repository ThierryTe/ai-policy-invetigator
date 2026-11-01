# Production CI/CD

Push main → test both applications → build both images → GHCR. Pushes never deploy.
Actions → **Deploy production → Run workflow** on **main** deploys the latest successful CI image pair.

## Architecture

The backend repository `ThierryTe/ai-policy-invetigator` coordinates both applications.
CI checks out frontend main from `ThierryTe/ai-policy-invetigator-frontend` once and
records that exact commit. It runs backend tests (including isolated PostgreSQL fixtures),
frontend unit tests, and deployment unit tests. Each Dockerfile builds its production
artifact once. PRs test/build without publication or production credentials.

Both existing GHCR packages receive `sha-<full source commit>` tags. One small artifact
per successful CI run records both source commits, both registry digests, and tested
Compose/scripts. Deployment selects the newest successful main CI run and its current
attempt's artifact. Missing/expired artifacts fail clearly: rerun CI. Deployment uses
`image@sha256:...`, never discovery tags or manually entered image references.

Strictly pinned SSH transfers configuration/scripts; the VPS pulls both images before
replacing either application container. The existing Compose project names, volumes,
private networks, Nginx Proxy Manager alias/domain and HTTPS configuration are preserved.
Workers are background processors **inside the backend**, not separate services.
PostgreSQL and model-init are never started, recreated, pulled or upgraded by CD.

## One-time GitHub configuration

Use backend environment **prod**, restricted to main. Existing reviewer policy is yours
to manage; this workflow adds no approval gate. Remove obsolete reviewer requirements
yourself if you want an immediate one-click deployment.

| Secret | Location / purpose |
|---|---|
| `VPS_HOST` | prod: hostname or IPv4 address |
| `VPS_USERNAME` | prod: existing SSH/Docker account |
| `VPS_SSH_KEY` | prod: dedicated private deployment key |
| `VPS_PORT` | prod: optional; defaults to 22 |
| `VPS_DEPLOY_PATH` | prod: `/opt/ai-policy-investigator` |
| `FRONTEND_READ_TOKEN` | Backend repository: only for private frontend checkout; frontend Contents read access |

Set **prod variable** `VPS_HOST_KEY` to the independently verified public
`ssh-ed25519 AAAA...` VPS host key. No unverified key scanning is used.
`GITHUB_TOKEN` is automatic. Grant the backend repository **Manage Actions access**
with Packages write on both existing GHCR packages (including frontend). Enable artifact storage.
If branch protection requires the old `verify` job, update it to the new
`test-and-publish` check before retiring the old required-check setting.

**Frontend pushes:** install [frontend-ci.yml.example](../deploy/simple/frontend-ci.yml.example)
as the frontend repository's `.github/workflows/verify.yml`, replacing its old
CI/publish/deploy chain. Add frontend secret `BACKEND_CI_TOKEN`: a fine-grained token
restricted to backend Contents write access, required by GitHub's repository-dispatch API.
A frontend main push then requests coordinated backend CI; rapid pushes may coalesce to
frontend main at checkout time. Until installed, only backend pushes publish coordinated
pairs. The old frontend reusable-workflow calls must be removed during this switch.
The frontend may retain its existing verification job and make the notification job
depend on it. Replace the old reusable `publish`/`deploy` jobs: their workflow files
have been archived and are no longer active in the backend repository.

## Diagnosing GHCR `permission_denied: write_package`

The coordinated publisher is backend `.github/workflows/ci.yml`, job
`test-and-publish`, in **`ThierryTe/ai-policy-invetigator`**, even for the frontend image
and even when a frontend push requests the run. Checking out frontend sources does
not change the job's repository or token identity. A `repository_dispatch` starts a
backend workflow with its own `GITHUB_TOKEN`; it does not transfer the dispatch token.

The workflow uses shell `docker login`, not `docker/login-action`. Its password is
`GHCR_TOKEN: ${{ github.token }}`, equivalent to `${{ secrets.GITHUB_TOKEN }}` in
the inspected failing revision. There is no PAT fallback. The workflow and the job
both request `contents: read` and `packages: write`; checkout credentials are not
persisted. The publisher identity is recorded in the job log and run summary without
printing any credential.

Keep these credentials separate:

| Credential | Repository / use | Required access |
|---|---|---|
| `GITHUB_TOKEN` | Backend job: login and push both GHCR images | Job `packages: write` AND package Actions Write for the backend repository |
| `FRONTEND_READ_TOKEN` | Backend: optional private frontend checkout only | Frontend Contents read |
| `BACKEND_CI_TOKEN` | Frontend: existing credential to notify backend only | Backend Contents write for `repository_dispatch`; no GHCR use |

Do not create another PAT or give the notification token package scopes to fix a
GHCR denial. The automatic backend `GITHUB_TOKEN` is sufficient with the package ACL.
At the time of the public audit below, the frontend workflow had no notification.
The corrected local frontend workflow replaces its old publish/deploy calls with a
notification after verification, using the existing `BACKEND_CI_TOKEN` secret. Its
push/develop and PR verification jobs are preserved. The example above also provides
a minimal notification-only configuration.
If that secret is absent, notifications require configuring an existing suitable
credential; this is independent of publishing images from backend pushes.

Manual GitHub checks:

1. Open the **frontend container package**
   [`ai-policy-invetigator-frontend`](https://github.com/users/ThierryTe/packages/container/ai-policy-invetigator-frontend/settings).
   Under **Package settings → Manage Actions access**, verify the exact repository
   **`ThierryTe/ai-policy-invetigator`** has **Write**. A Write grant for the frontend
   repository, a user/collaborator role, or merely linking the frontend source repository
   does not grant this backend workflow access. Repeat for the backend package.
   Keep the frontend source association; add backend Actions access independently.
2. In the failed backend run, open **test-and-publish → Set up job → GITHUB_TOKEN
   Permissions** and confirm **Packages: write**. The YAML requests it, but only this
   log confirms the effective permission. PR/fork/Dependabot restrictions or a reusable
   workflow caller can reduce permissions in other execution paths. This publisher is
   a normal backend job and never pushes images on `pull_request`.
3. In backend **Settings → Actions → General → Workflow permissions**, inspect the
   defaults and any organization/enterprise policy if the effective permission is
   read-only. A read-only *default* alone is not a reason to enable all write permissions:
   explicit workflow/job permissions adjust that default. No need to enable permission
   to create/approve pull requests. Package Actions access remains a separate requirement.
4. Match the failing run's workflow revision and registry/package spelling. The image
   source label points to the frontend repository but does not switch the publishing
   identity or grant backend Actions access. A successful login alone does not prove
   permission to push this existing package.
5. After an operator applies the missing package permission, rerunning CI only tests
   and publishes images; deployment remains a separate manual workflow. This investigation
   does not rerun CI, push images, change GitHub settings, or deploy.

Public GitHub inspection on 2026-11-01 confirmed
[run 41301619487, attempt 2](https://github.com/ThierryTe/ai-policy-invetigator/actions/runs/41301619487),
backend commit `013182abcda835c6b10f4fe916c51a940db18184`, failed at the combined image
build/publish step. That revision matches the inspected local workflow before this fix.
The public frontend `main` still called the archived reusable workflows and did not
use `BACKEND_CI_TOKEN`. Detailed logs and private package settings were unavailable
without authentication (HTTP 403 and 401); the effective permissions and package ACL
must therefore be confirmed manually, not inferred as observed facts.

References: [package workflow access](https://docs.github.com/en/packages/learn-github-packages/configuring-a-packages-access-control-and-visibility#ensuring-workflow-access-to-your-package),
[workflow permission calculation](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax#how-permissions-are-calculated-for-a-workflow-job),
[GitHub token context](https://docs.github.com/en/actions/reference/workflows-and-actions/contexts#github-context).

## One-time VPS configuration — operator only

No VPS actions are performed while implementing this pipeline. Review these prerequisites yourself:

- Preserve V8 release **`r041243000818-11`**, its backups, releases directory and recovery state.
- Keep `/opt/ai-policy-investigator/.env.production`, owned by the deployment account,
  mode 600. Preserve all existing credentials/settings. Set `APP_WORKER_ENABLED=true`
  and `APP_INVESTIGATION_WORKER_ENABLED=true` explicitly. A nonempty `MODEL_API_KEY`
  is required. These take effect only when you authorize deployment.
- A Linux amd64 VPS, Python 3.10+, Docker and Compose **2.24.4+** are required. The existing SSH account
  needs Docker access and write access to the project directory; no new service/sudo rule is needed.
- Allow outbound HTTPS to GHCR. For private packages, log in once as the deployment
  account using a Packages read token and `docker login ghcr.io --password-stdin`.
  Keep credentials in that account's private Docker credential configuration.
- Existing healthy projects: `ai-policy-investigator` (backend/postgres) and
  `ai-policy-investigator-ui` (frontend), one container per service, no published host ports.
- Existing volumes: `ai-policy-investigator_investigator_data`,
  `ai-policy-investigator_embedding_models`, `ai-policy-investigator_native_cache`.
  Model/native assets must already be populated. Volumes are external: empty replacements
  cannot be silently created. CD never deletes volumes or initializes a database/model.
- Existing networks: `ai-policy-investigator_application`, `ai-policy-investigator_database`,
  `ai-policy-investigator_default`, `nginx-proxy-manager_default`. Keep their current
  isolation and NPM routing to `ai-policy-investigator-web:8080`. Unexpected topology
  or mount names fail preflight rather than changing infrastructure.

## First deployment

1. Review changes, configure prerequisites and handle Git operations yourself. Push backend main.
2. Wait for **CI — test and publish** to succeed; inspect both commits/digests in its summary.
3. Backend **Actions → Deploy production → Run workflow**, branch **main**, operation **deploy**.
4. Read the deployment summary. No release ID, hashes or activation forms are needed.

Verification checks healthy frontend/backend/PostgreSQL containers, the backend health
endpoint, public Angular HTML and `/healthz`, plus `/api/auth/me` returning 401 through
public API routing. Public checks allow a short DNS/proxy settling period and validate TLS.

The existing private `/actuator/health` gains a status-only worker contributor. It
requires successful real queue-function polls, live executors, enabled flags, the database
security check, a configured Meta key, and a real local ONNX embedding. Busy workers get
bounded processing grace; stale polling/failed embeddings become unhealthy. The embedding
probe caches success for 60 seconds and failure for 10 seconds.

**No paid inference probe runs.** Key presence cannot prove Meta authentication/quota or
remote availability. Perform the complete upload/investigation demo through an explicitly
authorized user action. Existing queued investigations can naturally call Meta when workers
resume normal processing; that is separate from the readiness probe.

## Migration policy

Routine CD is **validation only**: `APP_MIGRATIONS_VALIDATE_ONLY=true` installs a Flyway
strategy that calls validate, refuses empty/pending/failed/missing/future histories, and
never calls migrate. Hibernate still validates the schema. CD reads the successful V8
history before and after replacement. Historical SQL is unchanged. No clean, repair,
baseline, reset or migration command exists in the new deployment scripts.

Future schema changes require a separately reviewed maintenance operation: review SQL
and previous-image compatibility, explicitly approve destructive changes, verify a backup,
and authorize the migration separately. Then deploy matching code. Do not bypass validation.
If the previous image becomes incompatible, establish a compatible recovery point before
using image rollback. Image rollback never reverses a database change.

## Rollback

Before replacement, private VPS `simple-deploy/snapshot-*` directories retain immutable
local image IDs, available registry manifest digests, Compose files, the env snapshot and
actual previous worker flags/health commands. `simple-deploy/previous.json` selects the
previous healthy configuration. Snapshots can contain secrets: never upload them to Actions.
Keep their cached images; do not prune them. CI artifacts last 90 days; VPS snapshots have
no automatic expiry. Legacy V8 recovery artifacts are untouched.

On deployment failure, unchanged readable Flyway history permits restoration of previous
frontend/backend images/settings, followed by container and public health checks. PostgreSQL
is never restarted. The job still fails, reporting whether rollback succeeded. An older V8
image restores its prior worker settings, which can be disabled, and its original health
command. Flyway is disabled for restored images after the schema-equality check.

Manual rollback: **Deploy production → Run workflow → operation rollback**. It uses the
VPS snapshot and cached images, requiring no historical CI artifact or registry access.
Schema change/unreadable history/failed rollback stops automation and writes
`simple-deploy/blocked.json`. Review/recover with explicit operator authorization before
removing that marker. Database restore remains a separate recovery operation.

## Local validation and legacy recovery

```sh
python3 -B -m unittest discover -s scripts/tests -p 'test_simple_*.py' -v
SPRINGDOTENV_ENABLED=false ./mvnw -B -Pneural-embeddings,database-tests verify
# In the frontend checkout:
npm test
```

Tests use failure injection and disposable synthetic PostgreSQL fixtures; no production DB
or real Meta transport is used. Compose config and workflow actionlint checks run locally.
Legacy workflow definitions are archived in `.github/legacy-workflows/` after replacement
validation; recovery scripts, runbooks and V8 artifacts remain intact. They are historical
material, not the routine deployment procedure. Hosted publication, live VPS pull access,
capacity/topology and first deployment still need operator validation.
