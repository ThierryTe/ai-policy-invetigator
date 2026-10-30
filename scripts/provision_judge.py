#!/usr/bin/env python3
"""Explicit judge provisioning through a local socket, optionally inside the existing PostgreSQL container."""
import argparse
import base64
from datetime import datetime, timezone
import getpass
import json
import os
import re
from pathlib import Path
import subprocess
import sys
import tempfile
import uuid
import warnings
import zlib

ROOT = Path(__file__).resolve().parents[1]
MIGRATION_INVENTORY = 'deploy/postgres/judge-migrations.json'
LOCAL_DOCKER_ENDPOINT = 'unix:///var/run/docker.sock'
OPERATOR_PATH = '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
PROJECT = 'ai-policy-investigator'
INSPECT_FORMAT = ('{"id":{{json .Id}},"running":{{json .State.Running}},'
                  '"project":{{json (index .Config.Labels "com.docker.compose.project")}},'
                  '"service":{{json (index .Config.Labels "com.docker.compose.service")}},'
                  '"ports":{{json .HostConfig.PortBindings}},'
                  '"published_ports":{{json .NetworkSettings.Ports}},"publish_all":{{json .HostConfig.PublishAllPorts}},'
                  '"network_count":{{len .NetworkSettings.Networks}},'
                  '"database_network":{{if index .NetworkSettings.Networks "ai-policy-investigator_database"}}true{{else}}false{{end}},'
                  '"data_volumes":[{{range .Mounts}}{{if eq .Destination "/var/lib/postgresql/data"}}{{json .Name}}{{end}}{{end}}]}')
PREFLIGHT_SQL = """
BEGIN READ ONLY;
SET LOCAL statement_timeout='15s';
SET LOCAL lock_timeout='5s';
SELECT json_build_object(
 'database',current_database(),'user',current_user,'session_user',session_user,
 'local_socket',inet_client_addr() IS NULL,
 'safe_owner',(SELECT NOT rolsuper AND NOT rolbypassrls FROM pg_roles WHERE rolname=current_user)
   AND NOT pg_has_role(current_user,'investigator_runtime','USAGE'),
 'owns_control_tables',(SELECT count(*)=6 AND bool_and(c.relowner=r.oid)
   FROM pg_class c CROSS JOIN pg_roles r WHERE r.rolname=current_user AND c.relnamespace='public'::regnamespace
   AND c.relname IN ('app_users','departments','memberships','policy_grants','demo_access','demo_meta_budget')),
 'rls_ready',(SELECT count(*)=8 AND bool_and(relrowsecurity AND relforcerowsecurity)
   FROM pg_class WHERE relnamespace='public'::regnamespace AND relname IN
   ('policies','policy_versions','document_pages','chunks','investigations','requirement_extractions','investigation_assessments','finding_reviews')),
 'extensions_ready',(SELECT count(*)=2 FROM pg_extension WHERE extname IN ('pgcrypto','vector')),
 'migrations',(SELECT json_agg(json_build_object('version',version,'script',script,'checksum',checksum,'success',success,'type',type)
   ORDER BY installed_rank) FROM public.flyway_schema_history));
ROLLBACK;
"""
FIELDS = {'email', 'department', 'organization_id', 'operator_user_id', 'investigation_id',
          'expires_at', 'read_policy_ids', 'synthetic_data_confirmed', 'max_imports', 'max_bytes',
          'max_investigations', 'max_pending', 'max_meta_attempts', 'shared_meta_attempts'}


class JudgeError(ValueError):
    """Fixed diagnostic codes only; no subprocess output or private input."""


def expected_migrations(root=ROOT):
    inventory = root / MIGRATION_INVENTORY
    if inventory.is_symlink() or not inventory.resolve().is_relative_to(root.resolve()):
        raise JudgeError('JUDGE_MIGRATION_INVENTORY_INVALID')
    if inventory.is_file():
        rows = json.loads(inventory.read_text())
    else:
        rows = []
        for path in sorted((root / 'src/main/resources/db/migration').glob('V*__*.sql')):
            match = re.fullmatch(r'V([0-9]+)__[a-z0-9_]+\.sql', path.name)
            if not match or path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
                raise JudgeError('JUDGE_MIGRATION_INVENTORY_INVALID')
            value = zlib.crc32(re.sub(r'\r\n|\r|\n', '', path.read_bytes().decode('utf-8-sig')).encode())
            rows.append({'version': match[1], 'script': path.name, 'checksum': value if value < 2**31 else value - 2**32})
    if not isinstance(rows, list) or not rows:
        raise JudgeError('JUDGE_MIGRATION_INVENTORY_INVALID')
    for row in rows:
        if (not isinstance(row, dict) or set(row) != {'version', 'script', 'checksum'}
                or not isinstance(row['version'], str) or not row['version'].isdecimal()
                or not isinstance(row['script'], str)
                or not re.fullmatch(r'V' + row['version'] + r'__[a-z0-9_]+\.sql', row['script'])
                or type(row['checksum']) is not int or not -2**31 <= row['checksum'] < 2**31):
            raise JudgeError('JUDGE_MIGRATION_INVENTORY_INVALID')
    if len({row['version'] for row in rows}) != len(rows) or not any(row['version'] == '7' for row in rows):
        raise JudgeError('JUDGE_MIGRATION_INVENTORY_INVALID')
    return sorted(rows, key=lambda row: int(row['version']))


def run_private(command, content=None):
    try:
        result = subprocess.run(command, input=content, text=True, capture_output=True,
                                timeout=45, env={'PATH': OPERATOR_PATH})
    except (OSError, subprocess.TimeoutExpired):
        raise JudgeError('JUDGE_LOCAL_DATABASE_UNAVAILABLE') from None
    if result.returncode:
        raise JudgeError('JUDGE_LOCAL_DATABASE_REFUSED')
    return result.stdout


def container_psql(container_id):
    if not isinstance(container_id, str) or not re.fullmatch(r'[0-9a-f]{64}', container_id):
        raise JudgeError('JUDGE_CONTAINER_ID_REQUIRED')
    # No secret-bearing Compose interpolation or Docker credential/config files are needed.
    with tempfile.TemporaryDirectory(prefix='judge-docker-config-') as config:
        raw = run_private(['docker', '--host', LOCAL_DOCKER_ENDPOINT, '--config', config,
                           'inspect', '--type', 'container', '--format', INSPECT_FORMAT, container_id])
    try:
        row = json.loads(raw)
        if (row['id'] != container_id or row['running'] is not True or row['project'] != PROJECT
                or row['service'] != 'postgres' or any((row['ports'] or {}).values())
                or any((row['published_ports'] or {}).values()) or row['publish_all'] is not False
                or row['network_count'] != 1 or row['database_network'] is not True
                or row['data_volumes'] != [PROJECT + '_investigator_data']):
            raise JudgeError('JUDGE_CONTAINER_TOPOLOGY_REFUSED')
    except (ValueError, TypeError, KeyError):
        raise JudgeError('JUDGE_CONTAINER_TOPOLOGY_REFUSED') from None
    # Exec stdin is a pipe, not a TTY. The host terminal remains available for getpass.
    # env -i prevents the container's existing database credentials reaching psql.
    return ['exec', '-i', '--user', 'postgres', container_id,
            'env', '-i', 'PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin',
            'PGPASSFILE=/dev/null', 'PGSERVICEFILE=/dev/null', 'PGAPPNAME=judge-provisioning',
            'psql', '-X', '-w', '-q', '-h', '/var/run/postgresql', '-U', 'investigator_owner',
            '-d', 'investigator', '-v', 'ON_ERROR_STOP=1']


def local_psql(socket_directory, database, db_user):
    if (not isinstance(socket_directory, str) or not Path(socket_directory).is_absolute()
            or any(c in socket_directory for c in ',\n\r\0')
            or any(not isinstance(value, str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_-]{0,62}', value)
                   for value in (database, db_user))):
        raise JudgeError('JUDGE_LOCAL_DATABASE_REQUIRED')
    return ['psql', '-X', '-w', '-q', '-h', socket_directory, '-U', db_user, '-d', database,
            '-v', 'ON_ERROR_STOP=1']


def database_run(command, content, container=False, tuples=False):
    if tuples:
        command = command + ['-A', '-t']
    if container:
        with tempfile.TemporaryDirectory(prefix='judge-docker-config-') as config:
            return run_private(['docker', '--host', LOCAL_DOCKER_ENDPOINT, '--config', config] + command, content)
    # Prevent libpq password/service files and inherited credential variables in local mode too.
    try:
        result = subprocess.run(command, input=content, text=True, capture_output=True, timeout=45,
                                env={'PATH': OPERATOR_PATH, 'PGPASSFILE': os.devnull, 'PGSERVICEFILE': os.devnull,
                                     'PGAPPNAME': 'judge-provisioning'})
    except (OSError, subprocess.TimeoutExpired):
        raise JudgeError('JUDGE_LOCAL_DATABASE_UNAVAILABLE') from None
    if result.returncode:
        raise JudgeError('JUDGE_LOCAL_DATABASE_REFUSED')
    return result.stdout


def preflight(command, database, db_user, container=False):
    expected = expected_migrations()
    raw = database_run(command, PREFLIGHT_SQL, container, tuples=True)
    try:
        data = json.loads(raw)
        applied = data['migrations']
        if (data['database'] != database or data['user'] != db_user or data['session_user'] != db_user
                or any(data[name] is not True for name in
                       ('local_socket', 'safe_owner', 'owns_control_tables', 'rls_ready', 'extensions_ready'))
                or not isinstance(applied, list)
                or any(row['success'] is not True or row['type'] != 'SQL' for row in applied)
                or [{'version': row['version'], 'script': row['script'], 'checksum': row['checksum']}
                    for row in applied] != expected):
            raise JudgeError('JUDGE_OWNER_OR_MIGRATIONS_REFUSED')
    except (ValueError, TypeError, KeyError):
        raise JudgeError('JUDGE_OWNER_OR_MIGRATIONS_REFUSED') from None
    return len(expected)


def validate_manifest(data):
    if not isinstance(data, dict) or set(data) != FIELDS or data['synthetic_data_confirmed'] is not True:
        raise ValueError('JUDGE_MANIFEST_INVALID')
    for field in ('organization_id', 'operator_user_id', 'investigation_id'):
        uuid.UUID(data[field])
    ids = data['read_policy_ids']
    if not isinstance(ids, list) or not 2 <= len(ids) <= 5 or len(set(ids)) != len(ids):
        raise ValueError('JUDGE_POLICY_ALLOWLIST_INVALID')
    for value in ids:
        uuid.UUID(value)
    for field in ('max_imports', 'max_bytes', 'max_investigations', 'max_pending', 'max_meta_attempts', 'shared_meta_attempts'):
        value = data[field]
        maximum = 2**31 - 1 if field in ('max_imports', 'max_investigations', 'max_pending') else 2**63 - 1
        if type(value) is not int or not 0 <= value <= maximum:
            raise ValueError('JUDGE_LIMIT_INVALID')
    if data['max_pending'] < 1 or data['shared_meta_attempts'] < 1:
        raise ValueError('JUDGE_LIMIT_INVALID')
    for field in ('email', 'department', 'expires_at'):
        if not isinstance(data[field], str) or any(ord(c) < 32 or ord(c) == 127 for c in data[field]):
            raise ValueError('JUDGE_METADATA_INVALID')
    email = data['email'].strip().lower()
    if len(email) > 254 or email.count('@') != 1 or not all(email.split('@')) or any(c.isspace() for c in email):
        raise ValueError('JUDGE_EMAIL_INVALID')
    if not 1 <= len(data['department'].strip()) <= 200:
        raise ValueError('JUDGE_DEPARTMENT_INVALID')
    expiry = datetime.fromisoformat(data['expires_at'].replace('Z', '+00:00'))
    if expiry.utcoffset() is None or expiry <= datetime.now(timezone.utc):
        raise ValueError('JUDGE_EXPIRY_INVALID')


def sql_input(data, password):
    validate_manifest(data)
    if not 16 <= len(password.encode('utf-8')) <= 72 or any(ord(c) < 32 or ord(c) == 127 for c in password):
        raise ValueError('JUDGE_PASSWORD_INVALID')
    template = (ROOT / 'scripts/provision_judge.sql').read_text()
    if template.count('-- JUDGE_INPUT --') != 1:
        raise ValueError('JUDGE_TEMPLATE_INVALID')
    encoded = base64.b64encode(json.dumps({**data, 'password': password}).encode()).decode()
    return template.replace('-- JUDGE_INPUT --', 'COPY pg_temp.judge_input FROM STDIN;\n' + encoded + '\n\\.\n')


def apply(data, password, socket_directory, database, db_user):
    content = sql_input(data, password)
    command = local_psql(socket_directory, database, db_user)
    preflight(command, database, db_user)
    database_run(command, "SET statement_timeout='20s'; SET lock_timeout='5s';\n" + content)


def apply_in_container(data, password, container_id):
    content = sql_input(data, password)
    # Recheck after the password prompt. Never follow a replaced container or switch database roles.
    command = container_psql(container_id)
    preflight(command, 'investigator', 'investigator_owner', container=True)
    database_run(command, "SET statement_timeout='20s'; SET lock_timeout='5s';\n" + content, container=True)


def selected_connection(args):
    if args.postgres_container:
        if args.database or args.db_user:
            raise JudgeError('JUDGE_CONTAINER_DATABASE_IS_FIXED')
        return container_psql(args.postgres_container), 'investigator', 'investigator_owner', True
    return local_psql(args.socket_directory, args.database, args.db_user), args.database, args.db_user, False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', required=True, type=Path, help='Public metadata and limits only; no password field.')
    action = parser.add_mutually_exclusive_group()
    action.add_argument('--apply', action='store_true', help='Explicitly create one new account; requires a hidden password prompt.')
    action.add_argument('--check-only', action='store_true', help='Read-only owner authentication, topology and migration checks; no account creation.')
    transport = parser.add_mutually_exclusive_group()
    transport.add_argument('--socket-directory', help='Absolute local PostgreSQL Unix socket directory; no TCP or SSH.')
    transport.add_argument('--postgres-container', help='Full existing Compose PostgreSQL container ID on the local Docker daemon.')
    parser.add_argument('--database')
    parser.add_argument('--db-user')
    args = parser.parse_args()
    try:
        data = json.loads(args.manifest.read_text())
        validate_manifest(data)
        if not args.apply and not args.check_only:
            print('Judge manifest validated locally. No database access or account creation.')
            return 0
        command, database, db_user, container = selected_connection(args)
        count = preflight(command, database, db_user, container)
        if args.check_only:
            print(f'Judge preflight passed: local owner authentication; migrations={count}. No account created.')
            return 0
        if not sys.stdin.isatty() or not sys.stderr.isatty():
            raise ValueError('JUDGE_LOCAL_TERMINAL_REQUIRED')
        with warnings.catch_warnings():
            warnings.simplefilter('error', getpass.GetPassWarning)
            password = getpass.getpass('Judge password (16-72 UTF-8 bytes): ')
            if password != getpass.getpass('Confirm password: '):
                raise ValueError('JUDGE_PASSWORD_MISMATCH')
        if container:
            apply_in_container(data, password, args.postgres_container)
        else:
            apply(data, password, args.socket_directory, args.database, args.db_user)
    except (ValueError, TypeError, KeyError, AttributeError, OSError, EOFError, KeyboardInterrupt,
            subprocess.TimeoutExpired, getpass.GetPassWarning) as error:
        print(str(error) if isinstance(error, JudgeError) else
              'Judge provisioning refused or input invalid. No private diagnostics printed.', file=sys.stderr)
        return 2
    print('One judge account provisioned with a private department and targeted READ grants. No credentials printed.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
