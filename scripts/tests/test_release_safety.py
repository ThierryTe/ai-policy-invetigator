"""V8 gates with synthetic metadata and mocked Docker/SSH; no real credentials or I/O."""
import copy
import io
import json
import os
from pathlib import Path
import re
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import release_safety as safety
import release_artifacts as artifacts
import run_production_deploy as pipeline
import production_release as controller
import transfer_production_release as transport
import validate_release_dispatch as dispatch
from deploy_local_images import DeploymentError
from test_production_release import manifest, BACK, FRONT


def attestations(phase='migrate-v8'):
    return {'RELEASE_PHASE': phase, 'EXPECTED_PREVIOUS': 'r122-1',
            'APPROVED_BACKEND_DIGEST': 'sha256:' + 'c' * 64,
            'RELEASE_OPERATOR': 'synthetic-operator', 'EVIDENCE_REF': 'CHG-TEST-123',
            **{'CONFIRM_' + k.upper(): str(k in safety.REQUIRED[phase]).lower() for k in safety.CONFIRMATIONS}}


def release(phase='migrate-v8'):
    data = manifest()
    data.update(migrations=safety.qualified_migrations(), runtime=dict.fromkeys(artifacts.RUNTIME_FILES, 'f' * 64),
                expectedPrevious='r122-1', releaseSafety=safety.from_environment(attestations(phase)))
    return data


class AttestationTest(unittest.TestCase):
    def test_each_phase_requires_exact_explicit_attestations(self):
        for phase in safety.REQUIRED:
            env = attestations(phase)
            record = safety.from_environment(env)
            self.assertFalse(record['external_checks_verified_by_automation'])
            self.assertFalse(record['binary_identity_verified'])
            for key in safety.REQUIRED[phase]:
                with self.subTest(phase=phase, missing=key):
                    for value in ('false', '', 'TRUE', '1'):
                        with self.assertRaises(DeploymentError):
                            safety.from_environment({**env, 'CONFIRM_' + key.upper(): value})
            other = next(iter(set(safety.CONFIRMATIONS) - safety.REQUIRED[phase]))
            with self.assertRaises(DeploymentError):
                safety.from_environment({**env, 'CONFIRM_' + other.upper(): 'true'})

    def test_target_digest_operator_and_reference_cannot_be_missing_or_injected(self):
        for key in ('EXPECTED_PREVIOUS', 'APPROVED_BACKEND_DIGEST', 'RELEASE_OPERATOR', 'EVIDENCE_REF'):
            for value in ('', 'private-marker\nforged=true'):
                with self.subTest(key=key), self.assertRaises(DeploymentError) as error:
                    safety.from_environment({**attestations(), key: value})
                self.assertNotIn('private-marker', str(error.exception))

    def test_attestations_cannot_claim_external_or_binary_verification(self):
        for key in ('external_checks_verified_by_automation', 'binary_identity_verified'):
            data = release()
            data['releaseSafety'][key] = True
            with self.assertRaisesRegex(DeploymentError, 'ATTESTATIONS_ARE_NOT_VERIFICATION'):
                safety.validate_release(data, True)

    def test_dispatch_permissions_and_rollback_remain_exclusive(self):
        base = {'OPERATION': 'deploy', 'BACKEND_SHA': BACK, 'FRONTEND_SHA': FRONT, 'ROLLBACK_RELEASE': ''}
        for phase, allow in [('migrate-v8', 'true'), ('activate-v8', 'false')]:
            phase_base = {**base, 'PREPARED_RELEASE': 'r122-1'} if phase == 'activate-v8' else base
            dispatch.validate({**phase_base, **attestations(phase), 'ALLOW_MIGRATIONS': allow})
            with self.assertRaises(DeploymentError):
                dispatch.validate({**phase_base, **attestations(phase), 'ALLOW_MIGRATIONS': str(allow != 'true').lower()})
        dispatch.validate({'OPERATION': 'rollback', 'ROLLBACK_RELEASE': 'r121-1', 'ALLOW_MIGRATIONS': 'false'})
        with self.assertRaises(DeploymentError):
            dispatch.validate({'OPERATION': 'rollback', 'ROLLBACK_RELEASE': 'r121-1', 'ALLOW_MIGRATIONS': 'true'})


class ArtifactBindingTest(unittest.TestCase):
    def test_embedded_migration_inventory_matches_pinned_qualification(self):
        jar = io.BytesIO()
        with zipfile.ZipFile(jar, 'w') as archive:
            for row in safety.qualified_migrations():
                source = safety.ROOT / 'src/main/resources/db/migration' / row['script']
                archive.writestr('BOOT-INF/classes/db/migration/' + source.name, source.read_bytes())
        data = release()
        data['migrations'] = artifacts.inventory(jar.getvalue())
        self.assertEqual(safety.validate_release(data, True), 'migrate-v8')
        for mutation in (lambda d: d['migrations'].pop(),
                         lambda d: d['migrations'][7].update(checksum=0),
                         lambda d: d['migrations'][0].update(sha256='0' * 64),
                         lambda d: d['migrations'].reverse()):
            changed = copy.deepcopy(data); mutation(changed)
            with self.assertRaisesRegex(DeploymentError, 'NOT_QUALIFIED_V8'):
                safety.validate_release(changed, True)

    def test_changed_historical_evidence_is_rejected(self):
        with patch.object(safety, 'EVIDENCE_SHA256', '0' * 64):
            with self.assertRaisesRegex(DeploymentError, 'EVIDENCE_CHANGED'):
                safety.qualified_migrations()

    def test_operator_approval_is_bound_to_actual_image_digest_and_base(self):
        for mutate, error in [(lambda d: d['images']['BACKEND_IMAGE_REF'].update(manifestDigest='sha256:' + '1' * 64), 'APPROVED_DIGEST'),
                              (lambda d: d.update(expectedPrevious='r120-1'), 'BASE_MISMATCH')]:
            data = release(); mutate(data)
            with self.assertRaisesRegex(DeploymentError, error): safety.validate_release(data, True)

    def test_target_phase_and_same_image_reactivation(self):
        data = release('activate-v8')
        previous = copy.deepcopy(data)
        previous.update(id='r122-1', releaseSafety=safety.from_environment(attestations()))
        applied = [{'version': str(n)} for n in range(1, 9)]
        safety.validate_target(data, previous, applied, 'activate-v8')
        for mutate in (lambda p: p.pop('releaseSafety'), lambda p: p.update(configurationSha='0' * 40),
                       lambda p: p['configuration'].update({'compose.yaml': '0' * 64}),
                       lambda p: p['runtime'].update({'scripts/production_release.py': '0' * 64}),
                       lambda p: p['images']['FRONTEND_IMAGE_REF'].update(manifestDigest='sha256:' + '1' * 64)):
            changed = copy.deepcopy(previous); mutate(changed)
            with self.assertRaises(DeploymentError): safety.validate_target(data, changed, applied, 'activate-v8')
        for bad in ([], applied[:-1], [*applied, {'version': '9'}]):
            with self.assertRaises(DeploymentError): safety.validate_target(data, previous, bad, 'activate-v8')
        with self.assertRaises(DeploymentError):
            safety.validate_target(release(), {'id': 'r122-1'}, applied, 'migrate-v8')

    def test_activation_names_every_changed_or_missing_identity_field_without_values(self):
        data = release('activate-v8')
        previous = copy.deepcopy(data)
        previous.update(id='r122-1', releaseSafety=safety.from_environment(attestations()))
        applied = [{'version': str(n)} for n in range(1, 9)]
        for key in safety.ACTIVATION_IDENTITY_FIELDS:
            changed = copy.deepcopy(previous)
            changed[key] = 'private-value-do-not-print'
            with self.subTest(field=key), self.assertRaises(DeploymentError) as error:
                safety.validate_target(data, changed, applied, 'activate-v8')
            self.assertEqual(str(error.exception), 'ACTIVATION_MUST_REUSE_MIGRATION_RELEASE: divergent_fields=' + key)
        for key in safety.ACTIVATION_IDENTITY_FIELDS:
            del previous[key]
        with self.assertRaises(DeploymentError) as error:
            safety.validate_target(data, previous, applied, 'activate-v8')
        self.assertEqual(str(error.exception), 'ACTIVATION_MUST_REUSE_MIGRATION_RELEASE: divergent_fields='
                         + ','.join(safety.ACTIVATION_IDENTITY_FIELDS))


class WorkerTest(unittest.TestCase):
    def test_private_flags_are_pinned_across_compose_calls(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'synthetic.env'
            path.write_text('APP_WORKER_ENABLED=false\nAPP_INVESTIGATION_WORKER_ENABLED=false\n')
            path.chmod(0o600)
            with patch.object(controller, 'compose_commands', return_value=(['back'], ['front'])), \
                 patch.object(controller, 'execute'), patch.object(controller, 'json_command', return_value={}), \
                 patch.object(controller, 'validate_configuration'):
                _, _, env, _ = controller.commands(release(), path)
            path.write_text('APP_WORKER_ENABLED=true\nAPP_INVESTIGATION_WORKER_ENABLED=true\n')
            self.assertEqual({k: env[k] for k in safety.WORKERS}, dict.fromkeys(safety.WORKERS, 'false'))

    def test_private_env_requires_one_unambiguous_literal_per_flag(self):
        good = 'APP_WORKER_ENABLED=false\nAPP_INVESTIGATION_WORKER_ENABLED=false\n'
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'synthetic.env'
            path.write_text(good)
            self.assertEqual(safety.explicit_worker_inputs(path), dict.fromkeys(safety.WORKERS, 'false'))
            for body in ('', good.splitlines()[0], good + good.splitlines()[0], good.replace('false', ''),
                         good.replace('false', 'False'), good.replace('false', '${FALLBACK}'),
                         good.replace('false', '"false"')):
                path.write_text(body)
                with self.assertRaises(DeploymentError): safety.explicit_worker_inputs(path)

    def test_resolved_workers_cannot_enable_during_migration_or_be_ambiguous(self):
        for phase, expected in [('migrate-v8', 'false'), ('activate-v8', 'true')]:
            config = {'services': {'backend': {'environment': dict.fromkeys(safety.WORKERS, expected)}}}
            safety.validate_workers(config, phase)
            for key in safety.WORKERS:
                for bad in (None, '', True, False, 'FALSE', ' true', 'true' if expected == 'false' else 'false'):
                    changed = copy.deepcopy(config); changed['services']['backend']['environment'][key] = bad
                    with self.assertRaises(DeploymentError): safety.validate_workers(changed, phase)


class EntrypointTest(unittest.TestCase):
    def args(self, output):
        return SimpleNamespace(operation='deploy', component=None, backend_sha=BACK, frontend_sha=FRONT,
                               configuration_sha=BACK, run_id='123', run_attempt='1', output=output,
                               allow_migrations=True, rollback_release='')

    def test_push_and_legacy_automatic_component_fail_before_any_network(self):
        for component, github in [('backend', {}), (None, {'GITHUB_ACTIONS': 'true', 'GITHUB_EVENT_NAME': 'push'})]:
            args = self.args(Path('/unused')); args.component = component
            with patch.dict(os.environ, {**attestations(), **github}, clear=True), \
                 patch.object(pipeline, 'current_release') as remote, patch.object(pipeline, 'prepare') as registry:
                with self.assertRaises(DeploymentError): pipeline.deploy(args)
                remote.assert_not_called(); registry.assert_not_called()

    def test_missing_confirmation_or_stale_approved_base_never_prepares_images(self):
        for env, current in [({}, 'r122-1'), (attestations(), 'r121-1')]:
            with patch.dict(os.environ, env, clear=True), patch.object(pipeline, 'current_release', return_value=current), \
                 patch.object(pipeline, 'prepare') as prepare:
                with self.assertRaises(DeploymentError): pipeline.deploy(self.args(Path('/unused')))
                prepare.assert_not_called()

    def test_operator_record_is_persisted_and_a_stale_base_is_never_retried(self):
        with tempfile.TemporaryDirectory() as directory:
            def prepare(output, *args):
                output.mkdir(); return release()
            with patch.dict(os.environ, attestations(), clear=True), patch.object(pipeline, 'current_release', return_value='r122-1'), \
                 patch.object(pipeline, 'prepare', side_effect=prepare) as prepared, \
                 patch.object(pipeline, 'transfer', side_effect=DeploymentError('DEPLOYMENT_BASE_CHANGED_RETRY')) as transfer:
                with self.assertRaises(DeploymentError): pipeline.deploy(self.args(Path(directory)))
                prepared.assert_called_once(); transfer.assert_called_once()
            record = json.loads((Path(directory) / 'r0123-11/release.json').read_text())['releaseSafety']
            self.assertEqual(record['evidence_ref'], 'CHG-TEST-123')
            self.assertFalse(record['external_checks_verified_by_automation'])

    def test_unattested_staged_transfer_fails_before_creating_ssh_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory); data = release(); del data['releaseSafety']
            (path / 'release.json').write_text(json.dumps(data))
            with patch.object(transport, 'connection') as ssh, self.assertRaises(DeploymentError):
                transport.transfer('deploy', data['id'], path, True)
            ssh.assert_not_called()

    def test_reviewed_transfer_includes_pinned_evidence_and_safety_runtime(self):
        from test_production_release import TransportTest
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory); data = release()
            (path / 'release.json').write_text(json.dumps(data))
            replies = ['', '', '', json.dumps({'id': data['id'], 'result': 'VALIDATED'})]
            with patch.dict(os.environ, TransportTest.ENV, clear=True), \
                 patch.object(transport, 'execute', side_effect=replies) as execute:
                transport.transfer('deploy', data['id'], path, True)
            self.assertIn(str(path / 'docs'), execute.call_args_list[1].args[0])
            for name in ('scripts/release_safety.py', 'scripts/qualification_v8_preflight.sql', safety.EVIDENCE):
                self.assertIn(name, artifacts.RUNTIME_FILES)


class ControllerGateTest(unittest.TestCase):
    def activate(self, directory, data, workers, preflight_failure=False, postgres=True, initial_version=7):
        previous = {'id': 'r122-1', 'migrations': data['migrations'][:7]}
        if data['releaseSafety']['phase'] == 'activate-v8':
            previous = copy.deepcopy(data)
            previous.update(id='r122-1', releaseSafety=safety.from_environment(attestations()))
        (directory / 'last-successful.json').write_text(json.dumps(previous))
        state = {'version': initial_version}
        events = []
        def execute(command, *args, **kwargs):
            events.append(command)
            if 'up' in command and command[-1] == 'backend': state['version'] = 8
            if command[:2] == ['back', 'ps']: return 'a' * 64
            if command[:2] == ['docker', 'wait']: return '0'
            if 'psql' in command:
                if preflight_failure is True or 'target_version=' + str(preflight_failure) in command:
                    raise DeploymentError('TARGET_V8_PREFLIGHT_FAILED')
                self.assertIn('BEGIN READ ONLY', kwargs['input'])
                return 'V8_QUALIFICATION_PREFLIGHT_PASS'
            return ''
        def history(*args):
            return [{**r, 'type': 'SQL', 'success': True} for r in data['migrations'][:state['version']]]
        patches = [patch.object(controller, 'reviewed_configuration'),
                   patch.object(controller, 'commands', return_value=(['back'], ['front'], {}, {'services': {'backend': {'environment': workers}}})),
                   patch.object(controller, 'verify_archives', return_value={k: {'diffIds': [], 'imageConfig': {}} for k in artifacts.KEYS}),
                   patch.object(controller, 'execute', side_effect=execute), patch.object(controller, 'history', side_effect=history),
                   patch.object(controller, 'inspect_image', return_value={'platform': 'linux/amd64'}),
                   patch.object(controller, 'json_command', return_value=[{'Os': 'linux', 'Architecture': 'amd64', 'RootFS': {'Layers': []}, 'Config': {}}]),
                   patch.object(controller, 'check_runtime'), patch.object(controller, 'verify_existing_postgres', return_value=postgres),
                   patch.object(controller, 'healthy_service'), patch.object(controller, 'routing')]
        from contextlib import ExitStack
        with ExitStack() as stack:
            for p in patches: stack.enter_context(p)
            try:
                return controller.activate(directory, data, {'envFile': 'synthetic', 'publicUrl': 'https://example.invalid'},
                                           allow_migrations=data['releaseSafety']['phase'] == 'migrate-v8', base=directory), events
            finally:
                self.events = events

    def test_enabled_workers_or_missing_attestation_cannot_load_images(self):
        for bad_record in (False, True):
            with tempfile.TemporaryDirectory() as temp:
                data = release()
                if bad_record: data['releaseSafety']['confirmations']['v7_backup'] = False
                with self.assertRaises(DeploymentError):
                    self.activate(Path(temp), data, dict.fromkeys(safety.WORKERS, 'true'))
                self.assertEqual(self.events, [])

    def test_separate_activation_reuses_validated_images_without_migrations(self):
        with tempfile.TemporaryDirectory() as temp:
            result, events = self.activate(Path(temp), release('activate-v8'),
                                           dict.fromkeys(safety.WORKERS, 'true'), initial_version=8)
            self.assertEqual(result['releaseSafety']['phase'], 'activate-v8')
            self.assertFalse(any('target_version=7' in c for c in events))
            self.assertTrue(any('test "$APP_WORKER_ENABLED" = true' in ' '.join(c) for c in events))

    def test_target_preflight_failure_or_wrong_database_prevents_application_start(self):
        for kwargs in ({'preflight_failure': True}, {'postgres': False}, {'initial_version': 8}):
            with tempfile.TemporaryDirectory() as temp:
                path = Path(temp)
                with self.assertRaises(DeploymentError):
                    self.activate(path, release(), dict.fromkeys(safety.WORKERS, 'false'), **kwargs)
                self.assertFalse(any('up' in c and c[-1] in ('backend', 'model-init') for c in self.events))
                self.assertEqual(json.loads((path / 'last-successful.json').read_text())['id'], 'r122-1')
                self.assertFalse((path / 'validated.json').exists())

    def test_failed_postmigration_preflight_never_opens_frontend_or_marks_success(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)
            with self.assertRaises(DeploymentError):
                self.activate(path, release(), dict.fromkeys(safety.WORKERS, 'false'), preflight_failure=8)
            self.assertTrue(any('up' in c and c[-1] == 'backend' for c in self.events))
            self.assertFalse(any('up' in c and c[-1] == 'frontend' for c in self.events))
            self.assertEqual(json.loads((path / 'last-successful.json').read_text())['id'], 'r122-1')
            self.assertFalse((path / 'validated.json').exists())

    def test_success_reports_actual_sql_checks_separately_from_attestations(self):
        with tempfile.TemporaryDirectory() as temp:
            result, events = self.activate(Path(temp), release(), dict.fromkeys(safety.WORKERS, 'false'))
            self.assertTrue(result['targetPreflightVerified'])
            self.assertTrue(result['qualifiedMigrationInventoryVerified'])
            self.assertFalse(result['releaseSafety']['external_checks_verified_by_automation'])
            self.assertFalse(result['binaryIdentityVerified'])
            checks = [c for c in events if 'psql' in c]
            self.assertTrue(any('target_version=7' in c for c in checks))
            self.assertTrue(any('target_version=8' in c for c in checks))
            self.assertTrue(any('test "$APP_WORKER_ENABLED" = false' in ' '.join(c) for c in events))
            self.assertLess(next(i for i, c in enumerate(events) if 'target_version=7' in c),
                            next(i for i, c in enumerate(events) if 'up' in c and c[-1] == 'backend'))


class WorkflowSafetyTest(unittest.TestCase):
    def test_push_ci_keeps_publication_but_has_no_deploy_job(self):
        text = (safety.ROOT / '.github/legacy-workflows/verify.yml').read_text()
        self.assertIn('uses: ./.github/workflows/publish-images.yml', text)
        self.assertNotIn('deploy-production.yml', text)
        self.assertIsNone(re.search(r'^  deploy:', text, re.M))

    def test_manual_main_backend_only_and_confirmations_precede_credentials(self):
        text = (safety.ROOT / '.github/legacy-workflows/deploy-production.yml').read_text()
        guard = next(line for line in text.splitlines() if line.strip().startswith('if:'))
        for required in ("github.event_name == 'workflow_dispatch'", "github.ref == 'refs/heads/main'",
                         "github.repository == 'ThierryTe/ai-policy-invetigator'"):
            self.assertIn(required, guard)
        self.assertIn('name: prod', text)
        self.assertNotIn('AUTO_APPLY_MIGRATIONS', text)
        self.assertNotIn('--component', text)
        for key in safety.CONFIRMATIONS:
            self.assertIn('CONFIRM_' + key.upper() + ': ${{ inputs.confirm_' + key + ' }}', text)
            self.assertRegex(text, r'      confirm_' + key + r':\n(?:        .*\n)*?        default: false')
        self.assertLess(text.index('scripts/validate_release_dispatch.py'), text.index('GHCR_TOKEN:'))
        self.assertIn('OPERATOR ATTESTATIONS', text)
        self.assertIn('does not establish JAR binary identity', text)


if __name__ == '__main__':
    unittest.main()
