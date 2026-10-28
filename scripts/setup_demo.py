#!/usr/bin/env python3
"""Explicit local operator seed; no app startup hooks, API bypass or model calls.

Requires APP_ENVIRONMENT=local, DEMO_USER_ENABLED=true and DEMO_PASSWORD in the
process environment. Existing root .env supplies Compose's database configuration;
this tool never imports a password from another repository or invents a default.
"""
import base64
import json
import os
from pathlib import Path
import subprocess
import sys

from smoke_workflow import pdf

ROOT = Path(__file__).resolve().parents[1]
EMAIL = 'demo@policy-investigator.local'
MARKER = '-- DEMO_INPUT --'


class DemoSetupError(Exception):
    pass


def validate_environment(env):
    if env.get('DEMO_USER_ENABLED') != 'true' or env.get('APP_ENVIRONMENT') != 'local':
        raise DemoSetupError('DEMO_SEED_DISABLED: export DEMO_USER_ENABLED=true and APP_ENVIRONMENT=local explicitly.')
    password = env.get('DEMO_PASSWORD', '')
    if (not 16 <= len(password.encode('utf-8')) <= 72 or
            any(ord(c) < 32 or ord(c) == 127 for c in password) or password.startswith('replace-with-')):
        raise DemoSetupError('DEMO_PASSWORD_REQUIRED: provide a private password of 16–72 UTF-8 bytes, without control characters.')
    return password


def sql_input(password):
    template = (ROOT / 'scripts/seed_demo.sql').read_text()
    if template.count(MARKER) != 1:
        raise DemoSetupError('DEMO_SEED_TEMPLATE_INVALID')
    encoded = base64.b64encode(password.encode()).decode('ascii')
    # COPY transports the secret as data. No password or encoding goes into SQL
    # literals, argv, stdout or application logs; the temp input drops at commit.
    copy = 'COPY pg_temp.demo_seed_input FROM STDIN;\ntrue\tlocal\t' + encoded + '\n\\.\n'
    return template.replace(MARKER, copy)


def write_fixtures(directory):
    golden = json.loads((ROOT / 'evaluation/phase3-golden.json').read_text())
    files = {
        '01-security-baseline.pdf': golden['baseline'],
        '02-security-replacement.pdf': golden['replacement'],
        '03-hr-conflicting.pdf': golden['cases'][0]['procedure'],
        '04-hr-compatible.pdf': golden['cases'][1]['procedure'],
    }
    directory.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        (directory / name).write_bytes(pdf(text))
    return len(files)


def setup(env=None):
    env = os.environ if env is None else env
    password = validate_environment(env)  # Refuse before invoking Docker or creating anything.
    if not (ROOT / '.env').is_file():
        raise DemoSetupError('LOCAL_ENV_MISSING: populate this backend repository’s root .env first.')
    command = ['docker', 'compose', '--env-file', '.env', 'exec', '-T', 'postgres',
               'psql', '-X', '-q', '-U', 'postgres', '-d', 'investigator', '-v', 'ON_ERROR_STOP=1']
    try:
        result = subprocess.run(command, input=sql_input(password), text=True, capture_output=True,
                                cwd=ROOT, env=dict(env), timeout=45)
    except (OSError, subprocess.TimeoutExpired):
        raise DemoSetupError('DEMO_DATABASE_UNAVAILABLE: start the dedicated local backend deployment first.') from None
    if result.returncode:
        # Never print SQL, exception objects, stdout or stderr, even on failure.
        raise DemoSetupError('DEMO_SEED_FAILED: verify migrations and that no unrelated account uses the demo identity.')
    try:
        count = write_fixtures(ROOT / '.local/demo/pdfs')
    except (OSError, ValueError, KeyError):
        raise DemoSetupError('DEMO_FIXTURE_EXPORT_FAILED: account provisioned; verify the local fixture directory and rerun.') from None
    return count


def main():
    try:
        count = setup()
    except DemoSetupError as error:
        print(str(error), file=sys.stderr)
        return 2
    print('Local demo account ready: ' + EMAIL)
    print('Current memberships: ADMIN in demo Security and HR departments only.')
    print(f'{count} synthetic PDFs exported to .local/demo/pdfs; no documents uploaded or sent to Meta.')
    print('Password was read from DEMO_PASSWORD and is never printed.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
