#!/usr/bin/env python3
"""Reject ambiguous manual input before any registry or SSH operation."""
import argparse
import json
import os
from pathlib import Path
import re
import sys
from deploy_local_images import DeploymentError, require
from release_artifacts import SHA, RELEASE_ID
from release_safety import CONFIRMATIONS, from_environment


DISPATCH_INPUTS = {
    'operation': 'OPERATION', 'prepared_release': 'PREPARED_RELEASE',
    'backend_sha': 'BACKEND_SHA', 'frontend_sha': 'FRONTEND_SHA', 'rollback_release': 'ROLLBACK_RELEASE',
    'allow_migrations': 'ALLOW_MIGRATIONS', 'phase': 'RELEASE_PHASE',
    'expected_previous': 'EXPECTED_PREVIOUS', 'approved_backend_digest': 'APPROVED_BACKEND_DIGEST',
    'evidence_ref': 'EVIDENCE_REF',
    **{'confirm_' + key: 'CONFIRM_' + key.upper() for key in CONFIRMATIONS},
}
BOOLEAN_INPUTS = {'allow_migrations', *('confirm_' + key for key in CONFIRMATIONS)}


def dispatch_environment(env, event_file):
    """Read form values once for both validation and execution; never inherit stale inputs."""
    require(env.get('GITHUB_EVENT_NAME') == 'workflow_dispatch', 'MANUAL_BACKEND_MAIN_DISPATCH_REQUIRED')
    try:
        event = json.loads(event_file.read_text())
    except (OSError, ValueError):
        raise DeploymentError('WORKFLOW_DISPATCH_EVENT_INVALID') from None
    require(isinstance(event, dict) and isinstance(event.get('inputs'), dict), 'WORKFLOW_DISPATCH_EVENT_INVALID')
    resolved = dict(env)
    for name, variable in DISPATCH_INPUTS.items():
        value = event['inputs'].get(name, '')
        if name in BOOLEAN_INPUTS and type(value) is bool:
            value = 'true' if value else 'false'
        require(isinstance(value, str), 'WORKFLOW_DISPATCH_INPUT_TYPE_INVALID_' + name.upper())
        resolved[variable] = value
    # This is GitHub's actor metadata, never a form field or inherited override.
    resolved['RELEASE_OPERATOR'] = env.get('GITHUB_ACTOR', '')
    return resolved


def validate(env):
    operation = env.get('OPERATION')
    if operation == 'deploy':
        require(all(re.fullmatch(SHA, env.get(k, '')) for k in ['BACKEND_SHA', 'FRONTEND_SHA']), 'TWO_FULL_SOURCE_SHAS_REQUIRED')
        require(not env.get('ROLLBACK_RELEASE'), 'DEPLOY_CANNOT_SELECT_ROLLBACK')
        record = from_environment(env)
        require(env.get('ALLOW_MIGRATIONS') in ('true', 'false')
                and (env['ALLOW_MIGRATIONS'] == 'true') == (record['phase'] == 'migrate-v8'),
                'PHASE_MIGRATION_PERMISSION_MISMATCH')
    else:
        require(operation == 'rollback' and re.fullmatch(RELEASE_ID, env.get('ROLLBACK_RELEASE', '')), 'VALIDATED_ROLLBACK_RELEASE_ID_REQUIRED')
        require(not env.get('BACKEND_SHA') and not env.get('FRONTEND_SHA'), 'ROLLBACK_CANNOT_SELECT_NEW_IMAGES')
        require(env.get('ALLOW_MIGRATIONS') == 'false', 'ROLLBACK_CANNOT_APPLY_MIGRATIONS')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--event-file', type=Path, help='GitHub workflow_dispatch event file; authoritative form inputs')
    args = parser.parse_args()
    try:
        env = dispatch_environment(os.environ, args.event_file) if args.event_file else os.environ
        validate(env)
    except DeploymentError as error:
        print(str(error), file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
