# Production CI/CD

Main pushes run **tests → Docker build/publication**, without automatic deployment.
Production delivery is an explicit backend `workflow_dispatch`, using the
[two-phase V8 runbook](V8_DEPLOYMENT_RUNBOOK.md). Develop pushes and pull requests run
CI only. Configure the [SSH host identity pin](#current-ssh-configuration) before delivery.
This guide does not certify a live VPS run or independently verify operator attestations.

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

The frontend's own verify.yml can continue calling the reusable publication workflow.
Legacy reusable deployment calls cannot run the deployment job. Deployment selects
GitHub Environment **prod in the backend repository** on a manual main dispatch.
Ordinary CI does not receive
VPS secrets. Spring Boot's APP_ENVIRONMENT=production is a separate runtime setting.

Protect main and require the appropriate CI checks. Configure required environment
reviewers, prevent self-review, restrict prod to main and disable bypass where supported.
These settings are not established by the YAML or by ticking a confirmation input.
Reusable publication access must remain allowed between the repositories.
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
verification. A deployment requires explicit approved backend/frontend SHAs and the
approved backend linux/amd64 child manifest digest, plus the phase's operator attestations.
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

Create or verify the protected backend Environment **prod**, restricted to main,
with independent required review. Environments/secrets are not implicitly shared.
Use the existing
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

Set these variables in the backend prod environment:

| Variable | Purpose |
|---|---|
| VPS_HOST_KEY | Independently verified single Ed25519 public host-key line; required for SSH/SCP |
| VPS_ENV_FILE | Actual absolute private production env-file path under the deployment directory |

`AUTO_APPLY_MIGRATIONS` and initial counterpart discovery variables no longer control
production deployment. Use the explicit phase, SHAs, base, digest and confirmations
documented in the V8 runbook. Publication may still maintain discovery channels.

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

### Public routing probe contract and false failures

The check lives in `scripts/production_release.py` (`routing` and `check_url`),
called after container health and migration validation. Its public base URL is
`https://ai-policy.tewendelabs.com`.

| Layer | Request | Required result | Timeout |
| --- | --- | --- | --- |
| Internal frontend | `wget --spider http://127.0.0.1:8080/healthz` inside the frontend | Exit zero | 45 s command timeout |
| Internal API proxy | `wget -S -O /dev/null http://127.0.0.1:8080/api/auth/me` inside the frontend | HTTP 401 without credentials | 45 s command timeout |
| Public frontend health | `GET /healthz` over HTTPS | Exactly 200 | 20 s socket timeout |
| Public application shell | `GET /` over HTTPS | Exactly 200 | 20 s socket timeout |
| Public API protection | `GET /api/auth/me` over HTTPS | Exactly 401 without credentials | 20 s socket timeout |

The internal `--spider` request uses wget's existence-check mode; it is separate
from the explicit public GET requests. Public probes run sequentially, once each,
and stop at the first failure. TLS certificate and hostname verification use
Python's defaults. HTTP redirects, including login redirects and HTTPS redirects,
are rejected. Force SSL does not require following redirects because these probes
already start at HTTPS. Angular's client-side redirect from `/` to `/overview`
does not produce an HTTP redirect for the probe. No JavaScript is executed.

Before routing, Compose waits up to 90 s for PostgreSQL, 360 s for the backend and
120 s for the frontend (command limits: 120, 390 and 150 s). The remote activation
command has a 2700 s timeout; the workflow job has a 75 minute limit. Public
routing failures are not retried by the release preparation loop, which retries
only `DEPLOYMENT_BASE_CHANGED_RETRY`.
Internal container health is checked independently: PostgreSQL uses `pg_isready`,
the backend probes `http://127.0.0.1:8080/actuator/health`, and the inspected
frontend image probes `http://127.0.0.1:8080/healthz`. A healthy container or a
completed investigation does not establish public edge reachability.

Anonymous public GET comparisons on 2026-10-30 reproduced a rejection based on
the request's user agent. With curl and only the user agent changed,
`Python-urllib/3.12` received 403 on all three public endpoints, whereas
`AI-Policy-Investigator-Deployment/1.0` received 200, 200 and 401 respectively.
Certificate verification succeeded and no redirects were returned. Response
headers identified Cloudflare. Repeating the `/healthz` comparison reproduced
403 versus 200. This proves that an accessible application can fail the original
probe; it does not establish the exact Cloudflare rule or the response observed
by the historical VPS run. Direct Python verification from the local machine
was blocked by its missing trusted issuer; TLS verification was not disabled.

The minimal correction explicitly identifies the deployment probe with that
user agent. It sends no credentials or cookies, does not impersonate a browser,
and preserves the exact status contract, redirect rejection and TLS verification.
A remaining rejection is still a failure, now reported with a bounded route label,
method and expected/received status, for example
`PUBLIC_ROUTING_STATUS_FAILED_GET_HEALTHZ_EXPECTED_200_GOT_403`.
Only these safe codes pass through the existing SSH diagnostic filter; arbitrary
response bodies, redirect locations and request URLs are not logged. Container,
SSH host-key and exact-image validation are unchanged. A failed public check still
prevents updating `validated.json` and `last-successful.json`, even though the
application containers may already be running the attempted release.

### Angular deep links and refresh

Public root health does not validate an Angular route, asset loading or a signed-in
session. Navigation within the running SPA is handled by Angular. A browser refresh
instead requests the deep URL from the server and recreates the JavaScript state.
Angular requires the server to return `index.html` for these routes; see the
[official deployment documentation](https://angular.dev/tools/cli/deployment).

The inspected local frontend configuration (`deploy/default.conf.template` in the
separate frontend checkout) already uses `try_files $uri $uri/ /index.html` and
keeps `/api/` in a separate proxy location. A public anonymous GET to the synthetic
path `/investigations/00000000-0000-0000-0000-000000000000` returned 200 without a
redirect and the same Angular host element, root base URL and application asset
references as `/`. Cloudflare injected different per-request challenge metadata,
so the full response bytes differed. No investigation API or inference was invoked.
This checks HTML fallback only, not rendering or authorization of an investigation.

The local frontend's `src/app/core/auth.ts` stores its token and identity only in
memory. `src/app/app.ts` displays the login component when identity is absent.
Reloading therefore loses the session and in-memory recent items and can show the
login screen on the same deep URL; this is independent of the deployment probe.
No missing SPA fallback was demonstrated, so neither Nginx nor session persistence
was changed. The local frontend checkout is not proof of the exact deployed source.

## Concurrency, release records and recovery

GitHub concurrency and the existing project file lock serialize reviewed deliveries.
A stale approved base is rejected; there is no automatic re-selection or retry.
A changed base or failed activation needs diagnosis and a new explicit approval.

New reviewed releases use releases/r0<RUN_ID>-<RUN_ATTEMPT*10+1>; older release IDs remain
valid for retention/recovery. release.json records source
SHAs, registry/archive hashes, runtime/configuration hashes and migrations extracted
from the selected JAR and the operator's `releaseSafety` record. External attestations
are labeled unverified by automation; SQL identity is not whole-JAR binary identity.
A safe failure.json records failures. last-successful.json changes
only after every health, migration and routing check passes. Monitor disk usage; nothing
is pruned automatically. Retain releases still referenced by container bind mounts.

For exceptional rollback, dispatch **Reviewed V8 production release** on backend
main with operation=rollback, a previously validated rollback_release ID, empty SHA
fields and allow_migrations=false. Retained local archives are reverified. Applied SQL
versions/scripts/checksums must match the target exactly. An incompatible newer schema
blocks rollback; PostgreSQL is never automatically restored, cleaned or rewound.
Identical schema history is necessary but does not prove semantic data compatibility.

Before a migration-bearing release, follow the [V8 runbook](V8_DEPLOYMENT_RUNBOOK.md),
including actual backup/isolated restore proof, writer freeze and explicit disabled-worker
flags. The controller repeats target SQL preflights, compares embedded migrations with
the pinned qualification and verifies the worker phase; it does not create a backup
or independently verify the operator's external evidence.
Review production results in Actions and the restricted release records. A green local
unit/configuration test does not prove hosted token access, SSH reachability, public
routing or successful production deployment.
