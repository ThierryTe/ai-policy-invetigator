# Interactive judge access — phase 1

Judge access uses the existing roles and RLS boundary. There is no `DEMO_TESTER` role,
public signup, authentication bypass, or general administration API. This phase changes
only the backend and operator tooling; the frontend is unchanged.

## Access model

Each judge receives a new individual account and a new private test department in an
organization containing synthetic demonstration data only. The account has exactly one
`ADMIN` membership, in that test department. It can upload policies and procedures,
append immutable versions, explicitly allow external processing, and investigate its own
policy changes with Meta Muse. No processing consent is granted automatically.

The operator selects one existing completed investigation and provides the exact set of
policy IDs used by its baseline, replacement and procedures. Provisioning grants only
`READ` on those policies to the new test department. The judge can open that existing
investigation, PDF sources, evidence, extractions and graph without making a Meta call.
It cannot append versions, change processing consent or review findings on that shared
scenario. Save and provide the existing `/investigations/<investigation-id>` link.

Sharing is at **policy level**, including all its versions and other investigations whose
entire scope is readable. RLS does not restrict reads to one investigation or one version.
Keep these policies exclusively synthetic, including future versions. Accounts in the
same department share its documents; provisioning therefore never reuses a department.
Demo writes are additionally restricted to the profile's test department, even if an
extra membership or cross-department WRITE grant is accidentally added later.

The software cannot establish that a PDF is synthetic. The operator must inspect the
allowlist and explicitly attest `synthetic_data_confirmed: true`. Do not select an
organization containing real customer or confidential documents.

## Persistent admission limits

Migration V7 adds private control-plane tables `demo_access` and `demo_meta_budget`.
The application database role cannot read, modify or truncate them, or call the private
quota helper directly. Existing content RLS remains enabled and forced. Startup rejects
unsafe runtime access to the new tables/helper as well as the existing RLS violations.

All limits are explicit operator inputs, with no daily reset:

| Limit | Charged when | Scope |
| --- | --- | --- |
| `max_imports` | A new ingestion job is admitted, including replacement versions | Account lifetime |
| `max_bytes` | Original PDF bytes for each admitted import | Account lifetime |
| `max_investigations` | A new investigation job is admitted | Account lifetime |
| `max_pending` | Combined ingestion and investigation jobs in QUEUED or RUNNING state | Account, current jobs |
| `max_meta_attempts` | Before every provider attempt, including retries | Account lifetime |
| `shared_meta_attempts` | Before every demo provider attempt | One collective pool for the whole database |

Admission locks the account quota row. Meta reservation locks the account row, then the
collective pool, then the job. Counters and job admission commit atomically. This works
across backend instances, not only threads in one process. Completing or failing a job
frees its pending slot. Failed work does not refund lifetime imports, bytes or investigations.

Existing HTTP idempotency keys are checked before admission. An identical replay returns
the original resource without charging again; a conflicting payload is rejected. A new
key is new work. Replaying after access expiration is denied. Direct duplicate calls to
the SQL admission functions fail and roll back rather than enqueue or charge twice.

Meta reservations commit before network I/O. Retries, timeouts and crashes after reservation
consume attempts conservatively; they are never refunded. A stale lease cannot consume an
attempt. Exhausting either account or collective attempts stops the next transport call.
The collective pool starts at zero: new demo profiles cannot call Meta until explicitly
configured. First successful provisioning may initialize it; subsequent provisioning must
match its limit and never resets or raises it.

These are **attempt caps, not currency or exact token budgets**. Existing per-investigation
limits remain: 20 reserved calls, the 40,000 recorded-token admission threshold, bounded
retries, output and response sizes, timeouts and leases. The recorded-token threshold can
be exceeded by the final response and cannot measure every failed provider call. Ordinary
accounts without a demo profile retain their existing behavior and do not use the demo pool.

## Expiration

`expires_at` must be an explicit future timestamp with a timezone. Expired profiles are
rejected at login, when an existing JWT is checked, in scoped backend operations, and by
the SQL content authorization functions. Admission/reservation checks wall-clock expiry
again after acquiring locks. Workers cannot obtain a new call reservation or persist
content checkpoints under an expired account. Database authorization and remote network
I/O cannot be atomic: expiration immediately after a successful reservation cannot recall
that already authorized attempt, whether it is about to be sent or is in flight. Its
attempt remains charged. Previously downloaded files cannot be revoked.

Expiration does not delete files, results or accounts. This phase adds no automatic cleanup
or retention scheduler. Operators remain responsible for later retention and revocation.
Do not delete a demo profile to revoke it: removing the profile would remove its demo
restrictions. Expire it or deactivate `app_users.active` instead.

## Context and document limits

The entire source scope is checked before a new investigation is admitted and again before
a worker makes its first provider call, including jobs queued before this release:
nonempty sources, at most 20 chunks and 16,000 UTF-16 characters per version, and 20,000
across all versions. Existing worker and provider validations remain in place.

The final serialized assessment also contains generated extraction JSON. Its exact size
cannot be known before extraction; the existing 32,000-character request limit still
applies before sending each request. A later assessment can therefore fail after some
extraction attempts. Source-size admission is not a guarantee that an investigation will
complete or that its semantic findings are correct.

Existing PDF restrictions remain: 10 MiB maximum, at most 100 pages, no encryption,
extractable text on every page, bounded extraction resources, and no built-in OCR.
An accepted PDF is not necessarily small enough for investigation. Use short documents.

## Operator provisioning

`scripts/provision_judge.py` never reads an environment/credential file. By default it
validates a public JSON manifest locally and does not access a database. Use a separate
manifest per judge with exactly these fields; replace placeholders before validation:

```json
{
  "email": "<individual judge email>",
  "department": "<unique test department name>",
  "organization_id": "<existing synthetic organization UUID>",
  "operator_user_id": "<existing owning-department administrator UUID>",
  "investigation_id": "<existing completed investigation UUID>",
  "read_policy_ids": ["<policy UUID>", "<procedure UUID>"],
  "synthetic_data_confirmed": true,
  "expires_at": "<future ISO-8601 timestamp with timezone>",
  "max_imports": 12,
  "max_bytes": 67108864,
  "max_investigations": 3,
  "max_pending": 2,
  "max_meta_attempts": 30,
  "shared_meta_attempts": 200
}
```

Numbers above illustrate a deliberately small test allowance; choose them explicitly for
the event and available provider budget. They are not application defaults. List all
distinct policies/procedures contributing to the selected investigation, with no extras
or duplicates. The operator identity must currently be an ADMIN in each owning department.
The SQL validates through that identity under RLS and requires a persisted COMPLETED job
and a complete assessment.

```sh
python3 -B scripts/provision_judge.py --manifest /path/to/judge-manifest.json
```

## One-time operator package for the existing Compose database

Use the existing running `postgres` container in Compose project `ai-policy-investigator`.
Python runs on the operator host; `psql` runs inside that container through `docker exec`.
No Python installation inside the database container, new container, image build, published
PostgreSQL port, socket mount on the host, or deployment-pipeline change is required.
The current release and its manifests remain untouched.

The operator needs Python 3.9+, the Docker CLI and existing authorized access to the local
Docker daemon. Use the existing deployment account or its already approved sudo access;
the tool does not install software or grant Docker permissions. The selected container
must be running, have the exact Compose project/service labels, use only the private
`ai-policy-investigator_database` network, mount the existing
`ai-policy-investigator_investigator_data` volume, and publish no ports.

### Prepare and transfer public tools

From the reviewed backend source, build a new archive at a new output path:

```sh
python3 -B scripts/package_judge_tools.py --output /tmp/judge-operator-tools.tar.gz
(cd /tmp && shasum -a 256 -c judge-operator-tools.tar.gz.sha256)
```

The allowlist contains exactly five regular public files:

```text
scripts/provision_judge.py
scripts/provision_judge.sql
docs/JUDGE_DEMO.md
deploy/postgres/judge-migrations.json
FILES.sha256
```

The migration inventory is generated from the reviewed source; no migration SQL,
Compose files, credentials, application binaries, private manifest or environment files
are packaged. `FILES.sha256` covers the other four files. The packager refuses existing
output files and symlinked sources. Use the same reviewed source as the deployed backend.

Transfer this package separately using the existing verified SSH destination. The
following commands are operator instructions, not actions performed during preparation.
Do not disable host-key checking or use the public website hostname as an assumed SSH
endpoint. Enter the actual approved SSH alias or `user@host`:

```sh
printf 'Verified VPS SSH destination: '
IFS= read -r VPS_SSH
: "${VPS_SSH:?SSH destination is required}"
scp /tmp/judge-operator-tools.tar.gz /tmp/judge-operator-tools.tar.gz.sha256 "${VPS_SSH}:"
ssh -t "$VPS_SSH"
```

### Install outside the validated release and select the database

Run in the authorized interactive operator session. Choose a fresh tools directory;
stop if that path already exists. Compare the archive checksum with the value verified
on the source machine as well as checking the transferred checksum file.

```sh
set -eu
cd "$HOME"
sha256sum -c judge-operator-tools.tar.gz.sha256
sudo -v
JUDGE_TOOLS=/opt/ai-policy-investigator/operator-tools/judge-access-v1
sudo test ! -e "$JUDGE_TOOLS"
sudo install -d -m 700 "$JUDGE_TOOLS"
sudo tar --extract --gzip --file judge-operator-tools.tar.gz --directory "$JUDGE_TOOLS" --no-same-owner
sudo sh -c 'cd "$1" && sha256sum -c FILES.sha256' sh "$JUDGE_TOOLS"
judge_postgres_id="$(sudo docker --host unix:///var/run/docker.sock ps --no-trunc \
  --filter label=com.docker.compose.project=ai-policy-investigator \
  --filter label=com.docker.compose.service=postgres --format '{{.ID}}')"
```

The selection must return exactly one full container ID. The tool rejects empty,
multiple, short or named selections. It validates only selected non-secret container
metadata; it never dumps the container environment or resolves Compose configuration.
The endpoint is pinned to `/var/run/docker.sock`, and each Docker invocation uses an
empty temporary Docker configuration directory. Remote contexts and inherited credential
variables are not used. Do not run deployment, restart, network or volume commands here.

Prepare the public judge manifest described above using actual IDs and limits, without
a password field. The path below is a proposed operator manifest path. Install a reviewed
manifest from its actual location, then validate it offline:

```sh
sudo install -m 600 /path/to/reviewed-judge-internal.json "$JUDGE_TOOLS/judge-internal.json"
sudo python3 -B "$JUDGE_TOOLS/scripts/provision_judge.py" \
  --manifest "$JUDGE_TOOLS/judge-internal.json"
```

Without `--apply` or `--check-only`, validation remains entirely local: no Docker,
database access or password prompt, even if a container option is supplied.

### Mandatory read-only authentication and migration check

```sh
sudo python3 -B "$JUDGE_TOOLS/scripts/provision_judge.py" \
  --manifest "$JUDGE_TOOLS/judge-internal.json" \
  --postgres-container "$judge_postgres_id" --check-only
```

Required output for this version:

```text
Judge preflight passed: local owner authentication; migrations=7. No account created.
```

The tool invokes `psql -X -w` as **database role `investigator_owner` directly**, through
`/var/run/postgresql` inside the existing container. The exec process uses the existing
OS user `postgres`; that is not a database-superuser login. `env -i` clears inherited
container credentials before `psql` starts, and `PGPASSFILE=/dev/null` and
`PGSERVICEFILE=/dev/null` disable credential/service files. No password is supplied for
this connection. The host does not need a PostgreSQL socket or client installation.

The read-only SQL confirms the database, direct session/current role, Unix socket,
non-superuser/non-BYPASSRLS owner privileges, required table ownership, forced content
RLS, extensions and exact successful migration inventory/checksums. It does not read
password hashes, tokens or document contents. It does not prove that the manifest's
selected documents are synthetic: the operator attestation is still required, and the
existing provisioning SQL checks the scenario, owning administrators and exact allowlist.

**Stop if owner authentication fails.** `-w` prevents a password prompt. The tool never
tries database role `postgres`, `SET ROLE`, a password file, TCP, or a different container;
it does not modify `pg_hba.conf`, roles or authentication rules. An existing peer mapping
or suitably restricted existing local authentication must already permit this owner
connection. Do not weaken authentication to make this procedure pass. If the deployed
container requires the owner's password, this procedure is blocked and needs a separately
reviewed authentication design. Local tests cannot establish the VPS's actual rules.

### Explicit creation after a successful check

Only when account creation is authorized, from the same interactive terminal:

```sh
sudo python3 -B "$JUDGE_TOOLS/scripts/provision_judge.py" \
  --manifest "$JUDGE_TOOLS/judge-internal.json" \
  --postgres-container "$judge_postgres_id" --apply
```

The preflight runs before password entry and again after hidden password confirmation,
before the provisioning SQL is submitted. A changed migration inventory, unsafe owner,
replaced container or authentication failure stops execution. In container mode the
database and role are fixed; `--database` and `--db-user` overrides are refused.

The new judge password travels only in process memory and COPY data over exec stdin.
The exec session has no TTY; the hidden password prompt stays on the host terminal.
No password is placed in command-line arguments, child environment variables, an
operator payload file, or terminal output. The SQL uses an ON COMMIT DROP temporary
input table and retains only the BCrypt hash in the account table. Database and Docker
error output is captured and replaced by fixed diagnostic codes. No account-creation
or live Meta call is part of `--check-only`.

The existing SQL transaction is unchanged: it refuses existing identities/departments,
incomplete scenarios, mismatched organizations, an inexact allowlist, invalid limits or
a changed collective budget. It never rotates a password, resets counters or changes
the scenario. Session lock and statement timeouts bound waits. If the CLI is interrupted
or loses its connection after submission, the outcome may be uncertain: verify the
account/profile by its email with authorized read-only queries before deciding what to
do next. There is no automatic retry; repeating an existing email is refused.

The original local-socket mode remains available for a separately qualified local
PostgreSQL environment, with the same owner/migration preflight. It accepts
`--socket-directory`, `--database` and `--db-user` instead of `--postgres-container`.
Neither mode reads or changes the production environment file. This package is not
included in the public application image or the automatic deployment runtime bundle.

## Judge workflow and phase-1 limitations

1. Sign in and open the supplied preloaded investigation link.
2. Upload a short policy V1, its direct successor V2, and at least one procedure into
   your test department. Wait for indexing.
3. Explicitly allow external processing on each document. Selected source text will be
   sent to Meta. Upload only material you are authorized to share with that service.
4. Start an investigation with an analysis date on or after every selected effective date.
5. Save its URL. The current frontend's recent list is memory-only and clears on sign-out.

The frontend is unchanged: it does not display remaining demo quotas or a pinned scenario
link, may show a write button for a READ-only shared document, and uses existing generic
messages for some backend errors. Server authorization remains authoritative. Quota
admission returns HTTP 429 with a fixed `DEMO_*_LIMIT` code; asynchronous Meta exhaustion
appears in persisted job progress. Expired JWT access returns HTTP 401.

This phase does not add general authenticated-request rate limiting, per-IP upload
bandwidth limits, a complete OS sandbox for PDF parsing, or automatic data cleanup.
The limits bound admitted work and demo provider attempts; they are not a full DDoS
defense. Existing login throttling remains unchanged. Keep judge credentials individual
and private, and bound the access window.

## Local verification

PostgreSQL tests use disposable pgvector containers, generated test credentials and a
mocked Meta transport. They exercise concurrent import/byte/investigation/pending
admission, account and collective attempt races, rollback, idempotence, expiry before
and during processing, blocked-lock expiry, source-context preflight, targeted READ,
private write isolation, and unsafe provisioning refusal. No live Meta request or
deployment is required.

```sh
SPRINGDOTENV_ENABLED=false mvn -B -o -Pdatabase-tests -Dtest=SecurityDatabaseTest test
python3 -B -m unittest discover -s scripts/tests -p test_provision_judge.py
python3 -B -m unittest discover -s scripts/tests -p test_package_judge_tools.py
```

The operator transport/package tests simulate Docker and PostgreSQL replies. They verify
local endpoint pinning, restricted container inspection, unpublished ports, direct owner
authentication checks, refusal without a password fallback, rechecks after hidden password
entry, migration drift, private diagnostic suppression, offline validation, and the package
allowlist. They do not create accounts or establish the deployed VPS's authentication
configuration. A successful operational `--check-only` is required there before `--apply`.
