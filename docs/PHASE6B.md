# Phase 6B — Secure VPS configuration, not deployed

Prepared October 28, 2026 using the owner's confirmed infrastructure:
`nginx-proxy-manager` is running on `nginx-proxy-manager_default`, with its existing
80/81/443 publications. This work does not alter that container, network, firewall,
other services or NPM settings. Both repositories remain on `develop`; no Git command
was run. All deployment and recovery commands below are **owner-run after approval**.

## Topology and repository boundaries

```text
Browser -- HTTPS --> existing Nginx Proxy Manager
                          |
       nginx-proxy-manager_default (existing, external, shared)
                          |
             ai-policy-investigator-web:8080
                 Angular / Nginx frontend
                          |
       ai-policy-investigator_application (internal: true)
                          |
       backend.ai-policy-investigator_application:8080
                          |
       ai-policy-investigator_database (internal: true)
                          |
                    postgres:5432

backend + model-init --> ai-policy-investigator_default --> Meta / public artifacts
```

Only the frontend joins the existing shared NPM network. Spring Boot, PostgreSQL
and model-init do not. PostgreSQL joins only the database network; the frontend
never joins it. Spring Boot has outbound access through its separate default
network; this is needed for Meta and a cold native-library cache. Model-init also
uses that network for the existing verified artifact downloads. The application
and database networks are internal Docker networks with no host port publications.
No service has a published host port in production, including the frontend.

- Backend overlay: `compose.production.yaml`, applied after backend `compose.yaml`.
- Frontend overlay: `deploy/frontend/compose.production.yaml` in this backend repo,
  applied after the separate frontend repo's `compose.yaml`. Its build context remains
  the frontend checkout. This keeps the frontend independently buildable and avoids
  copying application code or Git histories between repositories.
- The frontend overlay replaces its inherited networks and removes its loopback port.
  It pins `BACKEND_UPSTREAM=http://backend.ai-policy-investigator_application:8080`: the actual
  Spring Boot service name `backend`, qualified by its private application network.
  NPM routes to unique alias **`ai-policy-investigator-web`**, internal port **8080**.
- Production project names are pinned below. This preserves the existing backend
  `ai-policy-investigator_investigator_data`, `embedding_models` and `native_cache`
  named volumes and makes the cross-project application network name deterministic.
- Base local Compose files remain unchanged. Host Java can still use PostgreSQL on
  loopback 5546 and local Angular can use the API on loopback 18080.

The upstream is network-qualified because unrelated NPM projects may also have a
`backend` alias. Docker supports this lookup form in its
[resolver implementation](https://github.com/moby/moby/blob/master/daemon/libnetwork/sandbox.go).
A read-only health probe verified the equivalent lookup on the existing local network.
The unchanged frontend `proxy_set_header Host $host` preserves the real browser host;
the Docker network name is not sent as the HTTP Host header. The new production
network itself was not created or probed.

The separate application/database networks are declared for Compose to create only
at the later approved deployment. The NPM network is external: Compose must find it
already present and will never create or own it. Unrelated services on that network
have no direct membership, DNS route or published port to this backend/database.
This is configuration verification, not a claim that the VPS firewall has been tested.
Docker-host administrators retain privileged access to containers and volumes.

The frontend's Phase 6A access-log fix is now present in its source. Existing JWT,
authorization, RLS, consent, source verification, Nginx security headers and production
documentation denial are preserved. No CORS change or forwarded-IP trust was added.
The socket-peer login limiter still shares five attempts/minute behind the frontend;
allow the window to expire during repeated demonstrations.

## Production prerequisites and environment

Require modern Docker Compose supporting `!override` (2.24.4+) and `!reset`; locally
verified with Compose 5.1.3. See [Docker merge rules](https://docs.docker.com/reference/compose-file/merge/)
and [network isolation](https://docs.docker.com/reference/compose-file/networks/).
Docker image builds need no host Java/Maven/Node or installed ONNX files. The optional
operator helpers below require Python 3, standard library only. Backups use Linux
`sha256sum`. No new service or secret-management platform is introduced.

Set these **non-secret operator path variables** to the actual absolute paths:
`BACKEND_DIR`, `FRONTEND_DIR`, `DEPLOY_ENV_FILE`, `INVESTIGATOR_BACKUP_DIR`.
Do not use fabricated hostnames or paths from another project. Store the deployment
environment file and backups outside both checkouts; restrict the file to mode 600
and a dedicated AI Policy Investigator backup directory to mode 700. Protect backups using the existing encrypted,
access-controlled backup storage and retention policy; no new backup service is added.

Required deployment variables, without secret values:

| Variable | Use |
|---|---|
| `POSTGRES_ADMIN_PASSWORD` | Dedicated database bootstrap administrator |
| `OWNER_DB_PASSWORD` | Existing `investigator_owner` migration credential |
| `APP_DB_PASSWORD` | Existing `investigator_app` RLS-constrained runtime credential |
| `JWT_SECRET` | Private existing HS256 signing key of at least 32 bytes |
| `MODEL_API_KEY` | Authorized Meta Model API credential |

Use distinct real credentials, not example placeholders. Preserve values matching an
existing database volume. Editing the file does not rotate PostgreSQL passwords;
changing JWT_SECRET ends existing sessions. Real process variables take precedence
over the env file. No secret is passed as a build argument or injected into Angular.

Optional tuning remains in `.env.example`: Meta model/timeouts/retries/concurrency/
budget, worker flags, pool size, JWT issuer/audience and upload limits. Keep the
verified `muse-spark-1.3` model and default role names. Compose pins production mode,
dotenv off, Swagger/OpenAPI off, internal DB/model URIs and the exact embedding revision.
The frontend production overlay pins its upstream and network configuration, so
BACKEND_NETWORK/BACKEND_UPSTREAM overrides are not needed for this deployment.

A real public domain/DNS and certificate choice are still required from the owner.
No public domain, NPM version or certificate has been assumed. Confirm the new alias
is unused by another application before connecting this frontend at deployment time.

## Command setup and validation

Use one shell session after setting the actual path variables:

```sh
: "${BACKEND_DIR:?Set the actual absolute backend checkout path}"
: "${FRONTEND_DIR:?Set the actual absolute frontend checkout path}"
: "${DEPLOY_ENV_FILE:?Set the absolute path to the private production env file}"

backend_compose() {
  docker compose --project-directory "$BACKEND_DIR" --env-file "$DEPLOY_ENV_FILE" \
    -p ai-policy-investigator -f "$BACKEND_DIR/compose.yaml" \
    -f "$BACKEND_DIR/compose.production.yaml" --profile app "$@"
}
frontend_compose() {
  docker compose --project-directory "$FRONTEND_DIR" --env-file /dev/null \
    -p ai-policy-investigator-ui -f "$FRONTEND_DIR/compose.yaml" \
    -f "$BACKEND_DIR/deploy/frontend/compose.production.yaml" "$@"
}

backend_compose config --quiet
frontend_compose config --quiet
python3 "$BACKEND_DIR/scripts/verify_production_compose.py" --frontend-directory "$FRONTEND_DIR"
backend_compose build
frontend_compose build frontend
```

Validation and builds do not start the application or create its networks. The
verifier uses synthetic interpolation values, does not read the private env file
and never contacts Docker Engine. Its safe report checks all network memberships,
zero published ports, frontend env/alias, production flags, initializer gate,
read-only model mount and persistent database volume name. Do not print unrestricted
resolved Compose configuration: it contains runtime secrets.

## Deployment commands — do not execute before approval

These start only AI Policy Investigator's two named projects. They do not restart NPM
or unrelated services. Retain the same project names and production file arguments
for every lifecycle operation.

```sh
backend_compose up -d --force-recreate --wait --wait-timeout 300
backend_compose ps --all
frontend_compose up -d --wait --wait-timeout 120
frontend_compose ps --all
backend_compose exec -T backend wget --quiet --spider http://127.0.0.1:8080/actuator/health
frontend_compose exec -T frontend wget -q -O /dev/null http://127.0.0.1:8080/healthz
```

`model-init` exiting 0 is expected. It preserves the exact pinned MiniLM revision,
SHA-256 checks, 384 dimensions and named volume. Backend model mounts remain read-only;
the separate native cache remains writable by UID/GID 10001. Initial downloads require
outbound access. Subsequent ordinary `backend_compose up -d --wait --wait-timeout 300`
starts reuse valid caches; a cold native cache cannot start offline. Real Meta calls
always require outbound API access. No host model installation is needed.

Both healthchecks must pass before configuring the new NPM host. Production has no
localhost API/database/frontend port to curl from the host; run health probes inside
the containers as above. An unhealthy status alone does not trigger Docker restart.
Do not run base-only Compose lifecycle commands on this production deployment.

## Exact NPM Proxy Host settings — owner applies after approval

Create only a **new Proxy Host** in the existing NPM UI; do not change its container,
Docker networks, global configuration or existing Proxy Hosts. These settings follow
[NPM's Docker-network routing guidance](https://nginxproxymanager.com/advanced-config/#best-practice-use-a-docker-network).

| NPM field | Setting |
|---|---|
| Domain Names | The owner's actual chosen domain; not yet supplied |
| Scheme | `http` |
| Forward Hostname / IP | `ai-policy-investigator-web` |
| Forward Port | `8080` |
| Cache Assets | Off |
| Block Common Exploits | On; verify the upload/login workflow on the installed NPM version |
| Websockets Support | Off; investigations use ordinary HTTP polling |
| Access List | Publicly Accessible at the proxy; application JWT authorization remains enforced |
| Custom Locations | None; the whole origin, including `/api/`, goes through the frontend |
| SSL Certificate | The valid certificate for the chosen domain, or owner-approved new certificate |
| Force SSL | On after the certificate is valid |
| HTTP/2 | On if offered by the installed version |
| HSTS | Enable for this host after HTTPS verification; leave subdomain/preload options off |

For **this Proxy Host only**, Advanced configuration:

```nginx
client_max_body_size 11m;
proxy_read_timeout 65s;
proxy_send_timeout 65s;
# Query strings can contain policy search text. Disable this host's request access log.
access_log off;
```

Leave authentication headers intact. The frontend already forwards bearer tokens to
Spring Boot, disables API caching and provides CSP/nosniff/frame/referrer controls.
A custom proxy Basic Auth scheme can conflict with the same Authorization header;
the documented setup uses existing application JWT login. Do not enable debug or
request-body/header logging. Verify the host-specific generated NPM configuration
and logging behavior after approval; the installed NPM version was not inspected.
Do not add custom global NPM includes or restart existing services for this setup.

After approval, use an ordinary browser on the chosen HTTPS origin to verify login,
synthetic upload, progress, persisted findings, citations/PDFs and review. Confirm
`/v3/api-docs` and `/swagger-ui/index.html` stay inaccessible. From an existing container
on the shared NPM network, verify the unique frontend alias resolves and the actual
private backend/database IPs cannot be reached directly. Do not attach that container
to the private networks merely for testing. No such live VPS probes were run here.

## Secure first application administrator — owner runs after deployment approval

There is no registration API. `scripts/provision_user.sql` and `scripts/setup_demo.py`
are existing local/synthetic tools and are not used for production bootstrap.
The new `scripts/provision_initial_admin.py` is an explicit operator action, not an
application or database startup hook. It requires an empty identity store, migrations
already applied, and the existing dedicated database admin access.

Set your chosen non-secret identity metadata: `INVESTIGATOR_INITIAL_EMAIL`,
`INVESTIGATOR_INITIAL_ORGANIZATION`, `INVESTIGATOR_INITIAL_DEPARTMENT`. Then:

```sh
: "${INVESTIGATOR_INITIAL_EMAIL:?Set your chosen initial login email}"
: "${INVESTIGATOR_INITIAL_ORGANIZATION:?Set the organization name}"
: "${INVESTIGATOR_INITIAL_DEPARTMENT:?Set the owning department name}"
export INVESTIGATOR_INITIAL_EMAIL INVESTIGATOR_INITIAL_ORGANIZATION INVESTIGATOR_INITIAL_DEPARTMENT
export INVESTIGATOR_INITIAL_ADMIN_ENABLED=true
export BACKEND_DIR DEPLOY_ENV_FILE
python3 -c 'import getpass, os, subprocess, sys; env=os.environ.copy(); env["INVESTIGATOR_INITIAL_PASSWORD"]=getpass.getpass("Initial administrator password: "); sys.exit(subprocess.run([sys.executable, os.path.join(env["BACKEND_DIR"], "scripts/provision_initial_admin.py"), "--env-file", env["DEPLOY_ENV_FILE"]], env=env).returncode)'
unset INVESTIGATOR_INITIAL_ADMIN_ENABLED INVESTIGATOR_INITIAL_EMAIL INVESTIGATOR_INITIAL_ORGANIZATION INVESTIGATOR_INITIAL_DEPARTMENT
```

Use a private password of 16–72 UTF-8 bytes without control characters. The password
exists in the short-lived child environment and COPY data, never shell history,
command arguments, SQL literals, Docker/container env, logs or committed files.
The wrapper captures private database diagnostics and returns fixed safe errors.
The transaction creates one organization, one department and one active ADMIN using
the existing BCrypt mechanism. A repeated attempt **refuses** rather than rotating
credentials, claiming an existing account or modifying memberships. No consent/grant
or JWT/database-role changes are made. The bootstrap flag is not sent to NPM or the
application; these INVESTIGATOR-prefixed variables are unrelated to NPM administrator setup.

Sign in with the chosen email/password. ADMIN in the owning department permits upload,
investigation, explicit external-processing consent and human review. For the first
demo, upload both synthetic policy and procedure into this department. Additional
departments/memberships require a deliberate operator decision; no cross-department
grant is created automatically. Never copy the local demo database to production.

## PostgreSQL backup, restore and rollback

All original PDFs, versions, chunks, embeddings, findings, citations, reviews and
jobs are in the dedicated PostgreSQL database. Model/native caches are reproducible
public dependencies; retain their volumes for fast/offline warm restarts. Database
archives contain protected documents and password hashes: keep them private, encrypted
in existing backup storage, outside Git/build contexts, and verify retention/restoration.

### Backup of an existing AI Policy Investigator deployment

For a release rollback point, schedule maintenance and stop only this frontend and
backend; leave PostgreSQL running. This also stops new provider work. An ordinary online
`pg_dump` produces a consistent database snapshot, but does not rewind external Meta
calls; maintenance avoids in-flight application work during a release backup.

```sh
: "${INVESTIGATOR_BACKUP_DIR:?Set the private backup directory outside both repositories}"
umask 077
mkdir -p "$INVESTIGATOR_BACKUP_DIR"
chmod 700 "$INVESTIGATOR_BACKUP_DIR"
frontend_compose stop frontend
backend_compose stop backend
backup_file="$INVESTIGATOR_BACKUP_DIR/investigator-$(date -u +%Y%m%dT%H%M%SZ).dump"
if backend_compose exec -T postgres pg_dump -U postgres -d investigator --format=custom > "$backup_file.partial"; then
  mv "$backup_file.partial" "$backup_file"
else
  echo 'Database backup failed; do not continue the release.' >&2
  exit 1
fi
sha256sum "$backup_file" > "$backup_file.sha256"
backend_compose exec -T postgres pg_restore --list < "$backup_file" > "$backup_file.list"
```

Keep the dump and hash together; the list contains private object metadata and also
stays in restricted storage. `pg_dump` does not include cluster roles. For this project,
the unchanged first-volume initializer creates `investigator_owner`, `investigator_app`
and `investigator_runtime`; retain the matching private production credential file
separately in existing secure storage. Do not export global role password hashes.
The dump preserves ownership, grants, forced RLS, extensions, Flyway history and data.
See [PostgreSQL 16 pg_dump](https://www.postgresql.org/docs/16/app-pgdump.html).

### Restore — destructive, separate explicit operator decision

Restore only your trusted project dump to this dedicated PostgreSQL 16 deployment,
after verifying a backup of the current state and the target identity. Rehearse in
an isolated restore environment before using this against real data. No restore drill
or production data mutation was performed in Phase 6B.

For a fresh volume, start **only PostgreSQL** with `backend_compose up -d --wait postgres`
to initialize matching roles/extensions. Do not start Spring Boot migrations/workers
before restore. For an existing project, first stop its frontend/backend as above.
Keep the same PostgreSQL/pgvector version and private credentials.

```sh
: "${RESTORE_DUMP:?Set the verified project dump absolute path}"
: "${CONFIRM_INVESTIGATOR_RESTORE:?Set only after reviewing the destructive restore target}"
test "$CONFIRM_INVESTIGATOR_RESTORE" = 'ai-policy-investigator/investigator' || exit 1
sha256sum --check "$RESTORE_DUMP.sha256" || exit 1
frontend_compose stop frontend
backend_compose stop backend
backend_compose exec -T postgres pg_restore -U postgres -d investigator \
  --clean --if-exists --exit-on-error --single-transaction < "$RESTORE_DUMP"
```

Check that restore exits 0 **before** starting the matching release. Do not use
`--no-owner`, `--no-acl` or `--enable-row-security`: the restore must preserve authorization
objects and all authorized enterprise data, not a runtime user's filtered subset.
An error aborts the single transaction. Do not drop volumes, reset shared databases
or run `down --volumes`. See [PostgreSQL 16 pg_restore](https://www.postgresql.org/docs/16/app-pgrestore.html).

Then start the matching application release and verify health, JWT login, source PDF
hashes, versions, forced RLS/current grants, findings and append-only reviews. Existing
leases recover under the original worker fencing/deadline rules. Run real Meta calls
only with current explicit document consent. Confirm restored data with an authorized
account rather than trusting archive existence alone.

### Application-image rollback without Git operations

Before the **next release build**, record the current backend/frontend/model-init
image IDs and preserve them with your release record and matching database dump:

```sh
backend_previous=$(docker image inspect --format '{{.Id}}' ai-policy-investigator-backend)
frontend_previous=$(docker image inspect --format '{{.Id}}' ai-policy-investigator-ui-frontend)
initializer_previous=$(docker image inspect --format '{{.Id}}' ai-policy-investigator-model-init)
docker image save -o "$INVESTIGATOR_BACKUP_DIR/release-images.tar" \
  "$backend_previous" "$frontend_previous" "$initializer_previous"
```

These IDs are not credentials. Keep the source/config release record and private env
backup separately. For rollback, stop only this application's frontend/backend, load
the saved image archive if images were removed (`docker image load -i "$INVESTIGATOR_BACKUP_DIR/release-images.tar"`), and create two small **private** overlay
files outside the checkout containing the recorded IDs:

```yaml
# Backend rollback overlay (use the recorded real IDs, not these placeholders).
services:
  backend:
    image: sha256:RECORDED_BACKEND_IMAGE_ID
  model-init:
    image: sha256:RECORDED_INITIALIZER_IMAGE_ID
```

```yaml
# Frontend rollback overlay.
services:
  frontend:
    image: sha256:RECORDED_FRONTEND_IMAGE_ID
```

Set `BACKEND_ROLLBACK_FILE` and `FRONTEND_ROLLBACK_FILE` to those actual private files,
then retain the **current secure topology** and use the old images without rebuilding:

```sh
backend_compose -f "$BACKEND_ROLLBACK_FILE" up -d --no-build --pull never --wait --wait-timeout 300
frontend_compose -f "$FRONTEND_ROLLBACK_FILE" up -d --no-build --pull never --wait --wait-timeout 120
```

This Phase 6B does not change schema/migrations. If a future application release changes
schema, assess backward compatibility first; restore its matching pre-upgrade dump only
with explicit restore approval, accounting for loss of writes after that backup. Never
blindly run an older binary against an incompatible newer schema. Retain the same volume
names and current isolation overlays; do not roll back to public ports or shared backend
networking. No NPM restart, other-service change or Git operation is needed.

## Actual verification and remaining blockers

See [phase6b-results.json](verification/phase6b-results.json) for commands, counts and
scope. Verification includes Compose resolution/negative exposure tests, production
image builds, regression suites and a disposable PostgreSQL bootstrap test. The initial
administrator was not provisioned into any existing local or VPS application database.
No Compose `up`, application deployment, Docker network creation, SSH, NPM setting change,
firewall mutation, new Meta inference or public TLS test was performed.

Before actual deployment approval: supply the real domain/certificate choice, confirm
VPS architecture/resources and that the alias is unused, privately prepare the production
secrets/initial account metadata, and arrange the restore rehearsal/backup location.
Dynamic NPM-to-frontend routing, cross-network rejection, provider egress and the full
HTTPS browser workflow must be checked after approved deployment. Existing Phase 6A
runtime evidence is preserved and is not presented as a new topology runtime test.
