#!/usr/bin/env python3
"""Transfer the tested deployment artifact using the existing VPS secrets and a pinned host key."""
import base64
import os
from pathlib import Path
import re
import subprocess
import tempfile

from simple_diagnostics import CODES, emit, forward, phase

BASE = '/opt/ai-policy-investigator'
FILES = ['simple_deploy.py', 'simple_diagnostics.py', 'ci_images.py', 'images.json', 'compose.yaml',
         'compose.production.yaml', 'compose.images.yaml', 'compose.frontend.yaml']
SSH_CODES = CODES | frozenset('''
SSH_HOST_OR_USER_INVALID SSH_PORT_OR_DEPLOY_PATH_INVALID PINNED_ED25519_HOST_KEY_REQUIRED
PINNED_ED25519_HOST_KEY_INVALID SSH_PRIVATE_KEY_REQUIRED DEPLOY_INPUT_INVALID DEPLOY_BUNDLE_INCOMPLETE
'''.split())


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


def execute(command, *, step='ssh.deploy'):
    with phase('transport'):
        emit(step, 'started', render=True)
        try:
            result = subprocess.run(command, capture_output=True, text=True, errors='replace', timeout=1800)
        except subprocess.TimeoutExpired as error:
            # A timeout may carry bytes even with text=True. Keep any complete safe events.
            forward(error.stdout)
            forward(error.stderr)
            emit(step, 'failed', 'timeout', render=True)
            raise ValueError('SSH_REMOTE_OUTCOME_UNCONFIRMED') from None
        except OSError:
            emit(step, 'failed', 'unavailable', render=True)
            raise ValueError('SSH_TRANSFER_OR_REMOTE_DEPLOYMENT_FAILED') from None
        codes = forward(result.stdout) + forward(result.stderr)
        if result.returncode:
            emit(step, 'failed', 'transport_failed' if result.returncode == 255 else
                 ('remote_failed' if codes else 'unknown'), result.returncode, render=True)
    if result.returncode:
        # A broken connection is never evidence that remote rollback ran or completed.
        raise ValueError('SSH_REMOTE_OUTCOME_UNCONFIRMED' if result.returncode == 255 else
                         (codes[-1] if codes else 'SSH_TRANSFER_OR_REMOTE_DEPLOYMENT_FAILED'))
    return ''  # Raw remote stdout may contain environment values; never forward it.


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
            execute(ssh + ['umask 077 && test -d ' + BASE + ' && mkdir -p ' + remote], step='ssh.prepare')
            execute(['scp', *flags, '-P', port, *[str(bundle / name) for name in FILES], target + ':' + remote + '/'], step='ssh.transfer')
            execute(ssh + ['python3 ' + remote + '/simple_deploy.py ' + env['DEPLOY_OPERATION'] + ' --bundle ' + remote], step='ssh.deploy')
    except (ValueError, KeyError, OSError, subprocess.TimeoutExpired):
        # Only fixed error codes and validated diagnostic events reach Actions.
        error = str(__import__('sys').exc_info()[1])
        raise SystemExit(error if error in SSH_CODES else 'SSH_DEPLOYMENT_FAILED') from None


if __name__ == '__main__':
    main()
