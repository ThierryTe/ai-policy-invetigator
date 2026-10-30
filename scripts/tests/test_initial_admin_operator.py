"""Operator guards and packaged runtime; all credentials/configuration are synthetic."""
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import pty
import select
import shutil
import signal
import subprocess
import sys
import tarfile
import tempfile
import termios
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import package_initial_admin as bundle
import provision_initial_admin as bootstrap


class OperatorTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.env_file = self.root / 'private.env'
        self.env_file.write_text('# synthetic fixture only\n')
        self.env_file.chmod(0o600)
        self.snapshot = {'database': 'investigator', 'extensions_ready': True, 'users': 0, 'organizations': 0,
                         'migrations': [{**row, 'success': True, 'type': 'SQL'} for row in bootstrap.expected_migrations()]}
        self.env = {'INVESTIGATOR_INITIAL_ADMIN_ENABLED': 'true',
                    'INVESTIGATOR_INITIAL_EMAIL': 'Admin@test.invalid',
                    'INVESTIGATOR_INITIAL_PASSWORD': 'synthetic-operator-test-password',
                    'INVESTIGATOR_INITIAL_ORGANIZATION': 'Synthetic operator tests',
                    'INVESTIGATOR_INITIAL_DEPARTMENT': 'Policy analysis'}

    def reply(self, snapshot=None):
        return SimpleNamespace(returncode=0, stdout=json.dumps(self.snapshot if snapshot is None else snapshot), stderr='')

    def test_preflight_is_read_only_and_targets_only_local_existing_service(self):
        with patch.object(bootstrap.subprocess, 'run', return_value=self.reply()) as run:
            self.assertEqual(bootstrap.preflight(self.env_file, self.env), len(bootstrap.expected_migrations()))
        args = run.call_args.args[0]
        self.assertEqual(args[:4], ['docker', '--host', 'unix:///var/run/docker.sock', 'compose'])
        self.assertEqual(args[args.index('-p') + 1], 'ai-policy-investigator')
        self.assertEqual(args[args.index('exec') + 1:args.index('psql')], ['-T', 'postgres'])
        self.assertTrue(run.call_args.kwargs['input'].lstrip().startswith('BEGIN READ ONLY;'))
        self.assertNotIn('INSERT', run.call_args.kwargs['input'])
        self.assertFalse(any(key.startswith('INVESTIGATOR_INITIAL_') for key in run.call_args.kwargs['env']))
        self.assertFalse(set(args) & {'up', 'run', 'build', 'pull', 'create', 'restart', 'down'})

    def test_missing_extra_failed_duplicate_or_changed_migration_blocks_creation(self):
        snapshots = []
        for mutate in [lambda rows: rows.pop(), lambda rows: rows.append(dict(rows[0])),
                       lambda rows: rows[0].update(success=False), lambda rows: rows[0].update(checksum=0),
                       lambda rows: rows[0].update(script='V1__other.sql'),
                       lambda rows: rows[0].update(type='BASELINE'), lambda rows: rows.clear(),
                       lambda rows: rows.append({'version': '99', 'script': 'V99__future.sql',
                                                 'checksum': 1, 'success': True, 'type': 'SQL'})]:
            data = copy.deepcopy(self.snapshot)
            mutate(data['migrations'])
            snapshots.append(data)
        for data in snapshots:
            with self.subTest(migrations=data['migrations']):
                with patch.object(bootstrap.subprocess, 'run', return_value=self.reply(data)) as run:
                    with self.assertRaises(bootstrap.BootstrapError):
                        bootstrap.provision(self.env_file, self.env)
                    self.assertEqual(run.call_count, 1)  # No COPY/write call.

    def test_nonempty_store_wrong_database_or_missing_extensions_blocks_creation(self):
        for updates in [{'users': 1}, {'organizations': 1}, {'database': 'unrelated'}, {'extensions_ready': False}]:
            with patch.object(bootstrap.subprocess, 'run', return_value=self.reply({**self.snapshot, **updates})) as run:
                with self.assertRaises(bootstrap.BootstrapError):
                    bootstrap.provision(self.env_file, self.env)
                self.assertEqual(run.call_count, 1)

    def test_unreadable_response_and_database_errors_are_not_printed(self):
        for value in ['private-test-sentinel', '{}', '[]', '{"database": "investigator", "migrations": null}']:
            with patch.object(bootstrap.subprocess, 'run', return_value=SimpleNamespace(returncode=0, stdout=value)):
                with self.assertRaises(bootstrap.BootstrapError) as error:
                    bootstrap.preflight(self.env_file, {})
                self.assertNotIn('private-test-sentinel', str(error.exception))

    def test_private_env_permissions_and_symlinks_are_rejected_before_docker(self):
        self.env_file.chmod(0o644)
        link = self.root / 'linked.env'; link.symlink_to(self.env_file)
        for path in [self.env_file, link, self.root / 'missing']:
            with patch.object(bootstrap.subprocess, 'run') as run:
                with self.assertRaises(bootstrap.BootstrapError):
                    bootstrap.preflight(path, {})
                run.assert_not_called()

    def test_success_checks_before_copy_and_keeps_password_out_of_argv_and_child_env(self):
        with patch.object(bootstrap.subprocess, 'run', side_effect=[self.reply(), SimpleNamespace(returncode=0, stdout='')]) as run:
            bootstrap.provision(self.env_file, self.env)
        self.assertEqual(run.call_count, 2)
        first, second = run.call_args_list
        self.assertEqual(first.kwargs['input'], bootstrap.PREFLIGHT_SQL)
        self.assertIn('COPY pg_temp.initial_admin_input FROM STDIN;', second.kwargs['input'])
        for call in run.call_args_list:
            self.assertNotIn(self.env['INVESTIGATOR_INITIAL_PASSWORD'], repr(call.args))
            self.assertFalse(any(key.startswith('INVESTIGATOR_INITIAL_') for key in call.kwargs['env']))
            self.assertTrue(call.kwargs['capture_output'])

    def interactive_mocks(self):
        # Enter manually to keep each assertion's context visible in the tests.
        return patch.object(bootstrap.sys.stdin, 'isatty', return_value=True), patch.object(bootstrap.sys.stderr, 'isatty', return_value=True)

    def test_failed_preflight_never_prompts_for_password(self):
        stdin, stderr = self.interactive_mocks()
        with stdin, stderr, patch.object(bootstrap, 'preflight', side_effect=bootstrap.BootstrapError('STOP')):
            with patch('builtins.input') as prompt, patch.object(bootstrap.getpass, 'getpass') as password:
                with self.assertRaisesRegex(bootstrap.BootstrapError, 'STOP'):
                    bootstrap.interactive(self.env_file)
                prompt.assert_not_called(); password.assert_not_called()

    def test_interactive_requires_a_terminal(self):
        with patch.object(bootstrap.sys.stdin, 'isatty', return_value=False), patch.object(bootstrap, 'preflight') as check:
            with self.assertRaisesRegex(bootstrap.BootstrapError, 'TERMINAL_REQUIRED'):
                bootstrap.interactive(self.env_file)
            check.assert_not_called()

    def test_password_confirmation_and_final_confirmation_are_required(self):
        for passwords, confirmation in [(['synthetic-test-password', 'different'], 'CREATE INITIAL ADMIN'),
                                        (['synthetic-test-password'] * 2, 'no')]:
            stdin, stderr = self.interactive_mocks()
            with stdin, stderr, patch.object(bootstrap, 'preflight', return_value=6), patch.object(bootstrap, 'provision') as provision:
                with patch('builtins.input', side_effect=['admin@test.invalid', 'Synthetic', 'Policy', confirmation]), patch.object(bootstrap.getpass, 'getpass', side_effect=passwords), patch('sys.stdout', new_callable=io.StringIO):
                    with self.assertRaises(bootstrap.BootstrapError):
                        bootstrap.interactive(self.env_file)
                    provision.assert_not_called()

    def test_interactive_rechecks_after_prompts_without_echoing_password(self):
        stdin, stderr = self.interactive_mocks()
        with stdin, stderr, patch.object(bootstrap, 'preflight', side_effect=[6, bootstrap.BootstrapError('STORE_CHANGED')]) as check:
            with patch('builtins.input', side_effect=['admin@test.invalid', 'Synthetic', 'Policy', 'CREATE INITIAL ADMIN']), patch.object(bootstrap.getpass, 'getpass', return_value='synthetic-test-password'), patch.object(bootstrap, 'database_run') as database, patch('sys.stdout', new_callable=io.StringIO) as output:
                with self.assertRaisesRegex(bootstrap.BootstrapError, 'STORE_CHANGED'):
                    bootstrap.interactive(self.env_file)
                self.assertEqual(check.call_count, 2)
                database.assert_not_called()
                self.assertNotIn('synthetic-test-password', output.getvalue())

    def test_no_fallback_to_unmasked_password_input(self):
        stdin, stderr = self.interactive_mocks()
        with stdin, stderr, patch.object(bootstrap, 'preflight', return_value=6), patch.object(bootstrap, 'provision') as provision:
            with patch('builtins.input', side_effect=['admin@test.invalid', 'Synthetic', 'Policy']), patch.object(bootstrap.getpass, 'getpass', side_effect=bootstrap.getpass.GetPassWarning()), patch('sys.stdout', new_callable=io.StringIO):
                with self.assertRaises(bootstrap.getpass.GetPassWarning):
                    bootstrap.interactive(self.env_file)
                provision.assert_not_called()

    def test_check_only_never_provisions(self):
        with patch.object(sys, 'argv', ['bootstrap', '--env-file', str(self.env_file), '--check-only']), patch.object(bootstrap, 'preflight', return_value=6), patch.object(bootstrap, 'provision') as provision, patch('sys.stdout', new_callable=io.StringIO) as output:
            self.assertEqual(bootstrap.main(), 0)
            provision.assert_not_called()
            self.assertIn('No account created', output.getvalue())


class PackageTest(unittest.TestCase):
    def test_exact_public_allowlist_checksums_and_standalone_help(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'initial-admin.tar.gz'
            self.assertEqual(bundle.package(output), 7)
            with tarfile.open(output) as archive:
                names = set(archive.getnames())
                self.assertEqual(names, set(bundle.FILES) | {bootstrap.MIGRATION_INVENTORY, 'FILES.sha256'})
                self.assertFalse(any('.env' in name or name.startswith('src/') for name in names))
                self.assertTrue(all(member.isfile() and member.mode == 0o644 for member in archive.getmembers()))
                sums = archive.extractfile('FILES.sha256').read().decode()
                for line in sums.splitlines():
                    digest, name = line.split('  ', 1)
                    self.assertEqual(hashlib.sha256(archive.extractfile(name).read()).hexdigest(), digest)
                inventory = json.loads(archive.extractfile(bootstrap.MIGRATION_INVENTORY).read())
                self.assertEqual(inventory, bootstrap.expected_migrations())
                extract = Path(directory) / 'extracted'; extract.mkdir()
                archive.extractall(extract, filter='data')
            self.assertEqual(bootstrap.expected_migrations(extract), inventory)
            result = subprocess.run([sys.executable, '-B', str(extract / 'scripts/provision_initial_admin.py'), '--help'], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0)
            self.assertIn('--check-only', result.stdout); self.assertIn('--interactive', result.stdout)
            self.assertEqual(Path(str(output) + '.sha256').read_text(), hashlib.sha256(output.read_bytes()).hexdigest() + '  ' + output.name + '\n')
            with self.assertRaisesRegex(bootstrap.BootstrapError, 'OUTPUT_EXISTS'):
                bundle.package(output)

    def test_missing_or_symlink_source_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(bootstrap.BootstrapError):
                bundle.package(root / 'out.tar.gz', root)
            (root / 'compose.yaml').symlink_to(bootstrap.ROOT / 'compose.yaml')
            with self.assertRaises(bootstrap.BootstrapError):
                bundle.package(root / 'out.tar.gz', root)

    def test_packaged_compose_resolves_with_only_public_synthetic_configuration(self):
        if not shutil.which('docker'):
            self.skipTest('Compose CLI required; Docker Engine is not used.')
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'initial-admin.tar.gz'
            bundle.package(output)
            root = Path(directory) / 'tools'; root.mkdir()
            with tarfile.open(output) as archive:
                archive.extractall(root, filter='data')
            env = {'PATH': os.defpath, 'POSTGRES_ADMIN_PASSWORD': 'synthetic-test-only',
                   'OWNER_DB_PASSWORD': 'synthetic-test-only', 'APP_DB_PASSWORD': 'synthetic-test-only',
                   'JWT_SECRET': 'synthetic-test-only-at-least-32-characters'}
            result = subprocess.run([shutil.which('docker'), 'compose', '--project-directory', str(root),
                                     '--env-file', '/dev/null', '-p', 'ai-policy-investigator',
                                     '-f', str(root / 'compose.yaml'), '-f', str(root / 'compose.production.yaml'),
                                     '--profile', 'app', 'config', '--quiet'],
                                    env=env, text=True, capture_output=True, timeout=20)
            self.assertEqual(result.returncode, 0, 'Packaged Compose files did not resolve with synthetic settings.')

    def test_migration_inventory_matches_existing_release_checksum_algorithm(self):
        from release_artifacts import flyway_checksum
        for row in bootstrap.expected_migrations():
            source = bootstrap.ROOT / 'src/main/resources/db/migration' / row['script']
            self.assertEqual(row['checksum'], flyway_checksum(source.read_bytes()))

    def test_invalid_inventory_is_refused(self):
        for rows in [[], {}, [{'version': '1', 'script': '../escape', 'checksum': 1}],
                     [{'version': '1', 'script': 'V1__one.sql', 'checksum': True}],
                     [{'version': '1', 'script': 'V1__one.sql', 'checksum': 1}] * 2]:
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                file = root / bootstrap.MIGRATION_INVENTORY; file.parent.mkdir(parents=True)
                file.write_text(json.dumps(rows))
                with self.assertRaises(bootstrap.BootstrapError):
                    bootstrap.expected_migrations(root)

    def test_packaged_interactive_cli_uses_hidden_terminal_and_refuses_second_initialization(self):
        # A real PTY/getpass, but a fake Docker executable: no daemon or remote access.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive_file = root / 'tools.tar.gz'; bundle.package(archive_file)
            tools = root / 'tools'; tools.mkdir()
            with tarfile.open(archive_file) as archive:
                archive.extractall(tools, filter='data')
            expected = bootstrap.expected_migrations(tools)
            snapshot = {'database': 'investigator', 'extensions_ready': True, 'users': 0, 'organizations': 0,
                        'migrations': [{**row, 'success': True, 'type': 'SQL'} for row in expected]}
            snapshot_file = root / 'snapshot.json'; snapshot_file.write_text(json.dumps(snapshot))
            env_file = root / 'synthetic.env'; env_file.write_text('# synthetic only\n'); env_file.chmod(0o600)
            fakebin = root / 'bin'; fakebin.mkdir()
            docker = fakebin / 'docker'
            docker.write_text('#!' + sys.executable + '\n' + '''
import base64, json, os, pathlib, sys
root = pathlib.Path(__file__).resolve().parents[1]
assert sys.argv[1:4] == ['--host', 'unix:///var/run/docker.sock', 'compose']
assert 'exec' in sys.argv and 'postgres' in sys.argv
assert not any(k.startswith('INVESTIGATOR_INITIAL_') for k in os.environ)
payload = sys.stdin.read()
if payload.lstrip().startswith('BEGIN READ ONLY;'):
    snapshot = json.loads((root / 'snapshot.json').read_text())
    if (root / 'created').exists():
        snapshot.update(users=1, organizations=1)
    print(json.dumps(snapshot))
else:
    assert not (root / 'created').exists()
    assert 'COPY pg_temp.initial_admin_input FROM STDIN;' in payload
    encoded = payload.split('COPY pg_temp.initial_admin_input FROM STDIN;\\n')[1].splitlines()[0]
    data = json.loads(base64.b64decode(encoded))
    assert data['email'] == 'admin@test.invalid'
    assert data['password'] == 'synthetic-pty-password'
    (root / 'created').write_text('created without saving credentials')
''')
            docker.chmod(0o700)
            args = [sys.executable, '-B', str(tools / 'scripts/provision_initial_admin.py'),
                    '--env-file', str(env_file), '--interactive']
            env = {'PATH': str(fakebin) + ':' + os.defpath}
            pid, master = pty.fork()
            if pid == 0:
                os.execve(sys.executable, args, env)
            output = bytearray()
            deadline = time.monotonic() + 20
            reaped = False
            def receive_until(marker):
                while marker not in output:
                    remaining = deadline - time.monotonic()
                    self.assertGreater(remaining, 0, 'Interactive CLI timed out.')
                    ready, _, _ = select.select([master], [], [], remaining)
                    self.assertTrue(ready, 'Interactive CLI did not prompt.')
                    try:
                        content = os.read(master, 8192)
                    except OSError:
                        content = b''
                    self.assertTrue(content, 'Interactive CLI stopped before its expected prompt.')
                    output.extend(content)
            try:
                for prompt, response, hidden in [
                    (b'Login email: ', b'Admin@test.invalid\n', False),
                    (b'Organization: ', b'Synthetic organization\n', False),
                    (b'Owning department: ', b'Policy analysis\n', False),
                    (b'Initial administrator password (16-72 UTF-8 bytes): ', b'synthetic-pty-password\n', True),
                    (b'Confirm password: ', b'synthetic-pty-password\n', True),
                    (b'Type CREATE INITIAL ADMIN to create this account: ', b'CREATE INITIAL ADMIN\n', False),
                ]:
                    receive_until(prompt)
                    if hidden:
                        self.assertFalse(termios.tcgetattr(master)[3] & termios.ECHO)
                    os.write(master, response)
                receive_until(b'No credentials printed.')
                self.assertNotIn(b'synthetic-pty-password', output)
                while time.monotonic() < deadline:
                    done, status = os.waitpid(pid, os.WNOHANG)
                    if done:
                        reaped = True
                        self.assertEqual(os.waitstatus_to_exitcode(status), 0)
                        break
                    select.select([], [], [], 0.01)
                self.assertTrue(reaped, 'Interactive CLI failed to exit.')
            finally:
                os.close(master)
                if not reaped:
                    os.kill(pid, signal.SIGKILL)
                    os.waitpid(pid, 0)
            self.assertTrue((root / 'created').exists())
            check = subprocess.run(args[:-1] + ['--check-only'], env=env, text=True, capture_output=True, timeout=10)
            self.assertEqual(check.returncode, 2)
            self.assertEqual(check.stderr.strip(), 'INITIAL_ADMIN_REQUIRES_EMPTY_IDENTITY_STORE')
            self.assertNotIn('synthetic-pty-password', check.stdout + check.stderr)


if __name__ == '__main__':
    unittest.main()
