#!/usr/bin/env python3
"""Automate V7_BACKUP_RESTORE.md under the existing deployment lock.

Only PostgreSQL is started, in a new network-none container and independent volume.
All database output stays in private VPS files. No production writes or cleanup.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import secrets
import select
import shutil
import stat
import subprocess
import time

from deploy_local_images import DeploymentError, require, execute, json_command, PROJECT, UI_PROJECT
from release_artifacts import file_sha, archive_image, RELEASE_ID
from production_release import verify_loaded_content

ENV_FILE = Path('/opt/ai-policy-investigator/.env.production')
PG_MANIFEST = 'sha256:c72df104202409108a1660ecccd2b7ffac6b17e44c31b2636d10e983f410f8eb'
PG_CONFIG = 'sha256:56a5b20c7a157dbb94149ba3cce70da76f02e1645dec234379709ddaebe607ea'
TOOLS = Path(__file__).resolve().parent
SQL_SHA256 = {
    'qualification_v7_backup.sql': '8a0a58b7fb98e4ca39b570fbf3a48be6de401dfcfb41ebbabfabe57bbae12751',
    'qualification_v8_preflight.sql': '0209cd7f0631f0726f04fc79eb8990a1ddec6be6c7a88a19d0cf4498ab4b8a59',
}
INIT_SHA256 = '8a8bf87c66a2dad9efa0a1934fa7d58eea93e04469e15043f3f25e4a51a94261'
DOCKER_ENV = {'PATH': '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin',
              'DOCKER_HOST': 'unix:///var/run/docker.sock'}
RESTORE_START_TIMEOUT_SECONDS = 300


def restore_start_timeout(value=RESTORE_START_TIMEOUT_SECONDS):
    require(re.fullmatch(r'[0-9]{1,3}', str(value)) is not None
            and 60 <= int(value) <= 900, 'RESTORE_START_TIMEOUT_INVALID_60_TO_900_SECONDS')
    return int(value)


def restore_state(name, timeout=10):
    try:
        state = json.loads(execute(['docker', 'container', 'inspect', '--format', '{{json .State}}', name],
                                   DOCKER_ENV, code='RESTORE_STATE_INSPECTION_FAILED', timeout=timeout))
        require(isinstance(state, dict) and state.get('Status') in
                {'created', 'running', 'paused', 'restarting', 'removing', 'exited', 'dead'}
                and type(state.get('ExitCode')) is int and type(state.get('OOMKilled')) is bool,
                'RESTORE_STATE_INSPECTION_FAILED')
        return state
    except (ValueError, TypeError):
        raise DeploymentError('RESTORE_STATE_INSPECTION_FAILED') from None


def failure_record(evidence, filename, record):
    # A full/read-only filesystem must not replace the original failure code.
    try:
        (evidence / filename).write_text(json.dumps(record, indent=2) + '\n')
    except OSError:
        pass


def restore_start_failure(name, evidence, state, reason, timeout):
    """Raw diagnostics stay private; only fixed reason codes and scalar state escape."""
    log = evidence / 'restore-startup.log'
    collected = False
    try:
        with log.open('xb') as output:
            log.chmod(0o600)
            result = subprocess.run(['docker', 'logs', '--tail', '200', name], env=DOCKER_ENV,
                                    stdout=output, stderr=subprocess.STDOUT, timeout=10)
            collected = result.returncode == 0
        with log.open('rb') as output:
            output.seek(max(0, log.stat().st_size - 65536))
            text = output.read().decode('utf-8', errors='replace') if collected else ''
    except (OSError, subprocess.TimeoutExpired):
        text = ''
    detail = (text + '\n' + str(state.get('Error', ''))).lower()
    if state.get('OOMKilled'):
        reason = 'OOM_KILLED'
    elif 'no space left on device' in detail:
        reason = 'DISK_FULL'
    elif 'out of memory' in detail or 'cannot allocate memory' in detail:
        reason = 'MEMORY_EXHAUSTED'
    elif 'resource temporarily unavailable' in detail or 'cannot fork' in detail:
        reason = 'PROCESS_RESOURCE_EXHAUSTED'
    elif state.get('Status') in {'exited', 'dead'}:
        if ('/docker-entrypoint-initdb.d/01-investigator.sh' in text
                and 'PostgreSQL init process complete' not in text and state['ExitCode'] != 0):
            reason = 'INITIALIZER_NOT_READABLE' if 'permission denied' in detail else 'INITIALIZER_FAILED'
        else:
            reason = 'CONTAINER_EXITED_' + str(state['ExitCode'])
    elif state.get('Error'):
        reason = 'CONTAINER_RUNTIME_ERROR'
    code = 'RESTORE_POSTGRES_' + reason
    failure_record(evidence, 'restore-startup-failure.json', {
        'result': 'FAILED', 'code': code, 'timeoutSeconds': timeout,
        'containerStatus': state.get('Status'), 'exitCode': state.get('ExitCode'),
        'oomKilled': state.get('OOMKilled'), 'privateLogCollected': collected,
        'backupAndRestoreVerified': False, 'deploymentAuthorized': False})
    raise DeploymentError(code)


def wait_for_restore(name, evidence, timeout):
    deadline = time.monotonic() + timeout
    phase = 'INITIALIZING'
    while True:
        remaining = deadline - time.monotonic()
        state = restore_state(name, timeout=min(10, max(0.1, remaining)))
        if state['Status'] != 'running' or state.get('OOMKilled') or state.get('Error'):
            restore_start_failure(name, evidence, state, 'CONTAINER_NOT_RUNNING', timeout)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            restore_start_failure(name, evidence, state, 'START_TIMEOUT_' + phase, timeout)
        try:
            # The entrypoint runs a temporary server during initialization. PID 1
            # must have exec'd postgres before that server can count as ready.
            probe = subprocess.run(['docker', 'exec', '--user', 'postgres', name, 'sh', '-c',
                'test "$(cat /proc/1/comm)" = postgres || exit 10; '
                'exec pg_isready -q -h /var/run/postgresql -p 5432 -t 2 -U postgres -d investigator'],
                env=DOCKER_ENV, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                timeout=min(10, remaining))
            if probe.returncode == 0:
                if time.monotonic() <= deadline:
                    return
                continue
            phase = {10: 'INITIALIZING', 1: 'REJECTING_CONNECTIONS', 2: 'NO_RESPONSE'}.get(probe.returncode, 'PROBE_FAILED')
            if phase == 'PROBE_FAILED':
                restore_start_failure(name, evidence, restore_state(name), 'READINESS_PROBE_FAILED', timeout)
        except subprocess.TimeoutExpired:
            phase = 'PROBE_TIMEOUT'
        except OSError:
            restore_start_failure(name, evidence, state, 'READINESS_PROBE_FAILED', timeout)
        time.sleep(min(1, max(0, deadline - time.monotonic())))


def stop_restore(name, volume):
    require(re.fullmatch(r'investigator-v7-restore-[0-9a-f]{24}', name) is not None
            and volume == name + '-data', 'RESTORE_CLEANUP_TARGET_INVALID')
    rows = json_command(['docker', 'container', 'inspect', name], DOCKER_ENV,
                        code='RESTORE_CLEANUP_INSPECTION_FAILED')
    require(isinstance(rows, list) and len(rows) == 1 and isinstance(rows[0], dict),
            'RESTORE_CLEANUP_INSPECTION_FAILED')
    row = rows[0]
    require(row.get('Name') == '/' + name and re.fullmatch(r'[0-9a-f]{64}', row.get('Id', ''))
            and (row.get('Config', {}).get('Labels') or {}).get('purpose') == 'investigator-v7-restore'
            and any(m.get('Destination') == '/var/lib/postgresql/data' and m.get('Type') == 'volume'
                    and m.get('Name') == volume for m in row.get('Mounts', [])),
            'RESTORE_CLEANUP_OWNERSHIP_MISMATCH')
    # Stop by immutable ID after checking ownership. Never remove containers or volumes.
    execute(['docker', 'stop', row['Id']], DOCKER_ENV, code='ISOLATED_RESTORE_STOP_FAILED', timeout=60)


def private_env(path=ENV_FILE):
    require(path == ENV_FILE and path.resolve() == path and path.is_file()
            and path.stat().st_uid == os.geteuid() and stat.S_IMODE(path.stat().st_mode) == 0o600,
            'PRODUCTION_ENV_PATH_OR_PERMISSIONS_INVALID')


def container(service, project=PROJECT):
    ids = execute(['docker', 'ps', '-aq', '--filter', 'label=com.docker.compose.project=' + project,
                   '--filter', 'label=com.docker.compose.service=' + service], DOCKER_ENV).splitlines()
    require(len(ids) == 1 and re.fullmatch(r'[0-9a-f]{12,64}', ids[0]), 'EXACT_PRODUCTION_CONTAINER_REQUIRED')
    return json_command(['docker', 'inspect', ids[0]], DOCKER_ENV)[0]


def verify_source_content(row, proof):
    verify_loaded_content(row, proof)
    require(row.get('RootFS', {}).get('Type') == 'layers', 'SOURCE_IMAGE_ROOTFS_TYPE_MISMATCH')
    actual, expected = row.get('Config') or {}, proof['imageConfig']
    def normalized(value):
        return None if value in [None, '', [], {}] else value
    require(all(normalized(actual.get(k)) == normalized(expected.get(k)) for k in actual.keys() | expected.keys()),
            'SOURCE_IMAGE_RUNTIME_CONFIG_MISMATCH')


def source(base, expected):
    require(re.fullmatch(RELEASE_ID, expected or ''), 'APPROVED_PREVIOUS_RELEASE_REQUIRED')
    state = json.loads((base / 'last-successful.json').read_text())
    require(state['id'] == expected, 'APPROVED_RELEASE_BASE_CHANGED')
    release = base / 'releases' / expected
    require(release.resolve() == release, 'SOURCE_RELEASE_PATH_INVALID')
    marker = json.loads((release / 'validated.json').read_text())
    require(marker['id'] == expected and marker['result'] == 'VALIDATED', 'SOURCE_RELEASE_NOT_VALIDATED')
    data = json.loads((release / 'release.json').read_text())
    for name in ['compose.yaml', 'compose.production.yaml', 'deploy/postgres/init.sh']:
        require(file_sha(release / 'configuration' / name) == data['configuration'][name], 'SOURCE_CONFIGURATION_CHANGED')
    require(data['configuration']['deploy/postgres/init.sh'] == INIT_SHA256, 'SOURCE_INITIALIZER_CHANGED')
    pg = container('postgres')
    require(pg['State']['Running'] and not any((pg['HostConfig'].get('PortBindings') or {}).values())
            and set(pg['NetworkSettings']['Networks']) == {PROJECT + '_database'}, 'SOURCE_DATABASE_ISOLATION_INVALID')
    net = json_command(['docker', 'network', 'inspect', PROJECT + '_database'], DOCKER_ENV)[0]
    require(net['Internal'] is True, 'SOURCE_DATABASE_NETWORK_NOT_INTERNAL')
    mounts = {m['Destination']: m for m in pg['Mounts']}
    require(mounts['/var/lib/postgresql/data'].get('Name') == PROJECT + '_investigator_data', 'SOURCE_DATABASE_VOLUME_INVALID')
    init = mounts['/docker-entrypoint-initdb.d/01-investigator.sh']
    require(init['Type'] == 'bind' and init['RW'] is False
            and file_sha(Path(init['Source'])) == data['configuration']['deploy/postgres/init.sh'], 'SOURCE_INITIALIZER_CHANGED')
    image = data['images']['POSTGRES_IMAGE_REF']
    require(image['manifestDigest'] == PG_MANIFEST and image['configDigest'] == PG_CONFIG
            and image['sourceRef'] == 'pgvector/pgvector:0.8.0-pg16'
            and image['archive'] == 'POSTGRES_IMAGE_REF.tar', 'SOURCE_POSTGRES_EVIDENCE_MISMATCH')
    archive = release / image['archive']
    require(file_sha(archive) == image['archiveSha256'], 'SOURCE_ARCHIVE_CHANGED')
    proof = archive_image(archive, image['localRef'], PG_CONFIG, details=True)
    # Verified normalization explanation: IDs may differ; always compare actual content.
    verify_source_content(json_command(['docker', 'image', 'inspect', pg['Image']], DOCKER_ENV)[0], proof)
    apps = [container('backend'), container('frontend', UI_PROJECT)]
    for app, key in zip(apps, ['BACKEND_IMAGE_REF', 'FRONTEND_IMAGE_REF']):
        labels = app['Config']['Labels']
        working = release / 'configuration' / ('frontend' if key == 'FRONTEND_IMAGE_REF' else '')
        require(labels['com.docker.compose.project.working_dir'] == str(working),
                'SOURCE_APPLICATION_RELEASE_DIFFERS')
        row = data['images'][key]
        require(row['archive'] == key + '.tar', 'SOURCE_ARCHIVE_NAME_INVALID')
        path = release / row['archive']
        require(file_sha(path) == row['archiveSha256'], 'SOURCE_ARCHIVE_CHANGED')
        app_proof = archive_image(path, row['localRef'], row['configDigest'],
                                  data['backendSha'] if key == 'BACKEND_IMAGE_REF' else data['frontendSha'], details=True)
        verify_source_content(json_command(['docker', 'image', 'inspect', app['Image']], DOCKER_ENV)[0], app_proof)
    return release, pg, apps


def psql(cid, *args):
    return ['docker', 'exec', '-i', '--user', 'postgres', cid, 'psql', '-XqAt', '-U', 'postgres',
            '-d', 'investigator', '-v', 'ON_ERROR_STOP=1', *args]


def private_run(command, evidence, name, input_path=None, output_path=None, timeout=1200):
    """Stream dumps to disk, never memory/logs. Any stderr requires private review."""
    with (input_path.open('rb') if input_path else open(os.devnull, 'rb')) as stdin, \
            (output_path or evidence / (name + '.out')).open('xb') as stdout, \
            (evidence / (name + '.err')).open('xb') as stderr:
        try:
            result = subprocess.run(command, stdin=stdin, stdout=stdout, stderr=stderr,
                                    env=DOCKER_ENV, timeout=timeout)
        except (OSError, subprocess.TimeoutExpired):
            raise DeploymentError('PRIVATE_DATABASE_COMMAND_FAILED') from None
    require(result.returncode == 0, 'PRIVATE_DATABASE_COMMAND_FAILED')
    require((evidence / (name + '.err')).stat().st_size == 0, 'PRIVATE_DATABASE_STDERR_REQUIRES_REVIEW')


def preflight(cid, evidence, name):
    private_run(psql(cid, '-v', 'expected_database=investigator', '-v', 'target_version=7'),
                evidence, name, TOOLS / 'qualification_v8_preflight.sql')
    require('V8_QUALIFICATION_PREFLIGHT_PASS' in (evidence / (name + '.out')).read_text(), 'V7_PREFLIGHT_FAILED')


@contextmanager
def snapshot(cid, evidence):
    with (evidence / 'snapshot.err').open('xb') as error:
        proc = subprocess.Popen(psql(cid), env=DOCKER_ENV, stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=error, text=True)
        try:
            proc.stdin.write("SET idle_in_transaction_session_timeout='20min';\n"
                             'BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;\nSELECT pg_export_snapshot();\n')
            proc.stdin.flush()
            require(select.select([proc.stdout], [], [], 30)[0], 'SNAPSHOT_EXPORT_TIMEOUT')
            token = proc.stdout.readline().strip()
            require(re.fullmatch(r'[0-9A-Fa-f]+-[0-9A-Fa-f]+-[0-9]+', token), 'SNAPSHOT_EXPORT_FAILED')
            yield token
            require(proc.poll() is None, 'SNAPSHOT_SESSION_LOST')
        finally:
            try:
                proc.communicate('ROLLBACK;\n\\q\n', timeout=15)
            except (OSError, subprocess.TimeoutExpired):
                proc.kill(); proc.wait()
        require(proc.returncode == 0 and (evidence / 'snapshot.err').stat().st_size == 0,
                'SNAPSHOT_SESSION_FAILED')


def isolation(name, volume, image, evidence):
    c = json_command(['docker', 'inspect', name], DOCKER_ENV)[0]
    h = c['HostConfig']
    require(c['State']['Running'] and c['Image'] == image
            and c['Config']['Labels'].get('purpose') == 'investigator-v7-restore'
            and h['NetworkMode'] == 'none' and set(c['NetworkSettings']['Networks']) == {'none'}
            and not h['Privileged'] and h['PidMode'] in ('', 'private') and h['IpcMode'] in ('', 'private')
            and not any(h.get(k) for k in ['CapAdd', 'Devices', 'PortBindings', 'ExtraHosts', 'Links'])
            and h['RestartPolicy']['Name'] == 'no', 'RESTORE_ISOLATION_FAILED')
    require(not any('API_KEY=' in e or e.startswith(('DB_URL=', 'JWT_SECRET=')) for e in c['Config']['Env']),
            'RESTORE_PRODUCTION_ENV_FORBIDDEN')
    mounts = {m['Destination']: m for m in c['Mounts']}
    require(set(mounts) == {'/var/lib/postgresql/data', '/docker-entrypoint-initdb.d/01-investigator.sh'}
            and mounts['/var/lib/postgresql/data']['Name'] == volume
            and mounts['/docker-entrypoint-initdb.d/01-investigator.sh']['Source'] == str(evidence / 'init.sh')
            and not mounts['/docker-entrypoint-initdb.d/01-investigator.sh']['RW'], 'RESTORE_MOUNT_ISOLATION_FAILED')
    flags = execute(['docker', 'exec', name, 'sh', '-c',
                     'for n in /sys/class/net/*; do test -f "$n/flags" || continue; '
                     'printf "%s " "${n##*/}"; cat "$n/flags"; done'], DOCKER_ENV)
    require({line.split()[0] for line in flags.splitlines() if int(line.split()[1], 16) & 1} == {'lo'},
            'RESTORE_ACTIVE_NETWORK_INTERFACE')
    routes = execute(['docker', 'exec', name, 'cat', '/proc/net/route'], DOCKER_ENV)
    routes6 = execute(['docker', 'exec', name, 'cat', '/proc/net/ipv6_route'], DOCKER_ENV)
    require(len(routes.splitlines()) == 1 and all(line.split()[-1] == 'lo' for line in routes6.splitlines()),
            'RESTORE_EXTERNAL_ROUTE')


def evidence_directory(backup_root, database_bytes):
    require(backup_root.is_absolute() and backup_root.resolve() == backup_root and backup_root != Path('/')
            and not backup_root.is_relative_to('/opt/ai-policy-investigator')
            and not any((p / '.git').exists() for p in [backup_root, *backup_root.parents]), 'PRIVATE_BACKUP_PATH_INVALID')
    require(backup_root.is_dir() and backup_root.stat().st_uid == os.geteuid()
            and stat.S_IMODE(backup_root.stat().st_mode) == 0o700, 'PRIVATE_BACKUP_DIRECTORY_REQUIRED')
    # Dump + restored heap/indexes/WAL + margin; never prune to make space.
    needed = database_bytes * 4 + 1024**3
    require(shutil.disk_usage(backup_root).free >= needed, 'BACKUP_STORAGE_CAPACITY_INSUFFICIENT')
    docker_root = Path(json_command(['docker', 'info', '--format', '{{json .DockerRootDir}}'], DOCKER_ENV))
    require(shutil.disk_usage(docker_root).free >= needed, 'RESTORE_STORAGE_CAPACITY_INSUFFICIENT')
    path = backup_root / ('v7-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + secrets.token_hex(6))
    path.mkdir(mode=0o700)
    return path


def verify_backup(base, request, frozen=False):
    """Caller holds deployment.lock for the entire operation and any subsequent migration."""
    timeout = restore_start_timeout(request.get('restore_start_timeout_seconds', RESTORE_START_TIMEOUT_SECONDS))
    private_env()
    require(all(file_sha(TOOLS / name) == digest for name, digest in SQL_SHA256.items()), 'REVIEWED_SQL_CHECK_CHANGED')
    demo = request['demo_id']
    require(re.fullmatch(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}', demo or ''), 'COMPLETED_PRODUCTION_DEMO_UUID_REQUIRED')
    release, pg, apps = source(base, request['expected_previous'])
    if frozen:
        require(all(not app['State']['Running'] for app in apps), 'PRODUCTION_APPLICATION_WRITERS_NOT_STOPPED')
    size = execute(psql(pg['Id'], '-c', 'SELECT pg_database_size(current_database());'), DOCKER_ENV)
    require(size.strip().isdecimal(), 'DATABASE_SIZE_UNAVAILABLE')
    evidence = evidence_directory(Path(request['backup_root']), int(size.strip()))
    (evidence / 'tools.json').write_text(json.dumps({p: file_sha(TOOLS / p) for p in
        ['qualification_v8_preflight.sql', 'qualification_v7_backup.sql']}, indent=2) + '\n')
    shutil.copyfile(release / 'configuration/deploy/postgres/init.sh', evidence / 'init.sh')
    # copyfile under the reviewed entrypoint's umask 077 creates mode 0600.
    # The non-secret script must be readable by postgres inside its read-only
    # file bind mount; the containing evidence directory stays private (0700).
    (evidence / 'init.sh').chmod(0o644)
    preflight(pg['Id'], evidence, 'source-preflight')
    dump = evidence / 'investigator-v7.dump'
    with snapshot(pg['Id'], evidence) as token:
        partial = evidence / 'investigator-v7.dump.partial'
        private_run(['docker', 'exec', '--user', 'postgres', pg['Id'], 'pg_dump', '-U', 'postgres', '-d',
                     'investigator', '--format=custom', '--snapshot=' + token, '--lock-wait-timeout=5s'],
                    evidence, 'pg_dump', output_path=partial)
        require(partial.stat().st_size > 0, 'EMPTY_BACKUP')
        partial.rename(dump); dump.chmod(0o400)
        digest = file_sha(dump)
        (evidence / 'investigator-v7.dump.sha256').write_text(digest + '  investigator-v7.dump\n')
        private_run(['docker', 'exec', '-i', '--user', 'postgres', pg['Id'], 'pg_restore', '--list'],
                    evidence, 'archive-list', dump)
        require((evidence / 'archive-list.out').stat().st_size > 0, 'EMPTY_ARCHIVE_LIST')
        private_run(psql(pg['Id'], '-v', 'snapshot=' + token, '-v', 'demo_id=' + demo), evidence,
                    'source', TOOLS / 'qualification_v7_backup.sql')
    name = 'investigator-v7-restore-' + secrets.token_hex(12)
    volume = name + '-data'
    env_file = evidence / 'restore.env'
    env_file.write_text('POSTGRES_DB=investigator\nPOSTGRES_USER=postgres\n' + ''.join(
        key + '=' + secrets.token_hex(32) + '\n' for key in ['POSTGRES_PASSWORD', 'OWNER_DB_PASSWORD', 'APP_DB_PASSWORD']))
    env_file.chmod(0o600)
    run_attempted = False
    failed = False
    try:
        # Random names plus explicit absence checks; never reuse an existing volume/container.
        for kind, target in [('container', name), ('volume', volume)]:
            probe = subprocess.run(['docker', kind, 'inspect', target], env=DOCKER_ENV, capture_output=True)
            require(probe.returncode != 0, 'RESTORE_TARGET_ALREADY_EXISTS')
        execute(['docker', 'volume', 'create', '--label', 'purpose=investigator-v7-restore', volume], DOCKER_ENV)
        run_attempted = True
        try:
            execute(['docker', 'run', '-d', '--pull', 'never', '--name', name, '--network', 'none', '--restart', 'no',
                 '--memory', '1g', '--cpus', '1', '--pids-limit', '256', '--security-opt', 'no-new-privileges',
                 '--cap-drop', 'NET_RAW', '--cap-drop', 'NET_ADMIN', '--label', 'purpose=investigator-v7-restore',
                 '--env-file', str(env_file), '--mount', 'type=volume,source=' + volume + ',target=/var/lib/postgresql/data',
                 '--mount', 'type=bind,source=' + str(evidence / 'init.sh') + ',target=/docker-entrypoint-initdb.d/01-investigator.sh,readonly',
                 pg['Image'], 'postgres', '-c', 'listen_addresses=', '-c', 'max_connections=10'], DOCKER_ENV,
                 code='RESTORE_POSTGRES_LAUNCH_FAILED')
        except DeploymentError:
            # docker run may create the container even when its client fails.
            try:
                state = restore_state(name)
            except DeploymentError:
                state = {}
            restore_start_failure(name, evidence, state, 'LAUNCH_FAILED', timeout)
        wait_for_restore(name, evidence, timeout)
        isolation(name, volume, pg['Image'], evidence)
        require(file_sha(dump) == digest, 'BACKUP_CHECKSUM_CHANGED')
        private_run(['docker', 'exec', '-i', '--user', 'postgres', name, 'pg_restore', '-U', 'postgres', '-d',
                     'investigator', '--exit-on-error', '--single-transaction'], evidence, 'restore', dump)
        preflight(name, evidence, 'restored-preflight')
        private_run(psql(name, '-v', 'demo_id=' + demo), evidence, 'restored', TOOLS / 'qualification_v7_backup.sql')
        require((evidence / 'source.out').read_bytes() == (evidence / 'restored.out').read_bytes(), 'RESTORED_DATA_FINGERPRINT_MISMATCH')
        require(any(json.loads(line).get('result') == 'V7_BACKUP_DATA_CHECK_PASS'
                    for line in (evidence / 'restored.out').read_text().splitlines()), 'RESTORED_DATA_CHECK_INCOMPLETE')
        isolation(name, volume, pg['Image'], evidence)
        preflight(pg['Id'], evidence, 'source-final-preflight')
        require(file_sha(dump) == digest, 'BACKUP_CHECKSUM_CHANGED')
    except Exception:
        failed = True
        failure_record(evidence, 'rehearsal-failed.json', {
            'result': 'FAILED', 'backupAndRestoreVerified': False, 'deploymentAuthorized': False})
        raise
    finally:
        if run_attempted:
            try:
                stop_restore(name, volume)
            except (DeploymentError, OSError, ValueError, KeyError, TypeError):
                failure_record(evidence, 'cleanup-failed.json', {
                    'result': 'FAILED', 'code': 'ISOLATED_RESTORE_STOP_FAILED',
                    'backupAndRestoreVerified': False, 'deploymentAuthorized': False})
                if not failed:
                    raise DeploymentError('ISOLATED_RESTORE_STOP_FAILED') from None
    report = {'result': 'V7_BACKUP_AND_ISOLATED_RESTORE_VERIFIED', 'release': request['expected_previous'],
              'verifiedAtUtc': datetime.now(timezone.utc).isoformat(), 'sourceContainer': pg['Id'],
              'backupLocation': str(dump), 'sha256': digest, 'completedDemoInvestigation': demo,
              'restoreContainer': name, 'restoreVolume': volume, 'restoredFlywayVersion': '7',
              'applicationWritersStopped': frozen, 'externalWriterFreezeAttested': frozen,
              'deploymentAuthorized': False}
    (evidence / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    return evidence
