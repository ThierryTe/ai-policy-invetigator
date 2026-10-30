import base64
import contextlib
from datetime import datetime, timedelta, timezone
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock
import uuid

MODULE_PATH = Path(__file__).resolve().parents[1] / 'provision_judge.py'
spec = importlib.util.spec_from_file_location('provision_judge', MODULE_PATH)
judge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(judge)


class JudgeProvisioningTest(unittest.TestCase):
    container_id = '1' * 64

    def owner_snapshot(self):
        return {'database': 'investigator', 'user': 'investigator_owner', 'session_user': 'investigator_owner',
                'local_socket': True, 'safe_owner': True, 'owns_control_tables': True, 'rls_ready': True,
                'extensions_ready': True, 'migrations': [{**r, 'success': True, 'type': 'SQL'} for r in judge.expected_migrations()]}

    def container_snapshot(self):
        return {'id': self.container_id, 'running': True, 'project': 'ai-policy-investigator', 'service': 'postgres',
                'ports': {}, 'published_ports': {'5432/tcp': None}, 'publish_all': False,
                'network_count': 1, 'database_network': True, 'data_volumes': ['ai-policy-investigator_investigator_data']}

    def reply(self, data):
        return Mock(returncode=0, stdout=json.dumps(data))

    def manifest(self):
        return {'email': str(uuid.uuid4()) + '@test.invalid', 'department': 'Synthetic judge test',
                'organization_id': str(uuid.uuid4()), 'operator_user_id': str(uuid.uuid4()),
                'investigation_id': str(uuid.uuid4()), 'expires_at': (datetime.now(timezone.utc) + timedelta(days=1)).isoformat(),
                'read_policy_ids': [str(uuid.uuid4()), str(uuid.uuid4())], 'synthetic_data_confirmed': True,
                'max_imports': 12, 'max_bytes': 67108864, 'max_investigations': 3, 'max_pending': 2,
                'max_meta_attempts': 30, 'shared_meta_attempts': 200}

    def test_rejects_unsafe_or_ambiguous_manifest_fields(self):
        for field, value in [('synthetic_data_confirmed', False), ('max_pending', 0), ('max_imports', True),
                             ('max_bytes', -1), ('max_meta_attempts', 2**63), ('read_policy_ids', []),
                             ('expires_at', '2020-01-01T00:00:00Z'), ('expires_at', '2099-01-01T00:00:00'),
                             ('password', 'private-test-marker')]:
            with self.subTest(field=field):
                data = self.manifest()
                data[field] = value
                with self.assertRaises((ValueError, TypeError)):
                    judge.validate_manifest(data)

    def test_password_is_copy_data_and_cannot_break_sql(self):
        password = "test-only-quote'\\; dollar$$ " + str(uuid.uuid4())
        data = self.manifest()
        sql = judge.sql_input(data, password)
        self.assertNotIn(password, sql)
        encoded = sql.split('COPY pg_temp.judge_input FROM STDIN;\n')[1].split('\n')[0]
        self.assertEqual(json.loads(base64.b64decode(encoded))['password'], password)
        self.assertIn("VALUES(actor,dept,'ADMIN')", sql)
        self.assertIn("SELECT unnest(shared),dept,'READ'", sql)

    def test_apply_requires_a_single_local_socket_and_plain_database_identifier(self):
        for socket, database, user in [('/tmp', 'postgresql://remote/db', 'operator'),
                                       ('/tmp', 'host=remote', 'operator'), ('remote', 'test', 'operator'),
                                       ('/tmp,remote', 'test', 'operator'), ('/tmp', 'test', '--option')]:
            with self.subTest(socket=socket, database=database):
                with patch.object(judge.subprocess, 'run') as run:
                    with self.assertRaises(ValueError):
                        judge.apply(self.manifest(), str(uuid.uuid4()), socket, database, user)
                    run.assert_not_called()

    def test_apply_never_passes_private_input_in_arguments_or_environment(self):
        password = str(uuid.uuid4())
        with patch.object(judge.subprocess, 'run', side_effect=[self.reply(self.owner_snapshot()), Mock(returncode=0)]) as run:
            judge.apply(self.manifest(), password, '/tmp', 'investigator', 'investigator_owner')
        args, kwargs = run.call_args
        self.assertNotIn(password, repr(args))
        self.assertNotIn(password, repr(kwargs['env']))
        self.assertEqual(kwargs['env']['PGPASSFILE'], judge.os.devnull)
        self.assertEqual(kwargs['env']['PGSERVICEFILE'], judge.os.devnull)
        self.assertIn('-X', args[0])
        self.assertIn('-w', args[0])

    def test_database_errors_never_echo_private_diagnostics(self):
        with patch.object(judge.subprocess, 'run', return_value=Mock(returncode=1, stderr='private-test-marker')):
            with self.assertRaisesRegex(ValueError, '^JUDGE_LOCAL_DATABASE_REFUSED$'):
                judge.apply(self.manifest(), str(uuid.uuid4()), '/tmp', 'isolated_test', 'operator')

    def test_container_transport_is_local_and_never_reads_resolved_compose_or_credentials(self):
        password = str(uuid.uuid4())
        replies = [self.reply(self.container_snapshot()), self.reply(self.owner_snapshot()), Mock(returncode=0)]
        with patch.dict(judge.os.environ, {'DOCKER_HOST': 'tcp://remote:2375', 'PGPASSWORD': 'private-env-marker'}), \
                patch.object(judge.subprocess, 'run', side_effect=replies) as run:
            judge.apply_in_container(self.manifest(), password, self.container_id)
        self.assertEqual(run.call_count, 3)
        for call in run.call_args_list:
            command = call.args[0]
            self.assertEqual(command[:3], ['docker', '--host', 'unix:///var/run/docker.sock'])
            self.assertIn('--config', command)
            self.assertEqual(call.kwargs['env'], {'PATH': judge.OPERATOR_PATH})
            self.assertNotIn(password, repr(command))
            self.assertNotIn('private-env-marker', repr(call))
            self.assertFalse(set(command) & {'up', 'run', 'build', 'pull', 'start', 'restart', 'stop', 'cp', 'compose'})
        inspect, check, apply = run.call_args_list
        self.assertNotIn('.Config.Env', inspect.args[0][inspect.args[0].index('--format') + 1])
        self.assertEqual(check.args[0][check.args[0].index('-U') + 1], 'investigator_owner')
        self.assertIn('-w', check.args[0])
        self.assertIn('-X', check.args[0])
        self.assertIn('-i', check.args[0])
        self.assertNotIn('-t', apply.args[0])
        self.assertIn('PGPASSFILE=/dev/null', check.args[0])
        self.assertIn('PGSERVICEFILE=/dev/null', check.args[0])
        self.assertIn('env', check.args[0])
        self.assertIn('-i', check.args[0][check.args[0].index('env') + 1:])
        self.assertTrue(check.kwargs['input'].lstrip().startswith('BEGIN READ ONLY;'))
        self.assertNotIn('COPY ', check.kwargs['input'])
        self.assertIn('COPY pg_temp.judge_input FROM STDIN;', apply.kwargs['input'])

    def test_wrong_container_topology_is_refused_before_database_access(self):
        for changes in [{'id': '2' * 64}, {'running': False}, {'project': 'other'}, {'service': 'backend'},
                        {'ports': {'5432/tcp': [{'HostPort': '5432'}]}},
                        {'published_ports': {'5432/tcp': [{'HostPort': '5432'}]}}, {'publish_all': True},
                        {'network_count': 2}, {'database_network': False}, {'data_volumes': ['other']}]:
            with self.subTest(changes=changes), patch.object(judge.subprocess, 'run', return_value=self.reply({**self.container_snapshot(), **changes})) as run:
                with self.assertRaisesRegex(judge.JudgeError, 'JUDGE_CONTAINER_TOPOLOGY_REFUSED'):
                    judge.apply_in_container(self.manifest(), str(uuid.uuid4()), self.container_id)
                self.assertEqual(run.call_count, 1)

    def test_container_id_must_be_full_and_cannot_be_a_name_or_shell_expression(self):
        for value in ['postgres', 'abc123', '-x', '$(hostname)', 'tcp://remote', 'A' * 64]:
            with self.subTest(value=value), patch.object(judge.subprocess, 'run') as run:
                with self.assertRaises(judge.JudgeError):
                    judge.container_psql(value)
                run.assert_not_called()

    def test_owner_authentication_failure_never_falls_back_or_submits_provisioning_sql(self):
        with patch.object(judge.subprocess, 'run', side_effect=[self.reply(self.container_snapshot()),
                Mock(returncode=2, stderr='private-server-diagnostic')]) as run:
            with self.assertRaisesRegex(judge.JudgeError, '^JUDGE_LOCAL_DATABASE_REFUSED$'):
                judge.apply_in_container(self.manifest(), str(uuid.uuid4()), self.container_id)
        self.assertEqual(run.call_count, 2)
        self.assertNotIn('COPY ', run.call_args.kwargs['input'])
        self.assertEqual(run.call_args.args[0][run.call_args.args[0].index('-U') + 1], 'investigator_owner')

    def test_preflight_refuses_unsafe_roles_tcp_or_changed_migrations(self):
        changes = [{'database': 'other'}, {'user': 'postgres'}, {'session_user': 'postgres'},
                   {'local_socket': False}, {'safe_owner': False}, {'owns_control_tables': False},
                   {'rls_ready': False}, {'extensions_ready': False}]
        for field in ('checksum', 'script', 'success', 'type'):
            data = self.owner_snapshot()
            data['migrations'][-1][field] = {'checksum': 0, 'script': 'V7__other.sql', 'success': False, 'type': 'BASELINE'}[field]
            changes.append({'migrations': data['migrations']})
        changes.extend([{'migrations': self.owner_snapshot()['migrations'][:-1]}, {'migrations': []}])
        for delta in changes:
            with self.subTest(delta=delta), patch.object(judge, 'database_run', return_value=json.dumps({**self.owner_snapshot(), **delta})):
                with self.assertRaisesRegex(judge.JudgeError, '^JUDGE_OWNER_OR_MIGRATIONS_REFUSED$'):
                    judge.preflight([], 'investigator', 'investigator_owner', container=True)

    def test_cli_preflight_never_prompts_or_writes_and_default_stays_offline(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / 'manifest.json'
            manifest.write_text(json.dumps(self.manifest()))
            for mode in ([], ['--check-only']):
                with self.subTest(mode=mode), patch.object(judge.sys, 'argv', ['provision_judge.py', '--manifest', str(manifest), '--postgres-container', self.container_id] + mode), \
                        patch.object(judge.subprocess, 'run', side_effect=[self.reply(self.container_snapshot()), self.reply(self.owner_snapshot())]) as run, \
                        patch.object(judge.getpass, 'getpass') as prompt, contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(judge.main(), 0)
                    self.assertEqual(run.call_count, 2 if mode else 0)
                    prompt.assert_not_called()

    def test_cli_refused_authentication_does_not_prompt_for_judge_password(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / 'manifest.json'; manifest.write_text(json.dumps(self.manifest()))
            with patch.object(judge.sys, 'argv', ['provision_judge.py', '--manifest', str(manifest), '--postgres-container', self.container_id, '--apply']), \
                    patch.object(judge.subprocess, 'run', side_effect=[self.reply(self.container_snapshot()), Mock(returncode=2, stderr='private-marker')]) as run, \
                    patch.object(judge.getpass, 'getpass') as password, contextlib.redirect_stderr(io.StringIO()) as output:
                self.assertEqual(judge.main(), 2)
                password.assert_not_called()
                self.assertEqual(run.call_count, 2)
                self.assertNotIn('private-marker', output.getvalue())

    def test_cli_rechecks_before_apply_and_refuses_role_changes_after_prompt(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / 'manifest.json'; manifest.write_text(json.dumps(self.manifest()))
            replies = [self.reply(self.container_snapshot()), self.reply(self.owner_snapshot()),
                       self.reply(self.container_snapshot()), self.reply({**self.owner_snapshot(), 'session_user': 'postgres'})]
            with contextlib.redirect_stderr(io.StringIO()), \
                    patch.object(judge.sys, 'argv', ['provision_judge.py', '--manifest', str(manifest), '--postgres-container', self.container_id, '--apply']), \
                    patch.object(judge.subprocess, 'run', side_effect=replies) as run, \
                    patch.object(judge.sys.stdin, 'isatty', return_value=True), patch.object(judge.sys.stderr, 'isatty', return_value=True), \
                    patch.object(judge.getpass, 'getpass', return_value=str(uuid.uuid4())):
                self.assertEqual(judge.main(), 2)
                self.assertEqual(run.call_count, 4)
                self.assertFalse(any('COPY ' in (c.kwargs.get('input') or '') for c in run.call_args_list))

    def test_cli_apply_checks_before_and_after_hidden_password_entry(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / 'manifest.json'; manifest.write_text(json.dumps(self.manifest()))
            password = str(uuid.uuid4())
            replies = [self.reply(self.container_snapshot()), self.reply(self.owner_snapshot()),
                       self.reply(self.container_snapshot()), self.reply(self.owner_snapshot()), Mock(returncode=0)]
            with contextlib.redirect_stdout(io.StringIO()) as output, contextlib.redirect_stderr(io.StringIO()) as errors, \
                    patch.object(judge.sys, 'argv', ['provision_judge.py', '--manifest', str(manifest), '--postgres-container', self.container_id, '--apply']), \
                    patch.object(judge.subprocess, 'run', side_effect=replies) as run, \
                    patch.object(judge.sys.stdin, 'isatty', return_value=True), patch.object(judge.sys.stderr, 'isatty', return_value=True), \
                    patch.object(judge.getpass, 'getpass', return_value=password) as prompt:
                self.assertEqual(judge.main(), 0)
                self.assertEqual(prompt.call_count, 2)
                self.assertEqual(run.call_count, 5)
                self.assertNotIn(password, output.getvalue() + errors.getvalue())
                self.assertEqual(sum('COPY ' in (c.kwargs.get('input') or '') for c in run.call_args_list), 1)

    def test_container_mode_cannot_override_owner_or_database(self):
        for flag in ('--db-user', '--database'):
            args = Mock(postgres_container=self.container_id, database=None, db_user=None)
            setattr(args, 'db_user' if flag == '--db-user' else 'database', 'postgres')
            with self.subTest(flag=flag), patch.object(judge.subprocess, 'run') as run:
                with self.assertRaisesRegex(judge.JudgeError, 'JUDGE_CONTAINER_DATABASE_IS_FIXED'):
                    judge.selected_connection(args)
                run.assert_not_called()

    def test_default_mode_does_not_connect_or_request_a_password(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / 'manifest.json'
            manifest.write_text(json.dumps(self.manifest()))
            with patch.object(judge.sys, 'argv', ['provision_judge.py', '--manifest', str(manifest)]), \
                    patch.object(judge.subprocess, 'run') as run, patch.object(judge.getpass, 'getpass') as prompt, \
                    contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(judge.main(), 0)
                run.assert_not_called()
                prompt.assert_not_called()


if __name__ == '__main__':
    unittest.main()
