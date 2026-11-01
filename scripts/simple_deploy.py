#!/usr/bin/env python3
"""VPS-only image updates; no database writes, builds, pruning or legacy orchestration."""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.request

from simple_diagnostics import ROLLBACK, classify, emit, failure, phase, public_code, status

# Checked locally against the tested artifact before any SSH operation.
DIAGNOSTIC_PROTOCOL = 2

BASE = Path('/opt/ai-policy-investigator')
PUBLIC = 'https://ai-policy.tewendelabs.com'
PUBLIC_USER_AGENT = 'AI-Policy-Investigator-Deployment/1.0'
PUBLIC_TIMEOUT = 10
PUBLIC_ATTEMPTS = 12
PUBLIC_RETRY_DELAY = 5
PROJECT = 'ai-policy-investigator'
UI_PROJECT = 'ai-policy-investigator-ui'
FILES = ('compose.yaml', 'compose.production.yaml', 'compose.images.yaml', 'compose.frontend.yaml')


class DeployError(Exception):
    pass


def require(condition, code):
    if not condition:
        raise DeployError(code)


def run(command, env=None, timeout=360, *, step='command'):
    emit(step, 'started')
    try:
        result = subprocess.run(command, env=env, text=True, errors='replace', capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        error = DeployError('COMMAND_UNAVAILABLE_OR_TIMED_OUT')
        failure(error, 'timeout')
        raise error from None
    except OSError:
        error = DeployError('COMMAND_UNAVAILABLE_OR_TIMED_OUT')
        failure(error, 'unavailable')
        raise error from None
    if result.returncode:
        error = DeployError('COMMAND_FAILED_DOCKER' if command[0] == 'docker' else 'COMMAND_FAILED_COMMAND')
        failure(error, classify(result.stdout, result.stderr, step=step, exit_code=result.returncode), result.returncode)
        raise error
    return result.stdout


def save(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, indent=2) + '\n')
    temporary.chmod(0o600)
    temporary.replace(path)


def record_current(state, value):
    emit('state.current', 'started')
    try:
        save(state / 'current.json', value)
    except OSError:
        failure(sys.exc_info()[1], 'state_write')
        raise


def container(project, service):
    ids = run(['docker', 'ps', '-aq', '--filter', 'label=com.docker.compose.project=' + project,
               '--filter', 'label=com.docker.compose.service=' + service], step='container.' + service + '.list').split()
    require(len(ids) == 1, 'EXISTING_CONTAINER_REQUIRED_' + service.upper())
    return json.loads(run(['docker', 'inspect', ids[0]], step='container.' + service + '.inspect'))[0]


def healthy(row):
    require(row['State']['Running'] and row['State'].get('Health', {}).get('Status') == 'healthy',
            'CONTAINER_UNHEALTHY')


def history():
    postgres = container(PROJECT, 'postgres')
    healthy(postgres)
    sql = "SELECT coalesce(json_agg(t ORDER BY installed_rank),'[]'::json) FROM (SELECT installed_rank,version,script,checksum,success,type FROM public.flyway_schema_history) t"
    rows = json.loads(run(['docker', 'exec', '--user', 'postgres', postgres['Id'], 'psql', '-X', '-U', 'postgres',
                          '-d', 'investigator', '-At', '-v', 'ON_ERROR_STOP=1', '-c', sql], step='history'))
    require(rows and all(r['success'] for r in rows) and any(r['version'] == '8' for r in rows), 'HEALTHY_V8_HISTORY_REQUIRED')
    return rows


def public_check(*, attempt=1):
    # Standard TLS certificate validation, no redirects to another host or login page.
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, request, fp, code, msg, headers, newurl):
            return None
    opener = urllib.request.build_opener(NoRedirect)
    for path, expected, step in [('/', 200, 'public.root'), ('/healthz', 200, 'public.healthz'),
                                ('/api/auth/me', 401, 'public.auth_me')]:
        emit(step, 'started', attempt=attempt)
        # Match the identified probe in production_release.py: public edges may
        # reject Python's generic agent even while browser requests succeed.
        request = urllib.request.Request(PUBLIC + path, method='GET', headers={
            'User-Agent': PUBLIC_USER_AGENT})
        try:
            with opener.open(request, timeout=PUBLIC_TIMEOUT) as response:
                code = response.status
                body = response.read(1_000_000)
        except urllib.error.HTTPError as error:
            with error:
                code, body = error.code, b''
        except (OSError, urllib.error.URLError):
            emit(step, 'failed', 'public_connection', attempt=attempt)
            raise DeployError('PUBLIC_TLS_OR_CONNECTION_FAILED') from None
        failure = None
        if code != expected:
            failure = ('PUBLIC_HTTP_CHECK_FAILED', 'public_http')
        elif path == '/' and b'<app-root' not in body:
            failure = ('ANGULAR_APPLICATION_MISSING', 'public_application')
        elif path == '/healthz' and body.strip() != b'ok':
            failure = ('FRONTEND_HEALTH_BODY_INVALID', 'public_health_body')
        if failure:
            emit(step, 'failed', failure[1], http_status=code, attempt=attempt)
            raise DeployError(failure[0])
        emit(step, 'succeeded', http_status=code, attempt=attempt)


def wait_for_public():
    # Allow public proxy routes and Docker DNS to settle after container replacement.
    for attempt in range(1, PUBLIC_ATTEMPTS + 1):
        try:
            public_check(attempt=attempt)
            return
        except DeployError:
            if attempt == PUBLIC_ATTEMPTS:
                raise
            time.sleep(PUBLIC_RETRY_DELAY)


def verify(images):
    back, front, postgres = container(PROJECT, 'backend'), container(UI_PROJECT, 'frontend'), container(PROJECT, 'postgres')
    for row in (back, front, postgres):
        healthy(row)
    for component, row in [('backend', back), ('frontend', front)]:
        expected = json.loads(run(['docker', 'image', 'inspect', images[component]], step='image.' + component + '.inspect'))[0]['Id']
        require(row['Image'] == expected, 'RUNNING_IMAGE_MISMATCH')
    # This endpoint aggregates DB and the workers indicator (successful queue polls + a local embedding).
    result = run(['docker', 'exec', back['Id'], 'curl', '--fail', '--silent', '--max-time', '20',
                  'http://127.0.0.1:8080/actuator/health'], step='workers.health') if images.get('worker_probe', True) else None
    if result is not None:
        require(json.loads(result).get('status') == 'UP', 'BACKEND_OR_WORKERS_NOT_READY')
    wait_for_public()


def commands(bundle, env_file, images):
    env = {'PATH': os.environ['PATH'], 'HOME': os.environ['HOME'],
           'BACKEND_IMAGE_REF': images['backend'], 'FRONTEND_IMAGE_REF': images['frontend'],
           'POSTGRES_IMAGE_REF': images['postgres']}
    common = ['docker', 'compose', '--project-directory', str(bundle), '--env-file', str(env_file)]
    back = common + ['-p', PROJECT]
    for file in FILES[:3]:
        back += ['-f', str(bundle / file)]
    back += ['--profile', 'app']
    front = common + ['-p', UI_PROJECT, '-f', str(bundle / FILES[3])]
    if (bundle / 'runtime.json').is_file():
        back += ['-f', str(bundle / 'runtime.json')]
    if (bundle / 'frontend-runtime.json').is_file():
        front += ['-f', str(bundle / 'frontend-runtime.json')]
    return back, front, env


def check_topology(bundle, env_file, images):
    back, front, env = commands(bundle, env_file, images)
    config = json.loads(run(back + ['config', '--format', 'json'], env, step='compose.backend.config'))
    web = json.loads(run(front + ['config', '--format', 'json'], env, step='compose.frontend.config'))
    for name in ('APP_WORKER_ENABLED', 'APP_INVESTIGATION_WORKER_ENABLED'):
        require(config['services']['backend']['environment'][name] == 'true', 'SET_BOTH_WORKER_FLAGS_TRUE')
    require(bool(config['services']['backend']['environment'].get('MODEL_API_KEY', '').strip()), 'META_KEY_REQUIRED')
    for project, service, definition in [(PROJECT, 'backend', config), (PROJECT, 'postgres', config), (UI_PROJECT, 'frontend', web)]:
        row = container(project, service)
        healthy(row)
        require(not row['HostConfig'].get('PortBindings'), 'UNEXPECTED_PRODUCTION_HOST_PORTS')
        desired_networks = {definition['networks'][n]['name'] for n in definition['services'][service]['networks']}
        require(set(row['NetworkSettings']['Networks']) == desired_networks, 'EXISTING_NETWORKS_DIFFER_REVIEW_SETUP')
        desired_volumes = {(definition['volumes'][v['source']]['name'], v['target'], not v.get('read_only', False))
                           for v in definition['services'][service].get('volumes', []) if v['type'] == 'volume'}
        actual_volumes = {(v['Name'], v['Destination'], v['RW']) for v in row.get('Mounts', []) if v['Type'] == 'volume'}
        require(desired_volumes == actual_volumes, 'EXISTING_VOLUMES_DIFFER_REVIEW_SETUP')
    return back, front, env


def snapshot(bundle, env_file, state):
    back, front, pg = container(PROJECT, 'backend'), container(UI_PROJECT, 'frontend'), container(PROJECT, 'postgres')
    for row in (back, front, pg):
        healthy(row)
    destination = state / ('snapshot-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f'))
    current = state / 'current.json'
    source = Path(json.loads(current.read_text())['bundle']) if current.is_file() else bundle
    shutil.copytree(source, destination)
    shutil.copyfile(env_file, destination / 'production.env')
    (destination / 'production.env').chmod(0o600)
    # Preserve the actual previous worker flags, environment and health command, including V8 images without curl.
    for service, row, name in [('backend', back, 'runtime.json'), ('frontend', front, 'frontend-runtime.json')]:
        # Compose interpolates JSON strings too; preserve literal dollar signs in secrets.
        environment = {key: value.replace('$', '$$') for key, value in
                       (entry.split('=', 1) for entry in row['Config']['Env'])}
        if service == 'backend':
            # Schema equality is checked separately. Old images must never auto-migrate on rollback.
            environment['SPRING_FLYWAY_ENABLED'] = 'false'
        health = row['Config'].get('Healthcheck') or {}
        options = {'Test': 'test', 'Interval': 'interval', 'Timeout': 'timeout', 'StartPeriod': 'start_period', 'Retries': 'retries'}
        healthcheck = {options[k]: (str(v) + 'ns' if k in ('Interval', 'Timeout', 'StartPeriod') else v)
                       for k, v in health.items() if k in options}
        runtime = {'environment': environment, 'healthcheck': healthcheck}
        for original, option in [('Cmd', 'command'), ('Entrypoint', 'entrypoint'), ('User', 'user'), ('WorkingDir', 'working_dir')]:
            if original in row['Config']:
                runtime[option] = row['Config'][original]
        host = row.get('HostConfig', {})
        if 'ReadonlyRootfs' in host:
            runtime['read_only'] = host['ReadonlyRootfs']
        if host.get('Memory'):
            runtime['mem_limit'] = host['Memory']
        save(destination / name, {'services': {service: runtime}})
    images = {'backend': back['Image'], 'frontend': front['Image'], 'postgres': pg['Image'],
              'worker_probe': False}
    # Keep available registry manifest digests as well as immutable local image IDs.
    digests = {s: json.loads(run(['docker', 'image', 'inspect', row['Image']], step='image.' + s + '.inspect'))[0].get('RepoDigests', [])
               for s, row in [('backend', back), ('frontend', front), ('postgres', pg)]}
    record = {'bundle': str(destination), 'env_file': str(destination / 'production.env'),
              'images': images, 'registry_digests': digests, 'history': history()}
    save(destination / 'snapshot.json', record)
    return record


def restore(previous):
    require(history() == previous['history'], 'SCHEMA_CHANGED_ROLLBACK_BLOCKED')
    back, front, env = commands(Path(previous['bundle']), Path(previous['env_file']), previous['images'])
    for command, service in [(back, 'backend'), (front, 'frontend')]:
        run(command + ['up', '-d', '--no-deps', '--no-build', '--pull', 'never', '--wait', '--wait-timeout', '240', service],
            env, step='compose.' + service + '.up')
    verify(previous['images'])
    require(history() == previous['history'], 'SCHEMA_CHANGED_DURING_ROLLBACK')


def deploy(bundle, env_file, state):
    ROLLBACK.set('not_started')
    # Imported only for deployment; rollback uses cached images and snapshot metadata.
    from ci_images import validate
    data = validate(json.loads((bundle / 'images.json').read_text()))
    images = {**data['images'], 'postgres': container(PROJECT, 'postgres')['Image']}
    back, front, env = check_topology(bundle, env_file, images)
    # Preflight checks the existing release too; a transient public edge failure
    # must get the same settling period before any pull or application update.
    wait_for_public()
    # Pull both images before touching either running service. Never pull PostgreSQL or models.
    with phase('pull'):
        for component in ('backend', 'frontend'):
            run(['docker', 'pull', images[component]], timeout=300, step='image.' + component + '.pull')
    with phase('snapshot'):
        previous = snapshot(bundle, env_file, state)
        save(state / 'previous.json', previous)
    try:
        with phase('update'):
            for command, service in [(back, 'backend'), (front, 'frontend')]:
                run(command + ['up', '-d', '--no-deps', '--no-build', '--pull', 'never', '--wait', '--wait-timeout', '240', service],
                    env, step='compose.' + service + '.up')
        with phase('verify'):
            verify(images)
            require(history() == previous['history'], 'UNEXPECTED_SCHEMA_CHANGE')
        with phase('commit'):
            record_current(state, {'bundle': str(bundle), 'images': images, 'ci_run': data['run_id'],
                                   'backend_sha': data['backend_sha'], 'frontend_sha': data['frontend_sha']})
    except Exception as error:
        failure(error)
        status(public_code(error))
        with phase('rollback'):
            status('ROLLBACK_STARTED')
            try:
                restore(previous)
            except Exception as rollback_error:
                failure(rollback_error)
                status(public_code(rollback_error))
                status('ROLLBACK_FAILED')
                save(state / 'blocked.json', {'reason': 'ROLLBACK_FAILED_OR_SCHEMA_CHANGED', 'snapshot': previous['bundle']})
                raise DeployError('DEPLOY_FAILED_ROLLBACK_FAILED_OR_BLOCKED_REVIEW_PRIVATE_STATE') from None
            status('ROLLBACK_SUCCEEDED')
        raise DeployError('DEPLOY_FAILED_ROLLBACK_SUCCEEDED_DATABASE_UNCHANGED') from None
    status('DEPLOY_SUCCEEDED')


@contextmanager
def deployment_lock(state):
    with (state / 'deploy.lock').open('w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise DeployError('ANOTHER_DEPLOYMENT_IS_RUNNING') from None
        yield


@phase('preflight')
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['deploy', 'rollback'])
    parser.add_argument('--bundle', type=Path, required=True)
    args = parser.parse_args()
    rollback_token = ROLLBACK.set('not_started')
    os.umask(0o077)
    state = BASE / 'simple-deploy'
    env_file = BASE / '.env.production'
    try:
        require(env_file.is_file() and not env_file.is_symlink()
                and env_file.stat().st_uid == os.geteuid()
                and stat.S_IMODE(env_file.stat().st_mode) & 0o077 == 0, 'PRIVATE_PRODUCTION_ENV_REQUIRED')
        bundle = args.bundle.resolve()
        require(bundle.is_relative_to(state / 'incoming') and bundle.is_dir(), 'BUNDLE_PATH_INVALID')
        state.mkdir(mode=0o700, exist_ok=True)
        with deployment_lock(state):
            require(not (state / 'blocked.json').exists(), 'PREVIOUS_FAILURE_REQUIRES_REVIEW')
            if args.operation == 'rollback':
                previous = json.loads((state / 'previous.json').read_text())
                with phase('rollback'):
                    status('ROLLBACK_STARTED')
                    try:
                        restore(previous)
                        record_current(state, {'bundle': previous['bundle'], 'images': previous['images'], 'rollback': True})
                    except Exception as error:
                        failure(error)
                        status(public_code(error))
                        status('ROLLBACK_FAILED')
                        save(state / 'blocked.json', {'reason': 'ROLLBACK_FAILED_OR_SCHEMA_CHANGED', 'snapshot': previous['bundle']})
                        raise DeployError('ROLLBACK_FAILED_OR_SCHEMA_CHANGED_REVIEW_PRIVATE_STATE') from None
                    status('ROLLBACK_SUCCEEDED')
            else:
                deploy(bundle, env_file, state)
    except Exception as error:
        failure(error)
        status(public_code(error) if isinstance(error, DeployError) else 'DEPLOYMENT_INPUT_OR_STATE_INVALID')
        return 1
    finally:
        ROLLBACK.reset(rollback_token)
    return 0


if __name__ == '__main__':
    sys.exit(main())
