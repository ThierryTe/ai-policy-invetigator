#!/usr/bin/env python3
"""Reject ambiguous manual input before any registry or SSH operation."""
import os
import re
import sys
from deploy_local_images import DeploymentError, require
from release_artifacts import SHA, RELEASE_ID


def validate(env):
    operation = env.get('OPERATION')
    if operation == 'deploy':
        require(all(re.fullmatch(SHA, env.get(k, '')) for k in ['BACKEND_SHA', 'FRONTEND_SHA']), 'TWO_FULL_SOURCE_SHAS_REQUIRED')
        require(not env.get('ROLLBACK_RELEASE'), 'DEPLOY_CANNOT_SELECT_ROLLBACK')
    else:
        require(operation == 'rollback' and re.fullmatch(RELEASE_ID, env.get('ROLLBACK_RELEASE', '')), 'VALIDATED_ROLLBACK_RELEASE_ID_REQUIRED')
        require(not env.get('BACKEND_SHA') and not env.get('FRONTEND_SHA'), 'ROLLBACK_CANNOT_SELECT_NEW_IMAGES')
        require(env.get('ALLOW_MIGRATIONS') == 'false', 'ROLLBACK_CANNOT_APPLY_MIGRATIONS')


if __name__ == '__main__':
    try:
        validate(os.environ)
    except DeploymentError as error:
        print(str(error), file=sys.stderr)
        sys.exit(2)
