#!/usr/bin/env python3
"""Small CI artifact contract: select one successful run, never mutable image tags."""
import argparse
import json
import os
from pathlib import Path
import re
import urllib.parse
import urllib.request

REPOSITORY = 'ThierryTe/ai-policy-invetigator'
FRONTEND = 'ThierryTe/ai-policy-invetigator-frontend'
PACKAGES = {'backend': 'ghcr.io/thierryte/ai-policy-invetigator',
            'frontend': 'ghcr.io/thierryte/ai-policy-invetigator-frontend'}


class SelectionError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise SelectionError(message)


def validate(data, run_id=None, backend_sha=None):
    require(isinstance(data, dict) and data.get('repository') == REPOSITORY, 'IMAGE_REPOSITORY_INVALID')
    for name in ('backend_sha', 'frontend_sha'):
        require(isinstance(data.get(name), str) and re.fullmatch('[0-9a-f]{40}', data[name]), 'SOURCE_SHA_INVALID')
    require(type(data.get('run_id')) is int and data['run_id'] > 0, 'RUN_ID_INVALID')
    require(run_id is None or data['run_id'] == run_id, 'ARTIFACT_RUN_MISMATCH')
    require(backend_sha is None or data['backend_sha'] == backend_sha, 'ARTIFACT_SHA_MISMATCH')
    require(isinstance(data.get('images'), dict) and set(data['images']) == set(PACKAGES), 'IMAGE_PAIR_REQUIRED')
    for component, package in PACKAGES.items():
        ref = data['images'][component]
        require(isinstance(ref, str) and re.fullmatch(re.escape(package) + '@sha256:[0-9a-f]{64}', ref),
                'IMMUTABLE_IMAGE_REQUIRED')
    return data


def select(runs, repository=REPOSITORY):
    candidates = [r for r in runs if r.get('status') == 'completed' and r.get('conclusion') == 'success'
                  and r.get('event') in ('push', 'repository_dispatch') and r.get('head_branch') == 'main'
                  and r.get('path') == '.github/workflows/ci.yml'
                  and (r.get('head_repository') or {}).get('full_name') == repository
                  and re.fullmatch('[0-9a-f]{40}', r.get('head_sha', ''))]
    require(candidates, 'NO_SUCCESSFUL_MAIN_CI_RUN')
    return max(candidates, key=lambda r: int(r['run_number']))


def api(path):
    request = urllib.request.Request('https://api.github.com/repos/' + REPOSITORY + path, headers={
        'Authorization': 'Bearer ' + os.environ['GH_TOKEN'], 'Accept': 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28'})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['select', 'record', 'validate'])
    parser.add_argument('--file', type=Path)
    args = parser.parse_args()
    try:
        if args.operation == 'select':
            runs = api('/actions/workflows/ci.yml/runs?' + urllib.parse.urlencode({
                'branch': 'main', 'status': 'success', 'per_page': 100}))['workflow_runs']
            run = select(runs)
            name = f"deployment-{run['id']}-{run['run_attempt']}"
            artifacts = api(f"/actions/runs/{run['id']}/artifacts?per_page=100")['artifacts']
            require(any(a['name'] == name and not a['expired'] for a in artifacts), 'LATEST_CI_ARTIFACT_MISSING_RERUN_CI')
            with open(os.environ['GITHUB_OUTPUT'], 'a') as output:
                output.write(f"run_id={run['id']}\nbackend_sha={run['head_sha']}\nartifact_name={name}\n")
            print(f"Selected successful CI run {run['id']} ({run['head_sha']})")
        elif args.operation == 'record':
            data = {'repository': REPOSITORY, 'run_id': int(os.environ['GITHUB_RUN_ID']),
                    'backend_sha': os.environ['GITHUB_SHA'], 'frontend_sha': os.environ['FRONTEND_SHA'], 'images': {}}
            for component, package in PACKAGES.items():
                metadata = json.loads(Path(os.environ[component.upper() + '_METADATA']).read_text())
                data['images'][component] = package + '@' + metadata['containerimage.digest']
            args.file.write_text(json.dumps(validate(data), indent=2) + '\n')
        else:
            data = validate(json.loads(args.file.read_text()), int(os.environ['SELECTED_RUN_ID']), os.environ['SELECTED_SHA'])
            print(json.dumps(data, indent=2))
    except (ValueError, KeyError, TypeError, OSError) as error:
        detail = str(error) if isinstance(error, SelectionError) else 'CHECK_CI_ARTIFACT_AND_ACTIONS_READ_PERMISSION'
        raise SystemExit('CI_IMAGE_SELECTION_FAILED: ' + detail) from None


if __name__ == '__main__':
    main()
