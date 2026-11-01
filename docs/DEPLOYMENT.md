# Production operations

For automated publication and delivery, use [Production CI/CD](PRODUCTION_PIPELINE.md).
This guide covers the existing deployment topology, initial account and data recovery.
Commands below are operator procedures; documentation preparation does not execute them.

## Topology and persistent storage

```text
Browser --HTTPS--> Nginx Proxy Manager
                     |
       nginx-proxy-manager_default (existing shared network)
                     |
        ai-policy-investigator-web:8080 (Angular/Nginx)
                     |
       ai-policy-investigator_application (internal)
                     |
        backend:8080 (Spring Boot)
                     |
       ai-policy-investigator_database (internal)
                     |
             postgres:5432

backend/model-init --> project default egress --> Meta / public artifacts
```

Only the frontend joins the existing shared NPM network. Backend/PostgreSQL remain
private. No frontend, backend or PostgreSQL host port is published in production.
The frontend proxies /api to backend.ai-policy-investigator_application:8080, avoiding
collisions with unrelated services on the shared proxy network.

Backend project: ai-policy-investigator. Frontend project: ai-policy-investigator-ui.
Keep those names and the existing persistent volumes:

- ai-policy-investigator_investigator_data: PDFs, versions, vectors, jobs, findings and reviews.
- ai-policy-investigator_embedding_models: pinned model/tokenizer, read-only in Spring Boot.
- ai-policy-investigator_native_cache: public runtime/native dependencies, writable by UID 10001.

The initializer uses the revision/hashes in [model provenance](provenance/embedding-model.json).
The 384 dimensions remain fixed. Cold model/native initialization needs public downloads;
warm restarts reuse verified caches. Real Meta reasoning always needs outbound API access.

Routine CD merges backend compose.yaml, compose.production.yaml and
deploy/simple/compose.images.yaml, and uses deploy/simple/compose.frontend.yaml for the
frontend. It pulls only the CI-selected frontend/backend digests and updates those two
services with --no-deps. PostgreSQL and model-init are left running/untouched. Existing
model assets are required; the initializer is a separate bootstrap/recovery operation.
Never use base-only Compose up against this production deployment.

## Nginx Proxy Manager

Use the existing NPM installation and network; no new proxy service is required.
For the project's Proxy Host:

| Field | Value |
|---|---|
| Domain | ai-policy.tewendelabs.com |
| Scheme | http |
| Forward hostname | ai-policy-investigator-web |
| Forward port | 8080 |
| Custom locations | None; forward the entire origin including /api |
| Cache assets | Off |
| Websockets | Not required; progress uses HTTP polling |
| TLS | Valid certificate and Force SSL after certificate verification |

For this host only, preserve the application's upload/time limits and avoid sensitive
query strings in access logs:

```nginx
client_max_body_size 11m;
proxy_read_timeout 65s;
proxy_send_timeout 65s;
access_log off;
```

Preserve Authorization headers and no-store responses. A separate proxy Basic Auth
scheme may conflict with bearer JWTs. Do not enable request-body/token/debug logging.
The frontend already supplies CSP, nosniff, frame/referrer controls and uncached API/PDF
responses. Verify HTTPS, login/upload/evidence and Swagger denial after actual deployment.

## Initial administrator

Follow [First production login](FIRST_LOGIN.md) for the minimal tools package,
Mac-to-VPS transfer commands, mandatory read-only migration/empty-store checks and
hidden interactive password entry. Install the tools outside the validated release.
The automatic CI runtime bundle does not include these one-time tools.

There is no public signup, production demo password or startup seed. The operator
helper creates one organization, department and active ADMIN only in an empty identity
store. It refuses a second initialization and preserves the existing authentication,
BCrypt and department authorization. Do not use the local demo seed in production.

## Operator commands for an existing release

Use the actual validated release directory and production env file. These helpers are
for status/exec/stop/start of existing containers, not for creating/upgrading releases:

```sh
: "${RELEASE_DIR:?Absolute validated release directory under the deployment root}"
: "${DEPLOY_ENV_FILE:?Actual protected production env-file path}"
backend_compose() {
  docker compose --project-directory "$RELEASE_DIR/configuration" --env-file "$DEPLOY_ENV_FILE" \
    -p ai-policy-investigator -f "$RELEASE_DIR/configuration/compose.yaml" \
    -f "$RELEASE_DIR/configuration/compose.production.yaml" --profile app "$@"
}
frontend_compose() {
  docker compose --project-directory "$RELEASE_DIR/configuration/frontend" --env-file /dev/null \
    -p ai-policy-investigator-ui -f "$RELEASE_DIR/configuration/frontend/compose.yaml" \
    -f "$RELEASE_DIR/configuration/deploy/frontend/compose.production.yaml" "$@"
}
backend_compose ps --all
frontend_compose ps --all
```

Use the CI deployment/rollback workflow for image changes; do not run build, pull or
base-only up through these helpers. Inspect logs privately: never publish resolved
Compose, Docker environments, credentials or document text. An unhealthy status alone
does not cause Docker's restart policy to restart a container.

## PostgreSQL backup

For a V7 backup and fresh, network-isolated restore rehearsal without changing
production application containers, use [V7 backup and isolated restore](V7_BACKUP_RESTORE.md).
It shares one exported snapshot between the dump and source checks; a later
migration still requires its separately approved writer freeze and current backup.

Keep backups encrypted/access-controlled outside repositories/build contexts. They
contain protected documents and password hashes. pg_dump provides a consistent snapshot;
for a migration rollback point, stop only this application's frontend/backend first to
avoid in-flight writes/provider jobs. Leave PostgreSQL and unrelated services running.

```sh
: "${INVESTIGATOR_BACKUP_DIR:?Private backup directory outside repositories}"
umask 077
mkdir -p "$INVESTIGATOR_BACKUP_DIR"
chmod 700 "$INVESTIGATOR_BACKUP_DIR"
frontend_compose stop frontend
backend_compose stop backend
backup_file="$INVESTIGATOR_BACKUP_DIR/investigator-$(date -u +%Y%m%dT%H%M%SZ).dump"
if backend_compose exec -T postgres pg_dump -U postgres -d investigator --format=custom > "$backup_file.partial"; then
  mv "$backup_file.partial" "$backup_file"
else
  echo 'Backup failed; do not continue the release.' >&2
  exit 1
fi
sha256sum "$backup_file" > "$backup_file.sha256"
backend_compose exec -T postgres pg_restore --list < "$backup_file" > "$backup_file.list"
```

The list is private metadata too. Store matching role credentials securely and separately;
pg_dump does not include cluster roles. The initializer creates investigator_owner,
investigator_app and investigator_runtime; retain their privileges and forced RLS.
If merely resuming the same release after backup, start the existing backend/frontend
containers with backend_compose start backend and frontend_compose start frontend.

## Restore and rollback

An application rollback uses retained validated images and leaves PostgreSQL untouched;
see [the CI/CD rollback procedure](PRODUCTION_PIPELINE.md). A newer incompatible migration
blocks it. Restoration is a separate destructive operator decision, never an automatic
pipeline fallback. Verify a current backup, target database, matching roles/extensions,
PostgreSQL 16/pgvector version and compatible application release before proceeding.
Rehearse in an isolated environment first. Keep application containers stopped.

For an explicitly approved restore of this dedicated existing project database:

```sh
: "${RESTORE_DUMP:?Verified project dump absolute path}"
: "${CONFIRM_INVESTIGATOR_RESTORE:?Explicit reviewed restore target}"
test "$CONFIRM_INVESTIGATOR_RESTORE" = 'ai-policy-investigator/investigator' || exit 1
sha256sum --check "$RESTORE_DUMP.sha256" || exit 1
frontend_compose stop frontend
backend_compose stop backend
backend_compose exec -T postgres pg_restore -U postgres -d investigator \
  --clean --if-exists --exit-on-error --single-transaction < "$RESTORE_DUMP"
```

Do not strip ownership/ACL/RLS or drop volumes. A failed restore must not start the app.
A fresh cluster additionally needs the unchanged role/extension initialization before
restoration; do not start Spring Boot migrations/workers against it prematurely.
Deploy only the matching application release after successful restoration, then verify
login, access isolation, PDF hashes, versions, findings and append-only review history.
Restoration can lose writes after the backup and cannot rewind already transmitted Meta
requests. No restore rehearsal or live VPS recovery is claimed by this documentation.
