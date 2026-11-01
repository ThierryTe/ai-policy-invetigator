#!/usr/bin/env python3
"""Explicit, attested V8 delivery or retained-release rollback; never push-triggered."""
import argparse
import json
import os
from pathlib import Path
import re
import sys

from deploy_local_images import DeploymentError, require
from prepare_production_release import prepare
from publish_release_images import channel_revision
from release_artifacts import SHA, RELEASE_ID
from validate_release_dispatch import dispatch_environment, validate as validate_manual
from transfer_production_release import current_release, transfer
from release_safety import from_environment, validate_release


def automatic_pair(component, revision):
    require(component in ['backend', 'frontend'] and re.fullmatch(SHA, revision or ''), 'AUTOMATIC_SOURCE_INVALID')
    if component == 'backend':
        return revision, channel_revision('frontend', os.environ.get('INITIAL_FRONTEND_SHA', ''))
    return channel_revision('backend', os.environ.get('INITIAL_BACKEND_SHA', '')), revision


def deploy(args, env=None):
    env = os.environ if env is None else env
    require(not args.component, 'AUTOMATIC_PRODUCTION_DEPLOYMENT_DISABLED')
    if env.get('GITHUB_ACTIONS') == 'true':
        require(env.get('GITHUB_EVENT_NAME') == 'workflow_dispatch'
                and env.get('GITHUB_REPOSITORY') == 'ThierryTe/ai-policy-invetigator'
                and env.get('GITHUB_REF') == 'refs/heads/main', 'MANUAL_BACKEND_MAIN_DISPATCH_REQUIRED')
    if args.operation == 'rollback':
        require(re.fullmatch(RELEASE_ID, args.rollback_release or '') and not args.allow_migrations, 'ROLLBACK_INPUT_INVALID')
        return transfer('rollback', args.rollback_release)
    require(args.run_id.isdecimal() and args.run_attempt.isdecimal(), 'GITHUB_RUN_ID_INVALID')
    require(re.fullmatch(SHA, args.configuration_sha or ''), 'CONFIGURATION_SHA_REQUIRED')
    record = from_environment(env)
    validate_manual({**env, 'OPERATION': 'deploy', 'BACKEND_SHA': args.backend_sha,
                     'FRONTEND_SHA': args.frontend_sha, 'ROLLBACK_RELEASE': args.rollback_release,
                     'ALLOW_MIGRATIONS': str(args.allow_migrations).lower()})
    require(current_release() == record['expected_previous'], 'APPROVED_RELEASE_BASE_CHANGED')
    identity = 'r0' + args.run_id + '-' + str(int(args.run_attempt) * 10 + 1)
    directory = args.output / identity
    if record['phase'] == 'activate-v8' and env.get('PREPARED_RELEASE'):
        require(env['PREPARED_RELEASE'] == record['expected_previous'], 'ACTIVATION_PREPARED_RELEASE_MISMATCH')
        from reviewed_v8_release import APPROVED
        data = prepare(directory, args.backend_sha, args.frontend_sha, args.configuration_sha, identity,
                       approved_images=APPROVED)
    else:
        data = prepare(directory, args.backend_sha, args.frontend_sha, args.configuration_sha, identity)
    data['expectedPrevious'] = record['expected_previous']
    data['releaseSafety'] = record
    validate_release(data, args.allow_migrations)
    (directory / 'release.json').write_text(json.dumps(data, indent=2) + '\n')
    # A changed base or failure requires a new explicit approval, never an automatic retry.
    return transfer('deploy', identity, directory, args.allow_migrations)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--event-file', type=Path, help='GitHub workflow_dispatch event file; authoritative form inputs')
    parser.add_argument('--operation', choices=['deploy', 'rollback'], default='deploy')
    parser.add_argument('--component', choices=['backend', 'frontend'])
    parser.add_argument('--source-sha', default='')
    parser.add_argument('--backend-sha', default='')
    parser.add_argument('--frontend-sha', default='')
    parser.add_argument('--rollback-release', default='')
    parser.add_argument('--configuration-sha', default='')
    parser.add_argument('--run-id', default=os.environ.get('GITHUB_RUN_ID', ''))
    parser.add_argument('--run-attempt', default=os.environ.get('GITHUB_RUN_ATTEMPT', ''))
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--allow-migrations', action='store_true')
    args = parser.parse_args()
    try:
        env = dispatch_environment(os.environ, args.event_file) if args.event_file else os.environ
        if args.event_file:
            # The same authoritative form drives preflight and execution, including
            # false booleans and empty fields; CLI/env values cannot supply approvals.
            validate_manual(env)
            args.operation = env['OPERATION']
            args.backend_sha = env['BACKEND_SHA']
            args.frontend_sha = env['FRONTEND_SHA']
            args.rollback_release = env['ROLLBACK_RELEASE']
            args.allow_migrations = env['ALLOW_MIGRATIONS'] == 'true'
        require(not args.component, 'AUTOMATIC_PRODUCTION_DEPLOYMENT_DISABLED')
        validate_manual({**env, 'OPERATION': args.operation, 'BACKEND_SHA': args.backend_sha,
                         'FRONTEND_SHA': args.frontend_sha, 'ROLLBACK_RELEASE': args.rollback_release,
                         'ALLOW_MIGRATIONS': str(args.allow_migrations).lower()})
        result = deploy(args, env)
        print(json.dumps(result, indent=2))
    except (DeploymentError, OSError, ValueError, KeyError, TypeError):
        error = sys.exc_info()[1]
        print(str(error) if isinstance(error, DeploymentError) else 'PRODUCTION_PIPELINE_FAILED', file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
