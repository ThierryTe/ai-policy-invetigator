#!/usr/bin/env python3
"""Automatic post-publication deploy, or explicit manual deploy/rollback for recovery."""
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


def automatic_pair(component, revision):
    require(component in ['backend', 'frontend'] and re.fullmatch(SHA, revision or ''), 'AUTOMATIC_SOURCE_INVALID')
    if component == 'backend':
        return revision, channel_revision('frontend', os.environ.get('INITIAL_FRONTEND_SHA', ''))
    return channel_revision('backend', os.environ.get('INITIAL_BACKEND_SHA', '')), revision


def deploy(args):
    if args.operation == 'rollback':
        require(re.fullmatch(RELEASE_ID, args.rollback_release or '') and not args.allow_migrations, 'ROLLBACK_INPUT_INVALID')
        return transfer('rollback', args.rollback_release)
    require(args.run_id.isdecimal() and args.run_attempt.isdecimal(), 'GITHUB_RUN_ID_INVALID')
    require(re.fullmatch(SHA, args.configuration_sha or ''), 'CONFIGURATION_SHA_REQUIRED')
    for attempt in range(1, 4):
        base = current_release()
        backend, frontend = automatic_pair(args.component, args.source_sha) if args.component else (args.backend_sha, args.frontend_sha)
        require(all(re.fullmatch(SHA, v or '') for v in [backend, frontend]), 'TWO_FULL_SOURCE_SHAS_REQUIRED')
        # Separate IDs for stale-base retries and workflow reruns, within the existing ID format.
        namespace = {'backend': '1', 'frontend': '2', None: '0'}[args.component]
        identity = 'r' + namespace + args.run_id + '-' + str(int(args.run_attempt) * 10 + attempt)
        directory = args.output / identity
        data = prepare(directory, backend, frontend, args.configuration_sha, identity)
        data['expectedPrevious'] = base
        (directory / 'release.json').write_text(json.dumps(data, indent=2) + '\n')
        try:
            return transfer('deploy', identity, directory, args.allow_migrations)
        except DeploymentError as error:
            if 'DEPLOYMENT_BASE_CHANGED_RETRY' not in str(error) or attempt == 3:
                raise
            # Other repository deployed while we prepared. Resolve its new channel again;
            # never replace it using our now-stale counterpart selection.
    raise DeploymentError('DEPLOYMENT_RETRY_LIMIT_REACHED')


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
        require(not args.component or (not args.backend_sha and not args.frontend_sha and not args.rollback_release and args.operation == 'deploy'), 'AUTOMATIC_AND_MANUAL_INPUTS_DIFFER')
        if not args.component:
            validate_manual({'OPERATION': args.operation, 'BACKEND_SHA': args.backend_sha, 'FRONTEND_SHA': args.frontend_sha,
                             'ROLLBACK_RELEASE': args.rollback_release, 'ALLOW_MIGRATIONS': str(args.allow_migrations).lower()})
        result = deploy(args)
        print(json.dumps(result, indent=2))
    except (DeploymentError, OSError, ValueError, KeyError, TypeError):
        error = sys.exc_info()[1]
        print(str(error) if isinstance(error, DeploymentError) else 'PRODUCTION_PIPELINE_FAILED', file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
