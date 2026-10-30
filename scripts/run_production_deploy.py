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
from validate_release_dispatch import validate as validate_manual
from transfer_production_release import current_release, transfer
from release_safety import from_environment, validate_release


def automatic_pair(component, revision):
    require(component in ['backend', 'frontend'] and re.fullmatch(SHA, revision or ''), 'AUTOMATIC_SOURCE_INVALID')
    if component == 'backend':
        return revision, channel_revision('frontend', os.environ.get('INITIAL_FRONTEND_SHA', ''))
    return channel_revision('backend', os.environ.get('INITIAL_BACKEND_SHA', '')), revision


def deploy(args):
    require(not args.component, 'AUTOMATIC_PRODUCTION_DEPLOYMENT_DISABLED')
    if os.environ.get('GITHUB_ACTIONS') == 'true':
        require(os.environ.get('GITHUB_EVENT_NAME') == 'workflow_dispatch'
                and os.environ.get('GITHUB_REPOSITORY') == 'ThierryTe/ai-policy-invetigator'
                and os.environ.get('GITHUB_REF') == 'refs/heads/main', 'MANUAL_BACKEND_MAIN_DISPATCH_REQUIRED')
    if args.operation == 'rollback':
        require(re.fullmatch(RELEASE_ID, args.rollback_release or '') and not args.allow_migrations, 'ROLLBACK_INPUT_INVALID')
        return transfer('rollback', args.rollback_release)
    require(args.run_id.isdecimal() and args.run_attempt.isdecimal(), 'GITHUB_RUN_ID_INVALID')
    require(re.fullmatch(SHA, args.configuration_sha or ''), 'CONFIGURATION_SHA_REQUIRED')
    record = from_environment(os.environ)
    validate_manual({**os.environ, 'OPERATION': 'deploy', 'BACKEND_SHA': args.backend_sha,
                     'FRONTEND_SHA': args.frontend_sha, 'ROLLBACK_RELEASE': args.rollback_release,
                     'ALLOW_MIGRATIONS': str(args.allow_migrations).lower()})
    require(current_release() == record['expected_previous'], 'APPROVED_RELEASE_BASE_CHANGED')
    identity = 'r0' + args.run_id + '-' + str(int(args.run_attempt) * 10 + 1)
    directory = args.output / identity
    data = prepare(directory, args.backend_sha, args.frontend_sha, args.configuration_sha, identity)
    data['expectedPrevious'] = record['expected_previous']
    data['releaseSafety'] = record
    validate_release(data, args.allow_migrations)
    (directory / 'release.json').write_text(json.dumps(data, indent=2) + '\n')
    # A changed base or failure requires a new explicit approval, never an automatic retry.
    return transfer('deploy', identity, directory, args.allow_migrations)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
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
        require(not args.component, 'AUTOMATIC_PRODUCTION_DEPLOYMENT_DISABLED')
        validate_manual({**os.environ, 'OPERATION': args.operation, 'BACKEND_SHA': args.backend_sha,
                         'FRONTEND_SHA': args.frontend_sha, 'ROLLBACK_RELEASE': args.rollback_release,
                         'ALLOW_MIGRATIONS': str(args.allow_migrations).lower()})
        result = deploy(args)
        print(json.dumps(result, indent=2))
    except (DeploymentError, OSError, ValueError, KeyError, TypeError):
        error = sys.exc_info()[1]
        print(str(error) if isinstance(error, DeploymentError) else 'PRODUCTION_PIPELINE_FAILED', file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
