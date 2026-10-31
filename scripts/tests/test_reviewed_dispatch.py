"""Actual dispatch form -> Python CLI -> approval payload, with no registry/SSH access."""
from contextlib import redirect_stdout
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
import run_reviewed_release as runner
from deploy_local_images import DeploymentError

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / '.github/workflows/deploy-production.yml'
SCRIPT = ROOT / 'scripts/run_reviewed_release.py'


class ReviewedDispatchTest(unittest.TestCase):
    def form(self):
        # Read input declarations from the checked-in workflow, not an env fixture.
        dispatch = WORKFLOW.read_text().split('  workflow_dispatch:\n', 1)[1].split('\npermissions:', 1)[0]
        fields = dict(re.findall(r'^      ([a-z0-9_]+):\n(.*?)(?=^      [a-z0-9_]+:|\Z)', dispatch, re.M | re.S))
        self.assertEqual(set(fields), set(runner.DISPATCH_INPUTS))
        form = {}
        for name, definition in fields.items():
            boolean = '\n        type: boolean\n' in '\n' + definition
            self.assertEqual(boolean, name in runner.BOOLEAN_INPUTS)
            form[name] = False if boolean else ''
        form.update(operation='deploy-reviewed', prepared_release='r123-1', expected_previous='r122-1',
                    allow_migrations=True, phase='migrate-v8', evidence_ref='CHG-V8-20261031',
                    confirm_github_protection=True, confirm_write_freeze=True, confirm_image_qualification=True)
        return form

    def metadata(self):
        return {'GITHUB_EVENT_NAME': 'workflow_dispatch', 'GITHUB_REPOSITORY': 'ThierryTe/ai-policy-invetigator',
                'GITHUB_REF': 'refs/heads/main', 'GITHUB_ACTOR': 'synthetic-operator',
                'GITHUB_RUN_ID': '123', 'GITHUB_RUN_ATTEMPT': '2',
                'VPS_ENV_FILE': '/opt/ai-policy-investigator/.env.production'}

    def cli(self, form, metadata=None):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'event.json'
            path.write_text(json.dumps({'inputs': form}))
            return subprocess.run([sys.executable, '-B', str(SCRIPT), '--validate-only', '--event-file', str(path)],
                                  env=self.metadata() if metadata is None else metadata,
                                  capture_output=True, text=True, timeout=10)

    def resolve(self, form, env=None):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'event.json'
            path.write_text(json.dumps({'inputs': form}))
            return runner.dispatch_environment(self.metadata() if env is None else env, path)

    def test_both_workflow_calls_pass_the_actual_event_file(self):
        workflow = WORKFLOW.read_text()
        for title in ['Validate reviewed preparation or migration approval',
                      'Prepare or deploy the retained approved image pair']:
            step = workflow.split('      - name: ' + title + '\n', 1)[1].split('      - name:', 1)[0]
            call = next(line for line in step.splitlines() if 'scripts/run_reviewed_release.py' in line)
            self.assertIn('--event-file "$GITHUB_EVENT_PATH"', call)
            self.assertNotIn('${{ inputs.', call)
            self.assertIn('CONFIGURATION_SHA: ${{ steps.tooling.outputs.commit }}', step)

    def test_complete_deploy_form_passes_real_validate_only_cli_without_input_env(self):
        form = self.form()
        for strings in [False, True]:
            if strings:
                form = {key: ('true' if value else 'false') if type(value) is bool else value
                        for key, value in form.items()}
            with self.subTest(strings=strings):
                result = self.cli(form)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, '')
                self.assertEqual(result.stderr, '')

    def test_form_overrides_missing_or_stale_environment_without_changing_values(self):
        env = {**self.metadata(), **dict.fromkeys(runner.DISPATCH_INPUTS.values(), 'stale-value'),
               'RELEASE_OPERATOR': 'wrong-operator'}
        form = self.form()
        resolved = self.resolve(form, env)
        runner.validate(resolved)
        self.assertEqual(resolved['EVIDENCE_REF'], form['evidence_ref'])
        self.assertEqual(resolved['RELEASE_OPERATOR'], self.metadata()['GITHUB_ACTOR'])
        for key, variable in runner.DISPATCH_INPUTS.items():
            value = form[key]
            self.assertEqual(resolved[variable], ('true' if value else 'false') if type(value) is bool else value)

    def test_prepare_form_also_passes_the_same_event_path(self):
        form = self.form()
        form.update(operation='prepare-reviewed', prepared_release='', allow_migrations=False, evidence_ref='',
                    confirm_github_protection=False, confirm_write_freeze=False, confirm_image_qualification=False)
        env = {**self.metadata(), 'CONFIGURATION_SHA': 'a' * 40,
               'V7_DEMO_INVESTIGATION_ID': '11111111-2222-3333-4444-555555555555',
               'V7_BACKUP_DIR': '/private/backups', 'V7_RESTORE_START_TIMEOUT_SECONDS': '300'}
        result = self.cli(form, env)
        self.assertEqual(result.returncode, 0, result.stderr)
        for field, code in [('CONFIGURATION_SHA', 'CONFIGURATION_SHA_REQUIRED'),
                            ('V7_DEMO_INVESTIGATION_ID', 'COMPLETED_PRODUCTION_DEMO_UUID_REQUIRED'),
                            ('V7_BACKUP_DIR', 'PRIVATE_BACKUP_DIRECTORY_REQUIRED')]:
            missing = dict(env); missing.pop(field)
            with self.subTest(field=field):
                result = self.cli(form, missing)
                self.assertEqual(result.returncode, 2)
                self.assertIn(code, result.stderr)

    def test_every_required_form_field_missing_or_empty_blocks_before_any_remote_call(self):
        required = {'operation': 'REVIEWED_OPERATION_REQUIRED',
                    'expected_previous': 'APPROVED_PREVIOUS_RELEASE_REQUIRED',
                    'prepared_release': 'PREPARED_RELEASE_ID_REQUIRED',
                    'allow_migrations': 'EXPLICIT_V8_MIGRATION_APPROVAL_REQUIRED',
                    'phase': 'EXPLICIT_V8_MIGRATION_APPROVAL_REQUIRED',
                    'evidence_ref': 'NONSECRET_CHANGE_RECORD_REFERENCE_REQUIRED',
                    'confirm_github_protection': 'HUMAN_RELEASE_APPROVALS_REQUIRED_GITHUB_PROTECTION',
                    'confirm_write_freeze': 'HUMAN_RELEASE_APPROVALS_REQUIRED_WRITE_FREEZE',
                    'confirm_image_qualification': 'HUMAN_RELEASE_APPROVALS_REQUIRED_IMAGE_QUALIFICATION'}
        for key, code in required.items():
            for empty in [False, True]:
                form = self.form()
                if empty:
                    form[key] = ''
                else:
                    form.pop(key)
                # Even a valid inherited value must never fill a missing form field.
                inherited = {**self.metadata(), **self.resolve(self.form())}
                resolved = self.resolve(form, inherited)
                with self.subTest(field=key, empty=empty), \
                        patch.object(runner, 'current_release') as current, \
                        patch.object(runner, 'ghcr_manifest') as registry, patch.object(runner, 'transfer') as transfer:
                    with self.assertRaisesRegex(DeploymentError, code):
                        runner.run(resolved, Path('/unused'))
                    current.assert_not_called(); registry.assert_not_called(); transfer.assert_not_called()
                result = self.cli(form)
                self.assertEqual(result.returncode, 2)
                self.assertIn(code, result.stderr)

    def test_required_runner_metadata_missing_is_rejected_in_validate_only(self):
        required = {'GITHUB_ACTOR': 'RELEASE_OPERATOR_REQUIRED', 'GITHUB_RUN_ID': 'GITHUB_RUN_ID_INVALID',
                    'GITHUB_RUN_ATTEMPT': 'GITHUB_RUN_ATTEMPT_INVALID', 'VPS_ENV_FILE': 'PRODUCTION_ENV_PATH_INVALID',
                    'GITHUB_EVENT_NAME': 'MANUAL_BACKEND_MAIN_DISPATCH_REQUIRED',
                    'GITHUB_REPOSITORY': 'MANUAL_BACKEND_MAIN_DISPATCH_REQUIRED',
                    'GITHUB_REF': 'MANUAL_BACKEND_MAIN_DISPATCH_REQUIRED'}
        for key, code in required.items():
            env = self.metadata(); env.pop(key)
            with self.subTest(field=key):
                result = self.cli(self.form(), env)
                self.assertEqual(result.returncode, 2)
                self.assertIn(code, result.stderr)

    def test_invalid_approvals_and_wrong_execution_context_still_fail(self):
        cases = [('allow_migrations', False), ('phase', 'activate-v8'), ('prepared_release', 'bad-release'),
                 ('expected_previous', 'bad-release'), ('confirm_github_protection', False),
                 ('confirm_write_freeze', False), ('confirm_image_qualification', False)]
        for key, value in cases:
            form = self.form(); form[key] = value
            with self.subTest(field=key), patch.object(runner, 'current_release') as remote:
                with self.assertRaises(DeploymentError):
                    runner.run(self.resolve(form), Path('/unused'))
                remote.assert_not_called()
        for key, value in [('GITHUB_EVENT_NAME', 'push'), ('GITHUB_REPOSITORY', 'other/repository'),
                           ('GITHUB_REF', 'refs/heads/develop'), ('GITHUB_RUN_ID', 'invalid'),
                           ('GITHUB_RUN_ATTEMPT', 'invalid')]:
            env = self.metadata(); env[key] = value
            with self.subTest(field=key):
                result = self.cli(self.form(), env)
                self.assertEqual(result.returncode, 2)

    def test_invalid_reference_is_distinguished_from_missing_and_never_echoed(self):
        for value in ['chg-lowercase', 'ab', 'A' * 81, ' CHG-123', 'CHG-123\n',
                      'https://private.example.invalid/change', 'CHG-123;echo private']:
            form = self.form(); form['evidence_ref'] = value
            with self.subTest(value=value):
                result = self.cli(form)
                self.assertEqual(result.returncode, 2)
                self.assertIn('NONSECRET_CHANGE_RECORD_REFERENCE_INVALID_FORMAT', result.stderr)
                self.assertNotIn('NONSECRET_CHANGE_RECORD_REFERENCE_REQUIRED', result.stderr)
                self.assertNotIn(value, result.stderr + result.stdout)

    def test_all_missing_fields_are_reported_together(self):
        form = self.form()
        for key in ['prepared_release', 'expected_previous', 'phase', 'evidence_ref',
                    'confirm_github_protection', 'confirm_write_freeze', 'confirm_image_qualification']:
            form.pop(key)
        result = self.cli(form)
        self.assertEqual(result.returncode, 2)
        for code in ['PREPARED_RELEASE_ID_REQUIRED', 'APPROVED_PREVIOUS_RELEASE_REQUIRED',
                     'EXPLICIT_V8_MIGRATION_APPROVAL_REQUIRED', 'NONSECRET_CHANGE_RECORD_REFERENCE_REQUIRED',
                     'HUMAN_RELEASE_APPROVALS_REQUIRED_GITHUB_PROTECTION',
                     'HUMAN_RELEASE_APPROVALS_REQUIRED_WRITE_FREEZE',
                     'HUMAN_RELEASE_APPROVALS_REQUIRED_IMAGE_QUALIFICATION']:
            self.assertIn(code, result.stderr)

    def test_complete_form_reaches_approval_through_same_cli_entry_point(self):
        form = self.form()
        child = 'sha256:' + 'c' * 64
        # The reviewed backend child digest remains derived from the pinned image.
        form['approved_backend_digest'] = 'untrusted-form-value'
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'event.json'; path.write_text(json.dumps({'inputs': form}))
            with patch.dict(runner.os.environ, self.metadata(), clear=True), \
                    patch.object(sys, 'argv', [str(SCRIPT), '--event-file', str(path)]), \
                    patch.object(runner, 'current_release', return_value='r122-1'), \
                    patch.object(runner, 'ghcr_manifest', return_value={'manifestDigest': child}), \
                    patch.object(runner, 'transfer', return_value={'result': 'synthetic'}) as transfer, \
                    patch.object(runner, 'prepare') as prepare, redirect_stdout(io.StringIO()):
                self.assertEqual(runner.main(), 0)
                prepare.assert_not_called()
            transfer.assert_called_once()
            self.assertEqual(transfer.call_args.args, ('deploy-reviewed', 'r123-1'))
            self.assertTrue(transfer.call_args.kwargs['allow_migrations'])
            approval = transfer.call_args.kwargs['approval']
            self.assertEqual(approval['expected_previous'], form['expected_previous'])
            self.assertEqual(approval['runId'], '123')
            self.assertEqual(approval['runAttempt'], '2')
            env = approval['environment']
            self.assertEqual(env['EVIDENCE_REF'], form['evidence_ref'])
            self.assertEqual(env['RELEASE_OPERATOR'], 'synthetic-operator')
            self.assertEqual(env['RELEASE_PHASE'], 'migrate-v8')
            self.assertEqual(env['EXPECTED_PREVIOUS'], form['expected_previous'])
            self.assertEqual(env['APPROVED_BACKEND_DIGEST'], child)
            for key in runner.CONFIRMATIONS:
                expected = 'true' if key in {'github_protection', 'write_freeze', 'image_qualification'} else 'false'
                self.assertEqual(env['CONFIRM_' + key.upper()], expected)

    def test_event_failure_never_falls_back_to_inherited_approval(self):
        for content in ['{bad json', 'null', '{}', '{"inputs": []}']:
            with self.subTest(content=content), tempfile.TemporaryDirectory() as temp:
                path = Path(temp) / 'event.json'; path.write_text(content)
                with self.assertRaisesRegex(DeploymentError, '^WORKFLOW_DISPATCH_EVENT_INVALID$'):
                    runner.dispatch_environment(self.metadata(), path)
        for key, value in [('allow_migrations', 1), ('evidence_ref', None), ('prepared_release', [])]:
            form = self.form(); form[key] = value
            with self.subTest(field=key):
                with self.assertRaisesRegex(DeploymentError, '^WORKFLOW_DISPATCH_INPUT_TYPE_INVALID_' + key.upper() + '$'):
                    self.resolve(form)

    def test_reviewed_form_still_rejects_manual_image_or_rollback_selection(self):
        for key in ['backend_sha', 'frontend_sha', 'rollback_release']:
            form = self.form(); form[key] = 'a' * 40
            with self.subTest(field=key):
                result = self.cli(form)
                self.assertEqual(result.returncode, 2)
                self.assertIn('REVIEWED_OPERATION_USES_PINNED_PAIR', result.stderr)


if __name__ == '__main__':
    unittest.main()
