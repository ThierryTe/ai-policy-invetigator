#!/usr/bin/env python3
"""Classify image build inputs through GitHub's compare API, without Git commands.

Tooling/docs-only changes still run all CI tests, but do not rebuild/publish images.
Unknown/incomplete comparisons fail closed instead of guessing changed paths.
"""
import json
import os
from pathlib import Path
import re
import sys
import urllib.error
import urllib.request

from deploy_local_images import DeploymentError, require

EXACT = {'pom.xml', 'mvnw', '.dockerignore', 'deploy/backend/Dockerfile',
         'deploy/embeddings/Dockerfile', 'scripts/fetch_embeddings.py'}


def needs_images(paths):
    return any(p in EXACT or p.startswith(('src/', '.mvn/')) for p in paths)


def classify(event, fetch):
    if 'pull_request' in event:
        before, after = (event['pull_request'][side]['sha'] for side in ['base', 'head'])
    else:
        before, after = event.get('before', ''), event.get('after', '')
    require(all(re.fullmatch(r'[0-9a-f]{40}', s) for s in [before, after]), 'CI_COMPARISON_REVISIONS_REQUIRED')
    if before == '0' * 40:
        return True  # First source publication has no base.
    comparison = fetch(before, after)
    allowed = ('ahead', 'identical', 'diverged') if 'pull_request' in event else ('ahead', 'identical')
    require(comparison.get('status') in allowed, 'CI_COMPARISON_NOT_LINEAR')
    files = comparison.get('files')
    require(isinstance(files, list) and len(files) < 300, 'CI_COMPARISON_FILE_LIST_INCOMPLETE')
    require(all(isinstance(r, dict) and isinstance(r.get('filename'), str) for r in files), 'CI_COMPARISON_FILE_LIST_INVALID')
    require(files or comparison['status'] == 'identical', 'CI_COMPARISON_FILE_LIST_EMPTY')
    paths = [r[k] for r in files for k in ['filename', 'previous_filename'] if k in r]
    require(all(isinstance(p, str) for p in paths), 'CI_COMPARISON_FILE_LIST_INVALID')
    return needs_images(paths)


def main():
    try:
        require(os.environ.get('GITHUB_REPOSITORY') == 'ThierryTe/ai-policy-invetigator', 'CI_REPOSITORY_MISMATCH')
        def fetch(before, after):
            request = urllib.request.Request('https://api.github.com/repos/ThierryTe/ai-policy-invetigator/compare/'
                + before + '...' + after, headers={'Accept': 'application/vnd.github+json',
                'Authorization': 'Bearer ' + os.environ['GH_TOKEN'], 'X-GitHub-Api-Version': '2022-11-28'})
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.load(response)
        event = json.loads(Path(os.environ['GITHUB_EVENT_PATH']).read_text())
        changed = classify(event, fetch)
        with Path(os.environ['GITHUB_OUTPUT']).open('a') as output:
            output.write('changed=' + str(changed).lower() + '\n')
        print('Runtime image inputs changed: ' + str(changed).lower())
    except (DeploymentError, OSError, ValueError, KeyError, TypeError, urllib.error.URLError):
        print('CI_IMAGE_INPUT_COMPARISON_FAILED', file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
