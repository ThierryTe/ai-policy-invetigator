# V7 backup and isolated restore

**Current status: CI/CD automation is prepared locally; no production workflow was
dispatched, backup created, application stopped or migration applied. V8 remains HOLD.**
The preferred path is now the existing
[`deploy-production.yml`](../.github/legacy-workflows/deploy-production.yml) workflow's
`prepare-reviewed` and `deploy-reviewed` operations. See the exact inputs and
approval boundary in [REVIEWED_V8_DEPLOYMENT.md](REVIEWED_V8_DEPLOYMENT.md).
No image rebuild is involved. The SQL files below and the PostgreSQL initializer
remain unchanged; their previously reviewed hashes are enforced by the automation.

`prepare-reviewed` automates the source identity checks below, shared snapshot,
custom dump/checksum, archive listing, isolated PostgreSQL-only restore, complete
source/restore SQL comparison, both isolation checks and final V7 preflight. It
retains private evidence and a stopped rehearsal container/volume on the VPS.
`deploy-reviewed` requires explicit migration approval, stops only this project's
frontend/backend, repeats that entire verification under the writer freeze, then
calls the existing release controller with workers disabled. There is no automatic
dispatch, production restore, rollback, volume removal or cleanup. An online
preparation backup is never reused as the frozen migration cutoff.

The following manual procedure is retained for reference/recovery, not required
alongside a successful automated preparation. Use these commands only after the
corresponding explicit production authorization, on
the actual VPS as its existing Docker deployment account. Stop on any error. Do
not dispatch a release workflow, run Spring Boot/Flyway, or change application
container state. Retain all output privately; do not upload dumps, listings,
fingerprints, environment files or database logs to Actions/Git/public artifacts.
For the image investigation, use only path discovery and the source identity
check below, stopping at that Python block's closing `PY`. The subsequent backup,
SQL and restore steps belong to a separately authorized rehearsal.

This reuses the [existing Compose operator helper and custom-format backup](DEPLOYMENT.md),
the unchanged PostgreSQL initializer, and the existing read-only V7 preflight.
The controller in `scripts/production_release.py` deploys/migrates; it is **not** a
backup command. The general recovery guide's in-place `pg_restore --clean` is
**not** used for this rehearsal. Local migration tests that restore into another
database in the same cluster do not establish production isolation.

Expected topology from the repository (confirm remaining details on the VPS):
`/opt/ai-policy-investigator/releases/<validated-release>/configuration`, backend
project `ai-policy-investigator`, frontend project `ai-policy-investigator-ui`,
database `investigator`, PostgreSQL 16 / `pgvector:0.8.0-pg16`, data volume
`ai-policy-investigator_investigator_data`. Frontend alone joins the shared NPM
network; the backend has public egress for Meta. Work queues are PostgreSQL tables
`ingestion_tasks` and `investigation_jobs`. A rehearsal must not join **any** of
these networks or mount production database/model/native-cache volumes.

Image identity investigation: the operator reports last validated/backend release
`r141093671636-11` and PostgreSQL working directory `r140956670531-21`. Different
working directories are compatible with the controller's PostgreSQL
`up --no-recreate`; a later backend release does not recreate PostgreSQL.
Both reported manifests record the following identities:

| Identity | SHA-256 |
| --- | --- |
| Registry amd64 manifest | `c72df104202409108a1660ecccd2b7ffac6b17e44c31b2636d10e983f410f8eb` |
| Image config | `56a5b20c7a157dbb94149ba3cce70da76f02e1645dec234379709ddaebe607ea` |
| Reported running/store image | `a67e42063a5775bb28cec8a15bcbf851a3e6829ad0dbbd7e32a45c2fece3836f` |

Locally, the public `pgvector/pgvector` manifest and config were fetched by these
digests and their raw-byte hashes verified. All 16 compressed layers and their
uncompressed DiffIDs were verified too. Reconstructing the legacy-load Docker
schema-2 manifest (compact JSON; config descriptor unchanged except its Docker
media type; ordered uncompressed layer digests/sizes and Docker media types)
hashes **exactly** to `a67e4206…`. This establishes the normalization explanation
for these identities, not an incorrect recorded config digest. The repository's
`normalized_archive` drops the OCI index/layout/manifest blobs; containerd then
[reconstructs a Docker manifest on legacy import](https://github.com/containerd/containerd/blob/main/core/images/archive/importer.go).
Retagging or a tag containing a digest supplies no independent content proof.
The controller already compares archive-backed layers/runtime configuration when
store IDs differ; the source check below now does so unconditionally. Actual VPS
content, retained archives, file permissions and mount checks still need verification.

## 1. Secure access and inputs

Use an independently verified, pinned Ed25519 `known_hosts` file and the existing
SSH identity. Do not print keys, use `ssh-keyscan` as a trust decision, forward an
agent, or read secrets from Actions logs. On the operator workstation:

```bash
: "${VPS_HOST:?Approved production host}"
: "${VPS_USERNAME:?Existing deployment account}"
: "${VPS_SSH_KEY_FILE:?Existing private identity file}"
: "${VPS_KNOWN_HOSTS_FILE:?Independently verified pinned known_hosts file}"
ssh -F /dev/null -a -o BatchMode=yes -o IdentitiesOnly=yes \
  -o StrictHostKeyChecking=yes -o GlobalKnownHostsFile=/dev/null \
  -o HostKeyAlgorithms=ssh-ed25519 -o VerifyHostKeyDNS=no -o UpdateHostKeys=no \
  -o "UserKnownHostsFile=$VPS_KNOWN_HOSTS_FILE" -i "$VPS_SSH_KEY_FILE" \
  -p "${VPS_PORT:-22}" -t "$VPS_USERNAME@$VPS_HOST" 'bash --noprofile --norc'
```

On the VPS, provide `EXPECTED_V7_RELEASE` from the approved change record,
`DEPLOY_ENV_FILE=/opt/ai-policy-investigator/.env.production`, `DEMO_INVESTIGATION_ID` identifying
the **existing completed production demonstration**, and `INVESTIGATOR_BACKUP_DIR`
on an approved encrypted/access-controlled filesystem outside repositories and
deployment/build contexts. Do not infer the production demo ID from local demo
fixtures. Transfer the reviewed SQL files separately into a private operator-tools
directory, setting `V8_PREFLIGHT_SQL` and `BACKUP_CHECK_SQL` to their absolute paths.
Set `V8_PREFLIGHT_SHA256` and `BACKUP_CHECK_SHA256` from this reviewed checkout's
trusted SHA-256 values before executing them.
This does not modify a validated release or install another deployment system.

The existing production env file is `/opt/ai-policy-investigator/.env.production`.
The workflow now passes this exact path to Compose; do not discover, move, rewrite
or synthesize another env file. The following optional read-only commands show
only container IDs and selected path
labels, never container environment values:

```bash
set +x
export DOCKER_HOST=unix:///var/run/docker.sock
unset DOCKER_CONTEXT
for service in backend postgres; do
  docker ps -a --filter label=com.docker.compose.project=ai-policy-investigator \
    --filter "label=com.docker.compose.service=$service" --format '{{.ID}}'
done
# For each exact ID above, inspect only these labels; retain paths privately.
: "${CID:?One exact backend or postgres container ID from the listing}"
docker inspect --format '{{index .Config.Labels "com.docker.compose.project.working_dir"}}' "$CID"
docker inspect --format '{{index .Config.Labels "com.docker.compose.project.config_files"}}' "$CID"
docker inspect --format '{{index .Config.Labels "com.docker.compose.project.environment_file"}}' "$CID"
```

Reconcile the backend's env-file label with that fixed path
and the operator's deployment record; the older PostgreSQL container may retain
an older path. A missing environment-file label requires the deployment record,
not guessing `.env`, inspecting `Config.Env`, printing `compose config`, or copying
secrets out of containers. One current file may serve configurations in different
release directories because `--env-file` is explicit. The requirement is compatible
with that topology **if** the actual file exists, is a regular non-symlink file
owned by the deployment account with mode 600, and contains the correct production
inputs. Future transfers additionally require `VPS_ENV_FILE` under
`/opt/ai-policy-investigator`; an external/missing/inaccessible file is a blocker,
not grounds to change permissions, move it, or synthesize another file here.

Set `EXPECTED_PG_CONFIG_DIGEST` and `EXPECTED_PG_MANIFEST_DIGEST` from independently
reviewed release evidence (the full `sha256:` values above for this investigation).
Do **not** populate these expectations from the VPS's `release.json`, Docker tag,
or image inspection. The check below reads the config from the retained archive
without loading images or extracting archive paths; its hash is the independent
trust anchor. If the archive is unavailable, stop and obtain the pinned config
blob from the registry/retained release through a separately reviewed procedure.

Run the following in **terminal B**, keeping this Bash session open through step 5:

```bash
set -Eeuo pipefail
set +x
umask 077
export DOCKER_HOST=unix:///var/run/docker.sock
unset DOCKER_CONTEXT
: "${EXPECTED_V7_RELEASE:?Approved validated production V7 release ID}"
: "${DEPLOY_ENV_FILE:?Actual protected VPS production env file}"
: "${EXPECTED_PG_CONFIG_DIGEST:?Independently reviewed PostgreSQL config digest}"
: "${EXPECTED_PG_MANIFEST_DIGEST:?Independently reviewed PostgreSQL manifest digest}"
export EXPECTED_PG_CONFIG_DIGEST EXPECTED_PG_MANIFEST_DIGEST
: "${DEMO_INVESTIGATION_ID:?Approved existing completed production demo UUID}"
: "${INVESTIGATOR_BACKUP_DIR:?Private external backup directory}"
: "${V8_PREFLIGHT_SQL:?Reviewed qualification_v8_preflight.sql absolute path}"
: "${BACKUP_CHECK_SQL:?Reviewed qualification_v7_backup.sql absolute path}"
: "${V8_PREFLIGHT_SHA256:?Trusted SHA-256 of the reviewed existing preflight}"
: "${BACKUP_CHECK_SHA256:?Trusted SHA-256 of the reviewed backup data check}"
printf '%s  %s\n' "$V8_PREFLIGHT_SHA256" "$V8_PREFLIGHT_SQL" \
  "$BACKUP_CHECK_SHA256" "$BACKUP_CHECK_SQL" | sha256sum --check
test -f /opt/ai-policy-investigator/deployment.lock
exec 9</opt/ai-policy-investigator/deployment.lock
flock --exclusive --nonblock 9
export EXPECTED_V7_RELEASE
RELEASE_DIR=$(python3 - <<'PY'
import json, os, pathlib, re
base = pathlib.Path('/opt/ai-policy-investigator')
state = json.loads((base/'last-successful.json').read_text())
identity = state['id']
assert re.fullmatch(r'[a-zA-Z0-9_-]+', identity)
assert identity == os.environ['EXPECTED_V7_RELEASE'], 'APPROVED_BASE_MISMATCH'
release = base/'releases'/identity
assert release.resolve() == release and (release/'validated.json').is_file()
validated = json.loads((release/'validated.json').read_text())
assert validated['id'] == identity and validated['result'] == 'VALIDATED'
print(release)
PY
)
test -f "$DEPLOY_ENV_FILE"
[[ "$DEPLOY_ENV_FILE" = /* ]]
test ! -L "$DEPLOY_ENV_FILE"
test "$(stat -c %a "$DEPLOY_ENV_FILE")" = 600
test "$(stat -c %u "$DEPLOY_ENV_FILE")" = "$(id -u)"
backend_compose() {
  docker compose --project-directory "$RELEASE_DIR/configuration" --env-file "$DEPLOY_ENV_FILE" \
    -p ai-policy-investigator -f "$RELEASE_DIR/configuration/compose.yaml" \
    -f "$RELEASE_DIR/configuration/compose.production.yaml" --profile app "$@"
}
PG_CID=$(backend_compose ps -q postgres)
test -n "$PG_CID"
test "$(printf '%s\n' "$PG_CID" | wc -l)" -eq 1
export PG_CID RELEASE_DIR INVESTIGATOR_BACKUP_DIR
python3 - <<'PY'
import hashlib, json, os, pathlib, subprocess, tarfile
p = json.loads(subprocess.check_output(['docker','inspect',os.environ['PG_CID']]))[0]
assert p['State']['Running']
assert p['Config']['Labels']['com.docker.compose.project'] == 'ai-policy-investigator'
assert p['Config']['Labels']['com.docker.compose.service'] == 'postgres'
assert not any((p['HostConfig'].get('PortBindings') or {}).values())
data = [m for m in p['Mounts'] if m['Destination']=='/var/lib/postgresql/data']
assert len(data)==1 and data[0].get('Name')=='ai-policy-investigator_investigator_data'
assert set(p['NetworkSettings']['Networks']) == {'ai-policy-investigator_database'}
network = json.loads(subprocess.check_output(['docker','network','inspect','ai-policy-investigator_database']))[0]
assert network['Internal']
manifest = json.loads((pathlib.Path(os.environ['RELEASE_DIR'])/'release.json').read_text())
pg = manifest['images']['POSTGRES_IMAGE_REF']
assert pg['sourceRef'] == 'pgvector/pgvector:0.8.0-pg16'
assert pg['configDigest'] == os.environ['EXPECTED_PG_CONFIG_DIGEST'], 'SOURCE_CONFIG_EVIDENCE_MISMATCH'
assert pg['manifestDigest'] == os.environ['EXPECTED_PG_MANIFEST_DIGEST'], 'SOURCE_MANIFEST_EVIDENCE_MISMATCH'
assert pg['archive'] == 'POSTGRES_IMAGE_REF.tar'
archive = pathlib.Path(os.environ['RELEASE_DIR'])/pg['archive']
with archive.open('rb') as stream:
 assert hashlib.file_digest(stream,'sha256').hexdigest() == pg['archiveSha256'], 'SOURCE_ARCHIVE_CHANGED'
with tarfile.open(archive, 'r:') as saved:
 rows = json.loads(saved.extractfile('manifest.json').read())
 assert len(rows) == 1 and rows[0]['RepoTags'] == [pg['localRef']], 'SOURCE_ARCHIVE_SELECTION_MISMATCH'
 member = saved.getmember(rows[0]['Config'])
 assert member.isfile()
 config_bytes = saved.extractfile(member).read()
assert 'sha256:'+hashlib.sha256(config_bytes).hexdigest() == os.environ['EXPECTED_PG_CONFIG_DIGEST'], 'SOURCE_CONFIG_DIGEST_MISMATCH'
expected = json.loads(config_bytes)
image = json.loads(subprocess.check_output(['docker','image','inspect',p['Image']]))[0]
assert (image.get('Os'),image.get('Architecture')) == (expected.get('os'),expected.get('architecture')) == ('linux','amd64'), 'SOURCE_IMAGE_PLATFORM_MISMATCH'
assert image.get('RootFS',{}).get('Type') == expected['rootfs']['type'] == 'layers'
assert image['RootFS'].get('Layers') == expected['rootfs']['diff_ids'], 'SOURCE_IMAGE_LAYERS_MISMATCH'
actual_config, expected_config = image.get('Config') or {}, expected['config']
def normalized(value):
 return None if value in [None,'',[],{}] else value
for key in actual_config.keys() | expected_config.keys():
 assert normalized(actual_config.get(key)) == normalized(expected_config.get(key)), 'SOURCE_IMAGE_RUNTIME_CONFIG_MISMATCH'
for name in ['compose.yaml','compose.production.yaml','deploy/postgres/init.sh']:
 path = pathlib.Path(os.environ['RELEASE_DIR'])/'configuration'/name
 assert hashlib.file_digest(path.open('rb'),'sha256').hexdigest()==manifest['configuration'][name]
initializer = [m for m in p['Mounts'] if m['Destination']=='/docker-entrypoint-initdb.d/01-investigator.sh']
assert len(initializer)==1 and initializer[0]['Type']=='bind' and initializer[0]['RW'] is False
with pathlib.Path(initializer[0]['Source']).open('rb') as stream:
 assert hashlib.file_digest(stream,'sha256').hexdigest()==manifest['configuration']['deploy/postgres/init.sh'], 'SOURCE_INITIALIZER_CHANGED'
backup = pathlib.Path(os.environ['INVESTIGATOR_BACKUP_DIR']).resolve()
assert backup.is_absolute() and str(backup) != '/'
assert not backup.is_relative_to('/opt/ai-policy-investigator')
assert not any((parent/'.git').exists() for parent in [backup,*backup.parents])
PY
PG_IMAGE=$(docker inspect --format '{{.Image}}' "$PG_CID")
mkdir -p "$INVESTIGATOR_BACKUP_DIR"
chmod 700 "$INVESTIGATOR_BACKUP_DIR"
EVIDENCE=$(mktemp -d "$INVESTIGATOR_BACKUP_DIR/v7-$(date -u +%Y%m%dT%H%M%SZ)-XXXXXX")
export EVIDENCE
sha256sum "$V8_PREFLIGHT_SQL" "$BACKUP_CHECK_SQL" > "$EVIDENCE/tools.sha256"
cp "$RELEASE_DIR/configuration/deploy/postgres/init.sh" "$EVIDENCE/init.sh"
sha256sum "$EVIDENCE/init.sh" > "$EVIDENCE/init.sh.sha256"
backend_compose exec -T --user postgres postgres psql -X -U postgres -d investigator \
  -v ON_ERROR_STOP=1 -v expected_database=investigator -v target_version=7 \
  < "$V8_PREFLIGHT_SQL" > "$EVIDENCE/source-preflight.txt" 2> "$EVIDENCE/source-preflight.err"
df -h "$INVESTIGATOR_BACKUP_DIR"
backend_compose exec -T --user postgres postgres psql -XAt -U postgres -d investigator \
  -v ON_ERROR_STOP=1 -c 'SELECT pg_database_size(current_database());'
printf 'Private evidence directory: %s\nPostgres container: %s\n' "$EVIDENCE" "$PG_CID"
```

Before proceeding, check disk headroom for the full dump, fresh database, indexes
and WAL. Use approved capacity limits for the rehearsal; insufficient VPS capacity
is a blocker, not permission to prune production volumes. Validate the actual app
containers/release identity privately against the change record too. An absent
release marker, different topology, initializer, roles or extension version is a
blocker; do not guess another target. The lock blocks the existing release
controller, not writers or a human bypassing that controller.

## 2. Hold a shared read-only snapshot

In **terminal A**, on the same VPS, set `PG_CID` to the ID just checked in terminal B:

```bash
export DOCKER_HOST=unix:///var/run/docker.sock
unset DOCKER_CONTEXT
: "${PG_CID:?Exact checked production postgres container ID from terminal B}"
docker exec -it --user postgres "$PG_CID" psql -X -U postgres -d investigator -v ON_ERROR_STOP=1
```

At its psql prompt:

```sql
BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;
SELECT pg_export_snapshot();
```

Leave that transaction and terminal open. Copy the returned snapshot identifier
into `V7_SNAPSHOT` in terminal B. This is a snapshot token, not a credential. A
transaction timeout/disconnect invalidates it: start a new attempt in a new
evidence directory rather than dropping `--snapshot`. Keep the snapshot short to
avoid delaying vacuum. This synchronizes the dump and source fingerprints while
production writers continue. It does **not** establish a migration writer freeze
or capture later writes; refresh the backup under the approved freeze immediately
before any later migration. Sequence allocation is not transactional; do not
claim a write-frozen rollback cutoff for this online rehearsal.

## 3. Back up and check the exact archive

Continue in terminal B:

```bash
: "${V7_SNAPSHOT:?Snapshot identifier from the open terminal A transaction}"
BACKUP_FILE="$EVIDENCE/investigator-v7.dump"
backend_compose exec -T --user postgres postgres pg_dump -U postgres -d investigator \
  --format=custom --snapshot="$V7_SNAPSHOT" --lock-wait-timeout=5s \
  > "$BACKUP_FILE.partial" 2> "$EVIDENCE/pg_dump.err"
test -s "$BACKUP_FILE.partial"
mv "$BACKUP_FILE.partial" "$BACKUP_FILE"
chmod 400 "$BACKUP_FILE"
sha256sum "$BACKUP_FILE" > "$BACKUP_FILE.sha256"
sha256sum --check "$BACKUP_FILE.sha256"
backend_compose exec -T --user postgres postgres pg_restore --list \
  < "$BACKUP_FILE" > "$EVIDENCE/archive.list" 2> "$EVIDENCE/archive-list.err"
backend_compose exec -T --user postgres postgres psql -XqAt -U postgres -d investigator \
  -v ON_ERROR_STOP=1 -v snapshot="$V7_SNAPSHOT" -v demo_id="$DEMO_INVESTIGATION_ID" \
  < "$BACKUP_CHECK_SQL" > "$EVIDENCE/source.jsonl" 2> "$EVIDENCE/source.err"
```

Review stderr files privately for warnings; a nonempty readable archive listing
alone is insufficient. Any failure leaves the attestations pending. Once the dump
and source checks both pass, in terminal A run `ROLLBACK;` then `\q` to release the
snapshot. Leave terminal B's deployment lock held.

## 4. Restore into a fresh PostgreSQL-only container

This uses the exact already-loaded source PostgreSQL image ID, with no pull or
build, an independent volume, and the unchanged initializer. Only new random
rehearsal role passwords enter the new container. `pg_dump` omits cluster roles;
the initializer recreates their required names/privileges. Production credentials
must remain escrowed separately for disaster recovery. Do not export password
hashes with `pg_dumpall` or substitute `--no-owner`, `--no-acl` or `--disable-triggers`.

```bash
RESTORE_NAME="investigator-v7-restore-$(date -u +%Y%m%dT%H%M%SZ)-$(openssl rand -hex 4)"
RESTORE_VOLUME="$RESTORE_NAME-data"
export RESTORE_NAME RESTORE_VOLUME PG_IMAGE
python3 - <<'PY'
import os, pathlib, secrets
path = pathlib.Path(os.environ['EVIDENCE'])/'restore.env'
path.write_text('POSTGRES_DB=investigator\nPOSTGRES_USER=postgres\n' + ''.join(
    name+'='+secrets.token_hex(32)+'\n'
    for name in ['POSTGRES_PASSWORD','OWNER_DB_PASSWORD','APP_DB_PASSWORD']))
path.chmod(0o600)
PY
if docker container inspect "$RESTORE_NAME" >/dev/null 2>&1; then exit 1; fi
if docker volume inspect "$RESTORE_VOLUME" >/dev/null 2>&1; then exit 1; fi
docker volume create --label purpose=investigator-v7-restore "$RESTORE_VOLUME" > "$EVIDENCE/volume.txt"
docker run -d --pull never --name "$RESTORE_NAME" --network none --restart no \
  --memory 1g --cpus 1 --pids-limit 256 --security-opt no-new-privileges \
  --cap-drop NET_RAW --cap-drop NET_ADMIN \
  --label purpose=investigator-v7-restore --env-file "$EVIDENCE/restore.env" \
  --mount "type=volume,source=$RESTORE_VOLUME,target=/var/lib/postgresql/data" \
  --mount "type=bind,source=$EVIDENCE/init.sh,target=/docker-entrypoint-initdb.d/01-investigator.sh,readonly" \
  "$PG_IMAGE" postgres -c listen_addresses= -c max_connections=10 > "$EVIDENCE/container-id.txt"
ready=false
for attempt in {1..60}; do
  if docker exec --user postgres "$RESTORE_NAME" sh -c \
    'test "$(cat /proc/1/comm)" = postgres && pg_isready -U postgres -d investigator' >/dev/null 2>&1; then
    ready=true
    break
  fi
  sleep 1
done
test "$ready" = true
```

Verify isolation **before** loading data. Repeat this same block after the restore:

```bash
python3 - <<'PY'
import json, os, pathlib, subprocess
c = json.loads(subprocess.check_output(['docker','inspect',os.environ['RESTORE_NAME']]))[0]
h = c['HostConfig']
assert c['State']['Running'] and c['Image']==os.environ['PG_IMAGE']
assert c['Config']['Labels'].get('purpose')=='investigator-v7-restore'
assert h['NetworkMode']=='none' and set(c['NetworkSettings']['Networks'])=={'none'}
assert not h['Privileged'] and h['PidMode'] in ('','private') and h['IpcMode'] in ('','private')
assert not h.get('CapAdd') and not h.get('Devices')
assert not h['PortBindings'] and not h.get('ExtraHosts') and not h.get('Links')
assert h['RestartPolicy']['Name']=='no'
assert not any('API_KEY=' in e or e.startswith(('DB_URL=','JWT_SECRET=')) for e in c['Config']['Env'])
mounts = {m['Destination']:m for m in c['Mounts']}
assert set(mounts)=={'/var/lib/postgresql/data','/docker-entrypoint-initdb.d/01-investigator.sh'}
assert mounts['/var/lib/postgresql/data']['Name']==os.environ['RESTORE_VOLUME']
init = mounts['/docker-entrypoint-initdb.d/01-investigator.sh']
assert not init['RW'] and init['Source']==str(pathlib.Path(os.environ['EVIDENCE'])/'init.sh')
flags = subprocess.check_output(['docker','exec',os.environ['RESTORE_NAME'],'sh','-c',
 'for n in /sys/class/net/*; do test -f "$n/flags" || continue; printf "%s " "${n##*/}"; cat "$n/flags"; done'],text=True)
active = {line.split()[0] for line in flags.splitlines() if int(line.split()[1],16) & 1}
assert active=={'lo'}
routes = subprocess.check_output(['docker','exec',os.environ['RESTORE_NAME'],'cat','/proc/net/route'],text=True)
assert len(routes.splitlines())==1
routes6 = subprocess.check_output(['docker','exec',os.environ['RESTORE_NAME'],'cat','/proc/net/ipv6_route'],text=True)
assert all(line.split()[-1]=='lo' for line in routes6.splitlines())
record = {'result':'ISOLATION_PASS','container':c['Id'],'image':c['Image'],
          'networkMode':'none','activeInterfaces':['lo'],'publishedPorts':[],
          'volume':os.environ['RESTORE_VOLUME'],'applicationStarted':False}
(pathlib.Path(os.environ['EVIDENCE'])/'isolation.json').write_text(json.dumps(record,indent=2)+'\n')
PY
```

Only loopback is up, there is no external IPv4/IPv6 route, and no host port/socket or
production network/volume is shared. The container cannot reach production
services/queues or Meta over the network. PostgreSQL listens only on its local
Unix socket; `docker exec` performs all checks. No application, worker, model-init,
provider health probe, or database scheduling/claim function is run. Queued rows
are inert restored data. This isolation depends on preserving the checked Docker
configuration; a Docker administrator can later change it.
Some kernels expose inactive tunnel devices even with `--network none`; the check
requires that none is up and that neither IP family has an external route.

```bash
sha256sum --check "$BACKUP_FILE.sha256"
docker exec -i --user postgres "$RESTORE_NAME" pg_restore -U postgres -d investigator \
  --exit-on-error --single-transaction \
  < "$BACKUP_FILE" > "$EVIDENCE/restore.out" 2> "$EVIDENCE/restore.err"
docker exec -i --user postgres "$RESTORE_NAME" psql -X -U postgres -d investigator \
  -v ON_ERROR_STOP=1 -v expected_database=investigator -v target_version=7 \
  < "$V8_PREFLIGHT_SQL" > "$EVIDENCE/restored-preflight.txt" 2> "$EVIDENCE/restored-preflight.err"
docker exec -i --user postgres "$RESTORE_NAME" psql -XqAt -U postgres -d investigator \
  -v ON_ERROR_STOP=1 -v demo_id="$DEMO_INVESTIGATION_ID" \
  < "$BACKUP_CHECK_SQL" > "$EVIDENCE/restored.jsonl" 2> "$EVIDENCE/restored.err"
cmp "$EVIDENCE/source.jsonl" "$EVIDENCE/restored.jsonl"
sha256sum --check "$BACKUP_FILE.sha256"
```

Require zero exit statuses, exact V1–V7 scripts/checksums/success, matching private
counts/fingerprints for all public tables, roles/memberships/extensions/ACLs/RLS,
valid stored PDF hashes, and the exact completed demo with findings and all source
versions/extractions. Reviews, grants, accounts, leases and quota counters must
match; do not seed/reprovision/refund anything. Password hashes are restored by the
archive but deliberately excluded from the comparison report. Role credentials,
cluster-wide custom configuration/tablespaces, and post-snapshot sequence
allocation are outside this logical data comparison. Any discrepancy is a blocker
requiring review, never a reason to relax ownership/RLS checks.

## 5. Retain evidence and close the rehearsal

Repeat the isolation block above and review the private stderr files. Run the
existing **source** V7 preflight again to establish that production is still V7.
Only after all checks pass, produce this private record in terminal B:

```bash
backend_compose exec -T --user postgres postgres psql -X -U postgres -d investigator \
  -v ON_ERROR_STOP=1 -v expected_database=investigator -v target_version=7 \
  < "$V8_PREFLIGHT_SQL" > "$EVIDENCE/source-final-preflight.txt" 2> "$EVIDENCE/source-final-preflight.err"
export BACKUP_FILE DEMO_INVESTIGATION_ID
python3 - <<'PY'
import datetime, hashlib, json, os, pathlib
e = pathlib.Path(os.environ['EVIDENCE'])
assert json.loads((e/'isolation.json').read_text())['result']=='ISOLATION_PASS'
assert (e/'source.jsonl').read_bytes()==(e/'restored.jsonl').read_bytes()
assert any(json.loads(line).get('result')=='V7_BACKUP_DATA_CHECK_PASS'
           for line in (e/'restored.jsonl').read_text().splitlines())
dump = pathlib.Path(os.environ['BACKUP_FILE'])
h = hashlib.file_digest(dump.open('rb'),'sha256').hexdigest()
assert h==(e/'investigator-v7.dump.sha256').read_text().split()[0]
record = {'result':'V7_BACKUP_AND_ISOLATED_RESTORE_VERIFIED',
 'verifiedAtUtc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
 'release':os.environ['EXPECTED_V7_RELEASE'],'sourceContainer':os.environ['PG_CID'],
 'backupLocation':str(dump),'sha256':h,'restoredFlywayVersion':'7',
 'completedDemoInvestigation':os.environ['DEMO_INVESTIGATION_ID'],
 'backupVerified':True,'isolatedRestoreVerified':True,
 'writerFreezeVerified':False,'deploymentAuthorized':False}
(e/'report.json').write_text(json.dumps(record,indent=2)+'\n')
PY
docker stop "$RESTORE_NAME" > "$EVIDENCE/rehearsal-stopped.txt"
flock --unlock 9
exec 9<&-
```

Keep the stopped rehearsal container and its separate volume private until the
operator's retention policy permits cleanup. No automatic volume removal or
production recovery is included. On failure, close terminal A's snapshot, retain
private diagnostic files, stop **only** the uniquely named rehearsal container if
created, and release the lock; do not create a success record. Store matching V7
release artifacts, protected role credentials and required runtime configuration
with the recovery prerequisites. A checksum next to a dump detects corruption,
not malicious replacement of both: retain the trusted checksum in the protected
change record and verify it after any secure copy.

This record proves a specific V7 snapshot was restored in isolation. It neither
approves V8 nor satisfies the later write-freeze/image/reviewer requirements.
The legacy `deploy` operation's backup/restore inputs remain operator attestations.
For `deploy-reviewed`, leave those inputs false: the VPS earns these three gate
bits only by executing the unchanged checks on the fresh frozen backup. External
writer/delivery freeze, image qualification and protected-environment approval
remain human responsibilities.

References checked during preparation: PostgreSQL 16
[consistent custom backups](https://www.postgresql.org/docs/16/app-pgdump.html),
[exported snapshots](https://www.postgresql.org/docs/16/functions-admin.html#FUNCTIONS-SNAPSHOT-SYNCHRONIZATION),
[transactional restore](https://www.postgresql.org/docs/16/app-pgrestore.html), and
Docker's [none network driver](https://docs.docker.com/engine/network/drivers/none/).
