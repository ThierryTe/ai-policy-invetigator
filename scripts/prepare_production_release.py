#!/usr/bin/env python3
"""GitHub runner only: resolve registry digests, pull amd64, verify and save locally.

Never contacts the VPS. No builds, Git commands, production secrets or container starts.
"""
import argparse
import base64
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tarfile
import time
import urllib.error
import urllib.request

from deploy_local_images import DeploymentError, REPOSITORIES, require
from release_artifacts import (CONFIG_FILES, RUNTIME_FILES, SHA, DIGEST, RELEASE_ID, archive_image,
                               normalized_archive, file_sha, sha, validate_manifest)

ROOT = Path(__file__).resolve().parents[1]
ACCEPT = ', '.join(['application/vnd.oci.image.index.v1+json', 'application/vnd.oci.image.manifest.v1+json',
                    'application/vnd.docker.distribution.manifest.list.v2+json', 'application/vnd.docker.distribution.manifest.v2+json'])


def run(command, input=None, timeout=600):
    try:
        result = subprocess.run(command, input=input, capture_output=True, timeout=timeout)
        require(result.returncode == 0, 'RUNNER_DOCKER_OPERATION_FAILED')
        return result.stdout
    except (OSError, subprocess.TimeoutExpired):
        raise DeploymentError('RUNNER_DOCKER_UNAVAILABLE_OR_TIMEOUT') from None


def request(url, headers, allow_absent=False):
    for attempt in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30) as response:
                body = response.read(4 * 1024**2 + 1)
                require(len(body) <= 4 * 1024**2, 'REGISTRY_RESPONSE_TOO_LARGE')
                return body, response.headers
        except urllib.error.HTTPError as error:
            if error.code == 404 and allow_absent:
                return None, {}
            if error.code not in [429, 500, 502, 503, 504]:
                raise DeploymentError('REGISTRY_AUTH_OR_REFERENCE_FAILED') from None
        except (urllib.error.URLError, TimeoutError, OSError):
            pass
        if attempt < 2:
            time.sleep(attempt + 1)
    raise DeploymentError('REGISTRY_NETWORK_RETRIES_EXHAUSTED')


def ghcr_manifest(repository, tag, absent=False, missing_ok=False):
    package = repository.removeprefix('ghcr.io/')
    actor, token = os.environ.get('GITHUB_ACTOR', ''), os.environ.get('GHCR_TOKEN', '')
    require(actor and token, 'REGISTRY_JOB_TOKEN_REQUIRED')
    auth = base64.b64encode((actor + ':' + token).encode()).decode()
    body, _ = request('https://ghcr.io/token?service=ghcr.io&scope=repository:' + package + ':pull',
                      {'Authorization': 'Basic ' + auth})
    bearer = json.loads(body)['token']
    headers = {'Authorization': 'Bearer ' + bearer, 'Accept': ACCEPT}
    def fetch(ref, optional=False):
        body, response = request('https://ghcr.io/v2/' + package + '/manifests/' + ref, headers, optional)
        if body is None:
            return None, None
        digest = 'sha256:' + sha(body)
        require(not ref.startswith('sha256:') or ref == digest, 'REGISTRY_MANIFEST_DIGEST_MISMATCH')
        require(not response.get('Docker-Content-Digest') or response['Docker-Content-Digest'] == digest,
                'REGISTRY_HEADER_DIGEST_MISMATCH')
        return json.loads(body), digest
    manifest, top_digest = fetch(tag, absent or missing_ok)
    if manifest is None and missing_ok:
        return None
    if absent:
        require(manifest is None, 'IMMUTABLE_TAG_ALREADY_EXISTS')
        return None
    if 'manifests' in manifest:
        matches = [r for r in manifest['manifests'] if r.get('platform', {}).get('os') == 'linux'
                   and r.get('platform', {}).get('architecture') == 'amd64']
        require(len(matches) == 1, 'REGISTRY_AMD64_VARIANT_NOT_UNIQUE')
        manifest, digest = fetch(matches[0]['digest'])
    else:
        digest = top_digest
    require(re.fullmatch(DIGEST, manifest['config']['digest']), 'REGISTRY_CONFIG_DIGEST_INVALID')
    return {'manifestDigest': digest, 'configDigest': manifest['config']['digest'], 'indexDigest': top_digest}


def prepare(output, backend_sha, frontend_sha, configuration_sha, release_id, root=ROOT):
    require(all(re.fullmatch(SHA, value) for value in [backend_sha, frontend_sha, configuration_sha]), 'FULL_SOURCE_SHA_REQUIRED')
    require(re.fullmatch(RELEASE_ID, release_id), 'RELEASE_ID_INVALID')
    require(not output.exists(), 'RELEASE_OUTPUT_ALREADY_EXISTS')
    output.mkdir(parents=True, mode=0o700)
    data = {'format': 1, 'id': release_id, 'backendSha': backend_sha, 'frontendSha': frontend_sha,
            'configurationSha': configuration_sha, 'images': {}, 'configuration': {}}
    for key in [*REPOSITORIES, 'POSTGRES_IMAGE_REF']:
        repository = REPOSITORIES.get(key, 'pgvector/pgvector')
        revision = frontend_sha if key == 'FRONTEND_IMAGE_REF' else backend_sha
        tag = 'sha-' + revision if key in REPOSITORIES else '0.8.0-pg16'
        source = repository + ':' + tag
        if key in REPOSITORIES:
            metadata = ghcr_manifest(repository, tag)
        else:
            descriptor = json.loads(run(['docker', 'buildx', 'imagetools', 'inspect', source, '--format', '{{json .Manifest}}']))
            digest = descriptor.get('digest')
            if 'manifests' in descriptor:
                matches = [m for m in descriptor['manifests'] if m.get('platform', {}).get('os') == 'linux'
                           and m.get('platform', {}).get('architecture') == 'amd64']
                require(len(matches) == 1, 'POSTGRES_AMD64_VARIANT_NOT_UNIQUE')
                digest = matches[0]['digest']
            require(re.fullmatch(DIGEST, digest or ''), 'POSTGRES_DIGEST_INVALID')
            raw_manifest = run(['docker', 'buildx', 'imagetools', 'inspect', repository + '@' + digest, '--raw'])
            # Buildx may append one terminal newline to raw output. Require one exact hash match.
            candidates = [raw_manifest, raw_manifest.removesuffix(b'\n')]
            matching = next((raw for raw in candidates if 'sha256:' + sha(raw) == digest), None)
            require(matching is not None, 'POSTGRES_MANIFEST_DIGEST_MISMATCH')
            metadata = {'manifestDigest': digest, 'indexDigest': descriptor['digest'],
                        'configDigest': json.loads(matching)['config']['digest']}
        pinned = repository + '@' + metadata['manifestDigest']
        run(['docker', 'pull', '--platform', 'linux/amd64', pinned])
        image = json.loads(run(['docker', 'image', 'inspect', '--platform', 'linux/amd64', pinned]))[0]
        require((image.get('Os'), image.get('Architecture')) == ('linux', 'amd64'), 'RUNNER_IMAGE_PLATFORM_MISMATCH')
        # Docker/containerd IDs are store metadata, not a portable content proof.
        # The exported config blob and layer DiffIDs are verified cryptographically below.
        config_digest = metadata['configDigest']
        require(isinstance(image.get('Id'), str) and bool(image['Id']), 'RUNNER_IMAGE_METADATA_UNAVAILABLE')
        metadata['runnerImageId'] = image['Id']
        local_repo = REPOSITORIES.get(key, 'ai-policy-investigator-postgres')
        local_ref = local_repo + ':deploy-' + metadata['manifestDigest'][7:]
        run(['docker', 'image', 'tag', pinned, local_ref])
        raw, target = output / (key + '.raw'), output / (key + '.tar')
        run(['docker', 'image', 'save', '--platform', 'linux/amd64', '--output', str(raw), local_ref])
        normalized_archive(raw, target)
        migrations = archive_image(target, local_ref, config_digest, revision if key in REPOSITORIES else None,
                                   key == 'BACKEND_IMAGE_REF')
        raw.unlink()  # Only the runner's temporary file, never a Docker image/container/volume.
        metadata.update(sourceRef=source, localRef=local_ref, archive=target.name, archiveSha256=file_sha(target))
        data['images'][key] = metadata
        if key == 'BACKEND_IMAGE_REF':
            data['migrations'] = migrations
    config_root = output / 'configuration'
    for name in CONFIG_FILES:
        source = root / ('.ci/frontend/compose.yaml' if name == 'frontend/compose.yaml' else name)
        target = config_root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        content = source.read_bytes()
        target.write_bytes(content)
        data['configuration'][name] = sha(content)
    data['runtime'] = {}
    for name in RUNTIME_FILES:
        target = output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        content = (root / name).read_bytes()
        target.write_bytes(content)
        data['runtime'][name] = sha(content)
    validate_manifest(data)
    (output / 'release.json').write_text(json.dumps(data, indent=2) + '\n')
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--backend-sha')
    parser.add_argument('--frontend-sha')
    parser.add_argument('--configuration-sha')
    parser.add_argument('--release-id')
    parser.add_argument('--assert-tag-absent', choices=list(REPOSITORIES.values()))
    parser.add_argument('--tag')
    args = parser.parse_args()
    try:
        if args.assert_tag_absent:
            require(re.fullmatch('sha-' + SHA, args.tag or ''), 'FULL_SOURCE_SHA_REQUIRED')
            ghcr_manifest(args.assert_tag_absent, args.tag, absent=True)
        else:
            data = prepare(args.output, args.backend_sha, args.frontend_sha, args.configuration_sha, args.release_id)
            print(json.dumps({'prepared': data['id'], 'platform': 'linux/amd64', 'images': data['images']}, indent=2))
    except (DeploymentError, OSError, ValueError, KeyError, TypeError, tarfile.TarError):
        error = sys.exc_info()[1]
        print(str(error) if isinstance(error, DeploymentError) else 'RELEASE_PREPARATION_FAILED', file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
