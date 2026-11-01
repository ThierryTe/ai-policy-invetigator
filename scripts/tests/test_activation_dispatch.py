"""Activation form -> real CLI validation -> release payload; all remote calls mocked."""
from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import run_production_deploy as pipeline
import run_reviewed_release as reviewed
import release_safety as safety
import transfer_production_release as transport
import validate_release_dispatch as dispatch
from deploy_local_images import DeploymentError
from reviewed_v8_release import APPROVED
from test_release_safety import release

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / '.github/legacy-workflows/deploy-production.yml'
SCRIPT = ROOT / 'scripts/validate_release_dispatch.py'
REQUIRED = {'github_protection', 'write_freeze', 'image_qualification',
            'v8_acceptance', 'worker_reactivation'}
MIGRATION_ONLY = {'v7_preflight', 'v7_backup', 'isolated_restore'}


class ActivationDispatchTest(unittest.TestCase):
    def form(self, strings=False):
        declaration = WORKFLOW.read_text().split('  workflow_dispatch:\n', 1)[1].split('\npermissions:', 1)[0]
        fields = dict(re.findall(r'^      ([a-z0-9_]+):\n(.*?)(?=^      [a-z0-9_]+:|\Z)',
                                 declaration, re.M | re.S))
        self.assertEqual(set(fields), set(dispatch.DISPATCH_INPUTS))
        form = {}
        for name, definition in fields.items():
            boolean = '\n        type: boolean\n' in '\n' + definition
            self.assertEqual(boolean, name in dispatch.BOOLEAN_INPUTS)
            form[name] = False if boolean else ''
        form.update(operation='deploy', phase='activate-v8', allow_migrations=False,
                    prepared_release='r122-1', expected_previous='r122-1',
                    backend_sha='a' * 40, frontend_sha='b' * 40,
                    approved_backend_digest='sha256:' + 'c' * 64, evidence_ref='CHG-V8-20261101')
        for key in REQUIRED:
            form['confirm_' + key] = True
        if strings:
            form = {key: ('true' if value else 'false') if type(value) is bool else value
                    for key, value in form.items()}
        return form

    def metadata(self):
        return {'GITHUB_ACTIONS': 'true', 'GITHUB_EVENT_NAME': 'workflow_dispatch',
                'GITHUB_REPOSITORY': 'ThierryTe/ai-policy-invetigator', 'GITHUB_REF': 'refs/heads/main',
                'GITHUB_ACTOR': 'synthetic-operator', 'GITHUB_RUN_ID': '123', 'GITHUB_RUN_ATTEMPT': '2'}

    def stale_environment(self):
        return {**self.metadata(), **dict.fromkeys(dispatch.DISPATCH_INPUTS.values(), 'stale-value'),
                'RELEASE_OPERATOR': 'wrong-operator'}

    def validate_cli(self, path, env):
        return subprocess.run([sys.executable, '-B', str(SCRIPT), '--event-file', str(path)],
                              env=env, capture_output=True, text=True, timeout=10)

    def execute_cli(self, path, output, env, configuration_sha='a' * 40):
        # Deliberately conflicting old CLI/env inputs cannot alter the event form.
        argv = ['run_production_deploy.py', '--event-file', str(path), '--output', str(output),
                '--configuration-sha', configuration_sha, '--operation', 'rollback',
                '--backend-sha', 'd' * 40, '--frontend-sha', 'e' * 40,
                '--rollback-release', 'r999-1', '--allow-migrations']
        out, err = io.StringIO(), io.StringIO()
        with patch.dict(pipeline.os.environ, env, clear=True), patch.object(sys, 'argv', argv), \
                redirect_stdout(out), redirect_stderr(err):
            code = pipeline.main()
        return code, out.getvalue(), err.getvalue()

    def test_validation_and_execution_share_the_reviewed_event_decoder(self):
        self.assertIs(reviewed.dispatch_environment, dispatch.dispatch_environment)
        self.assertIs(pipeline.dispatch_environment, dispatch.dispatch_environment)
        workflow = WORKFLOW.read_text()
        for title, script in [
                ('Validate explicit inputs before registry or SSH access', 'validate_release_dispatch.py'),
                ('Transfer exact images and deploy via existing VPS SSH account', 'run_production_deploy.py')]:
            step = workflow.split('      - name: ' + title + '\n', 1)[1].split('      - name:', 1)[0]
            call = next(line for line in step.splitlines() if 'scripts/' + script in line)
            self.assertIn('--event-file "$GITHUB_EVENT_PATH"', call)
            for forbidden in ['${{ inputs.', '--allow-migrations', '--backend-sha', '--frontend-sha',
                              '--operation', '--rollback-release', '${args[@]}']:
                self.assertNotIn(forbidden, call)
        self.assertLess(workflow.index('scripts/validate_release_dispatch.py'), workflow.index('GHCR_TOKEN:'))

    def test_complete_activation_passes_real_validator_without_input_environment(self):
        for strings in [False, True]:
            for env in [self.metadata(), self.stale_environment()]:
                with self.subTest(strings=strings, stale='OPERATION' in env), tempfile.TemporaryDirectory() as temp:
                    path = Path(temp) / 'event.json'
                    path.write_text(json.dumps({'inputs': self.form(strings)}))
                    result = self.validate_cli(path, env)
                    self.assertEqual((result.returncode, result.stdout, result.stderr), (0, '', ''))

    def test_complete_activation_preserves_validation_values_through_execution_and_payload(self):
        for strings in [False, True]:
            with self.subTest(strings=strings), tempfile.TemporaryDirectory() as temp:
                path = Path(temp) / 'event.json'
                path.write_text(json.dumps({'inputs': self.form(strings)}))
                env = self.stale_environment()
                validated, executed = [], []
                real_validate = dispatch.validate

                def validate_preflight(resolved):
                    validated.append(dict(resolved))
                    real_validate(resolved)

                with patch.dict(dispatch.os.environ, env, clear=True), \
                        patch.object(sys, 'argv', [str(SCRIPT), '--event-file', str(path)]), \
                        patch.object(dispatch, 'validate', side_effect=validate_preflight):
                    self.assertEqual(dispatch.main(), 0)

                def validate_execution(resolved):
                    executed.append(dict(resolved))
                    real_validate(resolved)

                def prepare(directory, backend, frontend, configuration, identity, **kwargs):
                    self.assertEqual((backend, frontend, configuration), ('a' * 40, 'b' * 40, 'a' * 40))
                    self.assertEqual(kwargs, {'approved_images': APPROVED})
                    directory.mkdir()
                    data = release('activate-v8')
                    data['id'] = identity
                    return data

                with patch.object(pipeline, 'validate_manual', side_effect=validate_execution), \
                        patch.object(pipeline, 'current_release', return_value='r122-1') as current, \
                        patch.object(pipeline, 'prepare', side_effect=prepare) as prepared, \
                        patch.object(pipeline, 'transfer', return_value={'result': 'synthetic'}) as transfer:
                    code, out, err = self.execute_cli(path, Path(temp), env)
                self.assertEqual(code, 0, err)
                self.assertEqual(err, '')
                self.assertIn('synthetic', out)
                current.assert_called_once_with()
                prepared.assert_called_once()
                self.assertTrue(executed)
                self.assertTrue(all(item == validated[0] for item in executed))
                transfer.assert_called_once_with('deploy', 'r0123-21', Path(temp) / 'r0123-21', False)
                payload = json.loads((Path(temp) / 'r0123-21/release.json').read_text())
                record = payload['releaseSafety']
                self.assertEqual(record['phase'], 'activate-v8')
                self.assertEqual(record['operator'], self.metadata()['GITHUB_ACTOR'])
                self.assertEqual(record['evidence_ref'], self.form()['evidence_ref'])
                self.assertEqual(record['expected_previous'], self.form()['expected_previous'])
                self.assertEqual(record['approved_backend_digest'], self.form()['approved_backend_digest'])
                self.assertEqual(record['confirmations'], {key: key in REQUIRED for key in dispatch.CONFIRMATIONS})
                self.assertEqual(validated[0]['ALLOW_MIGRATIONS'], 'false')

    def assert_rejected(self, form, code, withheld=()):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'event.json'
            path.write_text(json.dumps({'inputs': form}))
            # Even valid inherited approvals must not replace absent form values.
            complete = self.form(strings=True)
            env = {**self.metadata(), **{variable: complete[name]
                                       for name, variable in dispatch.DISPATCH_INPUTS.items()},
                   'RELEASE_OPERATOR': self.metadata()['GITHUB_ACTOR']}
            result = self.validate_cli(path, env)
            self.assertEqual(result.returncode, 2)
            self.assertIn(code, result.stderr)
            for value in withheld:
                self.assertNotIn(value, result.stdout + result.stderr)
            with patch.object(pipeline, 'current_release') as current, \
                    patch.object(pipeline, 'prepare') as prepare, patch.object(pipeline, 'transfer') as transfer:
                status, out, err = self.execute_cli(path, Path(temp), env)
                self.assertEqual(status, 2)
                self.assertEqual(out, '')
                self.assertIn(code, err)
                for value in withheld:
                    self.assertNotIn(value, out + err)
                current.assert_not_called()
                prepare.assert_not_called()
                transfer.assert_not_called()

    def test_each_required_approval_absent_or_false_blocks_validation_and_execution(self):
        for key in sorted(REQUIRED):
            for value in [None, False, 'false']:
                form = self.form()
                if value is None:
                    form.pop('confirm_' + key)
                else:
                    form['confirm_' + key] = value
                with self.subTest(approval=key, value=value):
                    code = 'AMBIGUOUS_OPERATOR_CONFIRMATIONS' if value is None else 'PHASE_OPERATOR_CONFIRMATIONS_REQUIRED'
                    self.assert_rejected(form, code + ': incorrect_fields=confirm_' + key + ' (expected true)\n')

    def test_each_migration_approval_true_is_still_rejected_during_activation(self):
        for key in sorted(MIGRATION_ONLY):
            form = self.form()
            form['confirm_' + key] = True
            with self.subTest(approval=key):
                self.assert_rejected(form, 'PHASE_OPERATOR_CONFIRMATIONS_REQUIRED: incorrect_fields=confirm_'
                                     + key + ' (expected false)\n')

    def test_activation_never_accepts_migration_permission(self):
        form = self.form()
        form['allow_migrations'] = True
        self.assert_rejected(form, 'PHASE_MIGRATION_PERMISSION_MISMATCH: '
                             'incorrect_fields=allow_migrations (expected false)\n')

    def test_activation_requires_prepared_release_equal_to_expected_previous_before_ssh(self):
        for value in [None, '', 'not-a-release', 'r999-1']:
            form = self.form()
            form['expected_previous'] = 'r041243000818-11'
            if value is None:
                form.pop('prepared_release')
            else:
                form['prepared_release'] = value
            code = ('ACTIVATION_PREPARED_RELEASE_MISMATCH: divergent_fields=prepared_release,expected_previous'
                    if value == 'r999-1' else 'ACTIVATION_PREPARED_RELEASE_REQUIRED: incorrect_fields=prepared_release')
            with self.subTest(value=value):
                self.assert_rejected(form, code)

    def test_migration_ids_survive_event_payload_scp_ssh_and_server_configuration_comparison(self):
        from test_production_release import TransportTest
        retained = 'r041243000818-11'
        original_sha = 'a5b867b79504a59292cd52190908b51ec8c22080'
        newer_sha = '3d78daf745bc98f361ed8b5b0b28ba80044d9957'
        real_execute = transport.execute
        for configuration_sha in [original_sha, newer_sha]:
            with self.subTest(configuration_sha=configuration_sha), tempfile.TemporaryDirectory() as temp:
                form = self.form()
                form.update(prepared_release=retained, expected_previous=retained)
                path = Path(temp) / 'event.json'
                path.write_text(json.dumps({'inputs': form}))
                env = {**self.stale_environment(), **TransportTest.ENV}
                previous = release('migrate-v8')
                previous.update(id=retained, configurationSha=original_sha)
                commands, payloads = [], []

                def prepare(directory, backend, frontend, configuration, identity, **kwargs):
                    directory.mkdir()
                    data = release('activate-v8')
                    data.update(id=identity, configurationSha=configuration)
                    return data

                def execute(command, code, **kwargs):
                    commands.append(command)
                    if '/scripts/production_release.py deploy ' not in command[-1]:
                        return ''  # SSH mkdir and SCP are simulated; nothing leaves this host.
                    data = json.loads((Path(temp) / 'r0123-21/release.json').read_text())
                    payloads.append(data)
                    self.assertEqual(data['expectedPrevious'], retained)
                    self.assertEqual(data['releaseSafety']['expected_previous'], retained)
                    self.assertNotIn('--allow-migrations', command[-1])
                    try:
                        safety.validate_target(data, previous, [{'version': str(n)} for n in range(1, 9)], 'activate-v8')
                    except DeploymentError as error:
                        reply = subprocess.CompletedProcess(command, 2, '', str(error) + '\nprivate-ssh-marker\n')
                        with patch.object(transport.subprocess, 'run', return_value=reply):
                            return real_execute(command, code)
                    return json.dumps({'id': data['id'], 'result': 'VALIDATED'})

                with patch.object(pipeline, 'current_release', return_value=retained), \
                        patch.object(pipeline, 'prepare', side_effect=prepare), \
                        patch.object(transport, 'execute', side_effect=execute):
                    code, out, err = self.execute_cli(path, Path(temp), env, configuration_sha)
                self.assertEqual(len(payloads), 1)
                self.assertTrue(any(any(str(Path(temp) / 'r0123-21/release.json') == arg for arg in cmd)
                                    for cmd in commands))
                self.assertIn('production_release.py deploy r0123-21 --env-file ', commands[-1][-1])
                self.assertNotIn('private-ssh-marker', out + err)
                if configuration_sha == original_sha:
                    self.assertEqual(code, 0, err)
                else:
                    self.assertEqual(code, 2)
                    self.assertEqual(err, 'SSH_RELEASE_FAILED: ACTIVATION_MUST_REUSE_MIGRATION_RELEASE: '
                                         'divergent_fields=configurationSha\n')

    def test_all_nine_incorrect_fields_are_reported_together_without_weakening_gates(self):
        form = self.form()
        for key in dispatch.BOOLEAN_INPUTS:
            form[key] = not form[key]
        fields = ['confirm_' + key + ' (expected ' + ('true' if key in REQUIRED else 'false') + ')'
                  for key in dispatch.CONFIRMATIONS]
        fields.append('allow_migrations (expected false)')
        self.assert_rejected(form, 'PHASE_OPERATOR_CONFIRMATIONS_REQUIRED: incorrect_fields='
                             + ', '.join(fields) + '\n')

    def test_ambiguous_approval_reports_all_divergences_without_received_values_or_other_inputs(self):
        form = self.form()
        marker = 'SENSITIVE-MARKER-DO-NOT-PRINT'
        form.update(confirm_v8_acceptance=marker + '\nforged=true', confirm_v7_backup=True,
                    confirm_worker_reactivation=False, allow_migrations=True, unused_private_field=marker)
        self.assert_rejected(form, 'AMBIGUOUS_OPERATOR_CONFIRMATIONS: incorrect_fields='
                             'confirm_v7_backup (expected false), confirm_v8_acceptance (expected true), '
                             'confirm_worker_reactivation (expected true), allow_migrations (expected false)\n',
                             withheld=[marker, 'forged=true', 'unused_private_field'])

    def test_migration_diagnostics_keep_the_opposite_phase_requirements(self):
        form = self.form()
        form.update(phase='migrate-v8', allow_migrations=False, confirm_v7_preflight=True,
                    confirm_v7_backup=True, confirm_isolated_restore=False,
                    confirm_v8_acceptance=False, confirm_worker_reactivation=True)
        self.assert_rejected(form, 'PHASE_OPERATOR_CONFIRMATIONS_REQUIRED: incorrect_fields='
                             'confirm_isolated_restore (expected true), confirm_worker_reactivation (expected false), '
                             'allow_migrations (expected true)\n')

    def test_nonliteral_approvals_are_not_coerced_into_true(self):
        for value in ['', 'TRUE', '1', ' true']:
            form = self.form()
            form['confirm_v8_acceptance'] = value
            with self.subTest(value=value):
                self.assert_rejected(form, 'AMBIGUOUS_OPERATOR_CONFIRMATIONS')

    def test_invalid_event_never_falls_back_to_environment(self):
        for body in ['{bad', 'null', '{}', '{"inputs": []}',
                     json.dumps({'inputs': {**self.form(), 'confirm_v8_acceptance': 1}})]:
            with self.subTest(body=body), tempfile.TemporaryDirectory() as temp:
                path = Path(temp) / 'event.json'
                path.write_text(body)
                result = self.validate_cli(path, self.stale_environment())
                self.assertEqual(result.returncode, 2)
                self.assertIn('WORKFLOW_DISPATCH_', result.stderr)
                with patch.object(pipeline, 'deploy') as deploy:
                    status, _, err = self.execute_cli(path, Path(temp), self.stale_environment())
                    self.assertEqual(status, 2)
                    self.assertIn('WORKFLOW_DISPATCH_', err)
                    deploy.assert_not_called()

    def test_old_environment_only_path_reproduces_lost_confirmation_failure(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'event.json'
            path.write_text(json.dumps({'inputs': self.form()}))
            resolved = dispatch.dispatch_environment(self.metadata(), path)
            for key in sorted(REQUIRED):
                inherited = dict(resolved)
                inherited.pop('CONFIRM_' + key.upper())
                with self.subTest(approval=key):
                    with self.assertRaisesRegex(DeploymentError, '^PHASE_OPERATOR_CONFIRMATIONS_REQUIRED: '
                                                'incorrect_fields=confirm_' + key + r' \(expected true\)$'):
                        dispatch.validate(inherited)
                    result = self.validate_cli(path, inherited)
                    self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
