# Phase 6A — Docker security audit and deployment preparation

Historical Phase 6A report. The confirmed NPM topology and production commands in
[Phase 6B](PHASE6B.md) supersede the host-port/proxy instructions below. The frontend
access-log patch described here is now present in the frontend checkout.

Inspected October 28, 2026. Both working copies are on `develop`. No Git command,
reference-repository modification, new Meta inference or VPS deployment was performed.

## Confirmed findings and disposition

| Severity | Finding and evidence | Disposition / affected files |
|---|---|---|
| Medium | PostgreSQL and Spring Boot had restart policy `no` in both Compose and running containers. | Added `unless-stopped` to these services in backend `compose.yaml`. One-shot `model-init` remains `no`. |
| Medium | Frontend could reach PostgreSQL on the shared network. A separate bridge hides its DNS name, but the published database port also permitted connection by private IP on this Docker runtime. | PostgreSQL now joins only the project-managed `database` bridge; Spring Boot joins it and the unchanged default network. `compose.production.yaml` removes PostgreSQL host publication. Base Compose retains loopback access for local host Java/tools. |
| Medium | A synthetic SPA search query appeared verbatim in Nginx's default access log; `/api/` log suppression did not cover SPA routes. | Prepared `deployment/phase6a-frontend.patch` to disable server-level request access logging. Verified a temporary image; **the frontend working copy remains unchanged because it is outside this session's writable workspace**. Apply before production build. |
| Medium, operational limitation | Login throttling uses the actual socket peer. All clients through one Nginx container therefore share five attempts/minute; spoofed `X-Forwarded-For` did not bypass the limit. | Preserved existing authentication. Actual trusted HTTPS proxy topology is required before any client-IP trust change. Allow the window to expire between demo authentication runs. |

The new database network is managed by this Compose project; it does not assume a
VPS proxy network name. It is an ordinary separate bridge, not an outbound air gap.
Testing `internal: true` broke the existing host-loopback database workflow on this
runtime, so that setting was not retained. Production removes host publication instead.
Changing network definitions on existing containers once lost Docker DNS aliases;
recreating the affected containers restored them without deleting any volume. The
production commands below therefore explicitly recreate containers during updates.

## Existing controls verified or reviewed

- Backend: multi-stage Java 21 build; JRE-only runtime; UID/GID `10001:10001`,
  read-only root filesystem and read-only `/models`. `/runtime` is writable for
  cached native libraries. Executable temporary space is required by JNI/PDF parsing.
- Frontend: production Angular static build in a Node stage; unprivileged Nginx
  UID `101` on port 8080. Runtime has no Node/npm/build toolchain. Its filesystem
  remains writable for the existing Nginx configuration-template startup mechanism.
- Docker-reported image sizes: backend approximately 332 MB, frontend 25.7 MB,
  initializer 45.9 MB, PostgreSQL 156 MB; these are not memory requirements. Build
  stages and persisted native/model caches are separate. Tested architecture: amd64.
- PostgreSQL 16/pgvector data remains in the same named volume. No schema, migration,
  credentials or initializer SQL changed. The PostgreSQL entrypoint prepares storage
  as root and runs the server as its postgres account; do not force backend UID on it.
- Both `.dockerignore` files use allowlists. Actual scratch build-context exports
  excluded dotenv/private fixtures/Git/dependencies/generated output. Both current
  Git indexes had no sensitive dotenv, private-fixture or key/keystore paths tracked.
  Known local credentials did not occur in candidate sources, application resources,
  Docker contexts, image environment/history or inspected backend/database logs.
  These targeted checks are not an audit of all Git history or all unknown secrets.
- MODEL_API_KEY, JWT_SECRET and database credentials are supplied at runtime, never
  build arguments or image-layer secret values. Docker administrators can inspect
  runtime environment variables; protect Docker access and the private environment file.
- Browser requests use relative `/api/` URLs. Nginx proxies to Spring Boot over the
  existing Docker network. JWTs stay in Angular memory; no authentication cookie,
  localStorage or sessionStorage token was introduced. Cross-origin access is not enabled.
- Nginx enforces no-store caching, CSP, nosniff, frame denial, referrer and permissions
  headers. PDFs are fetched with authorization before blob viewing. Local checks cover
  these controls; public HTTPS/HSTS and outer proxy access/error logs are owner-managed.
- Production documentation is blocked in Nginx and denied by backend security even
  to authenticated users. Only health is exposed by Actuator, without component details.
- Long-running containers have healthchecks and restart policies. Compose startup
  waits for PostgreSQL health and successful model initialization before Spring Boot.
  Restart policies restart exited processes; **unhealthy alone does not restart them**.
- Existing ONNX revision, exact artifact hashes and 384 dimensions are preserved.
  The one-shot initializer runs as root only to prepare named-volume ownership.
  Models remain read-only in Spring Boot. Offline initializer verification reused both
  cached files; an offline JVM produced two real 384-dimensional vectors with cached
  native dependencies. Invalid-cache/network-failure paths remain covered by Python tests.

No container uses privileged mode or mounts the Docker socket. No extra infrastructure,
application endpoints, authentication changes or frontend architecture changes were added.
An image vulnerability scan and VPS/ARM verification were not performed.

## Apply the pending frontend fix

The patch contains only the Nginx request-log change. From the **frontend checkout**, use
non-Git patch tooling, with the actual backend checkout path:

```sh
patch --dry-run -p1 < ../aI-policy-investigator-backend/docs/deployment/phase6a-frontend.patch
patch -p1 < ../aI-policy-investigator-backend/docs/deployment/phase6a-frontend.patch
```

Review the patch first. If checkout paths differ, replace the path. If already applied,
the dry run will report that; do not apply it twice. Rebuild the frontend after applying.
The running original frontend was not replaced by the temporary verification container.

## Production environment

Use a private environment file **outside both checkouts**, owner-readable only
(`chmod 600`), or inject real process variables. Process variables take precedence.
Never paste values into a command, Dockerfile, tracked Compose file, issue or screenshot.
Do not print resolved `docker compose config`; use `config --quiet`.

Required names, without credential values:

| Name | Purpose |
|---|---|
| `POSTGRES_ADMIN_PASSWORD` | Dedicated PostgreSQL bootstrap administrator |
| `OWNER_DB_PASSWORD` | Non-superuser migration owner |
| `APP_DB_PASSWORD` | RLS-constrained runtime database role |
| `JWT_SECRET` | Existing HS256 signing key, at least 32 bytes |
| `MODEL_API_KEY` | Real Meta Model API credential for investigations |

Compose retains the fixed initializer roles `investigator_owner` and `investigator_app`;
keep the default username settings. Existing-volume passwords must match the initialized
roles; editing a file does not rotate database passwords. Changing JWT_SECRET invalidates
existing tokens. An empty Meta key does not prevent unrelated API startup, but blocks
model-dependent work; provide it for the hackathon demonstration.

Optional backend tuning is already listed in `.env.example`: `META_MODEL_ID`
(verified `muse-spark-1.3`), provider timeouts/retries/concurrency/budget, worker flags,
JDBC pool, issuer/audience and upload limits. Compose supplies container DB/model URIs
and the pinned embedding revision; no VPS-host model path or host Java is needed.
Production pins `APP_ENVIRONMENT=production`, `SPRINGDOTENV_ENABLED=false` and local
documentation flags off. Do not include `compose.local.yaml` in VPS commands.

Frontend runtime variables contain **no secrets**: `BACKEND_UPSTREAM` and
`BACKEND_NETWORK` default to the existing backend service/network. Override only with
actual deployed values. Never give the frontend a Meta key, signing key or DB password.

## Owner-run deployment after Phase 6B approval

These commands were tested locally; they have **not** been run on the VPS. Require
modern Docker Compose supporting `!reset` (local tested version 5.1.3). The production
override follows [Docker's documented merge reset syntax](https://docs.docker.com/reference/compose-file/merge/#reset-value).

1. Back up any existing database and confirm restoration procedure. Arrange an authorized
   application account using your operator provisioning process before the public demo.
   There is no public registration API. The local-only demo provisioner is not a
   production startup seed; do not copy the local demonstration database to the VPS.
2. From the backend checkout, set `DEPLOY_ENV_FILE` to the actual private environment
   file's absolute path. Validate, build, start and inspect:

   ```sh
   : "${DEPLOY_ENV_FILE:?Set the absolute path of the private backend environment file}"
   docker compose --env-file "$DEPLOY_ENV_FILE" -f compose.yaml -f compose.production.yaml --profile app config --quiet
   docker compose --env-file "$DEPLOY_ENV_FILE" -f compose.yaml -f compose.production.yaml --profile app build
   docker compose --env-file "$DEPLOY_ENV_FILE" -f compose.yaml -f compose.production.yaml --profile app up -d --force-recreate --wait --wait-timeout 240
   docker compose --env-file "$DEPLOY_ENV_FILE" -f compose.yaml -f compose.production.yaml --profile app ps --all
   curl --fail http://127.0.0.1:18080/actuator/health
   ```

   Allow initial public model/native downloads and image builds to finish. `model-init`
   exits 0; it is not a long-running service. PostgreSQL has **no published host port**
   with this override. The API is available only on host loopback port 18080 and the
   Docker service network. Never use `down --volumes` against persisted data.
3. From the frontend checkout, after applying its pending patch:

   ```sh
   docker compose config --quiet
   docker compose build frontend
   docker compose up -d --wait --wait-timeout 120
   curl --fail http://127.0.0.1:18081/healthz
   ```

   Start the backend first: the frontend joins its already-created default network.
   If the backend project name has been customized, set BACKEND_NETWORK to the actual
   network before these commands. This repository's default remains unchanged.
4. Preserve the existing HTTPS reverse proxy. A host proxy should send the **whole
   origin** to `127.0.0.1:18081`; Nginx then serves Angular and forwards `/api/`.
   A containerized proxy needs the owner's actual shared network and frontend service
   address; its own `127.0.0.1` does not refer to the host/frontend container. Do not
   attach PostgreSQL to a proxy network. Do not expose 5432 or 18080 publicly.
   No domain, certificate, proxy service name or VPS network is assumed here.
5. Ensure the existing proxy accepts at least 11 MB requests and has suitable API
   timeouts; durable investigations use polling. Restrict/redact outer proxy logs so
   search strings, credentials and bearer headers are not recorded. Retain HTTPS and
   appropriate HSTS at the existing TLS terminator. Verify public docs remain blocked.
6. Sign in, upload synthetic PDFs, run the real approved investigation and verify source
   PDFs/citations and human review using [the existing demo procedure](DEMO.md).
   Do this with the VPS-authorized account, not by enabling a production auth bypass.

For subsequent ordinary starts, use the same production file arguments with
`up -d --wait --wait-timeout 240`; verified caches are reused. Initial deployment needs
outbound image/artifact access; real Meta investigations always require outbound API
access. A cold native cache is not an offline deployment.

Base local workflow remains `docker compose --profile app up -d --wait` with `.env`;
PostgreSQL remains on `127.0.0.1:5546`. The explicit local documentation override remains
available. Stop local production verification and reapply base Compose before using
host Java against port 5546. No separate Spring profile/property file was introduced.

## Verification and outstanding prerequisites

Actual commands, results, image identifiers and safe runtime evidence are recorded in
[phase6a-results.json](verification/phase6a-results.json). All original phase evidence
is preserved. Verification used local Docker Desktop Linux amd64, synthetic data,
real persisted Muse results and real ONNX inference. It did not create new Meta calls.

Before Phase 6B: apply the pending frontend patch; supply the actual VPS proxy/network
and HTTPS settings; confirm architecture, available RAM/disk, backups and authorized
account provisioning. The shared-peer login limit remains unchanged. No claim is made
about VPS firewall rules, public TLS, outer proxy logging, daemon reboot behavior or
full history/image vulnerability scanning. Explicit approval is required for Phase 6B.
