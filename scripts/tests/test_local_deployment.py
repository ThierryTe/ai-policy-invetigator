"""Deployment guards without registry access or real application/container startup."""
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import deploy_local_images as deploy
import verify_production_compose as config


class LocalDeploymentTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.refs = deploy.release_images(deploy.ROOT / 'deploy/release.images.json')
        with patch.dict(os.environ, cls.refs):
            cls.back = config.resolved('ai-policy-investigator', deploy.ROOT, [deploy.ROOT / f for f in
                ['compose.yaml', 'compose.production.yaml', 'deploy/backend/compose.ghcr.yaml']])
            cls.front = config.resolved('ai-policy-investigator-ui', deploy.ROOT / '.ci/frontend', [
                deploy.ROOT / '.ci/frontend/compose.yaml', deploy.ROOT / 'deploy/frontend/compose.production.yaml',
                deploy.ROOT / 'deploy/frontend/compose.ghcr.yaml'])

    def setUp(self):
        self.b = copy.deepcopy(self.back)
        self.f = copy.deepcopy(self.front)

    def test_exact_loaded_tags_are_accepted_without_registry_digests(self):
        deploy.validate_configuration(self.b, self.f, self.refs)
        self.assertIn('/ai-policy-invetigator-frontend:sha-', self.refs['FRONTEND_IMAGE_REF'])

    def test_wrong_frontend_package_and_mixed_backend_versions_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'images.json'
            for key, value in [('FRONTEND_IMAGE_REF', self.refs['FRONTEND_IMAGE_REF'].replace('invetigator', 'investigator')),
                               ('MODEL_INIT_IMAGE_REF', self.refs['MODEL_INIT_IMAGE_REF'].split(':sha-')[0] + ':sha-' + '0' * 40)]:
                path.write_text(json.dumps({**self.refs, key: value}))
                with self.assertRaises(deploy.DeploymentError): deploy.release_images(path)

    def test_rejects_pull_build_ports_and_changed_volume(self):
        for mutate in [lambda b: b['services']['backend'].update(pull_policy='always'),
                       lambda b: b['services']['backend'].update(build={'context': '.'}),
                       lambda b: b['services']['postgres'].update(ports=[{'target': 5432}]),
                       lambda b: b['volumes']['native_cache'].update(name='wrong-cache')]:
            bad = copy.deepcopy(self.b); mutate(bad)
            with self.assertRaises(deploy.DeploymentError): deploy.validate_configuration(bad, self.f, self.refs)

    def test_missing_or_placeholder_secret_is_rejected(self):
        for value in ['', 'replace-with-a-real-key']:
            self.b['services']['backend']['environment']['MODEL_API_KEY'] = value
            with self.assertRaises(deploy.DeploymentError): deploy.validate_configuration(self.b, self.f, self.refs)

    def test_local_image_without_repo_digests_is_valid(self):
        image = {'Id': 'sha256:' + 'a' * 64, 'Architecture': 'amd64', 'Os': 'linux',
                 'RepoDigests': [], 'Config': {'Labels': {'org.opencontainers.image.revision': self.refs['BACKEND_IMAGE_REF'].split(':sha-')[1]}}}
        with patch.object(deploy, '_inspect_local_image', return_value=image):
            self.assertEqual(deploy.inspect_image(self.refs['BACKEND_IMAGE_REF'], 'amd64')['localImageId'], image['Id'])
            image['Architecture'] = 'arm64'
            with self.assertRaises(deploy.DeploymentError): deploy.inspect_image(self.refs['BACKEND_IMAGE_REF'], 'amd64')
            image['Architecture'] = 'amd64'; image['Config']['Labels']['org.opencontainers.image.revision'] = '0' * 40
            with self.assertRaises(deploy.DeploymentError): deploy.inspect_image(self.refs['BACKEND_IMAGE_REF'], 'amd64')

    def test_subprocess_errors_never_expose_private_diagnostics(self):
        with patch.object(deploy.subprocess, 'run', return_value=SimpleNamespace(returncode=1, stdout='private', stderr='private')):
            with self.assertRaises(deploy.DeploymentError) as error: deploy.execute(['docker', 'info'])
            self.assertNotIn('private', str(error.exception))

    def test_failed_preflight_never_starts_services_even_with_apply(self):
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / 'private.env'; env_file.write_text('# synthetic only\n'); env_file.chmod(0o600)
            with patch.object(deploy, 'compose_commands', return_value=(['backend'], ['frontend'])), \
                 patch.object(deploy, 'json_command', side_effect=[self.b, self.f]), \
                 patch.object(deploy, 'execute') as execute, \
                 patch.object(deploy, 'check_runtime', side_effect=deploy.DeploymentError('LOCAL_IMAGE_MISSING')):
                with self.assertRaises(deploy.DeploymentError):
                    deploy.deploy(env_file, Path(directory), deploy.ROOT / 'deploy/release.images.json', apply=True)
                self.assertTrue(all('up' not in call.args[0] for call in execute.call_args_list))

    def test_config_only_and_default_check_never_start_services(self):
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / 'private.env'; env_file.write_text('# synthetic only\n'); env_file.chmod(0o600)
            for config_only in [True, False]:
                with patch.object(deploy, 'compose_commands', return_value=(['backend'], ['frontend'])), \
                     patch.object(deploy, 'json_command', side_effect=[self.b, self.f]), \
                     patch.object(deploy, 'execute') as execute, \
                     patch.object(deploy, 'check_runtime', return_value=[]) as runtime, \
                     patch.object(deploy, 'check_existing'), \
                     patch.object(deploy, 'inspect_image', return_value={}):
                    result = deploy.deploy(env_file, Path(directory), deploy.ROOT / 'deploy/release.images.json', config_only=config_only)
                    self.assertFalse(result['started'])
                    self.assertTrue(all('up' not in call.args[0] for call in execute.call_args_list))
                    if config_only: runtime.assert_not_called()

    def test_apply_is_explicit_ordered_and_always_disables_pull_and_build(self):
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / 'private.env'; env_file.write_text('# synthetic only\n'); env_file.chmod(0o600)
            with patch.object(deploy, 'compose_commands', return_value=(['backend'], ['frontend'])), \
                 patch.object(deploy, 'json_command', side_effect=[self.b, self.f]), \
                 patch.object(deploy, 'execute') as execute, \
                 patch.object(deploy, 'check_runtime', return_value=[]), \
                 patch.object(deploy, 'check_existing'), \
                 patch.object(deploy, 'inspect_image', return_value={}):
                self.assertTrue(deploy.deploy(env_file, Path(directory), deploy.ROOT / 'deploy/release.images.json', apply=True)['started'])
                starts = [c.args[0] for c in execute.call_args_list if 'up' in c.args[0]]
                self.assertEqual([c[0] for c in starts], ['backend', 'frontend'])
                self.assertTrue(all('--no-recreate' in c and '--no-build' in c and c[c.index('--pull') + 1] == 'never' for c in starts))

    def test_existing_different_container_is_refused_instead_of_recreated(self):
        ref = self.refs['BACKEND_IMAGE_REF']; image_id = 'sha256:' + 'a' * 64
        row = {'Image': image_id, 'Config': {'Labels': {'com.docker.compose.service': 'backend',
                'com.docker.compose.config-hash': 'approved-hash'}}}
        for stored_hash in ['approved-hash', 'different-hash']:
            row['Config']['Labels']['com.docker.compose.config-hash'] = stored_hash
            with patch.object(deploy, 'execute', side_effect=['existing-id\n', 'backend approved-hash\n']), \
                 patch.object(deploy, 'json_command', return_value=[row]):
                args = (['compose'], {}, deploy.PROJECT, self.b, [{'reference': ref, 'localImageId': image_id}])
                if stored_hash == 'approved-hash': deploy.check_existing(*args)
                else:
                    with self.assertRaises(deploy.DeploymentError): deploy.check_existing(*args)

    def test_runtime_rejects_alias_collision_and_private_service_on_proxy(self):
        for labels, aliases in [({'com.docker.compose.project': 'other'}, [deploy.ALIAS]),
                                ({'com.docker.compose.project': deploy.PROJECT}, [])]:
            rows = [{'OSType': 'linux', 'Architecture': 'x86_64'},
                    [{'State': {'Running': True}, 'NetworkSettings': {'Networks': {deploy.PROXY: {}}}}],
                    [{'Containers': {'unrelated': {}}}],
                    [{'Config': {'Labels': labels}, 'NetworkSettings': {'Networks': {deploy.PROXY: {'Aliases': aliases}}}}]]
            with patch.object(deploy, 'json_command', side_effect=rows), \
                 patch.object(deploy, 'inspect_image', return_value={}), \
                 patch.object(deploy, 'execute', return_value=deploy.PROXY + '\n'):
                with self.assertRaises(deploy.DeploymentError): deploy.check_runtime(self.b)


class ImagePlatformInspectionTest(unittest.TestCase):
    """Docker 29/archive inspection cases; every subprocess is mocked."""
    reference = 'ghcr.io/thierryte/ai-policy-invetigator:sha-' + 'b' * 40

    def image(self, **changes):
        row = {'Id': 'sha256:' + 'a' * 64, 'Os': 'linux', 'Architecture': 'amd64',
               'Size': 333242844, 'RepoDigests': [], 'Config': {'Labels': {
                   'org.opencontainers.image.revision': 'b' * 40}}}
        row.update(changes)
        return row

    def response(self, row):
        return SimpleNamespace(returncode=0, stdout=json.dumps([row]), stderr='')

    def failure(self, diagnostic):
        return SimpleNamespace(returncode=1, stdout='[]', stderr=diagnostic)

    def test_blank_default_metadata_recovers_only_from_explicit_platform_inspection(self):
        original = self.image(Os='', Architecture='', Config=None)
        selected = self.image(Id='sha256:' + 'c' * 64)
        with patch.object(deploy.subprocess, 'run', side_effect=[self.response(original), self.response(selected)]) as run:
            result = deploy.inspect_image(self.reference, 'amd64')
            self.assertEqual(result['platform'], 'linux/amd64')
            self.assertEqual(result['localImageId'], original['Id'])
            self.assertTrue(result['ociRevisionPresent'])
            self.assertEqual([call.args[0] for call in run.call_args_list], [
                ['docker', 'image', 'inspect', self.reference],
                ['docker', 'image', 'inspect', '--platform', 'linux/amd64', self.reference]])

    def test_default_platform_alone_does_not_replace_explicit_check(self):
        with patch.object(deploy.subprocess, 'run', side_effect=[self.response(self.image()), self.response(self.image())]) as run:
            self.assertEqual(deploy.inspect_image(self.reference, 'amd64')['architecture'], 'amd64')
            self.assertEqual(run.call_count, 2)

    def test_unknown_selected_metadata_is_refused_despite_matching_size_or_descriptor(self):
        for selected in [self.image(Os='', Architecture=''), self.image(Os=None),
                         self.image(Architecture='unknown'), self.image(Architecture=64),
                         self.image(Os='', Architecture='', Descriptor={'platform': {'os': 'linux', 'architecture': 'amd64'}})]:
            with patch.object(deploy.subprocess, 'run', side_effect=[self.response(self.image()), self.response(selected)]):
                with self.assertRaisesRegex(deploy.DeploymentError, '^LOCAL_IMAGE_PLATFORM_METADATA_UNAVAILABLE_'):
                    deploy.inspect_image(self.reference, 'amd64')

    def test_explicit_wrong_os_or_architecture_is_refused(self):
        for selected in [self.image(Architecture='arm64'), self.image(Os='windows')]:
            with patch.object(deploy.subprocess, 'run', side_effect=[self.response(self.image()), self.response(selected)]):
                with self.assertRaisesRegex(deploy.DeploymentError, '^LOCAL_IMAGE_PLATFORM_MISMATCH_'):
                    deploy.inspect_image(self.reference, 'amd64')

    def test_selector_refusal_distinguishes_wrong_platform_from_unreadable_content(self):
        failure = self.failure('image was found but does not provide the specified platform (linux/amd64)')
        for original, code in [(self.image(Architecture='arm64'), 'MISMATCH'),
                               (self.image(Os='', Architecture=''), 'METADATA_UNAVAILABLE'),
                               (self.image(), 'METADATA_UNAVAILABLE')]:
            with patch.object(deploy.subprocess, 'run', side_effect=[self.response(original), failure]):
                with self.assertRaisesRegex(deploy.DeploymentError, '^LOCAL_IMAGE_PLATFORM_' + code + '_'):
                    deploy.inspect_image(self.reference, 'amd64')

    def test_missing_tag_has_distinct_error_and_no_selector_attempt(self):
        with patch.object(deploy.subprocess, 'run', return_value=self.failure('Error response from daemon: No such image: private-sentinel')) as run:
            with self.assertRaisesRegex(deploy.DeploymentError, '^LOCAL_IMAGE_MISSING_') as error:
                deploy.inspect_image(self.reference, 'amd64')
            self.assertNotIn('private-sentinel', str(error.exception))
            self.assertEqual(run.call_count, 1)

    def test_unsupported_platform_api_is_metadata_unavailable_not_wrong_architecture(self):
        for diagnostic in ['unknown flag: --platform', 'platform requires API version 1.49, server API version is 1.48']:
            with patch.object(deploy.subprocess, 'run', side_effect=[self.response(self.image()), self.failure(diagnostic)]):
                with self.assertRaisesRegex(deploy.DeploymentError, '^LOCAL_IMAGE_PLATFORM_METADATA_UNAVAILABLE_'):
                    deploy.inspect_image(self.reference, 'amd64')

    def test_malformed_inspect_json_fails_closed(self):
        for output in ['not JSON', '[]', '[null]', '{}']:
            response = SimpleNamespace(returncode=0, stdout=output, stderr='')
            with patch.object(deploy.subprocess, 'run', return_value=response):
                with self.assertRaisesRegex(deploy.DeploymentError, '^LOCAL_IMAGE_PLATFORM_METADATA_UNAVAILABLE_'):
                    deploy.inspect_image(self.reference, 'amd64')

    def test_daemon_errors_and_timeouts_are_not_reported_as_missing_image(self):
        with patch.object(deploy.subprocess, 'run', return_value=self.failure('Cannot connect to Docker daemon: private-sentinel')):
            with self.assertRaisesRegex(deploy.DeploymentError, '^LOCAL_IMAGE_INSPECTION_FAILED_') as error:
                deploy.inspect_image(self.reference, 'amd64')
            self.assertNotIn('private-sentinel', str(error.exception))
        with patch.object(deploy.subprocess, 'run', side_effect=deploy.subprocess.TimeoutExpired('docker', 45)):
            with self.assertRaisesRegex(deploy.DeploymentError, '^LOCAL_IMAGE_INSPECTION_FAILED_'):
                deploy.inspect_image(self.reference, 'amd64')

    def test_selected_platform_revision_is_still_checked(self):
        selected = self.image(Config={'Labels': {'org.opencontainers.image.revision': 'd' * 40}})
        with patch.object(deploy.subprocess, 'run', side_effect=[self.response(self.image(Os='', Architecture='')), self.response(selected)]):
            with self.assertRaisesRegex(deploy.DeploymentError, '^LOCAL_IMAGE_REVISION_MISMATCH_'):
                deploy.inspect_image(self.reference, 'amd64')


if __name__ == '__main__':
    unittest.main()
