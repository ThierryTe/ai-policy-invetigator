#!/usr/bin/env python3
"""VPS entry point for preparation and explicitly approved migration of retained images."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
import subprocess
import tarfile

from deploy_local_images import DeploymentError, require, execute
from release_artifacts import validate_manifest, file_sha, RELEASE_ID
from release_safety import from_environment, qualified_migrations, validate_release
from production_release import BASE, deployment_lock, reviewed_configuration, verify_archives, activate
from v7_backup_restore import ENV_FILE, PG_MANIFEST, PG_CONFIG, DOCKER_ENV, private_env, source, verify_backup, psql, TOOLS, private_run
from v7_backup_restore import restore_start_timeout, RESTORE_START_TIMEOUT_SECONDS

APPROVED = {
    'BACKEND_IMAGE_REF': 'sha256:97a96a48cb9e4ec47726cbcf7f9a7219ec174483165de23c9ed103e16ea813cb',
    'FRONTEND_IMAGE_REF': 'sha256:89517d956a3d348e364b8028e8695c42d206fd9eb26e9adbe8a99b403feb64dc',
    'POSTGRES_IMAGE_REF': PG_MANIFEST,
}


def validate_candidate(data):
    validate_manifest(data)
    require(data['migrations'] == qualified_migrations(), 'IMAGE_MIGRATIONS_NOT_QUALIFIED_V8')
    for key, digest in APPROVED.items():
        row = data['images'][key]
        require(row.get('indexDigest', row['manifestDigest']) == digest, 'REVIEWED_IMAGE_PAIR_CHANGED')
    require(data['images']['POSTGRES_IMAGE_REF']['configDigest'] == PG_CONFIG, 'POSTGRES_CONFIG_CHANGED')
    request = data['v7Preparation']
    require(request['expected_previous'] == data['expectedPrevious']
            and re.fullmatch(RELEASE_ID, request['expected_previous']), 'APPROVED_RELEASE_BASE_CHANGED')
    require(request['env_file'] == str(ENV_FILE), 'PRODUCTION_ENV_PATH_INVALID')
    restore_start_timeout(request.get('restore_start_timeout_seconds', RESTORE_START_TIMEOUT_SECONDS))
    return request


def conservation(cid, evidence, demo):
    # Reuse the original backup script's exact fingerprint/metadata queries.
    # Its V7-only qualification DO block ran unchanged on source and restored DB.
    # After migration, the unchanged V8 preflight checks the new SQL boundaries.
    original = (TOOLS / 'qualification_v7_backup.sql').read_text()
    prefix = original.split('DO $$', 1)[0]
    queries = '-- Same representation' + original.split('-- Same representation', 1)[1]
    sql = evidence / 'conservation.sql'
    sql.write_text(prefix + queries)
    private_run(psql(cid, '-v', 'demo_id=' + demo), evidence, 'post-v8', sql)
    def protected_rows(path):
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        # V8 intentionally changes Flyway, application policies and helper functions.
        return [r for r in rows if r.get('table') != 'flyway_schema_history'
                and not set(r).intersection({'policies', 'routines'})]
    require(protected_rows(evidence / 'source.out') == protected_rows(evidence / 'post-v8.out'),
            'V8_PRODUCTION_DATA_CONSERVATION_FAILED')


def run(operation, identity, approval=None, base=BASE):
    require(re.fullmatch(RELEASE_ID, identity or ''), 'RELEASE_ID_INVALID')
    os.umask(0o077)
    # All nested helpers must use this daemon, never an inherited Docker context.
    os.environ['DOCKER_HOST'] = DOCKER_ENV['DOCKER_HOST']
    os.environ.pop('DOCKER_CONTEXT', None)
    directory = base / 'releases' / identity
    require(directory.resolve() == directory, 'RELEASE_DIRECTORY_INVALID')
    data = json.loads((directory / 'release.json').read_text())
    request = validate_candidate(data)
    require(data['id'] == identity, 'RELEASE_ID_MISMATCH')
    for name, digest in data['runtime'].items():
        path = directory / name
        require(not path.is_symlink() and file_sha(path) == digest, 'RELEASE_RUNTIME_DIGEST_MISMATCH')
    reviewed_configuration(data, directory / 'configuration')
    private_env()
    with deployment_lock(base):
        require(not (directory / 'attempt.json').exists(), 'REVIEWED_DEPLOYMENT_ALREADY_ATTEMPTED')
        if operation == 'prepare-reviewed':
            require(not (directory / 'prepared.json').exists(), 'RELEASE_ALREADY_PREPARED')
            verify_archives(directory, data)
            evidence = verify_backup(base, request)
            result = {'result': 'PREPARED_AWAITING_V8_APPROVAL', 'id': identity,
                      'expectedPrevious': data['expectedPrevious'], 'releaseManifestSha256': file_sha(directory / 'release.json'),
                      'privateEvidence': str(evidence), 'preparedAtUtc': datetime.now(timezone.utc).isoformat()}
            (directory / 'prepared.json').write_text(json.dumps(result, indent=2) + '\n')
            return {'result': result['result'], 'id': identity, 'productionApplicationChanged': False,
                    'backendSha': data['backendSha'], 'frontendSha': data['frontendSha'],
                    'configurationSha': data['configurationSha'],
                    'images': {key: row['manifestDigest'] for key, row in data['images'].items()}}
        require(operation == 'deploy-reviewed' and approval is not None, 'EXPLICIT_V8_APPROVAL_REQUIRED')
        prepared = json.loads((directory / 'prepared.json').read_text())
        require(prepared['result'] == 'PREPARED_AWAITING_V8_APPROVAL' and prepared['id'] == identity
                and prepared['releaseManifestSha256'] == file_sha(directory / 'release.json'), 'PREPARED_RELEASE_CHANGED')
        require(approval['expected_previous'] == request['expected_previous'], 'APPROVED_RELEASE_BASE_CHANGED')
        # This is the exact destructive-availability/migration approval boundary.
        # Preparation never calls activate(), docker stop on apps, or a workflow dispatcher.
        approval_env = approval['environment']
        require(all(approval_env.get('CONFIRM_' + key) == 'true' for key in
                    ['GITHUB_PROTECTION', 'WRITE_FREEZE', 'IMAGE_QUALIFICATION']), 'HUMAN_RELEASE_APPROVALS_REQUIRED')
        # The existing controller's three backup gate bits are derived from automation.
        # This preview validates all other gates before stopping anything. It is never
        # persisted or used to activate unless the fresh backup/restore below passes.
        record = from_environment({**approval_env, 'CONFIRM_V7_PREFLIGHT': 'true',
                                   'CONFIRM_V7_BACKUP': 'true', 'CONFIRM_ISOLATED_RESTORE': 'true'})
        require(record['phase'] == 'migrate-v8', 'MIGRATION_PHASE_REQUIRED')
        require(record['expected_previous'] == request['expected_previous'], 'APPROVED_RELEASE_BASE_CHANGED')
        require(record['approved_backend_digest'] == data['images']['BACKEND_IMAGE_REF']['manifestDigest'],
                'APPROVED_CHILD_DIGEST_CHANGED')
        data['releaseSafety'] = record
        validate_release(data, True)
        verify_archives(directory, data)
        _, _, apps = source(base, request['expected_previous'])
        # Pin workers through the controller environment; never edit the production secret file.
        settings = {'envFile': str(ENV_FILE), 'publicUrl': 'https://ai-policy.tewendelabs.com'}
        from production_release import commands
        commands(data, ENV_FILE, directory / 'configuration')  # Validate config before any stop.
        (directory / 'approval.json').write_text(json.dumps(approval, indent=2) + '\n')
        (directory / 'attempt.json').write_text(json.dumps({'operation': operation,
            'startedAt': datetime.now(timezone.utc).isoformat(), 'allowMigrations': True}) + '\n')
        # Frontend first blocks new delivery; backend stop drains/terminates the only app writers.
        for app in reversed(apps):
            execute(['docker', 'stop', '--time', '60', app['Id']], DOCKER_ENV,
                    code='APPROVED_APPLICATION_STOP_FAILED', timeout=90)
        evidence = verify_backup(base, request, frozen=True)
        data['automatedV7Verification'] = {'privateEvidence': str(evidence),
                                          'result': 'V7_BACKUP_AND_ISOLATED_RESTORE_VERIFIED'}
        def acceptance():
            from v7_backup_restore import container
            conservation(container('postgres')['Id'], evidence, request['demo_id'])
        result = activate(directory, data, settings, allow_migrations=True, base=base,
                          root=directory / 'configuration', acceptance=acceptance)
        (directory / 'deployment-evidence.json').write_text(json.dumps({
            'privateEvidence': str(evidence), 'automatedV7PreflightBackupRestore': True,
            'postV8DataConservationVerified': True, 'workersEnabled': False}, indent=2) + '\n')
        return {'result': result['result'], 'id': identity, 'phase': 'migrate-v8', 'workersEnabled': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['prepare-reviewed', 'deploy-reviewed'])
    parser.add_argument('release_id')
    parser.add_argument('--approval-file', type=Path)
    args = parser.parse_args()
    try:
        approval = json.loads(args.approval_file.read_text()) if args.approval_file else None
        print(json.dumps(run(args.operation, args.release_id, approval)))
    except (DeploymentError, OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError, tarfile.TarError):
        error = sys.exc_info()[1]
        code = str(error) if isinstance(error, DeploymentError) else 'REVIEWED_RELEASE_FAILED'
        if re.fullmatch(RELEASE_ID, args.release_id or ''):
            directory = BASE / 'releases' / args.release_id
            try:
                if directory.is_dir() and directory.resolve() == directory:
                    (directory / 'reviewed-failure.json').write_text(json.dumps({'code': code,
                        'operation': args.operation, 'failedAtUtc': datetime.now(timezone.utc).isoformat(),
                        'automaticRecoveryAttempted': False}) + '\n')
            except OSError:
                pass
        print(code, file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
