#!/usr/bin/env python3
"""Versioned SSH deployment script, following spring-ai-rag's Compose mechanism.

Runs as the existing authorized Docker deployment account. No controller installation,
new sudo rule, registry login/pull, build, pruning or database rollback on the VPS.
"""
import argparse
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import re
import stat
import time
import pwd
from contextlib import contextmanager
import sys
import tarfile
import urllib.error
import urllib.request

from deploy_local_images import (DeploymentError, ROOT, PROJECT, UI_PROJECT, require, execute,
                                 json_command, compose_commands, validate_configuration,
                                 check_runtime, inspect_image)
from release_artifacts import (RELEASE_ID, CONFIG_FILES, RUNTIME_FILES, archive_image, file_sha,
                               sha, validate_manifest, migration_gate)

BASE = Path('/opt/ai-policy-investigator')


def reviewed_configuration(data, root=ROOT):
    for name in CONFIG_FILES:
        source = root / name
        require(source.is_file() and not source.is_symlink() and file_sha(source) == data['configuration'][name],
                'RELEASE_CONFIGURATION_DIGEST_MISMATCH')


def commands(data, env_file, root=ROOT):
    require(env_file.is_file() and not env_file.is_symlink()
            and env_file.stat().st_uid == os.geteuid()
            and stat.S_IMODE(env_file.stat().st_mode) & 0o077 == 0, 'PRIVATE_ENV_FILE_PERMISSIONS_REQUIRE_600')
    # Do not inherit stale image/secret variables from SSH or sudo.
    env = {'PATH': '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin', 'HOME': pwd.getpwuid(os.geteuid()).pw_dir}
    env.update({key: value['localRef'] for key, value in data['images'].items()})
    back, front = compose_commands(root, root / 'frontend', env_file)
    # Compose global options must precede the command (and may follow --profile app).
    back += ['-f', str(root / 'deploy/automation/compose.yaml')]
    for command in [back, front]:
        execute(command + ['config', '--quiet'], env, 'PRODUCTION_COMPOSE_CONFIG_FAILED')
    b = json_command(back + ['config', '--format', 'json'], env)
    f = json_command(front + ['config', '--format', 'json'], env)
    validate_configuration(b, f, env, postgres_image=env['POSTGRES_IMAGE_REF'])
    return back, front, env, b


def verify_archives(directory, data):
    proofs = {}
    for key, image in data['images'].items():
        path = directory / image['archive']
        require(file_sha(path) == image['archiveSha256'], 'RELEASE_ARCHIVE_TAMPERED')
        revision = data['frontendSha'] if key == 'FRONTEND_IMAGE_REF' else data['backendSha']
        proof = archive_image(path, image['localRef'], image['configDigest'],
                              revision if key != 'POSTGRES_IMAGE_REF' else None, key == 'BACKEND_IMAGE_REF', details=True)
        if key == 'BACKEND_IMAGE_REF':
            require(proof['migrations'] == data['migrations'], 'MIGRATION_INVENTORY_NOT_FROM_IMAGE')
        proofs[key] = proof
    return proofs


def history(back, env):
    exists = execute(back + ['exec', '-T', '--user', 'postgres', 'postgres', 'psql', '-X', '-U', 'postgres', '-d',
                            'investigator', '-At', '-v', 'ON_ERROR_STOP=1', '-c',
                            "SELECT to_regclass('public.flyway_schema_history') IS NOT NULL"], env, 'DATABASE_HISTORY_UNAVAILABLE').strip()
    if exists == 'f':
        count = execute(back + ['exec', '-T', '--user', 'postgres', 'postgres', 'psql', '-X', '-U', 'postgres', '-d',
                               'investigator', '-At', '-v', 'ON_ERROR_STOP=1', '-c',
                               "SELECT count(*) FROM pg_tables WHERE schemaname='public'"], env, 'DATABASE_HISTORY_UNAVAILABLE').strip()
        require(count == '0', 'UNTRACKED_DATABASE_SCHEMA')
        return []
    require(exists == 't', 'DATABASE_HISTORY_UNAVAILABLE')
    query = "SELECT coalesce(json_agg(t ORDER BY installed_rank), '[]'::json) FROM (SELECT installed_rank,version,script,checksum,success,type FROM public.flyway_schema_history) t"
    return json.loads(execute(back + ['exec', '-T', '--user', 'postgres', 'postgres', 'psql', '-X', '-U', 'postgres',
                                    '-d', 'investigator', '-At', '-v', 'ON_ERROR_STOP=1', '-c', query],
                             env, 'DATABASE_HISTORY_UNAVAILABLE'))


def verify_loaded_content(row, proof):
    # Docker 29 can regenerate a manifest ID while loading a legacy save archive.
    # Verify the selected platform, uncompressed layers and runtime configuration,
    # rather than assuming any registry manifest ID survives normalization/load.
    require((row.get('Os'), row.get('Architecture')) == ('linux', 'amd64'), 'LOADED_IMAGE_PLATFORM_MISMATCH')
    require(row.get('RootFS', {}).get('Layers') == proof['diffIds'], 'LOADED_IMAGE_LAYERS_MISMATCH')
    actual, expected = row.get('Config') or {}, proof['imageConfig']
    for key in ['User', 'Env', 'Cmd', 'Entrypoint', 'WorkingDir', 'Labels', 'Healthcheck',
                'ExposedPorts', 'Volumes', 'StopSignal', 'OnBuild', 'Shell']:
        def normalized(value):
            return None if value in [None, '', [], {}] else value
        require(normalized(actual.get(key)) == normalized(expected.get(key)), 'LOADED_IMAGE_RUNTIME_CONFIG_MISMATCH')


def verify_existing_postgres(allowed_ids, proof=None):
    ids = execute(['docker', 'ps', '-aq', '--filter', 'label=com.docker.compose.project=' + PROJECT,
                   '--filter', 'label=com.docker.compose.service=postgres']).splitlines()
    require(len(ids) <= 1, 'MULTIPLE_PROJECT_DATABASE_CONTAINERS')
    if ids:
        row = json_command(['docker', 'inspect', ids[0]])[0]
        if row['Image'] not in allowed_ids:
            require(proof is not None, 'EXISTING_POSTGRES_IMAGE_CHANGE_FORBIDDEN')
            # Existing Docker29 index/manifest IDs may differ for identical content.
            # An unknown platform still fails closed; only identical actual content is accepted.
            inspect_image(row['Image'], 'amd64')
            verify_loaded_content(json_command(['docker', 'image', 'inspect', '--platform', 'linux/amd64', row['Image']])[0], proof)
        require(set(row['NetworkSettings']['Networks']) == {PROJECT + '_database'}
                and not any((row['HostConfig'].get('PortBindings') or {}).values()), 'EXISTING_DATABASE_ISOLATION_DIFFERS')
        require(any(m.get('Name') == PROJECT + '_investigator_data' and m.get('Destination') == '/var/lib/postgresql/data'
                    for m in row['Mounts']), 'EXISTING_DATABASE_VOLUME_DIFFERS')
    return bool(ids)


def check_url(url, expected):
    try:
        # Default TLS certificate verification; redirects rejected to avoid accepting a login redirect.
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):
                return None
        opener = urllib.request.build_opener(NoRedirect)
        try:
            with opener.open(url, timeout=20) as response:
                status = response.status
        except urllib.error.HTTPError as error:
            status = error.code
        require(status == expected, 'PUBLIC_ROUTING_STATUS_FAILED')
    except (urllib.error.URLError, TimeoutError, OSError):
        raise DeploymentError('PUBLIC_ROUTING_NETWORK_OR_TLS_FAILED') from None


def healthy_service(command, service, env):
    identity = execute(command + ['ps', '-q', service], env).strip()
    require(re.fullmatch(r'[0-9a-f]{12,64}', identity), 'HEALTHCHECK_CONTAINER_MISSING')
    row = json_command(['docker', 'inspect', identity])[0]
    require(row.get('State', {}).get('Running') is True
            and row['State'].get('Health', {}).get('Status') == 'healthy', 'CONTAINER_NOT_HEALTHY')


def routing(front, env, public_url):
    execute(front + ['exec', '-T', 'frontend', 'wget', '-q', '--spider', 'http://127.0.0.1:8080/healthz'],
            env, 'FRONTEND_INTERNAL_HEALTH_FAILED')
    # Nginx -> backend protected API must return 401 without any token or credentials.
    output = execute(front + ['exec', '-T', 'frontend', 'sh', '-c',
                             'wget -S -O /dev/null http://127.0.0.1:8080/api/auth/me 2>&1 || true'],
                     env, 'API_ROUTING_PROBE_FAILED')
    require(re.search(r'HTTP/\S+ 401\b', output), 'API_AUTHENTICATED_ROUTE_NOT_PROTECTED_OR_UNREACHABLE')
    for path, status in [('/healthz', 200), ('/', 200), ('/api/auth/me', 401)]:
        check_url(public_url + path, status)


def activate(directory, data, settings, rollback=False, allow_migrations=False, base=BASE, root=ROOT):
    reviewed_configuration(data, root)
    back, front, env, config = commands(data, Path(settings['envFile']), root)
    proofs = verify_archives(directory, data)
    state_file = base / 'last-successful.json'
    previous = json.loads(state_file.read_text()) if state_file.exists() else None
    if not rollback and 'expectedPrevious' in data:
        require(data['expectedPrevious'] == (previous['id'] if previous else None), 'DEPLOYMENT_BASE_CHANGED_RETRY')
    if rollback:
        require((directory / 'validated.json').is_file(), 'ROLLBACK_TARGET_NEVER_VALIDATED')
        require(previous is not None and previous['id'] != data['id'], 'ROLLBACK_TARGET_IS_CURRENT_OR_UNKNOWN')
    # Verified normalized single-image archives only. No registry references needed by Docker load.
    for key, image in data['images'].items():
        execute(['docker', 'image', 'load', '--platform', 'linux/amd64', '--input', str(directory / image['archive'])],
                code='LOCAL_IMAGE_LOAD_FAILED', timeout=300)
        inspected = inspect_image(image['localRef'], 'amd64')
        selected = json_command(['docker', 'image', 'inspect', '--platform', 'linux/amd64', image['localRef']])[0]
        require(inspected['platform'] == 'linux/amd64', 'LOADED_IMAGE_PLATFORM_MISMATCH')
        verify_loaded_content(selected, proofs[key])
    check_runtime(config)  # Existing NPM, topology and explicit local platform checks; no Meta inference.
    postgres = data['images']['POSTGRES_IMAGE_REF']
    existing_database = verify_existing_postgres([postgres['configDigest'], postgres['manifestDigest']], proofs['POSTGRES_IMAGE_REF'])
    require(existing_database or allow_migrations, 'FIRST_INSTALL_MIGRATIONS_REQUIRE_APPROVAL')
    execute(back + ['up', '-d', '--no-recreate', '--no-build', '--pull', 'never', '--wait', '--wait-timeout', '90', 'postgres'],
            env, 'DATABASE_HEALTH_FAILED', timeout=120)
    healthy_service(back, 'postgres', env)
    applied = history(back, env)
    migration_gate(applied, data['migrations'], previous.get('migrations') if previous else None,
                   rollback, allow_migrations)
    # PostgreSQL is never recreated. Only this project's initializer/backend/frontend can be replaced.
    execute(back + ['up', '-d', '--no-deps', '--force-recreate', '--no-build', '--pull', 'never', 'model-init'],
            env, 'MODEL_INITIALIZER_START_FAILED')
    initializer = execute(back + ['ps', '-aq', 'model-init'], env).strip()
    require(re.fullmatch(r'[0-9a-f]{12,64}', initializer), 'MODEL_INITIALIZER_CONTAINER_MISSING')
    require(execute(['docker', 'wait', initializer], code='MODEL_INITIALIZER_TIMEOUT', timeout=600).strip() == '0',
            'MODEL_INITIALIZER_FAILED')
    execute(back + ['up', '-d', '--no-deps', '--force-recreate', '--no-build', '--pull', 'never', '--wait', '--wait-timeout', '360', 'backend'],
            env, 'BACKEND_HEALTH_FAILED', timeout=390)
    healthy_service(back, 'backend', env)
    execute(front + ['up', '-d', '--no-deps', '--force-recreate', '--no-build', '--pull', 'never', '--wait', '--wait-timeout', '120', 'frontend'],
            env, 'FRONTEND_HEALTH_FAILED', timeout=150)
    healthy_service(front, 'frontend', env)
    migration_gate(history(back, env), data['migrations'], rollback=True)
    routing(front, env, settings['publicUrl'])
    # Commit state only after every health, migration and routing check succeeds.
    result = {'id': data['id'], 'backendSha': data['backendSha'], 'frontendSha': data['frontendSha'],
              'migrations': data['migrations'], 'previous': previous['id'] if previous else None,
              'configurationSha': data['configurationSha'], 'images': data['images'],
              'validatedAt': datetime.now(timezone.utc).isoformat(), 'result': 'VALIDATED', 'rollback': rollback}
    (directory / 'validated.json').write_text(json.dumps(result, indent=2) + '\n')
    temporary = base / 'last-successful.tmp'
    temporary.write_text(json.dumps(result, indent=2) + '\n')
    temporary.replace(state_file)
    return result


@contextmanager
def deployment_lock(base=BASE, timeout=900):
    # GitHub concurrency is repository-scoped. This lock also serializes the frontend caller.
    with (base / 'deployment.lock').open('a') as lock:
        deadline = time.monotonic() + timeout
        while True:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                require(time.monotonic() < deadline, 'DEPLOYMENT_LOCK_TIMEOUT')
                time.sleep(1)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['deploy', 'rollback'])
    parser.add_argument('release_id')
    parser.add_argument('--env-file', required=True, type=Path)
    parser.add_argument('--allow-migrations', action='store_true')
    args = parser.parse_args()
    directory = None
    try:
        require(re.fullmatch(RELEASE_ID, args.release_id), 'RELEASE_ID_INVALID')
        require(not args.allow_migrations or args.operation == 'deploy', 'ROLLBACK_CANNOT_APPLY_MIGRATIONS')
        require(args.env_file.resolve().is_relative_to(BASE), 'PRIVATE_ENV_FILE_MUST_BE_INSIDE_PROJECT')
        directory = BASE / 'releases' / args.release_id
        require(not directory.is_symlink() and directory.resolve() == directory, 'RELEASE_DIRECTORY_INVALID')
        data = validate_manifest(json.loads((directory / 'release.json').read_text()))
        require(data['id'] == args.release_id and 'runtime' in data, 'RELEASE_ID_OR_RUNTIME_INVALID')
        for name, digest in data['runtime'].items():
            require(not (directory / name).is_symlink() and file_sha(directory / name) == digest, 'RELEASE_RUNTIME_DIGEST_MISMATCH')
        with deployment_lock():
            (directory / 'attempt.json').write_text(json.dumps({'operation': args.operation,
                'startedAt': datetime.now(timezone.utc).isoformat(), 'allowMigrations': args.allow_migrations}) + '\n')
            result = activate(directory, data, {'envFile': str(args.env_file),
                'publicUrl': 'https://ai-policy.tewendelabs.com'}, args.operation == 'rollback', args.allow_migrations,
                root=directory / 'configuration')
        print(json.dumps(result, indent=2))
    except (DeploymentError, OSError, ValueError, KeyError, TypeError, tarfile.TarError):
        error = sys.exc_info()[1]
        code = str(error) if isinstance(error, DeploymentError) else 'PRODUCTION_RELEASE_FAILED'
        if directory is not None and directory.is_dir():
            try:
                (directory / 'failure.json').write_text(json.dumps({'code': code, 'failedAt': datetime.now(timezone.utc).isoformat()}) + '\n')
            except OSError:
                pass
        print(code, file=sys.stderr)
        print('Release not marked successful; no database rollback was attempted.', file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
