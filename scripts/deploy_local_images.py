#!/usr/bin/env python3
"""Validate first; deploy only with --apply. No registry access, builds, Git or pruning."""
import argparse
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys

from verify_production_compose import validate, PROXY, APPLICATION, ALIAS

ROOT = Path(__file__).resolve().parents[1]
PROJECT = 'ai-policy-investigator'
UI_PROJECT = 'ai-policy-investigator-ui'
REPOSITORIES = {
    'BACKEND_IMAGE_REF': 'ghcr.io/thierryte/ai-policy-invetigator',
    'MODEL_INIT_IMAGE_REF': 'ghcr.io/thierryte/ai-policy-invetigator-model-init',
    'FRONTEND_IMAGE_REF': 'ghcr.io/thierryte/ai-policy-invetigator-frontend',
}


class DeploymentError(Exception):
    """Fixed safe codes only; never print Docker diagnostics or resolved secret values."""


def require(value, code):
    if not value:
        raise DeploymentError(code)


def release_images(path):
    try:
        data = json.loads(path.read_text())
        require(isinstance(data, dict) and set(data) == set(REPOSITORIES), 'RELEASE_KEYS_INVALID')
        for key, repository in REPOSITORIES.items():
            require(isinstance(data[key], str) and re.fullmatch(
                re.escape(repository) + r'(?::sha-[0-9a-f]{40}|@sha256:[0-9a-f]{64})', data[key]),
                'RELEASE_IMAGE_REFERENCE_INVALID_' + key)
        if ':sha-' in data['BACKEND_IMAGE_REF'] and ':sha-' in data['MODEL_INIT_IMAGE_REF']:
            require(data['BACKEND_IMAGE_REF'].split(':sha-')[1] == data['MODEL_INIT_IMAGE_REF'].split(':sha-')[1],
                    'BACKEND_INITIALIZER_VERSIONS_DIFFER')
        return data
    except (OSError, ValueError, TypeError):
        raise DeploymentError('RELEASE_FILE_INVALID') from None


def execute(command, env=None, code='DOCKER_COMMAND_FAILED', timeout=45):
    try:
        result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=timeout)
        require(result.returncode == 0, code)
        return result.stdout
    except (OSError, subprocess.TimeoutExpired):
        raise DeploymentError(code) from None


def json_command(command, env=None, code='DOCKER_INSPECTION_FAILED'):
    try:
        return json.loads(execute(command, env, code))
    except (ValueError, TypeError):
        raise DeploymentError(code) from None


def compose_commands(root, frontend, env_file):
    back = ['docker', 'compose', '--project-directory', str(root), '--env-file', str(env_file), '-p', PROJECT]
    for name in ['compose.yaml', 'compose.production.yaml', 'deploy/backend/compose.ghcr.yaml']:
        require((root / name).is_file(), 'BACKEND_DEPLOYMENT_FILE_MISSING')
        back += ['-f', str(root / name)]
    back += ['--profile', 'app']
    front = ['docker', 'compose', '--project-directory', str(frontend), '--env-file', '/dev/null', '-p', UI_PROJECT]
    for file in [frontend / 'compose.yaml', root / 'deploy/frontend/compose.production.yaml', root / 'deploy/frontend/compose.ghcr.yaml']:
        require(file.is_file(), 'FRONTEND_DEPLOYMENT_FILE_MISSING')
        front += ['-f', str(file)]
    require((root / 'deploy/postgres/init.sh').is_file(), 'DATABASE_INITIALIZER_MISSING')
    return back, front


def validate_configuration(back, front, images, postgres_image='pgvector/pgvector:0.8.0-pg16'):
    try:
        validate(back, front)
        services = [*back['services'].values(), *front['services'].values()]
        require(all(s.get('pull_policy') == 'never' and not s.get('build') for s in services), 'PULL_OR_BUILD_NOT_DISABLED')
        require(back['services']['backend']['image'] == images['BACKEND_IMAGE_REF']
                and back['services']['model-init']['image'] == images['MODEL_INIT_IMAGE_REF']
                and front['services']['frontend']['image'] == images['FRONTEND_IMAGE_REF'], 'RELEASE_IMAGES_NOT_APPLIED')
        require(back['services']['postgres']['image'] == postgres_image, 'POSTGRES_IMAGE_CHANGED')
        env = back['services']['backend']['environment']
        secrets = {k: env.get(k, '') for k in ['MODEL_API_KEY', 'JWT_SECRET', 'APP_DB_PASSWORD', 'OWNER_DB_PASSWORD']}
        secrets['POSTGRES_ADMIN_PASSWORD'] = back['services']['postgres']['environment'].get('POSTGRES_PASSWORD', '')
        require(all(isinstance(v, str) and v.strip() and not v.startswith('replace-with-') for v in secrets.values()),
                'PRODUCTION_SECRETS_MISSING_OR_PLACEHOLDERS')
        require(len(secrets['JWT_SECRET'].encode()) >= 32, 'JWT_SECRET_TOO_SHORT')
        require(env['APP_DB_USERNAME'] == 'investigator_app' and env['OWNER_DB_USERNAME'] == 'investigator_owner', 'DATABASE_ROLES_DIFFER_FROM_INITIALIZER')
        for volume in ['investigator_data', 'embedding_models', 'native_cache']:
            require(back['volumes'][volume]['name'] == PROJECT + '_' + volume, 'PERSISTENT_VOLUME_CHANGED')
        require(back['services']['backend'].get('read_only') is True
                and back['services']['model-init'].get('read_only') is True, 'ROOT_FILESYSTEM_NOT_READ_ONLY')
        require(back['services']['backend']['healthcheck'] and back['services']['postgres']['healthcheck'], 'HEALTHCHECK_MISSING')
    except (ValueError, KeyError, TypeError, StopIteration):
        raise DeploymentError('PRODUCTION_TOPOLOGY_INVALID') from None


class _PlatformSelectionUnavailable(DeploymentError):
    """The tag exists, but Docker cannot select the requested local platform."""


def _inspect_local_image(reference, platform=None):
    command = ['docker', 'image', 'inspect']
    if platform:
        command += ['--platform', platform]
    command.append(reference)
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=45)
    except (OSError, subprocess.TimeoutExpired):
        raise DeploymentError('LOCAL_IMAGE_INSPECTION_FAILED_' + reference) from None
    if result.returncode:
        # Classify known Docker diagnostics internally; never echo arbitrary stderr/JSON.
        diagnostic = (result.stderr + result.stdout).lower()
        if 'no such image:' in diagnostic or 'no such object:' in diagnostic:
            raise DeploymentError('LOCAL_IMAGE_MISSING_' + reference)
        if platform and any(text in diagnostic for text in [
                'does not provide the specified platform', 'does not match the specified platform',
                'does not provide any platform']):
            raise _PlatformSelectionUnavailable('LOCAL_IMAGE_PLATFORM_METADATA_UNAVAILABLE_' + reference)
        if platform and ('unknown flag: --platform' in diagnostic
                         or ('platform' in diagnostic and 'api version' in diagnostic)):
            raise DeploymentError('LOCAL_IMAGE_PLATFORM_METADATA_UNAVAILABLE_' + reference)
        raise DeploymentError('LOCAL_IMAGE_INSPECTION_FAILED_' + reference)
    try:
        rows = json.loads(result.stdout)
        if not isinstance(rows, list) or len(rows) != 1 or not isinstance(rows[0], dict):
            raise ValueError('Invalid image inspection shape')
        return rows[0]
    except (ValueError, TypeError):
        raise DeploymentError('LOCAL_IMAGE_PLATFORM_METADATA_UNAVAILABLE_' + reference) from None


def _known_image_platform(row):
    values = (row.get('Os'), row.get('Architecture'))
    return all(isinstance(v, str) and v.strip() and v.lower() not in ['unknown', 'unspecified'] for v in values)


def inspect_image(reference, architecture):
    original = _inspect_local_image(reference)  # Establish local presence and retain the tag's image ID.
    try:
        row = _inspect_local_image(reference, 'linux/' + architecture)
    except _PlatformSelectionUnavailable:
        # A missing selectable variant can also mean incomplete/unreadable local content.
        # Report a wrong platform only when the original metadata actually identifies one.
        if _known_image_platform(original) and (original['Os'], original['Architecture']) != ('linux', architecture):
            raise DeploymentError('LOCAL_IMAGE_PLATFORM_MISMATCH_' + reference) from None
        raise DeploymentError('LOCAL_IMAGE_PLATFORM_METADATA_UNAVAILABLE_' + reference) from None
    require(_known_image_platform(row), 'LOCAL_IMAGE_PLATFORM_METADATA_UNAVAILABLE_' + reference)
    require(row['Os'] == 'linux' and row['Architecture'] == architecture, 'LOCAL_IMAGE_PLATFORM_MISMATCH_' + reference)
    require(isinstance(original.get('Id'), str) and bool(original['Id']), 'LOCAL_IMAGE_PLATFORM_METADATA_UNAVAILABLE_' + reference)
    revision = ((row.get('Config') or {}).get('Labels') or {}).get('org.opencontainers.image.revision')
    if revision and ':sha-' in reference:
        require(revision == reference.split(':sha-')[1], 'LOCAL_IMAGE_REVISION_MISMATCH_' + reference)
    # RepoDigests is deliberately not required: docker load preserves local tags/IDs.
    return {'reference': reference, 'localImageId': original['Id'], 'architecture': row['Architecture'],
            'platform': row['Os'] + '/' + row['Architecture'], 'platformVerification': 'explicit-local-inspect',
            'ociRevisionPresent': bool(revision)}


def check_runtime(back):
    info = json_command(['docker', 'info', '--format', '{{json .}}'], code='DOCKER_ENGINE_UNAVAILABLE')
    architecture = {'x86_64': 'amd64', 'aarch64': 'arm64'}.get(info.get('Architecture'), info.get('Architecture'))
    require(info.get('OSType') == 'linux' and architecture == 'amd64', 'ONLY_LINUX_AMD64_RUNTIME_VERIFIED')
    inspected = [inspect_image(s['image'], architecture) for s in back['services'].values()]
    names = execute(['docker', 'network', 'ls', '--format', '{{.Name}}']).splitlines()
    require(PROXY in names, 'EXISTING_NPM_NETWORK_MISSING')
    npm = json_command(['docker', 'inspect', 'nginx-proxy-manager'], code='EXISTING_NPM_CONTAINER_MISSING')[0]
    require(npm['State']['Running'] and PROXY in npm['NetworkSettings']['Networks'], 'NPM_NOT_RUNNING_ON_CONFIRMED_NETWORK')
    network = json_command(['docker', 'network', 'inspect', PROXY])[0]
    for container_id in (network.get('Containers') or {}):
        container = json_command(['docker', 'inspect', container_id])[0]
        labels = container.get('Config', {}).get('Labels') or {}
        aliases = container['NetworkSettings']['Networks'][PROXY].get('Aliases') or []
        own_frontend = labels.get('com.docker.compose.project') == UI_PROJECT and labels.get('com.docker.compose.service') == 'frontend'
        require(ALIAS not in aliases or own_frontend, 'FRONTEND_PROXY_ALIAS_ALREADY_OWNED')
        require(labels.get('com.docker.compose.project') != PROJECT, 'PRIVATE_PROJECT_CONTAINER_ON_PROXY_NETWORK')
    for name, definition in back['networks'].items():
        actual = definition['name']
        if actual in names:
            row = json_command(['docker', 'network', 'inspect', actual])[0]
            require((row.get('Labels') or {}).get('com.docker.compose.project') == PROJECT, 'PROJECT_NETWORK_NAME_COLLISION')
            require(bool(row.get('Internal')) == bool(definition.get('internal')), 'EXISTING_PROJECT_NETWORK_POLICY_DIFFERS')
    return inspected


def check_existing(command, env, project, configuration, inspected):
    """Retries may reuse matching containers; never replace an existing container."""
    containers = execute(['docker', 'ps', '-a', '-q', '--filter', 'label=com.docker.compose.project=' + project]).splitlines()
    if not containers:
        return
    hashes = dict(line.split() for line in execute(command + ['config', '--hash', '*'], env,
                  'EXISTING_CONFIGURATION_HASH_CHECK_FAILED').splitlines())
    image_ids = {image['reference']: image['localImageId'] for image in inspected}
    for container_id in containers:
        row = json_command(['docker', 'inspect', container_id])[0]
        labels = row.get('Config', {}).get('Labels') or {}
        service = labels.get('com.docker.compose.service')
        require(service in configuration['services'], 'UNEXPECTED_EXISTING_PROJECT_CONTAINER')
        require(labels.get('com.docker.compose.config-hash') == hashes.get(service)
                and service in hashes, 'EXISTING_CONTAINER_CONFIG_DIFFERS_REVIEW_REQUIRED')
        require(row['Image'] == image_ids[configuration['services'][service]['image']],
                'EXISTING_CONTAINER_IMAGE_DIFFERS_REVIEW_REQUIRED')


def deploy(env_file, frontend, release_file, apply=False, config_only=False, root=ROOT):
    require(env_file.is_file(), 'PRIVATE_ENV_FILE_REQUIRED')
    require(stat.S_IMODE(env_file.stat().st_mode) & 0o077 == 0, 'PRIVATE_ENV_FILE_PERMISSIONS_REQUIRE_600')
    images = release_images(release_file)
    env = os.environ.copy()
    env.update(images)  # The explicitly selected release wins over stale image variables.
    back_cmd, front_cmd = compose_commands(root, frontend, env_file)
    for cmd in [back_cmd, front_cmd]:
        execute(cmd + ['config', '--quiet'], env, 'COMPOSE_CONFIG_FAILED')
    back = json_command(back_cmd + ['config', '--format', 'json'], env, 'BACKEND_CONFIG_FAILED')
    front = json_command(front_cmd + ['config', '--format', 'json'], env, 'FRONTEND_CONFIG_FAILED')
    validate_configuration(back, front, images)
    if config_only:
        return {'result': 'CONFIG_VALIDATED_RUNTIME_NOT_CHECKED', 'started': False, 'pullOrBuild': False}
    inspected = check_runtime(back)
    inspected.append(inspect_image(images['FRONTEND_IMAGE_REF'], 'amd64'))
    check_existing(back_cmd, env, PROJECT, back, inspected)
    check_existing(front_cmd, env, UI_PROJECT, front, inspected)
    result = {'result': 'PREFLIGHT_PASSED', 'images': inspected, 'started': False, 'pullOrBuild': False,
              'metaConnectivity': 'Not probed; private default network provides configured egress',
              'modelCache': 'Validated by the unchanged initializer at startup; a cold cache needs public downloads'}
    if apply:
        print('Preflight passed. Starting only AI Policy Investigator; no pull/build.', flush=True)
        execute(back_cmd + ['up', '-d', '--no-recreate', '--no-build', '--pull', 'never', '--wait', '--wait-timeout', '300'],
                env, 'BACKEND_START_FAILED_CHECK_PROJECT_HEALTH_AND_MODEL_INIT_LOGS', timeout=330)
        execute(front_cmd + ['up', '-d', '--no-recreate', '--no-build', '--pull', 'never', '--wait', '--wait-timeout', '120'],
                env, 'FRONTEND_START_FAILED_BACKEND_MAY_ALREADY_BE_RUNNING', timeout=150)
        result.update(result='PROJECT_HEALTHCHECKS_PASSED_PUBLIC_ROUTING_NOT_TESTED', started=True)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file', required=True, type=Path)
    parser.add_argument('--frontend-directory', type=Path, default=ROOT / 'frontend')
    parser.add_argument('--release-file', type=Path, default=ROOT / 'deploy/release.images.json')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--config-only', action='store_true', help='Resolve and validate config; no runtime/network/image probes.')
    mode.add_argument('--apply', action='store_true', help='Start this project only after every preflight passes.')
    args = parser.parse_args()
    try:
        result = deploy(args.env_file.resolve(), args.frontend_directory.resolve(), args.release_file.resolve(),
                        apply=args.apply, config_only=args.config_only)
    except (DeploymentError, OSError, KeyError, TypeError, IndexError, ValueError):
        # Print only our own fixed codes; generic failures never expose Docker JSON/env diagnostics.
        error = sys.exc_info()[1]
        print(str(error) if isinstance(error, DeploymentError) else 'DEPLOYMENT_PREFLIGHT_FAILED', file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
