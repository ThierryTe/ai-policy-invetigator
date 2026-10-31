#!/usr/bin/env python3
"""Existing VPS_* SSH conventions, strict host keys, runner-to-VPS file transfer."""
import argparse
import base64
import binascii
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import tempfile

from deploy_local_images import DeploymentError, require
from release_artifacts import RELEASE_ID, validate_manifest
from release_safety import validate_release

BASE = '/opt/ai-policy-investigator'


def pinned_host_key(value):
    """One public Ed25519 host key from the protected prod variable, never a scan.

    Accept the server's .pub line (optional trailing comment). Bound and validate
    its SSH wire encoding before creating files or invoking any network operation.
    """
    require(isinstance(value, str) and bool(value.strip()), 'SSH_HOST_KEY_REQUIRED')
    require(len(value) <= 1024 and '\n' not in value.strip() and '\r' not in value.strip(), 'SSH_HOST_KEY_INVALID')
    parts = value.strip().split()
    require(len(parts) >= 2 and parts[0] == 'ssh-ed25519', 'SSH_HOST_KEY_MUST_BE_ED25519')
    try:
        blob = base64.b64decode(parts[1], validate=True)
    except (ValueError, binascii.Error):
        raise DeploymentError('SSH_HOST_KEY_INVALID') from None
    # RFC4253 strings: algorithm length + algorithm + key length + 32-byte key.
    require(len(blob) == 51 and blob[:4] == b'\x00\x00\x00\x0b'
            and blob[4:15] == b'ssh-ed25519' and blob[15:19] == b'\x00\x00\x00\x20', 'SSH_HOST_KEY_INVALID')
    return 'ssh-ed25519 ' + base64.b64encode(blob).decode('ascii')


def execute(command, code, timeout=1200):
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
        if result.returncode:
            safe = next((line for line in result.stderr.splitlines() if re.fullmatch(r'[A-Z][A-Z0-9_]{5,120}', line)), None)
            raise DeploymentError(code + (': ' + safe if safe else ''))
        return result.stdout
    except (OSError, subprocess.TimeoutExpired):
        raise DeploymentError(code) from None


def connection(directory, environ):
    host, user, port = environ.get('VPS_HOST', ''), environ.get('VPS_USERNAME', ''), environ.get('VPS_PORT') or '22'
    require(re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9.-]*', host), 'SSH_HOST_REQUIRED_NO_IPV6_LITERAL')
    require(re.fullmatch(r'[a-z_][a-z0-9_-]*', user), 'SSH_USERNAME_INVALID')
    require(port.isdecimal() and 1 <= int(port) <= 65535, 'SSH_PORT_INVALID')
    port = str(int(port))
    require(environ.get('VPS_DEPLOY_PATH') == BASE, 'VPS_DEPLOY_PATH_MUST_SELECT_THIS_PROJECT')
    require(environ.get('VPS_SSH_KEY'), 'SSH_SECRETS_REQUIRED')
    public_key = pinned_host_key(environ.get('VPS_HOST_KEY', ''))
    key, hosts = directory / 'identity', directory / 'known_hosts'
    key.write_text(environ['VPS_SSH_KEY'].rstrip() + '\n'); key.chmod(0o600)
    hostname = host if port == '22' else '[' + host + ']:' + port
    hosts.write_text(hostname + ' ' + public_key + '\n'); hosts.chmod(0o600)
    flags = ['-F', '/dev/null', '-i', str(key), '-o', 'BatchMode=yes', '-o', 'IdentitiesOnly=yes',
             '-o', 'StrictHostKeyChecking=yes', '-o', 'UserKnownHostsFile=' + str(hosts),
             '-o', 'GlobalKnownHostsFile=/dev/null', '-o', 'HostKeyAlgorithms=ssh-ed25519',
             '-o', 'VerifyHostKeyDNS=no', '-o', 'UpdateHostKeys=no',
             '-o', 'ConnectTimeout=20', '-o', 'ServerAliveInterval=15', '-o', 'ServerAliveCountMax=3']
    return ['ssh', *flags, '-p', port, user + '@' + host], ['scp', *flags, '-P', port], user + '@' + host


def current_release():
    # Atomic state contains public version metadata only; no env or Docker inspection.
    code = "import json,pathlib;p=pathlib.Path('/opt/ai-policy-investigator/last-successful.json');print(json.dumps({'id':json.loads(p.read_text())['id'] if p.is_file() else None}))"
    with tempfile.TemporaryDirectory(prefix='policy-ssh-') as temporary:
        ssh, _, _ = connection(Path(temporary), os.environ)
        data = json.loads(execute(ssh + ['python3 -c ' + shlex.quote(code)], 'SSH_RELEASE_STATUS_FAILED'))
    identity = data['id']
    require(identity is None or re.fullmatch(RELEASE_ID, identity), 'REMOTE_RELEASE_STATE_INVALID')
    return identity


def transfer(operation, release_id, directory=None, allow_migrations=False, approval=None):
    require(re.fullmatch(RELEASE_ID, release_id or ''), 'RELEASE_ID_INVALID')
    require(operation in ['deploy', 'rollback', 'prepare-reviewed', 'deploy-reviewed'], 'OPERATION_INVALID')
    require(not allow_migrations or operation in ['deploy', 'deploy-reviewed'], 'ROLLBACK_CANNOT_APPLY_MIGRATIONS')
    upload = operation in ['deploy', 'prepare-reviewed']
    if upload:
        require(directory is not None, 'PREPARED_RELEASE_DIRECTORY_REQUIRED')
        data = validate_manifest(json.loads((directory / 'release.json').read_text()))
        require(data['id'] == release_id and 'runtime' in data, 'RELEASE_ID_OR_RUNTIME_INVALID')
        if operation == 'deploy':
            validate_release(data, allow_migrations)
        else:
            from reviewed_v8_release import validate_candidate
            validate_candidate(data)
    env_file = os.environ.get('VPS_ENV_FILE', '')
    require(re.fullmatch(re.escape(BASE) + r'/[A-Za-z0-9_./-]+', env_file)
            and Path(env_file).resolve().is_relative_to(BASE), 'VPS_ENV_FILE_REQUIRED_INSIDE_PROJECT')
    if operation in ['prepare-reviewed', 'deploy-reviewed']:
        require(env_file == BASE + '/.env.production', 'PRODUCTION_ENV_PATH_INVALID')
    with tempfile.TemporaryDirectory(prefix='policy-ssh-') as temporary:
        ssh, scp, target = connection(Path(temporary), os.environ)
        remote = BASE + '/releases/' + release_id
        if upload:
            execute(ssh + ['umask 077 && test -d ' + BASE + ' && mkdir -p ' + BASE + '/releases && mkdir ' + remote], 'SSH_RELEASE_DIRECTORY_FAILED')
            execute(scp + ['-r', str(directory / 'configuration'), str(directory / 'scripts'),
                           str(directory / 'docs'), target + ':' + remote + '/'], 'SSH_CONFIGURATION_TRANSFER_FAILED')
            files = [directory / 'release.json', *(directory / row['archive'] for row in data['images'].values())]
            execute(scp + [str(f) for f in files] + [target + ':' + remote + '/'], 'SSH_IMAGE_TRANSFER_FAILED')
        if operation in ['prepare-reviewed', 'deploy-reviewed']:
            command = 'python3 ' + remote + '/scripts/reviewed_v8_release.py ' + operation + ' ' + release_id
            if operation == 'deploy-reviewed':
                require(allow_migrations and approval is not None, 'EXPLICIT_V8_APPROVAL_REQUIRED')
                path = Path(temporary) / 'approval.json'
                path.write_text(json.dumps(approval) + '\n'); path.chmod(0o600)
                execute(scp + [str(path), target + ':' + remote + '/requested-approval.json'], 'SSH_APPROVAL_TRANSFER_FAILED')
                command += ' --approval-file ' + remote + '/requested-approval.json'
        else:
            command = 'python3 ' + remote + '/scripts/production_release.py ' + operation + ' ' + release_id + ' --env-file ' + shlex.quote(env_file)
        if allow_migrations and operation == 'deploy':
            command += ' --allow-migrations'
        result = json.loads(execute(ssh + [command], 'SSH_RELEASE_FAILED', timeout=3600))
        expected_result = 'PREPARED_AWAITING_V8_APPROVAL' if operation == 'prepare-reviewed' else 'VALIDATED'
        require(result.get('result') == expected_result and result.get('id') == release_id, 'REMOTE_VALIDATION_REPORT_INVALID')
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['deploy', 'rollback'])
    parser.add_argument('--release-id', required=True)
    parser.add_argument('--directory', type=Path)
    parser.add_argument('--allow-migrations', action='store_true')
    args = parser.parse_args()
    try:
        print(json.dumps(transfer(args.operation, args.release_id, args.directory, args.allow_migrations), indent=2))
    except (DeploymentError, OSError, ValueError, KeyError, TypeError):
        error = sys.exc_info()[1]
        print(str(error) if isinstance(error, DeploymentError) else 'SSH_TRANSFER_FAILED', file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
