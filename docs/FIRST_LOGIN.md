# First production login

This procedure prepares and transfers public operator tools from the Mac, then creates
one initial ADMIN from an interactive SSH terminal. It targets the existing Docker
Compose project `ai-policy-investigator`, database `investigator`, under
`/opt/ai-policy-investigator`, using `/opt/ai-policy-investigator/.env.production`.
The automatic CI release does not contain these tools. Install them separately under
`/opt/ai-policy-investigator/operator-tools/initial-admin-v1`; do not change the current
release, release manifests, application images, migrations or environment file.

## Preconditions

- Use the actual SSH destination for this VPS (`user@host` or an existing SSH alias),
  with its host identity already verified. The public website hostname alone does
  not establish the SSH destination. Do not disable SSH host-key checking.
- The operator needs an interactive terminal, Python 3.9 or newer, `sudo` access,
  Docker Engine and Docker Compose 2.24.4 or newer (or a compatible newer version).
  The existing production Compose files use `!reset` and `!override`.
- The existing `postgres` service in project `ai-policy-investigator` must be running
  on the VPS's local `/var/run/docker.sock`. The helper pins this socket, regardless
  of Docker contexts or `DOCKER_HOST`. It only executes commands in that container.
- `/opt/ai-policy-investigator/.env.production` must already exist, be a regular file
  rather than a symlink, and have no group/other permissions (normally mode 600).
  Python checks file metadata; only Compose reads the file for interpolation.
  Never print, source, copy or regenerate its contents for this procedure.
- Applied SQL migrations must exactly match this package: versions V1–V6, filenames,
  checksums and successful status, with no missing, extra, failed or duplicate entries.
  Extensions `pgcrypto` and `vector` must exist. Do not deploy or migrate concurrently.
- Both `app_users` and `organizations` must be empty. If either is nonempty, stop.
  Do not delete existing data or bypass the checks to claim an existing installation.
- Have your chosen login email, organization and owning department ready. Choose a
  unique password in your password manager, 16–72 UTF-8 bytes, without control
  characters. Password entry is hidden and must be confirmed.

## Package contents

`scripts/package_initial_admin.py` creates an allowlisted archive with exactly seven
public regular files and an external archive SHA-256 checksum:

```text
compose.yaml
compose.production.yaml
scripts/provision_initial_admin.py
deploy/postgres/provision-initial-admin.sql
deploy/postgres/initial-admin-migrations.json
docs/FIRST_LOGIN.md
FILES.sha256
```

The two Compose files and provisioning SQL are copied from this backend. The migration
inventory is generated from the unchanged local migrations; their SQL is not packaged.
`FILES.sha256` covers the other six files. There are no credentials, environment files,
application binaries, frontend files, deployment runners or database startup scripts.
Relative build/mount paths in Compose are not used by `exec`; this package cannot be
used to install the application. Never run `up`, `run`, `build`, `pull` or `down` here.

## On the Mac: verify and transfer the prepared package

Run from your normal terminal. The package has already been prepared locally at the
path below; the verification command refuses an accidental transfer of damaged data.
Only the SSH destination must be entered; no production secret is requested.

```sh
set -eu
cd /Users/tewendekima/Desktop/project-tewendelabs/aI-policy-investigator-backend
(
  cd .local/initial-admin
  shasum -a 256 -c ai-policy-initial-admin.tar.gz.sha256
)
printf 'VPS SSH destination (user@host or configured alias): '
IFS= read -r VPS_SSH
: "${VPS_SSH:?SSH destination is required}"
scp .local/initial-admin/ai-policy-initial-admin.tar.gz .local/initial-admin/ai-policy-initial-admin.tar.gz.sha256 "${VPS_SSH}:"
ssh -t "$VPS_SSH"
```

For a future rebuild, use the following command before transfer. It deliberately refuses
an existing archive or checksum; choose a new output directory for a new package,
then adjust the transfer paths. Do not overwrite a package already under review.

```sh
python3 -B scripts/package_initial_admin.py --output .local/initial-admin-rebuilt/ai-policy-initial-admin.tar.gz
```

The SHA-256 displayed on the Mac can also be compared with the VPS checksum. The
archive and checksum are transferred together over the verified SSH connection.

## On the VPS: install the tools separately and check without writing

Run these commands inside the interactive SSH session opened above. `set -e` stops
this sequence on failure. If the target tools directory already exists, stop and review
it instead of overwriting it. No command below edits the deployed release or prints
configuration values.

```sh
set -eu
cd "$HOME"
sha256sum -c ai-policy-initial-admin.tar.gz.sha256
sudo -v
TOOLS=/opt/ai-policy-investigator/operator-tools/initial-admin-v1
sudo test ! -e "$TOOLS"
sudo install -d -m 700 "$TOOLS"
sudo tar --extract --gzip --file ai-policy-initial-admin.tar.gz --directory "$TOOLS" --no-same-owner
sudo sh -c 'cd "$1" && sha256sum -c FILES.sha256' sh "$TOOLS"
sudo python3 -B "$TOOLS/scripts/provision_initial_admin.py" --env-file /opt/ai-policy-investigator/.env.production --check-only
```

Required result before proceeding:

```text
Preflight passed: database=investigator; users=0; organizations=0; migrations=6. No account created.
```

This is a read-only SQL transaction. It reads counts and public migration metadata,
not user records, password hashes or secrets. Errors from Docker/psql are captured
and replaced by fixed codes. A missing table, unavailable database, wrong migration,
nonempty store, missing extension or unsafe environment-file mode causes failure.
The helper does not apply migrations, repair the database or start any service.

## On the VPS: create the initial ADMIN interactively

Proceed only after the previous check succeeds:

```sh
sudo python3 -B /opt/ai-policy-investigator/operator-tools/initial-admin-v1/scripts/provision_initial_admin.py --env-file /opt/ai-policy-investigator/.env.production --interactive
```

The helper rechecks the database before prompting for email, organization and owning
department, then requests the password twice with terminal echo disabled. It refuses
noninteractive input and any fallback to an unmasked password prompt. Finally type
exactly `CREATE INITIAL ADMIN` to confirm creation. No password needs to be entered
in a shell command or exported as an environment variable.

After confirmation it rechecks migrations and emptiness again. The existing SQL then
uses an advisory transaction lock and table locks, rechecks emptiness inside the
transaction, and creates exactly one organization, one department, one active user
and one department-scoped ADMIN membership. A second/concurrent initialization cannot
replace credentials or claim an existing account. No processing consent or document
sharing is created automatically.

Expected success:

```text
Initial administrator provisioned in one owning department. No credentials printed.
```

The Python helper holds the password in memory and sends it as COPY data over stdin
to psql; it is not a command argument, SQL literal, printed value, file or Docker exec
environment variable. Base64 is transport encoding, not encryption. Existing BCrypt
hashing uses a random salt and cost 10. Do not enable terminal recording, request-body
logging, shell tracing or SQL input capture during provisioning.

If the command times out or the connection is interrupted, do not assume rollback.
Rerun `--check-only`: a nonempty store blocks a second initialization. Try the normal
login with the chosen credentials; do not reset data or rerun a demo seed.

## First browser login

Open `https://ai-policy.tewendelabs.com/overview`, enter the chosen email and password,
and select **Sign in**. Login and `/api/auth/me` should return 200, and the department
membership should have role ADMIN. Inspect status codes only; do not export request
bodies, Authorization headers, JWTs or HAR files. A page refresh or expiration after
15 minutes requires a new login because the frontend keeps the JWT only in memory.

The account can import documents and investigate within its department. For a first
functional test, import a synthetic policy V1, its direct successor V2 and one synthetic
procedure; wait for all three to be INDEXED, explicitly allow external processing on
both documents, then select them at `/investigations/new` with a compatible analysis
date. Expect creation 202 followed by COMPLETED. This separately requires working
ingestion/investigation workers, embeddings and Meta access; do not expose any keys.

## Safe failure codes

| Code | Action |
|---|---|
| `PRIVATE_ENV_FILE_REQUIRED` | Verify the stated file exists and is not a symlink; do not print it. |
| `PRIVATE_ENV_FILE_PERMISSIONS_REQUIRED` | Stop until its owner has secured its permissions. |
| `INITIAL_ADMIN_MIGRATIONS_MISMATCH` | Stop; reconcile the package with the deployed schema through the normal release process. |
| `INITIAL_ADMIN_DATABASE_EXTENSIONS_REQUIRED` | Stop; the existing database is missing required initialization. |
| `INITIAL_ADMIN_REQUIRES_EMPTY_IDENTITY_STORE` | Stop; an organization or user already exists. |
| `INITIAL_ADMIN_INTERACTIVE_TERMINAL_REQUIRED` | Use a real interactive SSH terminal; do not pipe the password. |
| `INITIAL_ADMIN_PASSWORD_CONFIRMATION_MISMATCH` / `INITIAL_ADMIN_CANCELLED` | No creation was attempted; restart the interactive command if intended. |
| `INITIAL_ADMIN_FAILED_CHECK_EMPTY_IDENTITY_STORE_AND_MIGRATIONS` | Inspect service availability and database state without printing secrets or raw private diagnostics. |
| `INITIAL_ADMIN_DATABASE_UNAVAILABLE` | Check the local Docker/service availability; check the store before retrying. |

## Local verification

Only local tests with synthetic inputs and disposable PostgreSQL are used. No VPS,
production credentials, release deployment, Java/Angular modification or migration
change is needed.

```sh
python3 -B -m unittest scripts.tests.test_initial_admin scripts.tests.test_initial_admin_operator scripts.tests.test_package_deployment scripts.tests.test_production_compose -v
SPRINGDOTENV_ENABLED=false mvn -B -o -Pdatabase-tests '-Dtest=InitialAdminDatabaseTest,SecurityDatabaseTest#deploymentChecksumsMatchActualFlywayHistory' test
```

The Python tests cover mandatory read-only checks, migration mismatches, existing
identities, secret transport, hidden interactive input, confirmation, repeat checks,
package allowlists/checksums, standalone execution and the real packaged Compose
configuration with synthetic values. Existing Java tests verify SQL rollback, second
initialization refusal, Spring-compatible BCrypt and checksums against actual Flyway
history. These checks do not establish the current production database state.

Verified locally on 29 October 2026: 31 Python tests passed, including an extracted
package running in a real pseudo-terminal with a simulated Docker command (password
echo disabled and second initialization refused); four existing Java/PostgreSQL tests
passed on disposable local Testcontainers databases. Docker access for the Java tests
required execution outside the sandbox. All five shell blocks pass `sh -n`.
No VPS connection, production provisioning or production secret inspection was performed.

