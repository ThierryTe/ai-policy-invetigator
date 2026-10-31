#!/usr/bin/env python3
"""Runner entry point: reuse the approved images, existing SSH transport and release lock."""
import argparse
import json
import os
from pathlib import Path
import re
import sys
import tarfile

from deploy_local_images import DeploymentError, REPOSITORIES, require
from prepare_production_release import prepare, ghcr_manifest
from publish_release_images import configuration, SOURCE_REPOSITORIES
from release_artifacts import SHA, RELEASE_ID
from release_safety import CONFIRMATIONS
from reviewed_v8_release import APPROVED, validate_candidate
from transfer_production_release import transfer, current_release
from v7_backup_restore import ENV_FILE


def validate(env):
    operation = env.get('OPERATION')
    require(operation in ('prepare-reviewed', 'deploy-reviewed'), 'REVIEWED_OPERATION_REQUIRED')
    require(re.fullmatch(RELEASE_ID, env.get('EXPECTED_PREVIOUS', '')), 'APPROVED_PREVIOUS_RELEASE_REQUIRED')
    require(env.get('VPS_ENV_FILE') == str(ENV_FILE), 'PRODUCTION_ENV_PATH_INVALID')
    if operation == 'prepare-reviewed':
        require(env.get('ALLOW_MIGRATIONS') == 'false', 'PREPARATION_CANNOT_MIGRATE')
        require(not env.get('PREPARED_RELEASE'), 'PREPARATION_CANNOT_REUSE_RELEASE_ID')
        require(re.fullmatch(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}', env.get('V7_DEMO_INVESTIGATION_ID', '')),
                'COMPLETED_PRODUCTION_DEMO_UUID_REQUIRED')
        require(Path(env.get('V7_BACKUP_DIR', '')).is_absolute(), 'PRIVATE_BACKUP_DIRECTORY_REQUIRED')
    else:
        require(re.fullmatch(RELEASE_ID, env.get('PREPARED_RELEASE', '')), 'PREPARED_RELEASE_ID_REQUIRED')
        require(env.get('ALLOW_MIGRATIONS') == 'true' and env.get('RELEASE_PHASE') == 'migrate-v8', 'EXPLICIT_V8_MIGRATION_APPROVAL_REQUIRED')
        for key in ['GITHUB_PROTECTION', 'WRITE_FREEZE', 'IMAGE_QUALIFICATION']:
            require(env.get('CONFIRM_' + key) == 'true', 'HUMAN_RELEASE_APPROVALS_REQUIRED')
        require(re.fullmatch(r'[A-Z0-9][A-Z0-9._-]{2,79}', env.get('EVIDENCE_REF', '')), 'NONSECRET_CHANGE_RECORD_REFERENCE_REQUIRED')
        require(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,63}', env.get('RELEASE_OPERATOR', '')), 'RELEASE_OPERATOR_REQUIRED')
    require(not any(env.get(k) for k in ['BACKEND_SHA', 'FRONTEND_SHA', 'ROLLBACK_RELEASE']), 'REVIEWED_OPERATION_USES_PINNED_PAIR')


def reviewed_revisions():
    revisions = []
    for key, component in [('BACKEND_IMAGE_REF', 'backend'), ('FRONTEND_IMAGE_REF', 'frontend')]:
        metadata = ghcr_manifest(REPOSITORIES[key], APPROVED[key])
        require(metadata['indexDigest'] == APPROVED[key], 'APPROVED_IMAGE_DIGEST_CHANGED')
        labels = configuration(REPOSITORIES[key], metadata)['config']['Labels']
        revision = labels.get('org.opencontainers.image.revision', '')
        require(re.fullmatch(SHA, revision) and labels.get('org.opencontainers.image.source') == SOURCE_REPOSITORIES[component],
                'APPROVED_IMAGE_SOURCE_IDENTITY_INVALID')
        revisions.append(revision)
    return revisions


def run(env, output):
    validate(env)
    require(env.get('GITHUB_EVENT_NAME') == 'workflow_dispatch'
            and env.get('GITHUB_REPOSITORY') == 'ThierryTe/ai-policy-invetigator'
            and env.get('GITHUB_REF') == 'refs/heads/main', 'MANUAL_BACKEND_MAIN_DISPATCH_REQUIRED')
    require(current_release() == env['EXPECTED_PREVIOUS'], 'APPROVED_RELEASE_BASE_CHANGED')
    if env['OPERATION'] == 'prepare-reviewed':
        require(re.fullmatch(SHA, env.get('CONFIGURATION_SHA', '')), 'CONFIGURATION_SHA_REQUIRED')
        require(env.get('GITHUB_RUN_ID', '').isdecimal() and env.get('GITHUB_RUN_ATTEMPT', '').isdecimal(), 'GITHUB_RUN_ID_INVALID')
        backend, frontend = reviewed_revisions()
        identity = 'r0' + env['GITHUB_RUN_ID'] + '-' + str(int(env['GITHUB_RUN_ATTEMPT']) * 10 + 1)
        output.mkdir(parents=True, exist_ok=True)
        directory = output / identity
        data = prepare(directory, backend, frontend, env['CONFIGURATION_SHA'], identity, approved_images=APPROVED)
        data['expectedPrevious'] = env['EXPECTED_PREVIOUS']
        data['v7Preparation'] = {'expected_previous': env['EXPECTED_PREVIOUS'], 'env_file': str(ENV_FILE),
                                 'demo_id': env['V7_DEMO_INVESTIGATION_ID'], 'backup_root': env['V7_BACKUP_DIR']}
        validate_candidate(data)
        (directory / 'release.json').write_text(json.dumps(data, indent=2) + '\n')
        return transfer('prepare-reviewed', identity, directory)
    # The immutable approved index resolves to the same reviewed amd64 child.
    metadata = ghcr_manifest(REPOSITORIES['BACKEND_IMAGE_REF'], APPROVED['BACKEND_IMAGE_REF'])
    approval_env = {key: env.get(key, '') for key in ['EXPECTED_PREVIOUS', 'RELEASE_PHASE', 'RELEASE_OPERATOR', 'EVIDENCE_REF']}
    approval_env['APPROVED_BACKEND_DIGEST'] = metadata['manifestDigest']
    for key in CONFIRMATIONS:
        approval_env['CONFIRM_' + key.upper()] = env.get('CONFIRM_' + key.upper(), 'false') if key in (
            'github_protection', 'write_freeze', 'image_qualification') else 'false'
    # Human approvals validated above. Backup confirmations are earned on the VPS;
    # activate() is unreachable unless the fresh frozen backup/restore succeeds.
    approval = {'expected_previous': env['EXPECTED_PREVIOUS'], 'environment': approval_env,
                'runId': env['GITHUB_RUN_ID'], 'runAttempt': env['GITHUB_RUN_ATTEMPT'],
                'automatedChecksRequired': ['v7_preflight', 'v7_backup', 'isolated_restore']}
    return transfer('deploy-reviewed', env['PREPARED_RELEASE'], allow_migrations=True, approval=approval)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--validate-only', action='store_true')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    try:
        if args.validate_only:
            validate(os.environ)
        else:
            print(json.dumps(run(os.environ, args.output), indent=2))
    except (DeploymentError, OSError, ValueError, KeyError, TypeError, tarfile.TarError):
        error = sys.exc_info()[1]
        print(str(error) if isinstance(error, DeploymentError) else 'REVIEWED_RELEASE_PIPELINE_FAILED', file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
