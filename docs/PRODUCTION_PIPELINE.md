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
No files in the sibling frontend checkout were edited by this implementation.

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
