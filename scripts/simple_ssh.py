#!/usr/bin/env python3
"""Transfer the tested deployment artifact using the existing VPS secrets and a pinned host key."""
import base64
import os
from pathlib import Path
import re
import subprocess
import tempfile

BASE = '/opt/ai-policy-investigator'
FILES = ['simple_deploy.py', 'ci_images.py', 'images.json', 'compose.yaml',
         'compose.production.yaml', 'compose.images.yaml', 'compose.frontend.yaml']


def settings(env):
    host, user, port = env.get('VPS_HOST', ''), env.get('VPS_USERNAME', ''), env.get('VPS_PORT') or '22'
    if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9.-]*', host) or not re.fullmatch(r'[a-z_][a-z0-9_-]*', user):
        raise ValueError('SSH_HOST_OR_USER_INVALID')
    if not port.isdecimal() or not 1 <= int(port) <= 65535 or env.get('VPS_DEPLOY_PATH') != BASE:
        raise ValueError('SSH_PORT_OR_DEPLOY_PATH_INVALID')
    pin = env.get('VPS_HOST_KEY', '').strip().split()
    if len(pin) < 2 or pin[0] != 'ssh-ed25519':
        raise ValueError('PINNED_ED25519_HOST_KEY_REQUIRED')
    blob = base64.b64decode(pin[1], validate=True)
    if len(blob) != 51 or blob[:19] != b'\x00\x00\x00\x0bssh-ed25519\x00\x00\x00\x20':
        raise ValueError('PINNED_ED25519_HOST_KEY_INVALID')
    if not env.get('VPS_SSH_KEY'):
        raise ValueError('SSH_PRIVATE_KEY_REQUIRED')
    return host, user, str(int(port)), 'ssh-ed25519 ' + pin[1]


def execute(command):
    result = subprocess.run(command, capture_output=True, text=True, timeout=1800)
    if result.returncode:
        codes = [line for line in result.stderr.splitlines() if re.fullmatch('[A-Z][A-Z0-9_]{4,120}', line)]
        raise ValueError(codes[-1] if codes else 'SSH_TRANSFER_OR_REMOTE_DEPLOYMENT_FAILED')
    return result.stdout


def main():
    try:
        env = os.environ
        host, user, port, pin = settings(env)
        identity = env['GITHUB_RUN_ID'] + '-' + env['GITHUB_RUN_ATTEMPT']
        if not re.fullmatch('[0-9]+-[0-9]+', identity) or env['DEPLOY_OPERATION'] not in ('deploy', 'rollback'):
            raise ValueError('DEPLOY_INPUT_INVALID')
        bundle = Path(env['DEPLOY_BUNDLE'])
        if any(not (bundle / name).is_file() or (bundle / name).is_symlink() for name in FILES):
            raise ValueError('DEPLOY_BUNDLE_INCOMPLETE')
        with tempfile.TemporaryDirectory(prefix='simple-policy-ssh-') as directory:
            key, known = Path(directory) / 'identity', Path(directory) / 'known_hosts'
            key.write_text(env['VPS_SSH_KEY'].rstrip() + '\n')
            key.chmod(0o600)
            known.write_text((host if port == '22' else '[' + host + ']:' + port) + ' ' + pin + '\n')
            flags = ['-F', '/dev/null', '-i', str(key), '-o', 'BatchMode=yes', '-o', 'IdentitiesOnly=yes',
                     '-o', 'StrictHostKeyChecking=yes', '-o', 'UserKnownHostsFile=' + str(known),
                     '-o', 'GlobalKnownHostsFile=/dev/null', '-o', 'HostKeyAlgorithms=ssh-ed25519',
                     '-o', 'ConnectTimeout=20', '-o', 'ServerAliveInterval=15', '-o', 'ServerAliveCountMax=3']
            target = user + '@' + host
            ssh = ['ssh', *flags, '-p', port, target]
            remote = BASE + '/simple-deploy/incoming/' + identity
            execute(ssh + ['umask 077 && test -d ' + BASE + ' && mkdir -p ' + remote])
            execute(['scp', *flags, '-P', port, *[str(bundle / name) for name in FILES], target + ':' + remote + '/'])
            print(execute(ssh + ['python3 ' + remote + '/simple_deploy.py ' + env['DEPLOY_OPERATION'] + ' --bundle ' + remote]))
    except (ValueError, KeyError, OSError, subprocess.TimeoutExpired):
        # Only fixed error codes, never SSH diagnostics, remote configuration or environment values.
        error = str(__import__('sys').exc_info()[1])
        raise SystemExit(error if re.fullmatch('[A-Z][A-Z0-9_]{4,120}', error) else 'SSH_DEPLOYMENT_FAILED') from None


if __name__ == '__main__':
    main()
