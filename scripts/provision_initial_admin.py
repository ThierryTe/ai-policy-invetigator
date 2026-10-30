#!/usr/bin/env python3
"""Explicit operator bootstrap for an empty identity store; never an application hook."""
import argparse
import base64
import getpass
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import warnings
import zlib

ROOT = Path(__file__).resolve().parents[1]
MARKER = '-- INITIAL_ADMIN_INPUT --'
MIGRATION_INVENTORY = 'deploy/postgres/initial-admin-migrations.json'
PREFLIGHT_SQL = """
BEGIN READ ONLY;
SELECT json_build_object(
 'database',current_database(),
 'extensions_ready',(SELECT count(*)=2 FROM pg_extension WHERE extname IN ('pgcrypto','vector')),
 'users',(SELECT count(*) FROM public.app_users),
 'organizations',(SELECT count(*) FROM public.organizations),
 'migrations',(SELECT json_agg(json_build_object(
   'version',version,'script',script,'checksum',checksum,'success',success,'type',type))
   FROM public.flyway_schema_history));
ROLLBACK;
"""


class BootstrapError(Exception):
    pass


def expected_migrations(root=ROOT):
    """Public migration metadata only; never package SQL migrations or private config."""
    inventory = root / MIGRATION_INVENTORY
    if inventory.is_symlink():
        raise BootstrapError('INITIAL_ADMIN_MIGRATION_INVENTORY_INVALID')
    if inventory.is_file():
        rows = json.loads(inventory.read_text())
    else:
        rows = []
        for path in sorted((root / 'src/main/resources/db/migration').glob('V*__*.sql')):
            match = re.fullmatch(r'V([0-9]+)__[a-z0-9_]+\.sql', path.name)
            if not match or path.is_symlink():
                raise BootstrapError('INITIAL_ADMIN_MIGRATION_INVENTORY_INVALID')
            # Flyway CRC32: ignore a leading UTF-8 BOM and line terminators.
            checksum = zlib.crc32(re.sub(r'\r\n|\r|\n', '', path.read_bytes().decode('utf-8-sig')).encode())
            rows.append({'version': match[1], 'script': path.name,
                         'checksum': checksum if checksum < 2**31 else checksum - 2**32})
    if not isinstance(rows, list) or not rows:
        raise BootstrapError('INITIAL_ADMIN_MIGRATION_INVENTORY_INVALID')
    for row in rows:
        if (not isinstance(row, dict) or set(row) != {'version', 'script', 'checksum'}
                or not isinstance(row['version'], str) or not row['version'].isdecimal()
                or not isinstance(row['script'], str)
                or not re.fullmatch(r'V' + row['version'] + r'__[a-z0-9_]+\.sql', row['script'])
                or type(row['checksum']) is not int or not -2**31 <= row['checksum'] < 2**31):
            raise BootstrapError('INITIAL_ADMIN_MIGRATION_INVENTORY_INVALID')
    if len({row['version'] for row in rows}) != len(rows):
        raise BootstrapError('INITIAL_ADMIN_MIGRATION_INVENTORY_INVALID')
    return sorted(rows, key=lambda row: int(row['version']))


def compose_command(env_file):
    # Stat only: Python never opens or prints the private environment file.
    if not env_file.is_file() or env_file.is_symlink():
        raise BootstrapError('PRIVATE_ENV_FILE_REQUIRED')
    if stat.S_IMODE(env_file.stat().st_mode) & 0o077:
        raise BootstrapError('PRIVATE_ENV_FILE_PERMISSIONS_REQUIRED')
    # Pin the VPS's local socket; ignore any remote Docker context/DOCKER_HOST.
    return ['docker', '--host', 'unix:///var/run/docker.sock', 'compose',
            '--project-directory', str(ROOT), '--env-file', str(env_file.resolve()),
            '-p', 'ai-policy-investigator', '-f', str(ROOT / 'compose.yaml'),
            '-f', str(ROOT / 'compose.production.yaml'), '--profile', 'app',
            'exec', '-T', 'postgres', 'psql', '-X', '-q', '-U', 'postgres',
            '-d', 'investigator', '-v', 'ON_ERROR_STOP=1']


def database_run(args, content, env):
    try:
        # No bootstrap input is passed into Compose/container environments or argv.
        child_env = {k: v for k, v in env.items() if not k.startswith('INVESTIGATOR_INITIAL_')}
        result = subprocess.run(args, input=content, text=True, capture_output=True,
                                env=child_env, timeout=45)
    except (OSError, subprocess.TimeoutExpired):
        raise BootstrapError('INITIAL_ADMIN_DATABASE_UNAVAILABLE') from None
    if result.returncode:
        # Database diagnostics can contain private input; never echo them.
        raise BootstrapError('INITIAL_ADMIN_FAILED_CHECK_EMPTY_IDENTITY_STORE_AND_MIGRATIONS')
    return result.stdout


def preflight(env_file, env=None):
    env = os.environ if env is None else env
    expected = expected_migrations()
    raw = database_run(compose_command(env_file) + ['-A', '-t'], PREFLIGHT_SQL, env)
    try:
        data = json.loads(raw)
        applied = data['migrations']
        if data['extensions_ready'] is not True:
            raise BootstrapError('INITIAL_ADMIN_DATABASE_EXTENSIONS_REQUIRED')
        if (data['database'] != 'investigator' or not isinstance(applied, list)
                or any(row['success'] is not True or row['type'] != 'SQL' for row in applied)
                or sorted([{'version': row['version'], 'script': row['script'], 'checksum': row['checksum']}
                           for row in applied], key=lambda row: int(row['version'])) != expected):
            raise BootstrapError('INITIAL_ADMIN_MIGRATIONS_MISMATCH')
        if type(data['users']) is not int or type(data['organizations']) is not int:
            raise ValueError()
        if data['users'] != 0 or data['organizations'] != 0:
            raise BootstrapError('INITIAL_ADMIN_REQUIRES_EMPTY_IDENTITY_STORE')
    except (ValueError, KeyError, TypeError):
        raise BootstrapError('INITIAL_ADMIN_PREFLIGHT_INVALID_RESPONSE') from None
    return len(expected)


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
    preflight(env_file, env)  # Mandatory for interactive and environment-based callers.
    database_run(compose_command(env_file), content, env)


def interactive(env_file):
    if not sys.stdin.isatty() or not sys.stderr.isatty():
        raise BootstrapError('INITIAL_ADMIN_INTERACTIVE_TERMINAL_REQUIRED')
    count = preflight(env_file)
    print(f'Preflight passed: database=investigator; users=0; organizations=0; migrations={count}.')
    env = dict(os.environ)
    env['INVESTIGATOR_INITIAL_ADMIN_ENABLED'] = 'true'
    env['INVESTIGATOR_INITIAL_EMAIL'] = input('Login email: ').strip()
    env['INVESTIGATOR_INITIAL_ORGANIZATION'] = input('Organization: ').strip()
    env['INVESTIGATOR_INITIAL_DEPARTMENT'] = input('Owning department: ').strip()
    with warnings.catch_warnings():
        warnings.simplefilter('error', getpass.GetPassWarning)
        password = getpass.getpass('Initial administrator password (16-72 UTF-8 bytes): ')
        if password != getpass.getpass('Confirm password: '):
            raise BootstrapError('INITIAL_ADMIN_PASSWORD_CONFIRMATION_MISMATCH')
    env['INVESTIGATOR_INITIAL_PASSWORD'] = password
    input_data(env)
    if input('Type CREATE INITIAL ADMIN to create this account: ') != 'CREATE INITIAL ADMIN':
        raise BootstrapError('INITIAL_ADMIN_CANCELLED')
    provision(env_file, env)  # Recheck after prompts; SQL also locks/rechecks the empty store.


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file', required=True, type=Path)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--check-only', action='store_true', help='Read-only migrations and empty-store checks; never create an account.')
    mode.add_argument('--interactive', action='store_true', help='Check first, then prompt for metadata and a hidden password.')
    options = parser.parse_args()
    try:
        if options.check_only:
            count = preflight(options.env_file)
            print(f'Preflight passed: database=investigator; users=0; organizations=0; migrations={count}. No account created.')
            return 0
        if options.interactive:
            interactive(options.env_file)
        else:
            provision(options.env_file)
    except (BootstrapError, OSError, ValueError, EOFError, KeyboardInterrupt, getpass.GetPassWarning) as error:
        code = str(error) if isinstance(error, BootstrapError) else 'INITIAL_ADMIN_LOCAL_IO_FAILED'
        print(code, file=sys.stderr)
        return 2
    print('Initial administrator provisioned in one owning department. No credentials printed.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
