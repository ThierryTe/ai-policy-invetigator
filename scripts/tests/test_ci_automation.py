"""Main-branch publication and automatic pair selection; no Docker/SSH/registry calls."""
import copy
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import re
import subprocess
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import publish_release_images as publisher
import run_production_deploy as pipeline
import production_release as remote
import transfer_production_release as transport
import prepare_production_release as preparation
from deploy_local_images import DeploymentError, REPOSITORIES
import test_production_release as fixtures
from test_production_release import BACK, FRONT, manifest, migration

META = {'manifestDigest': 'sha256:' + 'a' * 64, 'configDigest': 'sha256:' + 'b' * 64, 'indexDigest': 'sha256:' + 'a' * 64}


class PublicationTest(unittest.TestCase):
    def setUp(self):
        environment = patch.dict(os.environ, {}, clear=True)
        environment.start()
        self.addCleanup(environment.stop)

    def test_publication_retains_source_tooling_run_and_all_digest_identities(self):
        env = {'GITHUB_ACTIONS': 'true', 'GITHUB_REPOSITORY': 'ThierryTe/ai-policy-invetigator-frontend',
               'GITHUB_SHA': FRONT, 'GITHUB_RUN_ID': '123', 'GITHUB_RUN_ATTEMPT': '2',
               'PUBLICATION_TOOLING_SHA': BACK}
        with patch.dict(os.environ, env, clear=True), patch.object(publisher, 'ghcr_manifest', return_value=META), \
                patch.object(publisher, 'verified'), patch.object(publisher, 'run'):
            result = publisher.publish('frontend', FRONT, Path('/unused'))
        self.assertEqual(result['identities'][REPOSITORIES['FRONTEND_IMAGE_REF']], META)
        self.assertEqual(result['provenance']['sourceRevision'], FRONT)
        self.assertEqual(result['provenance']['toolingRevision'], BACK)
        self.assertEqual(result['provenance']['githubRun']['runAttempt'], '2')

    def test_invalid_ci_provenance_stops_before_registry_or_publication(self):
        env = {'GITHUB_ACTIONS': 'true', 'GITHUB_REPOSITORY': 'ThierryTe/ai-policy-invetigator',
               'GITHUB_SHA': BACK, 'GITHUB_RUN_ID': '123', 'GITHUB_RUN_ATTEMPT': '1',
               'PUBLICATION_TOOLING_SHA': BACK}
        for key, value in [('PUBLICATION_TOOLING_SHA', 'main'), ('PUBLICATION_TOOLING_SHA', FRONT),
                           ('GITHUB_SHA', FRONT), ('GITHUB_REPOSITORY', 'other/repo'), ('GITHUB_RUN_ID', '')]:
            with self.subTest(key=key, value=value), patch.dict(os.environ, {**env, key: value}, clear=True), \
                    patch.object(publisher, 'ghcr_manifest') as registry, patch.object(publisher, 'run') as docker:
                with self.assertRaises(DeploymentError):
                    publisher.publish('backend', BACK, Path('/unused'))
                registry.assert_not_called(); docker.assert_not_called()

    def test_new_backend_pair_is_verified_before_channel_advances(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in ['deploy/backend/Dockerfile', 'deploy/embeddings/Dockerfile']:
                file = root / name; file.parent.mkdir(parents=True, exist_ok=True); file.write_text('synthetic')
            events = []
            def lookup(repository, tag, **kwargs):
                events.append(('lookup', repository, tag)); return None if kwargs.get('missing_ok') else META
            def run(command, **kwargs): events.append(('docker', command)); return b''
            def verified(*args): events.append(('verified', args[0])); return META
            with patch.object(publisher, 'ghcr_manifest', side_effect=lookup), patch.object(publisher, 'run', side_effect=run), \
                 patch.object(publisher, 'verified', side_effect=verified):
                result = publisher.publish('backend', BACK, root)
            builds = [event[1] for event in events if event[0] == 'docker' and event[1][1] == 'build']
            self.assertEqual(len(builds), 2)
            self.assertTrue(all('--platform' in cmd and 'linux/amd64' in cmd for cmd in builds))
            promotions = [i for i, event in enumerate(events) if event[0] == 'docker' and 'create' in event[1]]
            checks = [i for i, event in enumerate(events) if event[0] == 'verified']
            self.assertLess(max(checks), min(promotions))
            self.assertEqual(set(result['images']), {REPOSITORIES['BACKEND_IMAGE_REF'], REPOSITORIES['MODEL_INIT_IMAGE_REF']})

    def test_rerun_reuses_verified_sha_tags_without_rebuild_or_overwrite(self):
        with patch.object(publisher, 'ghcr_manifest', return_value=META), patch.object(publisher, 'verified'), \
             patch.object(publisher, 'run') as run:
            publisher.publish('backend', BACK, Path('/no-build-needed'))
        self.assertEqual(run.call_count, 2)
        self.assertTrue(all(call.args[0][1:4] == ['buildx', 'imagetools', 'create'] for call in run.call_args_list))
        self.assertTrue(all(':release-main' in ' '.join(call.args[0]) for call in run.call_args_list))

    def test_partial_backend_publication_never_advances_channels(self):
        with patch.object(publisher, 'ghcr_manifest', side_effect=[META, DeploymentError('REGISTRY_NETWORK_RETRIES_EXHAUSTED')]), \
             patch.object(publisher, 'verified'), patch.object(publisher, 'run') as run:
            with self.assertRaises(DeploymentError): publisher.publish('backend', BACK, Path('/unused'))
        run.assert_not_called()

    def test_frontend_package_uses_actual_invetigator_spelling(self):
        with patch.object(publisher, 'ghcr_manifest', return_value=META), patch.object(publisher, 'verified'), \
             patch.object(publisher, 'run') as run:
            result = publisher.publish('frontend', FRONT, Path('/unused'))
        self.assertEqual(list(result['images']), ['ghcr.io/thierryte/ai-policy-invetigator-frontend'])
        self.assertNotIn('ai-policy-investigator-frontend:', ' '.join(run.call_args.args[0]))

    def test_failed_config_integrity_or_wrong_architecture_prevents_publication(self):
        for content in [b'{"os":"linux","architecture":"arm64"}', b'{}']:
            metadata = {**META, 'configDigest': 'sha256:' + preparation.sha(content)}
            payload = [(b'{"token":"synthetic"}', {}), (content, {})]
            with patch.dict(os.environ, {'GITHUB_ACTOR': 'test', 'GHCR_TOKEN': 'synthetic'}), \
                 patch.object(publisher, 'request', side_effect=payload):
                with self.assertRaises(DeploymentError): publisher.configuration(REPOSITORIES['BACKEND_IMAGE_REF'], metadata)
        with patch.dict(os.environ, {'GITHUB_ACTOR': 'test', 'GHCR_TOKEN': 'synthetic'}), \
             patch.object(publisher, 'request', side_effect=[(b'{"token":"synthetic"}', {}), (b'bad', {})]):
            with self.assertRaisesRegex(DeploymentError, 'DIGEST'): publisher.configuration(REPOSITORIES['BACKEND_IMAGE_REF'], META)

    def test_actual_frontend_repository_source_label_is_accepted(self):
        # Literal identity comes from the inspected local remote, independently of the implementation constant.
        image = {'config': {'Labels': {
            'org.opencontainers.image.revision': FRONT,
            'org.opencontainers.image.source': 'https://github.com/ThierryTe/ai-policy-invetigator-frontend'}}}
        with patch.object(publisher, 'configuration', return_value=image):
            self.assertEqual(publisher.verified(REPOSITORIES['FRONTEND_IMAGE_REF'], FRONT, META, 'frontend'), META)

    def test_similarly_spelled_but_wrong_frontend_repository_is_rejected(self):
        image = {'config': {'Labels': {
            'org.opencontainers.image.revision': FRONT,
            'org.opencontainers.image.source': 'https://github.com/ThierryTe/ai-policy-investigator-frontend'}}}
        with patch.object(publisher, 'configuration', return_value=image):
            with self.assertRaisesRegex(DeploymentError, 'SOURCE_REPOSITORY_MISMATCH'):
                publisher.verified(REPOSITORIES['FRONTEND_IMAGE_REF'], FRONT, META, 'frontend')


class PublicationWorkflowTest(unittest.TestCase):
    def test_manual_publication_requires_successful_main_ci_for_exact_source(self):
        text = (Path(__file__).resolve().parents[2] / '.github/legacy-workflows/publish-images.yml').read_text()
        step = text.split('- name: Require successful backend CI for manual publication\n', 1)[1]
        match = re.search(r"python3 - <<'PY'\n(.*?)\n          PY", step, re.S)
        code = '\n'.join(line[10:] for line in match[1].splitlines())
        valid = {'head_sha': BACK, 'head_branch': 'main', 'event': 'push',
                 'path': '.github/workflows/verify.yml', 'status': 'completed', 'conclusion': 'success',
                 'head_repository': {'full_name': 'ThierryTe/ai-policy-invetigator'}}
        invalid = [[]] + [[{**valid, key: value}] for key, value in [
            ('head_sha', FRONT), ('head_branch', 'develop'), ('event', 'pull_request'),
            ('path', '.github/workflows/other.yml'), ('status', 'in_progress'),
            ('conclusion', 'failure'), ('conclusion', 'cancelled'),
            ('head_repository', {'full_name': 'other/repository'}), ('head_repository', None),
        ]]
        for runs in [[valid], *invalid]:
            with self.subTest(runs=runs), patch.dict(os.environ, {'GITHUB_SHA': BACK}, clear=True), \
                    patch('urllib.request.urlopen', return_value=io.BytesIO(json.dumps({'workflow_runs': runs}).encode())) as lookup:
                if runs == [valid]:
                    exec(compile(code, '<manual-ci-guard>', 'exec'), {})
                else:
                    with self.assertRaisesRegex(SystemExit, 'SUCCESSFUL_BACKEND_CI_FOR_EXACT_SHA_REQUIRED'):
                        exec(compile(code, '<manual-ci-guard>', 'exec'), {})
                self.assertIn('head_sha=' + BACK, lookup.call_args.args[0].full_url)
        with patch.dict(os.environ, {'GITHUB_SHA': BACK}, clear=True), \
                patch('urllib.request.urlopen', side_effect=TimeoutError):
            with self.assertRaises(TimeoutError):
                exec(compile(code, '<manual-ci-guard>', 'exec'), {})
        self.assertIn('  workflow_dispatch:\n', text)
        self.assertIn('  workflow_call:\n', text)
        self.assertIn('options: [backend]', text)
        self.assertIn("github.event_name != 'workflow_dispatch' && inputs.component == 'frontend'", text)
        self.assertLess(text.index('SUCCESSFUL_BACKEND_CI_FOR_EXACT_SHA_REQUIRED'), text.index('uses: actions/checkout'))

    def test_tooling_revision_guard_rejects_floating_or_injected_refs(self):
        text = (Path(__file__).resolve().parents[2] / '.github/legacy-workflows/publish-images.yml').read_text()
        match = re.search(r"python3 - <<'PY'\n(.*?)\n          PY", text, re.S)
        self.assertIsNotNone(match)
        code = '\n'.join(line[10:] for line in match[1].splitlines())
        for revision in [BACK, '', 'main', 'abc', 'a' * 39, 'a' * 41, BACK + '\nmain']:
            with self.subTest(revision=revision):
                result = subprocess.run([sys.executable, '-c', code], env={'TOOLING_SHA': revision},
                                        text=True, capture_output=True)
                self.assertEqual(result.returncode == 0, revision == BACK)
        self.assertLess(text.index('FULL_PUBLICATION_TOOLING_SHA_REQUIRED'), text.index('uses: actions/checkout'))
        self.assertNotIn("|| 'main'", text)
        self.assertIn('PUBLICATION_TOOLING_SHA: ${{ steps.tooling.outputs.commit }}', text)
        self.assertIn('path: ${{ runner.temp }}/publication.json', text)
        self.assertNotIn('environment:', text)
        self.assertNotIn('VPS_', text)
        for use in re.findall(r'uses: ([^\s]+)', text):
            self.assertRegex(use, r'@[0-9a-f]{40}$')


class PairSelectionTest(unittest.TestCase):
    def config(self, component='frontend', revision=FRONT):
        return {'config': {'Labels': {'org.opencontainers.image.revision': revision,
                                     'org.opencontainers.image.source': publisher.SOURCE_REPOSITORIES[component]}}}

    def test_channel_resolves_an_immutable_sha_and_checks_its_digest(self):
        with patch.object(publisher, 'ghcr_manifest', return_value=META), \
             patch.object(publisher, 'configuration', return_value=self.config()):
            self.assertEqual(publisher.channel_revision('frontend'), FRONT)
        with patch.object(publisher, 'ghcr_manifest', side_effect=[META, {**META, 'manifestDigest': 'sha256:' + 'c' * 64}]), \
             patch.object(publisher, 'configuration', return_value=self.config()):
            with self.assertRaisesRegex(DeploymentError, 'IMMUTABLE_DIGEST_MISMATCH'): publisher.channel_revision('frontend')

    def test_one_time_bootstrap_only_for_missing_channel_not_registry_failure(self):
        with patch.object(publisher, 'ghcr_manifest', side_effect=[None, META, META]), \
             patch.object(publisher, 'configuration', return_value=self.config()):
            self.assertEqual(publisher.channel_revision('frontend', FRONT), FRONT)
        with patch.object(publisher, 'ghcr_manifest', side_effect=DeploymentError('REGISTRY_AUTH_OR_REFERENCE_FAILED')):
            with self.assertRaisesRegex(DeploymentError, 'AUTH'): publisher.channel_revision('frontend', FRONT)
        with patch.object(publisher, 'ghcr_manifest', return_value=None):
            with self.assertRaisesRegex(DeploymentError, 'INITIAL_COUNTERPART'): publisher.channel_revision('frontend')

    def test_backend_counterpart_checks_matching_initializer_sha(self):
        with patch.object(publisher, 'ghcr_manifest', return_value=META) as lookup, \
             patch.object(publisher, 'configuration', return_value=self.config('backend', BACK)):
            self.assertEqual(publisher.channel_revision('backend'), BACK)
        self.assertIn((REPOSITORIES['MODEL_INIT_IMAGE_REF'], 'sha-' + BACK), [c.args for c in lookup.call_args_list])

    def test_each_repo_pins_its_own_validated_sha_and_selects_other_channel(self):
        with patch.object(pipeline, 'channel_revision', return_value=FRONT):
            self.assertEqual(pipeline.automatic_pair('backend', BACK), (BACK, FRONT))
        with patch.object(pipeline, 'channel_revision', return_value=BACK):
            self.assertEqual(pipeline.automatic_pair('frontend', FRONT), (BACK, FRONT))

    def test_remote_state_read_never_reads_production_secrets(self):
        from test_production_release import TransportTest
        with patch.dict(os.environ, TransportTest.ENV), \
             patch.object(transport, 'execute', return_value='{"id":"r123-1"}') as execute:
            self.assertEqual(transport.current_release(), 'r123-1')
        command = execute.call_args.args[0][-1]
        self.assertIn('last-successful.json', command); self.assertNotIn('.env', command); self.assertNotIn('docker', command)


class ConcurrentDeployTest(unittest.TestCase):
    def args(self, directory):
        return SimpleNamespace(operation='deploy', component=None, source_sha='', backend_sha=BACK, frontend_sha=FRONT,
                               configuration_sha=BACK, run_id='123', run_attempt='1', output=directory,
                               allow_migrations=True, rollback_release='')

    def test_changed_remote_base_is_rejected_before_images_are_loaded(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            state = {'id': 'r122-1', 'migrations': [migration()]}
            (directory / 'last-successful.json').write_text(json.dumps(state))
            with self.assertRaisesRegex(DeploymentError, 'DEPLOYMENT_BASE_CHANGED_RETRY'):
                fixtures.ControllerTest()._activation(directory, expected_previous=None)
            self.assertEqual(json.loads((directory / 'last-successful.json').read_text()), state)

    def test_stale_base_requires_new_approval_without_automatic_pair_retry(self):
        from test_release_safety import attestations, release
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); captured = []
            def prepare(output, backend, frontend, configuration, identity):
                output.mkdir(); captured.append((backend, frontend, identity)); return release()
            with patch.dict(os.environ, attestations(), clear=True), \
                 patch.object(pipeline, 'current_release', return_value='r122-1'), \
                 patch.object(pipeline, 'prepare', side_effect=prepare), \
                 patch.object(pipeline, 'transfer', side_effect=DeploymentError('SSH_RELEASE_FAILED: DEPLOYMENT_BASE_CHANGED_RETRY')) as transferred:
                with self.assertRaisesRegex(DeploymentError, 'BASE_CHANGED'):
                    pipeline.deploy(self.args(root))
                transferred.assert_called_once()
            self.assertEqual(captured, [(BACK, FRONT, 'r0123-11')])
            self.assertEqual(json.loads((root / 'r0123-11/release.json').read_text())['expectedPrevious'], 'r122-1')

    def test_provider_network_or_health_errors_do_not_trigger_blind_redeploy(self):
        from test_release_safety import attestations, release
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            def prepare(output, *args): output.mkdir(); return release()
            with patch.dict(os.environ, attestations(), clear=True), \
                 patch.object(pipeline, 'current_release', return_value='r122-1'), \
                 patch.object(pipeline, 'prepare', side_effect=prepare), \
                 patch.object(pipeline, 'transfer', side_effect=DeploymentError('BACKEND_HEALTH_FAILED')) as transfer:
                with self.assertRaisesRegex(DeploymentError, 'HEALTH'): pipeline.deploy(self.args(root))
                self.assertEqual(transfer.call_count, 1)

    def test_cross_repo_lock_waits_then_releases_and_times_out_safely(self):
        with tempfile.TemporaryDirectory() as temporary:
            with patch.object(remote.fcntl, 'flock', side_effect=[BlockingIOError(), None, None]) as lock, \
                 patch.object(remote.time, 'sleep') as sleep:
                with remote.deployment_lock(Path(temporary)): pass
                self.assertEqual(sleep.call_count, 1); self.assertEqual(lock.call_count, 3)
            with patch.object(remote.fcntl, 'flock', side_effect=BlockingIOError()), \
                 patch.object(remote.time, 'monotonic', side_effect=[0, 2]):
                with self.assertRaisesRegex(DeploymentError, 'LOCK_TIMEOUT'):
                    with remote.deployment_lock(Path(temporary), timeout=1): pass


class Docker29ContentVerificationTest(unittest.TestCase):
    def test_loaded_manifest_id_may_change_but_content_and_platform_must_match(self):
        proof = {'diffIds': ['sha256:' + 'a' * 64], 'imageConfig': {'User': '10001', 'Env': ['SAFE=synthetic'],
                 'Cmd': ['java', '-jar', '/app/investigator.jar'], 'Labels': {'org.opencontainers.image.revision': BACK}}}
        row = {'Id': 'sha256:' + 'f' * 64, 'Os': 'linux', 'Architecture': 'amd64',
               'RootFS': {'Layers': proof['diffIds']}, 'Config': copy.deepcopy(proof['imageConfig'])}
        remote.verify_loaded_content(row, proof)
        for mutation in [lambda r: r.update(Architecture='arm64'), lambda r: r['RootFS'].update(Layers=[]),
                         lambda r: r['Config'].update(Cmd=['other']), lambda r: r['Config'].update(User='root'),
                         lambda r: r['Config'].update(Env=['OTHER=value'])]:
            candidate = copy.deepcopy(row); mutation(candidate)
            with self.assertRaises(DeploymentError): remote.verify_loaded_content(candidate, proof)

    def test_existing_postgres_with_different_store_id_requires_identical_content(self):
        proof = {'diffIds': ['sha256:' + 'a' * 64], 'imageConfig': {'Cmd': ['postgres']}}
        container = {'Image': 'sha256:' + 'f' * 64, 'NetworkSettings': {'Networks': {'ai-policy-investigator_database': {}}},
                     'HostConfig': {'PortBindings': None}, 'Mounts': [{'Name': 'ai-policy-investigator_investigator_data',
                     'Destination': '/var/lib/postgresql/data'}]}
        image = {'Os': 'linux', 'Architecture': 'amd64', 'RootFS': {'Layers': proof['diffIds']}, 'Config': {'Cmd': ['postgres']}}
        with patch.object(remote, 'execute', return_value='id'), patch.object(remote, 'inspect_image'), \
             patch.object(remote, 'json_command', side_effect=[[container], [image]]):
            self.assertTrue(remote.verify_existing_postgres(['different-id'], proof))
        image['RootFS']['Layers'] = ['different']
        with patch.object(remote, 'execute', return_value='id'), patch.object(remote, 'inspect_image'), \
             patch.object(remote, 'json_command', side_effect=[[container], [image]]):
            with self.assertRaisesRegex(DeploymentError, 'LAYERS_MISMATCH'): remote.verify_existing_postgres(['different-id'], proof)


if __name__ == '__main__':
    unittest.main()
