#!/usr/bin/env python3
"""Explicit operator bootstrap for an empty identity store; never an application hook."""
import argparse
import base64
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
MARKER = '-- INITIAL_ADMIN_INPUT --'


class BootstrapError(Exception):
    pass


def input_data(env):
    if env.get('INVESTIGATOR_INITIAL_ADMIN_ENABLED') != 'true':
        raise BootstrapError('INITIAL_ADMIN_DISABLED')
    fields = {name: env.get(key, '') for name, key in {
        'email': 'INVESTIGATOR_INITIAL_EMAIL', 'password': 'INVESTIGATOR_INITIAL_PASSWORD',
        'organization': 'INVESTIGATOR_INITIAL_ORGANIZATION', 'department': 'INVESTIGATOR_INITIAL_DEPARTMENT'}.items()}
    email = fields['email'].strip().lower()
    if len(email) > 254 or email.count('@') != 1 or any(c.isspace() for c in email) or not all(email.split('@')):
        raise BootstrapError('INITIAL_ADMIN_EMAIL_REQUIRED')
    fields['email'] = email
    password = fields['password']
    try:
        for value in fields.values():
            value.encode('utf-8')
    except UnicodeError:
        raise BootstrapError('INITIAL_ADMIN_INPUT_INVALID') from None
    if not 16 <= len(password.encode()) <= 72 or password.startswith('replace-with-'):
        raise BootstrapError('INITIAL_ADMIN_PASSWORD_REQUIRED')
    if any(ord(c) < 32 or ord(c) == 127 for value in fields.values() for c in value):
        raise BootstrapError('INITIAL_ADMIN_INPUT_INVALID')
    if any(not fields[k].strip() or len(fields[k]) > 200 for k in ['organization', 'department']):
        raise BootstrapError('INITIAL_ADMIN_NAMES_REQUIRED')
    return fields


def sql_input(env):
    data = input_data(env)
    template = (ROOT / 'deploy/postgres/provision-initial-admin.sql').read_text()
    if template.count(MARKER) != 1:
        raise BootstrapError('INITIAL_ADMIN_TEMPLATE_INVALID')
    encoded = base64.b64encode(json.dumps(data).encode()).decode()
    return template.replace(MARKER, 'COPY pg_temp.initial_admin_input FROM STDIN;\n' + encoded + '\n\\.\n')


def provision(env_file, env=None):
    env = os.environ if env is None else env
    content = sql_input(env)  # Refuse before invoking Docker unless explicitly enabled.
    if not env_file.is_file():
        raise BootstrapError('PRIVATE_ENV_FILE_REQUIRED')
    args = ['docker', 'compose', '--project-directory', str(ROOT), '--env-file', str(env_file.resolve()),
            '-p', 'ai-policy-investigator', '-f', str(ROOT / 'compose.yaml'), '-f', str(ROOT / 'compose.production.yaml'),
            '--profile', 'app', 'exec', '-T', 'postgres', 'psql', '-X', '-q', '-U', 'postgres', '-d', 'investigator',
            '-v', 'ON_ERROR_STOP=1']
    try:
        # Do not pass bootstrap credentials into Compose/container environments or argv.
        child_env = {k: v for k, v in env.items() if not k.startswith('INVESTIGATOR_INITIAL_')}
        result = subprocess.run(args, input=content, text=True, capture_output=True, env=child_env, timeout=45)
    except (OSError, subprocess.TimeoutExpired):
        raise BootstrapError('INITIAL_ADMIN_DATABASE_UNAVAILABLE') from None
    if result.returncode:
        # Database diagnostics can contain private input; never echo them.
        raise BootstrapError('INITIAL_ADMIN_FAILED_CHECK_EMPTY_IDENTITY_STORE_AND_MIGRATIONS')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file', required=True, type=Path)
    options = parser.parse_args()
    try:
        provision(options.env_file)
    except (BootstrapError, OSError) as error:
        code = str(error) if isinstance(error, BootstrapError) else 'INITIAL_ADMIN_LOCAL_IO_FAILED'
        print(code, file=sys.stderr)
        return 2
    print('Initial administrator provisioned in one owning department. No credentials printed.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
