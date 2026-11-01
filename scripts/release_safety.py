"""V8 delivery gates; operator attestations are never external-check verification."""
import hashlib
import json
import re
from pathlib import Path

from deploy_local_images import require

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = 'docs/verification/v8-artifact.json'
EVIDENCE_SHA256 = '405ee2075eeb9db5eb090e208d848e16eb805977553e4a9917cd765e83cc2fad'
CONFIRMATIONS = ('github_protection', 'v7_preflight', 'v7_backup', 'isolated_restore',
                 'write_freeze', 'image_qualification', 'v8_acceptance', 'worker_reactivation')
COMMON = {'github_protection', 'write_freeze', 'image_qualification'}
REQUIRED = {'migrate-v8': COMMON | {'v7_preflight', 'v7_backup', 'isolated_restore'},
            'activate-v8': COMMON | {'v8_acceptance', 'worker_reactivation'}}
WORKERS = ('APP_WORKER_ENABLED', 'APP_INVESTIGATION_WORKER_ENABLED')
ACTIVATION_IDENTITY_FIELDS = ('backendSha', 'frontendSha', 'configurationSha', 'configuration', 'runtime', 'migrations')


def explicit_worker_inputs(path):
    """Require one literal per flag in the private env file; never echo its contents."""
    values = {}
    for line in path.read_text().splitlines():
        match = re.match(r'^\s*(?:export\s+)?(APP_WORKER_ENABLED|APP_INVESTIGATION_WORKER_ENABLED)\s*=\s*(.*)$', line)
        if match:
            key, raw = match.groups()
            literal = re.fullmatch(r'(true|false)(?:\s+#.*)?', raw.strip())
            require(key not in values and literal is not None, 'AMBIGUOUS_PRODUCTION_WORKER_INPUT')
            values[key] = literal[1]
    require(set(values) == set(WORKERS), 'EXPLICIT_PRODUCTION_WORKER_INPUTS_REQUIRED')
    return values


def qualified_migrations():
    body = (ROOT / EVIDENCE).read_bytes()
    require(hashlib.sha256(body).hexdigest() == EVIDENCE_SHA256, 'V8_QUALIFICATION_EVIDENCE_CHANGED')
    rows = json.loads(body)['migrations']
    require([r['version'] for r in rows] == [str(n) for n in range(1, 9)], 'V8_QUALIFICATION_INVENTORY_INVALID')
    return rows


def validate_attestation(record):
    require(isinstance(record, dict) and set(record) == {
        'phase', 'expected_previous', 'approved_backend_digest', 'operator', 'evidence_ref',
        'confirmations', 'qualified_evidence_sha256', 'external_checks_verified_by_automation',
        'binary_identity_verified'}, 'RELEASE_ATTESTATION_REQUIRED')
    phase = record['phase']
    require(isinstance(phase, str) and phase in REQUIRED, 'EXPLICIT_V8_PHASE_REQUIRED')
    require(isinstance(record['expected_previous'], str)
            and re.fullmatch(r'r[0-9]+-[0-9]+', record['expected_previous']), 'APPROVED_PREVIOUS_RELEASE_REQUIRED')
    require(isinstance(record['approved_backend_digest'], str)
            and re.fullmatch(r'sha256:[0-9a-f]{64}', record['approved_backend_digest']), 'APPROVED_BACKEND_DIGEST_REQUIRED')
    require(isinstance(record['operator'], str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,63}', record['operator']),
            'RELEASE_OPERATOR_REQUIRED')
    require(isinstance(record['evidence_ref'], str) and re.fullmatch(r'[A-Z0-9][A-Z0-9._-]{2,79}', record['evidence_ref']),
            'NONSECRET_CHANGE_RECORD_REFERENCE_REQUIRED')
    require(record['qualified_evidence_sha256'] == EVIDENCE_SHA256, 'V8_QUALIFICATION_REFERENCE_MISMATCH')
    require(record['external_checks_verified_by_automation'] is False and record['binary_identity_verified'] is False,
            'ATTESTATIONS_ARE_NOT_VERIFICATION')
    confirms = record['confirmations']
    require(isinstance(confirms, dict) and set(confirms) == set(CONFIRMATIONS)
            and all(type(v) is bool for v in confirms.values()), 'AMBIGUOUS_OPERATOR_CONFIRMATIONS')
    require({k for k, v in confirms.items() if v} == REQUIRED[phase], 'PHASE_OPERATOR_CONFIRMATIONS_REQUIRED')
    return phase


def from_environment(env):
    confirmations = {}
    for key in CONFIRMATIONS:
        value = env.get('CONFIRM_' + key.upper(), 'false')
        require(value in ('true', 'false'), 'AMBIGUOUS_OPERATOR_CONFIRMATIONS')
        confirmations[key] = value == 'true'
    record = {'phase': env.get('RELEASE_PHASE', ''), 'expected_previous': env.get('EXPECTED_PREVIOUS', ''),
              'approved_backend_digest': env.get('APPROVED_BACKEND_DIGEST', ''),
              'operator': env.get('RELEASE_OPERATOR', ''), 'evidence_ref': env.get('EVIDENCE_REF', ''),
              'confirmations': confirmations, 'qualified_evidence_sha256': EVIDENCE_SHA256,
              'external_checks_verified_by_automation': False, 'binary_identity_verified': False}
    validate_attestation(record)
    return record


def validate_release(data, allow_migrations):
    record = data.get('releaseSafety')
    phase = validate_attestation(record)
    require(type(allow_migrations) is bool and allow_migrations == (phase == 'migrate-v8'),
            'PHASE_MIGRATION_PERMISSION_MISMATCH')
    require(data.get('expectedPrevious') == record['expected_previous'], 'APPROVED_RELEASE_BASE_MISMATCH')
    require(data.get('migrations') == qualified_migrations(), 'IMAGE_MIGRATIONS_NOT_QUALIFIED_V8')
    require(data['images']['BACKEND_IMAGE_REF']['manifestDigest'] == record['approved_backend_digest'],
            'BACKEND_IMAGE_NOT_OPERATOR_APPROVED_DIGEST')
    return phase


def validate_workers(config, phase):
    values = config['services']['backend']['environment']
    expected = 'false' if phase == 'migrate-v8' else 'true'
    require(phase in REQUIRED and all(type(values.get(k)) is str and values[k] == expected for k in WORKERS),
            'WORKER_FLAGS_MUST_MATCH_EXPLICIT_PHASE')


def validate_target(data, previous, applied, phase):
    require(previous is not None and previous.get('id') == data['expectedPrevious'], 'APPROVED_RELEASE_BASE_CHANGED')
    versions = [r.get('version') for r in applied]
    require(versions == [str(n) for n in range(1, 8 if phase == 'migrate-v8' else 9)],
            'V8_PHASE_DATABASE_HISTORY_MISMATCH')
    if phase == 'activate-v8':
        require(previous.get('releaseSafety', {}).get('phase') == 'migrate-v8', 'VALIDATED_DISABLED_WORKER_PHASE_REQUIRED')
        divergent = [key for key in ACTIVATION_IDENTITY_FIELDS if key not in previous or data.get(key) != previous[key]]
        require(not divergent, 'ACTIVATION_MUST_REUSE_MIGRATION_RELEASE: divergent_fields=' + ','.join(divergent))
        require(set(previous.get('images', {})) == set(data['images']), 'ACTIVATION_IMAGE_SET_CHANGED')
        for key, image in data['images'].items():
            require(all(image.get(field) == previous['images'][key].get(field)
                        for field in ('manifestDigest', 'configDigest', 'sourceRef', 'localRef')),
                    'ACTIVATION_IMAGE_SET_CHANGED')
