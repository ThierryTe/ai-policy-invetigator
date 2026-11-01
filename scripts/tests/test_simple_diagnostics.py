"""Failure injection only: subprocess/SSH/Docker and public probes are mocked."""
from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import simple_deploy as deploy
import simple_diagnostics as diagnostics
import simple_ssh as ssh
import test_simple_pipeline as fixtures


class DockerDiagnosticsTest(unittest.TestCase):
    def test_classifies_realistic_errors_without_copying_any_captured_text(self):
        cases = [
            ('permission denied while trying to connect to the Docker daemon socket at unix:///var/run/docker.sock', 'daemon_permission'),
            ('Cannot connect to the Docker daemon at unix:///var/run/docker.sock. Is the docker daemon running?', 'daemon_unavailable'),
            ('Error response from daemon: Head "https://ghcr.io/v2/private/manifests/sha256:123": denied', 'registry_denied'),
            ('unauthorized: authentication required', 'registry_denied'),
            ('manifest unknown', 'image_missing'),
            ('network private-network declared as external, but could not be found', 'external_resource'),
            ('no space left on device', 'disk_full'),
            ('no matching manifest for linux/arm64/v8', 'platform_mismatch'),
            ('x509: certificate signed by unknown authority', 'tls'),
            ('dial tcp: lookup ghcr.io: no such host', 'network'),
            ('unknown flag: --wait', 'compose_unsupported'),
            ("docker: 'compose' is not a docker command.", 'compose_unsupported'),
            ('could not determine a constructor for the tag !override', 'compose_unsupported'),
            ('error while interpolating services.backend.environment: required variable MODEL_API_KEY is missing a value', 'compose_invalid'),
            ('container sensitive-name is unhealthy', 'unhealthy'),
            ('container sensitive-name exited (1)', 'container_exited'),
            ('Conflict. The container name is already in use', 'conflict'),
            ('unrecognized failure with a secret', 'unknown'),
        ]
        for message, reason in cases:
            with self.subTest(reason=reason):
                captured = io.StringIO()
                result = subprocess.CompletedProcess(['docker'], 1, 'stdout-secret', message + '\npassword=stderr-secret')
                with patch.object(deploy.subprocess, 'run', return_value=result), redirect_stderr(captured), \
                        self.assertRaisesRegex(deploy.DeployError, '^COMMAND_FAILED_DOCKER$'):
                    deploy.run(['docker', 'pull', 'argument-secret'], {'TOKEN': 'env-secret'}, step='image.backend.pull')
                output = captured.getvalue()
                self.assertIn('"reason": "' + reason + '"', output)
                self.assertIn('"exit_code": 1', output)
                for secret in ('stdout-secret', 'stderr-secret', 'argument-secret', 'env-secret', 'sensitive-name', 'MODEL_API_KEY'):
                    self.assertNotIn(secret, output)

    def test_stdout_is_classified_when_compose_writes_failure_there(self):
        result = subprocess.CompletedProcess(['docker'], 17, 'container private-name is unhealthy', '')
        captured = io.StringIO()
        with patch.object(deploy.subprocess, 'run', return_value=result), redirect_stderr(captured), \
                diagnostics.phase('update'), self.assertRaises(deploy.DeployError):
            deploy.run(['docker', 'compose', 'up'], step='compose.frontend.up')
        self.assertIn('"reason": "unhealthy"', captured.getvalue())
        self.assertIn('"exit_code": 17', captured.getvalue())
        self.assertIn('"phase": "update"', captured.getvalue())
        self.assertNotIn('private-name', captured.getvalue())

    def test_timeout_and_missing_executable_do_not_expose_exception_or_partial_output(self):
        for error, reason in [(subprocess.TimeoutExpired(['private-command'], 3, b'token-secret', b'password-secret'), 'timeout'),
                              (OSError('private path and credentials'), 'unavailable')]:
            captured = io.StringIO()
            with self.subTest(reason=reason), patch.object(deploy.subprocess, 'run', side_effect=error), \
                    redirect_stderr(captured), self.assertRaisesRegex(deploy.DeployError, '^COMMAND_UNAVAILABLE_OR_TIMED_OUT$'):
                deploy.run(['docker'], step='compose.backend.up')
            self.assertIn('"reason": "' + reason + '"', captured.getvalue())
            self.assertNotIn('private', captured.getvalue())
            self.assertNotIn('secret', captured.getvalue())

    def test_successful_config_and_inspect_output_remains_internal(self):
        captured = io.StringIO()
        result = subprocess.CompletedProcess(['docker'], 0, '{"JWT_SECRET":"private-secret"}', 'private-warning')
        with patch.object(deploy.subprocess, 'run', return_value=result), redirect_stderr(captured):
            self.assertEqual(deploy.run(['docker'], step='compose.backend.config'), result.stdout)
        self.assertNotIn('private', captured.getvalue())
        self.assertNotIn('JWT_SECRET', captured.getvalue())

    def test_silent_health_probe_exit_status_provides_a_diagnostic(self):
        for code, reason in [(7, 'health_connection'), (22, 'health_http'), (28, 'health_timeout')]:
            with self.subTest(code=code):
                self.assertEqual(diagnostics.classify('', '', step='workers.health', exit_code=code), reason)

    def test_database_permission_failure_is_not_misreported_as_registry_access(self):
        self.assertEqual(diagnostics.classify('', 'ERROR: permission denied for table private-history', step='history'), 'database')


class DiagnosticTransportTest(unittest.TestCase):
    def event(self, **changes):
        return {**dict(phase='update', step='compose.backend.up', result='failed', reason='unhealthy', exit_code=1), **changes}

    def test_docker_failure_crosses_both_layers_and_preserves_command_reason_and_exit(self):
        remote = io.StringIO()
        result = subprocess.CompletedProcess(['docker'], 42, '', 'denied: Bearer synthetic-token\nJWT_SECRET=private-secret')
        with patch.object(deploy.subprocess, 'run', return_value=result), redirect_stderr(remote), diagnostics.phase('pull'):
            try:
                deploy.run(['docker', 'pull', 'private-argument'], step='image.frontend.pull')
            except deploy.DeployError as error:
                diagnostics.status(diagnostics.public_code(error))
        captured = io.StringIO()
        with patch.object(ssh.subprocess, 'run', return_value=subprocess.CompletedProcess(['ssh'], 1, 'private-stdout', remote.getvalue())), \
                redirect_stderr(captured), self.assertRaisesRegex(ValueError, '^COMMAND_FAILED_DOCKER$'):
            ssh.execute(['ssh', 'private-host'])
        output = captured.getvalue()
        for expected in ('phase=pull', 'step=image.frontend.pull', 'exit=42', 'docker pull [frontend immutable CI image]',
                         'reason=registry_denied', 'VPS GHCR credentials'):
            self.assertIn(expected, output)
        for secret in ('synthetic-token', 'private-secret', 'private-stdout', 'private-argument', 'private-host', 'JWT_SECRET'):
            self.assertNotIn(secret, output)

    def test_rejects_untrusted_remote_lines_fields_types_and_workflow_commands(self):
        invalid = [self.event(step='secret'), self.event(reason='TOKEN_SECRET'), self.event(phase='secret'),
                   self.event(command='docker login --password=secret'), self.event(exit_code='secret'),
                   self.event(exit_code=True), self.event(exit_code=1000), self.event(step=[]), ['secret'], None]
        remote = '\n'.join(diagnostics.PREFIX + json.dumps(value) for value in invalid)
        remote += '\n' + diagnostics.PREFIX + '{malformed\nTOKEN_SECRET\n::add-mask::secret\n\x1b[31msecret\n'
        captured = io.StringIO()
        with redirect_stderr(captured):
            diagnostics.forward(remote)
        self.assertEqual(captured.getvalue(), '')

    def test_success_does_not_echo_arbitrary_stdout_or_stderr(self):
        captured = io.StringIO()
        with patch.object(ssh.subprocess, 'run', return_value=subprocess.CompletedProcess(['ssh'], 0, 'stdout-secret', 'stderr-secret')), \
                redirect_stderr(captured):
            self.assertEqual(ssh.execute(['ssh']), '')
        self.assertNotIn('secret', captured.getvalue())

    def test_timeout_forwards_complete_safe_partial_events_but_outcome_is_unconfirmed(self):
        data = (diagnostics.PREFIX + json.dumps(self.event()) + '\nprivate-secret\n').encode()
        captured = io.StringIO()
        error = subprocess.TimeoutExpired(['ssh', 'private-host'], 1800, data, b'password-secret')
        with patch.object(ssh.subprocess, 'run', side_effect=error), redirect_stderr(captured), \
                self.assertRaisesRegex(ValueError, '^SSH_REMOTE_OUTCOME_UNCONFIRMED$'):
            ssh.execute(['ssh'])
        self.assertIn('step=compose.backend.up', captured.getvalue())
        self.assertIn('reason=timeout', captured.getvalue())
        self.assertNotIn('secret', captured.getvalue())
        self.assertNotIn('private-host', captured.getvalue())

    def test_broken_connection_never_claims_rollback_completed(self):
        captured = io.StringIO()
        with patch.object(ssh.subprocess, 'run', return_value=subprocess.CompletedProcess(['ssh'], 255, '', 'ROLLBACK_STARTED\nprivate-secret')), \
                redirect_stderr(captured), self.assertRaisesRegex(ValueError, '^SSH_REMOTE_OUTCOME_UNCONFIRMED$'):
            ssh.execute(['ssh'])
        self.assertIn('remote outcome and rollback are unconfirmed', captured.getvalue())
        self.assertNotIn('ROLLBACK_SUCCEEDED', captured.getvalue())

    def test_bundle_contract_includes_diagnostics_for_deploy_and_manual_rollback(self):
        root = Path(__file__).resolve().parents[2]
        self.assertIn('simple_diagnostics.py', ssh.FILES)
        for name in ('ci.yml', 'deploy.yml'):
            text = (root / '.github/workflows' / name).read_text()
            self.assertIn('cp scripts/simple_deploy.py scripts/simple_diagnostics.py scripts/ci_images.py', text)
        self.assertIn('set -euo pipefail\n          python3 -B scripts/simple_ssh.py', (root / '.github/workflows/deploy.yml').read_text())

    def test_ssh_main_does_not_echo_arbitrary_uppercase_exception_values(self):
        with patch.object(ssh, 'settings', side_effect=OSError('PRIVATE_UPPERCASE_SECRET')), self.assertRaises(SystemExit) as error:
            ssh.main()
        self.assertEqual(str(error.exception), 'SSH_DEPLOYMENT_FAILED')

    def test_old_artifact_is_rejected_locally_before_any_transport(self):
        with tempfile.TemporaryDirectory() as directory:
            for name in ssh.FILES:
                if name != 'simple_diagnostics.py':
                    (Path(directory) / name).write_text('synthetic')
            env = {'GITHUB_RUN_ID': '1', 'GITHUB_RUN_ATTEMPT': '1', 'DEPLOY_OPERATION': 'deploy', 'DEPLOY_BUNDLE': directory}
            with patch.dict(ssh.os.environ, env), patch.object(ssh, 'settings', return_value=('host', 'user', '22', 'pin')), \
                    patch.object(ssh, 'execute') as execute, self.assertRaises(SystemExit) as error:
                ssh.main()
            self.assertEqual(str(error.exception), 'DEPLOY_BUNDLE_INCOMPLETE')
            execute.assert_not_called()


class PartialDeploymentTest(unittest.TestCase):
    # Reuse only the synthetic fixture, without inheriting and rerunning its tests.
    setUp = fixtures.DeploymentTest.setUp

    def execute(self, *, failed_step=None, rollback_failure=None, commit_failure=False):
        self.calls = []
        self.original_save = deploy.save
        def run(command, *args, step=None, **kwargs):
            self.calls.append((step, command))
            if step == failed_step:
                # Exercise the actual failure formatter as well as the deploy controller.
                result = subprocess.CompletedProcess(command, 1, '', 'container private-name is unhealthy\nTOKEN=secret')
                with patch.object(deploy.subprocess, 'run', return_value=result):
                    return self.real_run(command, *args, step=step, **kwargs)
            return ''
        def save(path, value):
            if commit_failure and path.name == 'current.json':
                raise OSError('private-disk-error')
            self.original_save(path, value)
        self.real_run = deploy.run
        self.captured = io.StringIO()
        with patch.object(deploy, 'container', return_value={'Image': self.images['postgres']}), \
                patch.object(deploy, 'check_topology', return_value=(['backend-compose'], ['frontend-compose'], {})), \
                patch.object(deploy, 'public_check'), patch.object(deploy, 'snapshot', return_value=self.previous), \
                patch.object(deploy, 'run', side_effect=run), patch.object(deploy, 'verify'), \
                patch.object(deploy, 'history', return_value=self.previous['history']), patch.object(deploy, 'save', side_effect=save), \
                patch.object(deploy, 'restore', side_effect=rollback_failure) as restore, redirect_stderr(self.captured):
            try:
                deploy.deploy(self.bundle, self.env_file, self.state)
            except deploy.DeployError as error:
                return str(error), restore.call_count
        return 'OK', restore.call_count

    def test_each_update_failure_including_frontend_after_backend_triggers_rollback(self):
        for service in ('backend', 'frontend'):
            with self.subTest(service=service):
                code, count = self.execute(failed_step='compose.' + service + '.up')
                self.assertEqual(code, 'DEPLOY_FAILED_ROLLBACK_SUCCEEDED_DATABASE_UNCHANGED')
                self.assertEqual(count, 1)
                self.assertTrue((self.state / 'previous.json').is_file())
                self.assertFalse((self.state / 'current.json').exists())
                self.assertIn('"step": "compose.' + service + '.up"', self.captured.getvalue())
                self.assertIn('ROLLBACK_STARTED', self.captured.getvalue())
                self.assertIn('ROLLBACK_SUCCEEDED', self.captured.getvalue())
                self.assertNotIn('secret', self.captured.getvalue())
                if service == 'frontend':
                    self.assertIn('compose.backend.up', [step for step, _ in self.calls])

    def test_final_state_write_failure_now_triggers_rollback_and_preserves_old_current(self):
        deploy.save(self.state / 'current.json', {'old': 'state'})
        code, count = self.execute(commit_failure=True)
        self.assertEqual(code, 'DEPLOY_FAILED_ROLLBACK_SUCCEEDED_DATABASE_UNCHANGED')
        self.assertEqual(count, 1)
        self.assertEqual(json.loads((self.state / 'current.json').read_text()), {'old': 'state'})
        self.assertIn('"phase": "commit"', self.captured.getvalue())
        self.assertIn('"reason": "state_write"', self.captured.getvalue())
        self.assertNotIn('private-disk-error', self.captured.getvalue())

    def test_second_pull_failure_leaves_only_cache_changes_and_never_updates_services(self):
        code, count = self.execute(failed_step='image.frontend.pull')
        self.assertEqual(code, 'COMMAND_FAILED_DOCKER')
        self.assertEqual(count, 0)
        self.assertEqual([step for step, _ in self.calls], ['image.backend.pull', 'image.frontend.pull'])
        self.assertFalse((self.state / 'previous.json').exists())

    def test_rollback_failure_keeps_original_diagnostic_and_blocks_next_deployment(self):
        code, count = self.execute(failed_step='compose.frontend.up', rollback_failure=deploy.DeployError('SCHEMA_CHANGED_ROLLBACK_BLOCKED'))
        self.assertEqual(code, 'DEPLOY_FAILED_ROLLBACK_FAILED_OR_BLOCKED_REVIEW_PRIVATE_STATE')
        self.assertEqual(count, 1)
        self.assertTrue((self.state / 'blocked.json').is_file())
        for expected in ('compose.frontend.up', 'SCHEMA_CHANGED_ROLLBACK_BLOCKED', 'ROLLBACK_FAILED'):
            self.assertIn(expected, self.captured.getvalue())

    def test_restore_really_updates_both_old_images_without_pull_and_checks_health(self):
        with patch.object(deploy, 'history', return_value=self.previous['history']), \
                patch.object(deploy, 'run') as run, patch.object(deploy, 'verify') as verify:
            deploy.restore(self.previous)
        self.assertEqual([call.kwargs['step'] for call in run.call_args_list], ['compose.backend.up', 'compose.frontend.up'])
        for call in run.call_args_list:
            command = call.args[0]
            self.assertIn('--no-deps', command)
            self.assertIn('--no-build', command)
            self.assertEqual(command[command.index('--pull') + 1], 'never')
            self.assertIn('--wait', command)
        verify.assert_called_once_with(self.previous['images'])

    def main_fixture(self, operation):
        state = self.root / 'simple-deploy'
        incoming = state / 'incoming' / '1-1'
        incoming.mkdir(parents=True)
        env_file = self.root / '.env.production'
        env_file.write_text('JWT_SECRET=private-secret\n')
        env_file.chmod(0o600)
        deploy.save(state / 'previous.json', self.previous)
        return state, ['simple_deploy.py', operation, '--bundle', str(incoming)]

    def test_block_marker_rejects_next_deployment_before_any_docker_command(self):
        state, argv = self.main_fixture('deploy')
        deploy.save(state / 'blocked.json', {'reason': 'synthetic'})
        captured = io.StringIO()
        with patch.object(deploy, 'BASE', self.root), patch.object(sys, 'argv', argv), \
                patch.object(deploy, 'deploy') as action, patch.object(deploy, 'run') as run, redirect_stderr(captured):
            self.assertEqual(deploy.main(), 1)
        action.assert_not_called()
        run.assert_not_called()
        self.assertIn('PREVIOUS_FAILURE_REQUIRES_REVIEW', captured.getvalue())

    def test_manual_rollback_state_write_failure_is_not_reported_as_success(self):
        state, argv = self.main_fixture('rollback')
        real_save = deploy.save
        def save(path, value):
            if path.name == 'current.json':
                raise OSError('private-error')
            real_save(path, value)
        captured = io.StringIO()
        with patch.object(deploy, 'BASE', self.root), patch.object(sys, 'argv', argv), \
                patch.object(deploy, 'save', side_effect=save), patch.object(deploy, 'restore') as restore, redirect_stderr(captured):
            self.assertEqual(deploy.main(), 1)
        restore.assert_called_once_with(self.previous)
        self.assertTrue((state / 'blocked.json').is_file())
        self.assertIn('"reason": "state_write"', captured.getvalue())
        self.assertNotIn('ROLLBACK_SUCCEEDED', captured.getvalue())
        self.assertNotIn('private-error', captured.getvalue())


if __name__ == '__main__':
    unittest.main()
