# Production CI/CD

The backend and frontend use the same pipeline: **tests → Docker build/publication →
SSH/Compose deployment**. Main pushes are configured to trigger this chain after
successful validation; develop pushes and pull requests only run CI. Manual dispatch
remains for recovery/rollback. Configure the [SSH host identity pin](#current-ssh-configuration)
before delivery. This guide does not certify a live VPS run.

## Repositories and workflows

| Component | GitHub repository |
|---|---|
| Backend | ThierryTe/ai-policy-invetigator |
| Frontend | ThierryTe/ai-policy-invetigator-frontend |

Local checkout names can differ. Both remote repositories and all three GHCR packages
use **invetigator**. The backend owns the reusable workflows:

- `.github/workflows/verify.yml`: Java/Python/PostgreSQL tests and production image build.
- `.github/workflows/publish-images.yml`: publication after the caller's CI succeeds.
- `.github/workflows/deploy-production.yml`: runner-side image preparation and deployment.

The frontend's own verify.yml runs npm ci, Angular tests and production/Docker builds,
then calls those reusable backend workflows on main. The shared deployment job selects
GitHub Environment **prod in the calling repository**. Ordinary CI does not receive
VPS secrets. Spring Boot's APP_ENVIRONMENT=production is a separate runtime setting.

Protect main and require the appropriate CI checks. For fully automatic delivery,
do not require an additional Environment reviewer for each prod deployment. Reusable
workflow access must be allowed between the repositories. The frontend uses the stable
backend main for deployment tooling; the actual checkout commit is recorded per release.
Third-party Actions retain immutable SHA pins.

## Image selection and delivery

The published packages are:

```text
ghcr.io/thierryte/ai-policy-invetigator
ghcr.io/thierryte/ai-policy-invetigator-model-init
ghcr.io/thierryte/ai-policy-invetigator-frontend
```

Each publication uses `sha-<full source SHA>`. Existing SHA tags are verified/reused,
never overwritten. Backend and model-init use the same source SHA. Publication advances
the release-main discovery channel only after the component's immutable images pass
verification. A deployment keeps its newly validated component SHA and discovers the
companion component, checking its OCI revision against the immutable tag/digest.
**release-main is never used as a Compose production image reference.**

The GitHub runner downloads exact linux/amd64 image manifests and verifies config
hashes, source labels, archive contents and uncompressed layer DiffIDs. It transfers
three application images plus the unchanged PostgreSQL 16/pgvector image, allowlisted
Compose files and versioned operator code. No env file, SSH key, database dump or Git
history is included. No private image is uploaded as a public Actions artifact.

The configured delivery path avoids VPS GHCR pulls: SSH/SCP transports archives,
then Docker loads local `:deploy-<digest>` aliases. Compose resolves with pull_policy:never
and runs with --no-build/--pull never. There is no global prune or down operation.
The existing authorized SSH/Docker account runs the script; no preinstalled controller,
new VPS service or sudo launcher is required. Docker access is privileged and its key
must be protected accordingly.

Docker29 may expose store-specific manifest IDs, and docker load need not preserve
RepoDigests. The pipeline verifies actual selected platform, layers and runtime config
rather than relying on portable image IDs, registry RepoDigests or reported image size.
Missing images, wrong architecture, unavailable platform metadata and incomplete archives
remain distinct failures. Unknown platforms are never accepted.

## One-time GitHub configuration

Create or verify Environment **prod in both repositories**, restricted to main.
Environments/secrets are not implicitly shared between repositories. Use the existing
VPS secret conventions, supplying values privately through GitHub:

| Secret | Purpose |
|---|---|
| VPS_HOST | Actual VPS hostname or IPv4 address |
| VPS_USERNAME | Existing authorized SSH/Docker deployment account |
| VPS_SSH_KEY | Dedicated private deployment key |
| VPS_PORT | Actual SSH port; defaults to 22 |
| VPS_DEPLOY_PATH | /opt/ai-policy-investigator |

### Current SSH configuration

The five secrets above retain the existing SSH conventions. Previously the transfer
script also required VPS_KNOWN_HOSTS, which the workflow did not supply. It now accepts
the **public Environment variable VPS_HOST_KEY**, explicitly passed by the reusable
workflow. No VPS_KNOWN_HOSTS secret is needed. Configure this variable in **prod in
both repositories**, because the Environment belongs to the calling repository.

Obtain the VPS's Ed25519 **public** host key through an independently trusted channel,
such as the hosting provider's authenticated console. The owner can inspect it there:

```sh
sudo cat /etc/ssh/ssh_host_ed25519_key.pub
sudo ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub -E sha256
```

Set VPS_HOST_KEY to the complete single public-key line, in the form
`ssh-ed25519 <base64-public-host-key> [optional comment]`. This is a public identity
pin, not the private deployment key or the server's private host key. Protect its
integrity with the Environment's access controls. The server must already offer that
Ed25519 host key; these instructions do not change its SSH configuration.

The script validates the key's structure before creating credential files or connecting.
It binds the pin to VPS_HOST and VPS_PORT in a temporary, mode-600 known_hosts file.
Both SSH and SCP use StrictHostKeyChecking=yes, only that trust file and the pinned
Ed25519 algorithm; unrelated runner trust files, SSH configuration and DNS verification
cannot supply an alternative key. Missing/malformed pins fail with SSH_HOST_KEY_REQUIRED
or SSH_HOST_KEY_INVALID/SSH_HOST_KEY_MUST_BE_ED25519. An unknown or changed server key
is refused by OpenSSH. Host-key rotation requires independent verification and an
intentional variable update; an unauthenticated ssh-keyscan is not a trust source.
See [OpenSSH's host verification options](https://man.openbsd.org/ssh_config).

The read-only spring-ai-rag reference uses the same five secrets with Appleboy SSH/SCP
Actions, but its workflow supplies no explicit host fingerprint. We retain its existing
secret conventions while pinning the server identity explicitly here. Local tests verify
parsing and effective SSH options without contacting the VPS; they do not prove a live
server handshake or successful delivery.

Set these prod variables in both repositories:

| Variable | Purpose |
|---|---|
| VPS_HOST_KEY | Independently verified single Ed25519 public host-key line; required for SSH/SCP |
| VPS_ENV_FILE | Actual absolute private production env-file path under the deployment directory |
| INITIAL_BACKEND_SHA | Existing published backend/model-init source SHA for first-channel bootstrap |
| INITIAL_FRONTEND_SHA | Existing published frontend source SHA for first-channel bootstrap |
| AUTO_APPLY_MIGRATIONS | true only under the project's reviewed migration policy; absent/false blocks pending SQL |

The initial SHA variables are used only when a discovery channel is absent (404),
not on authentication, network or integrity failure. They need no per-release update.
The initial locally loaded image selection is recorded in `deploy/release.images.json`;
choose bootstrap SHAs from real published artefacts rather than inventing tags.

GITHUB_TOKEN is supplied by Actions: packages:write for publication and packages:read
for delivery. Grant both caller repositories read access to all three GHCR packages
and each publisher write access to its own package(s). A PAT is not required when
those grants and reusable-workflow access are configured.

The five application secrets stay in the existing protected VPS env file:
MODEL_API_KEY, JWT_SECRET, POSTGRES_ADMIN_PASSWORD, OWNER_DB_PASSWORD and APP_DB_PASSWORD.
The file must be readable by its execution account, owned by it and mode 600. Do not
pass these values to frontend builds or Actions image-build arguments. Preserve database
passwords matching existing roles; editing env values does not rotate PostgreSQL roles.

## VPS prerequisites and verification

Use Docker29/Compose 5, Python 3.11+ and linux/amd64. The existing deployment account
needs project-directory and Docker access; scripts do not grant privileges or change
global Docker, SSH, IPv6, firewall or NPM settings. The existing NPM network, protected
secrets, database volumes and ONNX cache must be preserved. See [operations](DEPLOYMENT.md)
for topology, initial account and backup/restore.

The preflight validates secrets without printing them, Compose topology, existing NPM,
local image content/platform, persistent volume names and current database compatibility.
PostgreSQL is reused with --no-recreate. Only this project's initializer/backend/frontend
containers can be replaced. The initializer verifies the pinned model/cache and must
exit zero. All long-lived containers must be healthy.

The script checks internal frontend health and /api/auth/me returning 401 without a token,
then HTTPS `/healthz` and `/` returning 200 and `/api/auth/me` returning 401 through NPM,
with valid TLS and no redirects. These verify routing/authentication boundaries, not an
authenticated investigation or live Meta inference. No real Meta call runs in normal CI.

## Concurrency, release records and recovery

GitHub concurrency groups are repository-scoped. A shared project file lock on the VPS
serializes both callers. If the other repository deployed while archives were being
prepared, the stale base is rejected before image loading/startup and the runner resolves
the updated pair again, at most three times. Provider/network/health errors are not
blindly retried as successful deployments.

Releases are stored in releases/r<NAMESPACE><RUN_ID>-<RUN_ATTEMPT*10+attempt>, where
namespace 1 denotes backend, 2 frontend and 0 manual recovery. release.json records source
SHAs, registry/archive hashes, runtime/configuration hashes and migrations extracted
from the selected JAR. A safe failure.json records failures. last-successful.json changes
only after every health, migration and routing check passes. Monitor disk usage; nothing
is pruned automatically. Retain releases still referenced by container bind mounts.

For exceptional rollback, dispatch **Deploy production after publication** on backend
main with operation=rollback, a previously validated rollback_release ID, empty SHA
fields and allow_migrations=false. Retained local archives are reverified. Applied SQL
versions/scripts/checksums must match the target exactly. An incompatible newer schema
blocks rollback; PostgreSQL is never automatically restored, cleaned or rewound.
Identical schema history is necessary but does not prove semantic data compatibility.

Before a migration-bearing release, follow the [backup procedure](DEPLOYMENT.md).
Review production results in Actions and the restricted release records. A green local
unit/configuration test does not prove hosted token access, SSH reachability, public
routing or successful production deployment.
