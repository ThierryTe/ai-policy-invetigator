#!/usr/bin/env python3
"""After successful CI: build/publish immutable images, then advance discovery channel.

Same build -> push sequence as spring-ai-rag. Existing SHA tags are verified/reused,
never overwritten. No SSH or production credentials. Both repositories call this file.
"""
import argparse
import base64
import json
import os
from pathlib import Path
import re
import sys

from deploy_local_images import DeploymentError, REPOSITORIES, require
from prepare_production_release import ghcr_manifest, request, run
from release_artifacts import SHA, sha

CHANNEL = 'release-main'  # Discovery only. Compose always receives verified local digest aliases.
SOURCE_REPOSITORIES = {
    'backend': 'https://github.com/ThierryTe/ai-policy-invetigator',
    'frontend': 'https://github.com/ThierryTe/ai-policy-invetigator-frontend',
}


def configuration(repository, metadata):
    require(repository in REPOSITORIES.values(), 'UNAPPROVED_REGISTRY_REPOSITORY')
    actor, token = os.environ.get('GITHUB_ACTOR', ''), os.environ.get('GHCR_TOKEN', '')
    require(actor and token, 'REGISTRY_JOB_TOKEN_REQUIRED')
    package = repository.removeprefix('ghcr.io/')
    auth = base64.b64encode((actor + ':' + token).encode()).decode()
    body, _ = request('https://ghcr.io/token?service=ghcr.io&scope=repository:' + package + ':pull', {'Authorization': 'Basic ' + auth})
    bearer = json.loads(body)['token']
    blob, _ = request('https://ghcr.io/v2/' + package + '/blobs/' + metadata['configDigest'], {'Authorization': 'Bearer ' + bearer})
    require('sha256:' + sha(blob) == metadata['configDigest'], 'REGISTRY_CONFIG_DIGEST_MISMATCH')
    data = json.loads(blob)
    require((data.get('os'), data.get('architecture')) == ('linux', 'amd64'), 'REGISTRY_CONFIG_PLATFORM_MISMATCH')
    return data


def verified(repository, revision, metadata, component):
    labels = (configuration(repository, metadata).get('config') or {}).get('Labels') or {}
    require(labels.get('org.opencontainers.image.revision') == revision, 'PUBLISHED_SOURCE_REVISION_MISMATCH')
    require(labels.get('org.opencontainers.image.source') == SOURCE_REPOSITORIES[component], 'PUBLISHED_SOURCE_REPOSITORY_MISMATCH')
    return metadata


def publish(component, revision, context):
    require(component in SOURCE_REPOSITORIES and re.fullmatch(SHA, revision or ''), 'PUBLICATION_INPUT_INVALID')
    paths = [('BACKEND_IMAGE_REF', 'deploy/backend/Dockerfile'), ('MODEL_INIT_IMAGE_REF', 'deploy/embeddings/Dockerfile')] \
        if component == 'backend' else [('FRONTEND_IMAGE_REF', 'Dockerfile')]
    published = []
    for key, dockerfile in paths:
        repository = REPOSITORIES[key]
        tag = 'sha-' + revision
        metadata = ghcr_manifest(repository, tag, missing_ok=True)
        if metadata is None:
            require((context / dockerfile).is_file(), 'PUBLICATION_DOCKERFILE_MISSING')
            run(['docker', 'build', '--platform', 'linux/amd64', '--file', str(context / dockerfile),
                 '--label', 'org.opencontainers.image.source=' + SOURCE_REPOSITORIES[component],
                 '--label', 'org.opencontainers.image.revision=' + revision,
                 '--tag', repository + ':' + tag, str(context)], timeout=1200)
            run(['docker', 'push', repository + ':' + tag])
            metadata = ghcr_manifest(repository, tag)
        verified(repository, revision, metadata, component)
        published.append((repository, metadata))
    # Promote only after every immutable artifact of this component is available and verified.
    for repository, metadata in published:
        run(['docker', 'buildx', 'imagetools', 'create', '--tag', repository + ':' + CHANNEL,
             repository + '@' + metadata['manifestDigest']])
    return {'component': component, 'sha': revision, 'images': {repo: value['manifestDigest'] for repo, value in published}}


def channel_revision(component, initial_revision=''):
    key = 'BACKEND_IMAGE_REF' if component == 'backend' else 'FRONTEND_IMAGE_REF'
    repository = REPOSITORIES[key]
    metadata = ghcr_manifest(repository, CHANNEL, missing_ok=True)
    if metadata is None:
        require(re.fullmatch(SHA, initial_revision or ''), 'INITIAL_COUNTERPART_SHA_REQUIRED_UNTIL_FIRST_PUBLICATION')
        metadata = ghcr_manifest(repository, 'sha-' + initial_revision)
        revision = initial_revision
    else:
        revision = ((configuration(repository, metadata).get('config') or {}).get('Labels') or {}).get('org.opencontainers.image.revision', '')
        require(re.fullmatch(SHA, revision), 'CHANNEL_REVISION_INVALID')
    immutable = ghcr_manifest(repository, 'sha-' + revision)
    require(immutable['manifestDigest'] == metadata['manifestDigest'], 'CHANNEL_IMMUTABLE_DIGEST_MISMATCH')
    verified(repository, revision, immutable, component)
    if component == 'backend':
        initializer = REPOSITORIES['MODEL_INIT_IMAGE_REF']
        verified(initializer, revision, ghcr_manifest(initializer, 'sha-' + revision), component)
    return revision


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('component', choices=['backend', 'frontend'])
    parser.add_argument('--sha', required=True)
    parser.add_argument('--context', required=True, type=Path)
    args = parser.parse_args()
    try:
        result = publish(args.component, args.sha, args.context.resolve())
        print(json.dumps(result, indent=2))
    except (DeploymentError, OSError, ValueError, KeyError, TypeError):
        error = sys.exc_info()[1]
        print(str(error) if isinstance(error, DeploymentError) else 'PUBLICATION_FAILED', file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
