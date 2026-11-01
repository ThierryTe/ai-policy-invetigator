"""Closed diagnostic protocol: no subprocess text, arguments or environment is public.

Both ends validate the protocol. Matching Docker messages selects fixed explanations;
it never copies captured text, even when it contains unknown or multiline secrets.
"""
from contextlib import contextmanager
from contextvars import ContextVar
import json
import re
import sys

PREFIX = 'DEPLOY_DIAGNOSTIC '
PHASE = ContextVar('deployment_phase', default='preflight')
PHASES = {'preflight', 'pull', 'snapshot', 'update', 'verify', 'commit', 'rollback', 'transport'}
PUBLIC_STEPS = {
    'public.root': 'GET https://ai-policy.tewendelabs.com/ [expected HTTP 200, Angular HTML]',
    'public.healthz': 'GET https://ai-policy.tewendelabs.com/healthz [expected HTTP 200, body ok]',
    'public.auth_me': 'GET https://ai-policy.tewendelabs.com/api/auth/me [expected HTTP 401, anonymous]',
}
STEPS = {
    **PUBLIC_STEPS,
    'compose.backend.config': 'docker compose [backend files] config --format json',
    'compose.frontend.config': 'docker compose [frontend files] config --format json',
    'compose.backend.up': 'docker compose [backend files] up -d --no-deps --no-build --pull never --wait --wait-timeout 240 backend',
    'compose.frontend.up': 'docker compose [frontend files] up -d --no-deps --no-build --pull never --wait --wait-timeout 240 frontend',
    'history': 'docker exec --user postgres [postgres container] psql [read Flyway history]',
    'workers.health': 'docker exec [backend container] curl [local actuator health]',
    'state.current': 'write current.json atomically',
    'ssh.prepare': 'ssh [pinned host] [prepare incoming directory]',
    'ssh.transfer': 'scp [deployment bundle] [pinned host]',
    'ssh.deploy': 'ssh [pinned host] python3 simple_deploy.py [operation]',
    'command': '[unlabelled command]',
}
for service in ('backend', 'frontend', 'postgres'):
    STEPS['container.' + service + '.list'] = 'docker ps -aq [project and ' + service + ' service labels]'
    STEPS['container.' + service + '.inspect'] = 'docker inspect [' + service + ' container]'
    STEPS['image.' + service + '.inspect'] = 'docker image inspect [' + service + ' image]'
for service in ('backend', 'frontend'):
    STEPS['image.' + service + '.pull'] = 'docker pull [' + service + ' immutable CI image]'

# Order matters: permission to the daemon socket differs from registry permissions.
RULES = [
    ('daemon_permission', r'permission denied.*(?:docker\.sock|docker daemon socket)|(?:docker\.sock|docker daemon socket).*permission denied',
     'Permission denied on Docker socket; check the deployment user Docker access.'),
    ('daemon_unavailable', r'cannot connect to the docker daemon|is the docker daemon running|error during connect',
     'Docker daemon connection failed; check daemon availability and socket configuration.'),
    ('registry_denied', r'unauthorized|authentication required|denied|forbidden|status(?: code)?:? 40[13]',
     'Registry access denied; check VPS GHCR credentials and package read permissions (CI login is separate).'),
    ('image_missing', r'manifest unknown|manifest.*not found|no such image',
     'Image or resource not found; check published digest, cached rollback image and external resources.'),
    ('disk_full', r'no space left on device|disk quota exceeded',
     'Docker storage is full; check disk space and inodes before retrying.'),
    ('platform_mismatch', r'no matching manifest|does not match the specified platform|exec format error',
     'Image platform is incompatible with the VPS architecture.'),
    ('tls', r'x509:|tls handshake|certificate signed by unknown authority|certificate has expired',
     'TLS verification failed; check trust configuration, registry certificate and system clock.'),
    ('network', r'no such host|temporary failure in name resolution|network is unreachable|i/o timeout|context deadline exceeded|connection refused',
     'Registry or Docker network request failed; check DNS, connectivity and timeout.'),
    ('compose_unsupported', r'unknown flag|unknown shorthand flag|unknown command|is not a docker command|unsupported tag|could not find expected tag|!reset|!override',
     'Compose command or YAML tag unsupported; check the installed Compose plugin version.'),
    ('compose_invalid', r'required variable|missing mandatory value|invalid interpolation|invalid compose|validating .*:|yaml:',
     'Compose configuration invalid or required variable missing; review the private production env and Compose files.'),
    ('external_resource', r'declared as external|external .*not (?:be )?found|network .*not found|volume .*not found',
     'Required external network or volume is missing; review the existing production topology.'),
    ('unhealthy', r'unhealthy|did not pass|health.?check.*fail|timed out.*healthy|timeout.*healthy',
     'Container health check failed; review application readiness and health checks privately on the VPS.'),
    ('container_exited', r'container .*exited|container .*is not running|container .*restarting',
     'Container stopped or is restarting; review its exit status and application startup privately on the VPS.'),
    ('database', r'psql: error:|fatal:|error:.*(?:relation|permission denied for|database)',
     'PostgreSQL history query failed; review database availability, role permissions and schema history privately on the VPS.'),
    ('conflict', r'already in use|conflict|address already in use',
     'Docker resource conflict; review container names and port bindings.'),
]
REASONS = {key: hint for key, _, hint in RULES}
REASONS.update({
    'none': '',
    'unknown': 'Unclassified command failure; raw output withheld because it may contain secrets. Review privately on the VPS.',
    'timeout': 'Command timed out; partial changes are possible. Check the rollback outcome.',
    'unavailable': 'Executable unavailable or could not be started; check installation and execution permissions.',
    'transport_failed': 'SSH transport failed; remote outcome and rollback are unconfirmed. Review VPS state before retrying.',
    'state_write': 'Could not persist deployment state; check filesystem permissions and free space.',
    'remote_failed': 'Remote deployment failed; see the preceding step diagnostics and rollback outcome.',
    'health_http': 'Backend health endpoint returned an HTTP error; review backend and worker readiness privately on the VPS.',
    'health_connection': 'Backend health endpoint could not be reached inside its container; check application startup and listen port.',
    'health_timeout': 'Backend health request timed out; check application and worker readiness.',
    'public_http': 'Unexpected public HTTP status; check the indicated route and public proxy rules.',
    'public_connection': 'Public connection or TLS check failed; check DNS, proxy readiness and certificate trust.',
    'public_application': 'Public root did not serve Angular HTML.',
    'public_health_body': 'Public frontend health did not return ok.',
})
CODES = frozenset('''
COMMAND_FAILED_DOCKER COMMAND_FAILED_COMMAND COMMAND_UNAVAILABLE_OR_TIMED_OUT
EXISTING_CONTAINER_REQUIRED_BACKEND EXISTING_CONTAINER_REQUIRED_FRONTEND EXISTING_CONTAINER_REQUIRED_POSTGRES
CONTAINER_UNHEALTHY HEALTHY_V8_HISTORY_REQUIRED PUBLIC_TLS_OR_CONNECTION_FAILED PUBLIC_HTTP_CHECK_FAILED
ANGULAR_APPLICATION_MISSING FRONTEND_HEALTH_BODY_INVALID RUNNING_IMAGE_MISMATCH BACKEND_OR_WORKERS_NOT_READY
SET_BOTH_WORKER_FLAGS_TRUE META_KEY_REQUIRED UNEXPECTED_PRODUCTION_HOST_PORTS
EXISTING_NETWORKS_DIFFER_REVIEW_SETUP EXISTING_VOLUMES_DIFFER_REVIEW_SETUP
SCHEMA_CHANGED_ROLLBACK_BLOCKED SCHEMA_CHANGED_DURING_ROLLBACK UNEXPECTED_SCHEMA_CHANGE
DEPLOY_FAILED_ROLLBACK_FAILED_OR_BLOCKED_REVIEW_PRIVATE_STATE DEPLOY_FAILED_ROLLBACK_SUCCEEDED_DATABASE_UNCHANGED
ANOTHER_DEPLOYMENT_IS_RUNNING PRIVATE_PRODUCTION_ENV_REQUIRED BUNDLE_PATH_INVALID PREVIOUS_FAILURE_REQUIRES_REVIEW
ROLLBACK_FAILED_OR_SCHEMA_CHANGED_REVIEW_PRIVATE_STATE DEPLOYMENT_INPUT_OR_STATE_INVALID
DEPLOY_SUCCEEDED ROLLBACK_STARTED ROLLBACK_SUCCEEDED ROLLBACK_FAILED
SSH_TRANSFER_OR_REMOTE_DEPLOYMENT_FAILED SSH_REMOTE_OUTCOME_UNCONFIRMED
'''.split())


def classify(stdout, stderr, *, step='command', exit_code=None):
    def decoded(value):
        return value.decode('utf-8', errors='replace') if isinstance(value, bytes) else (value or '')
    # Only the selected enum escapes this function, never a matching substring.
    text = decoded(stderr) + '\n' + decoded(stdout)
    for reason, pattern, _ in RULES:
        if reason == 'registry_denied' and step not in ('command', 'image.backend.pull', 'image.frontend.pull'):
            continue
        if re.search(pattern, text, re.IGNORECASE):
            return reason
    if step == 'workers.health':
        # curl --silent provides no stderr for these failures.
        return {7: 'health_connection', 22: 'health_http', 28: 'health_timeout'}.get(exit_code, 'unknown')
    return 'unknown'


def validated_event(value):
    if not isinstance(value, dict):
        return False
    public = isinstance(value.get('step'), str) and value['step'] in PUBLIC_STEPS
    fields = {'phase', 'step', 'result', 'reason', 'exit_code'}
    if public:
        fields |= {'http_status', 'attempt'}
    if set(value) != fields:
        return False
    if public and not (
            (value['http_status'] is None or (type(value['http_status']) is int and 100 <= value['http_status'] <= 599))
            and type(value['attempt']) is int and 1 <= value['attempt'] <= 100):
        return False
    if any(not isinstance(value[k], str) for k in ('phase', 'step', 'result', 'reason')):
        return False
    code = value['exit_code']
    return (value['phase'] in PHASES and value['step'] in STEPS
            and value['result'] in {'started', 'failed', 'succeeded'} and value['reason'] in REASONS
            and (code is None or (type(code) is int and -255 <= code <= 255)))


def render_event(value):
    detail = (' attempt={attempt} http_status={http_status}'.format(**value)
              if value['step'] in PUBLIC_STEPS else '')
    print('phase={phase} step={step} result={result} exit={exit_code} command="{command}" reason={reason}: {hint}'.format(
        **value, command=STEPS[value['step']], hint=REASONS[value['reason']]) + detail, file=sys.stderr, flush=True)


def emit(step, result, reason='none', exit_code=None, *, render=False, http_status=None, attempt=None):
    value = dict(phase=PHASE.get(), step=step, result=result, reason=reason, exit_code=exit_code)
    if step in PUBLIC_STEPS:
        value.update(http_status=http_status, attempt=attempt)
    if validated_event(value):
        if render:
            render_event(value)
        else:
            print(PREFIX + json.dumps(value, sort_keys=True), file=sys.stderr, flush=True)


def public_code(error):
    code = str(error)
    return code if code in CODES else 'DEPLOYMENT_INPUT_OR_STATE_INVALID'


def status(code):
    print(public_code(code), file=sys.stderr, flush=True)


def forward(output):
    """Decode untrusted SSH output, then render only values from the closed vocabulary."""
    if isinstance(output, bytes):
        output = output.decode('utf-8', errors='replace')
    codes = []
    for line in (output or '').splitlines():
        if line in CODES:
            status(line)
            codes.append(line)
        elif line.startswith(PREFIX):
            try:
                value = json.loads(line[len(PREFIX):])
            except (ValueError, RecursionError):
                continue
            if validated_event(value):
                # Never echo the original line, extra fields, raw command or free text.
                render_event(value)
    return codes


@contextmanager
def phase(name):
    token = PHASE.set(name)
    try:
        yield
    finally:
        PHASE.reset(token)
