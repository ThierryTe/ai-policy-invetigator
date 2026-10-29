"""Production automation tests: synthetic archives and mocked registry/SSH/Docker only."""
import base64
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest
import urllib.error
import zipfile
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import release_artifacts as artifacts
import prepare_production_release as prepare
import production_release as controller
import transfer_production_release as transport
import validate_release_dispatch as dispatch
from deploy_local_images import DeploymentError, REPOSITORIES

BACK, FRONT = 'a' * 40, 'b' * 40


def migration(version='1', data=b'SELECT 1;\n'):
    return {'version': version, 'script': f'V{version}__test.sql', 'checksum': artifacts.flyway_checksum(data), 'sha256': artifacts.sha(data)}


def fixture(directory, key='BACKEND_IMAGE_REF', architecture='amd64', revision=BACK):
    jar = io.BytesIO()
    with zipfile.ZipFile(jar, 'w') as output:
        output.writestr('BOOT-INF/classes/db/migration/V1__test.sql', b'SELECT 1;\n')
    layer_bytes = io.BytesIO()
    with tarfile.open(fileobj=layer_bytes, mode='w') as layer:
        info = tarfile.TarInfo('app/investigator.jar'); info.size = len(jar.getvalue())
        layer.addfile(info, io.BytesIO(jar.getvalue()))
    raw_layer = layer_bytes.getvalue()
    config = json.dumps({'os': 'linux', 'architecture': architecture,
                         'config': {'Labels': {'org.opencontainers.image.revision': revision}},
                         'rootfs': {'diff_ids': ['sha256:' + artifacts.sha(raw_layer)]}}).encode()
    digest = 'sha256:' + artifacts.sha(config)
    manifest_digest = 'sha256:' + 'c' * 64
    reference = REPOSITORIES.get(key, 'ai-policy-investigator-postgres') + ':deploy-' + manifest_digest[7:]
    content = {'manifest.json': json.dumps([{'Config': 'config.json', 'RepoTags': [reference], 'Layers': ['layer.tar']}]).encode(),
               'config.json': config, 'layer.tar': raw_layer}
    path = directory / (key + '.tar')
    write_tar(path, content)
    return path, reference, digest, content


def write_tar(path, content):
    with tarfile.open(path, 'w:') as output:
        for name, value in content.items():
            info = tarfile.TarInfo(name); info.size = len(value)
            output.addfile(info, io.BytesIO(value))


def manifest():
    data = {'format': 1, 'id': 'r123-1', 'backendSha': BACK, 'frontendSha': FRONT, 'configurationSha': BACK,
            'images': {}, 'configuration': dict.fromkeys(artifacts.CONFIG_FILES, 'f' * 64), 'migrations': [migration()]}
    for key in artifacts.KEYS:
        repo = REPOSITORIES.get(key, 'ai-policy-investigator-postgres')
        data['images'][key] = {'manifestDigest': 'sha256:' + 'c' * 64, 'configDigest': 'sha256:' + 'd' * 64,
                              'archive': key + '.tar', 'archiveSha256': 'e' * 64,
                              'localRef': repo + ':deploy-' + 'c' * 64,
                              'sourceRef': REPOSITORIES[key] + ':sha-' + (FRONT if key == 'FRONTEND_IMAGE_REF' else BACK)
                              if key in REPOSITORIES else 'pgvector/pgvector:0.8.0-pg16'}
    return data


class ArtifactTest(unittest.TestCase):
    def test_archive_verifies_config_platform_layers_revision_and_actual_jar(self):
        with tempfile.TemporaryDirectory() as temporary:
            path, ref, digest, _ = fixture(Path(temporary))
            self.assertEqual(artifacts.archive_image(path, ref, digest, BACK, True), [migration()])

    def test_wrong_architecture_revision_config_and_extra_images_fail(self):
        with tempfile.TemporaryDirectory() as temporary:
            path, ref, digest, content = fixture(Path(temporary), architecture='arm64')
            with self.assertRaisesRegex(DeploymentError, 'PLATFORM'): artifacts.archive_image(path, ref, digest)
            path, ref, digest, content = fixture(Path(temporary))
            with self.assertRaisesRegex(DeploymentError, 'REVISION'): artifacts.archive_image(path, ref, digest, FRONT)
            with self.assertRaisesRegex(DeploymentError, 'CONFIG_DIGEST'): artifacts.archive_image(path, ref, 'sha256:' + '0' * 64)
            rows = json.loads(content['manifest.json']); rows[0]['RepoTags'].append('unrelated:tag')
            content['manifest.json'] = json.dumps(rows).encode(); write_tar(path, content)
            with self.assertRaisesRegex(DeploymentError, 'ALLOWLIST'): artifacts.archive_image(path, ref, digest)

    def test_tampered_layer_path_traversal_and_hidden_index_fail(self):
        with tempfile.TemporaryDirectory() as temporary:
            for mutation in ['layer', '../escape', 'index.json']:
                path, ref, digest, content = fixture(Path(temporary))
                content['layer.tar' if mutation == 'layer' else mutation] = b'tampered'
                write_tar(path, content)
                with self.assertRaises(DeploymentError): artifacts.archive_image(path, ref, digest)

    def test_normalization_removes_oci_side_metadata(self):
        with tempfile.TemporaryDirectory() as temporary:
            path, ref, digest, content = fixture(Path(temporary)); content['index.json'] = b'{}'; write_tar(path, content)
            target = Path(temporary) / 'normalized.tar'
            artifacts.normalized_archive(path, target)
            self.assertEqual(artifacts.archive_image(target, ref, digest, BACK, True), [migration()])

    def test_missing_archive_is_not_reported_as_platform_mismatch(self):
        with self.assertRaises(FileNotFoundError): artifacts.archive_image(Path('/nonexistent/release.tar'), 'ref', 'digest')

    def test_release_manifest_binds_pair_paths_local_references_and_approved_postgres(self):
        self.assertEqual(artifacts.validate_manifest(manifest())['id'], 'r123-1')
        for change in [lambda d: d.update(id='../bad'),
                       lambda d: d['images']['MODEL_INIT_IMAGE_REF'].update(sourceRef=REPOSITORIES['MODEL_INIT_IMAGE_REF'] + ':sha-' + FRONT),
                       lambda d: d['images']['BACKEND_IMAGE_REF'].update(localRef='unrelated:tag'),
                       lambda d: d['images']['POSTGRES_IMAGE_REF'].update(sourceRef='postgres:17'),
                       lambda d: d['images']['FRONTEND_IMAGE_REF'].update(archive='../escape'),
                       lambda d: d['configuration'].update({'secrets.env': 'f' * 64})]:
            data = manifest(); change(data)
            with self.assertRaises(DeploymentError): artifacts.validate_manifest(data)

    def test_flyway_checksum_ignores_only_line_terminators_and_initial_bom(self):
        self.assertEqual(artifacts.flyway_checksum(b'SELECT 1;\n'), 78787420)
        self.assertEqual(artifacts.flyway_checksum(b'\xef\xbb\xbfSELECT 1;\r\n'), artifacts.flyway_checksum(b'SELECT 1;'))
        self.assertNotEqual(artifacts.flyway_checksum(b'SELECT  1;'), artifacts.flyway_checksum(b'SELECT 1;'))

    def test_unknown_repeatable_migration_and_placeholder_rejected(self):
        for name, sql in [('R__repeat.sql', b'SELECT 1;'), ('V1__test.sql', b'SELECT ${value};')]:
            jar = io.BytesIO()
            with zipfile.ZipFile(jar, 'w') as output: output.writestr('BOOT-INF/classes/db/migration/' + name, sql)
            with self.assertRaises(DeploymentError): artifacts.inventory(jar.getvalue())


class MigrationTest(unittest.TestCase):
    def setUp(self):
        self.target = [migration()]
        self.applied = [{**migration(), 'success': True, 'type': 'SQL'}]

    def test_exact_database_allows_application_rollback(self):
        artifacts.migration_gate(self.applied, self.target, rollback=True)

    def test_first_install_pending_migrations_need_explicit_approval(self):
        with self.assertRaisesRegex(DeploymentError, 'APPROVAL'): artifacts.migration_gate([], self.target)
        artifacts.migration_gate([], self.target, allow_migrations=True)

    def test_rollback_blocks_newer_database_and_missing_or_changed_migrations(self):
        for applied in [[], [*self.applied, {**migration('2'), 'success': True, 'type': 'SQL'}],
                        [{**self.applied[0], 'checksum': 0}], [{**self.applied[0], 'success': False}],
                        [{**self.applied[0], 'type': 'BASELINE'}]]:
            with self.assertRaises(DeploymentError): artifacts.migration_gate(applied, self.target, rollback=True)

    def test_forward_changed_previous_sql_is_rejected_even_with_migration_approval(self):
        with self.assertRaisesRegex(DeploymentError, 'PREVIOUS_MIGRATION_CHANGED'):
            artifacts.migration_gate([], [migration(data=b'SELECT 2;')], previous=self.target, allow_migrations=True)


class RegistryTest(unittest.TestCase):
    def test_network_retries_bounded_and_no_diagnostics_or_tokens_leaked(self):
        with patch.object(prepare.urllib.request, 'urlopen', side_effect=urllib.error.URLError('sensitive-marker')), \
             patch.object(prepare.time, 'sleep') as sleep:
            with self.assertRaisesRegex(DeploymentError, '^REGISTRY_NETWORK_RETRIES_EXHAUSTED$'):
                prepare.request('https://ghcr.io/test', {'Authorization': 'secret-test'})
            self.assertEqual(sleep.call_count, 2)

    def test_missing_image_and_auth_fail_closed_not_an_absent_publish_tag(self):
        for status in [401, 403, 404]:
            error = urllib.error.HTTPError('url', status, 'private', {}, None)
            with patch.object(prepare.urllib.request, 'urlopen', side_effect=error):
                with self.assertRaises(DeploymentError): prepare.request('https://ghcr.io/test', {}, allow_absent=status != 404)
        with patch.object(prepare.urllib.request, 'urlopen', side_effect=urllib.error.HTTPError('url', 404, '', {}, None)):
            self.assertIsNone(prepare.request('https://ghcr.io/test', {}, allow_absent=True)[0])

    def test_registry_child_digest_and_amd64_selection_are_verified(self):
        child = json.dumps({'config': {'digest': 'sha256:' + 'd' * 64}}).encode()
        digest = 'sha256:' + artifacts.sha(child)
        index = json.dumps({'manifests': [{'digest': digest, 'platform': {'os': 'linux', 'architecture': 'amd64'}}]}).encode()
        with patch.dict(os.environ, {'GITHUB_ACTOR': 'test', 'GHCR_TOKEN': 'synthetic'}):
            with patch.object(prepare, 'request', side_effect=[(b'{"token":"synthetic"}', {}), (index, {}), (child, {})]):
                self.assertEqual(prepare.ghcr_manifest(REPOSITORIES['BACKEND_IMAGE_REF'], 'sha-' + BACK)['manifestDigest'], digest)
            with patch.object(prepare, 'request', side_effect=[(b'{"token":"synthetic"}', {}), (index, {}), (child + b' ', {})]):
                with self.assertRaisesRegex(DeploymentError, 'DIGEST_MISMATCH'): prepare.ghcr_manifest(REPOSITORIES['BACKEND_IMAGE_REF'], 'sha-' + BACK)
            arm = index.replace(b'amd64', b'arm64')
            with patch.object(prepare, 'request', side_effect=[(b'{"token":"synthetic"}', {}), (arm, {})]):
                with self.assertRaisesRegex(DeploymentError, 'AMD64'): prepare.ghcr_manifest(REPOSITORIES['BACKEND_IMAGE_REF'], 'sha-' + BACK)

    def test_existing_immutable_tag_is_not_overwritten(self):
        with patch.dict(os.environ, {'GITHUB_ACTOR': 'test', 'GHCR_TOKEN': 'synthetic'}), \
             patch.object(prepare, 'request', side_effect=[(b'{"token":"synthetic"}', {}), (b'{}', {})]):
            with self.assertRaisesRegex(DeploymentError, 'IMMUTABLE_TAG_ALREADY_EXISTS'):
                prepare.ghcr_manifest(REPOSITORIES['BACKEND_IMAGE_REF'], 'sha-' + BACK, absent=True)


class RunnerDockerDiagnosticsTest(unittest.TestCase):
    PINNED = REPOSITORIES['BACKEND_IMAGE_REF'] + '@sha256:' + 'c' * 64

    def failure(self, command, stderr, stdout=b''):
        result = subprocess.CompletedProcess(command, 125, stdout, stderr)
        with patch.object(prepare.subprocess, 'run', return_value=result):
            with self.assertRaises(DeploymentError) as caught:
                prepare.run(command)
        return str(caught.exception)

    def test_failed_operation_image_and_exit_code_are_reported(self):
        for operation in [('pull',), ('image', 'inspect'), ('image', 'tag'),
                          ('image', 'save'), ('buildx', 'imagetools', 'inspect')]:
            with self.subTest(operation=operation):
                command = ['docker', *operation, self.PINNED]
                error = self.failure(command, b'unknown flag: --platform')
                self.assertIn('RUNNER_DOCKER_OPERATION_FAILED', error)
                self.assertIn('docker ' + ' '.join(operation), error)
                self.assertIn(self.PINNED, error)
                self.assertIn('exit=125', error)
                self.assertIn('PLATFORM_OPTION_UNSUPPORTED', error)

    def test_docker_reasons_have_actionable_safe_diagnostics(self):
        cases = [
            (b'--platform requires API version 1.49, but the Docker daemon API version is 1.47', 'API_VERSION_UNSUPPORTED'),
            (b'Error response from daemon: denied: permission_denied: read_package', 'ACCESS_DENIED'),
            (b'Error response from daemon: manifest unknown', 'IMAGE_NOT_FOUND'),
            (b'no suitable export target found for platform linux/amd64', 'PLATFORM_UNAVAILABLE'),
            (b'no space left on device', 'DISK_FULL'),
            (b'Cannot connect to the Docker daemon. Is the docker daemon running?', 'DAEMON_UNAVAILABLE'),
            (b'x509: certificate signed by unknown authority', 'TLS_ERROR'),
            (b'lookup ghcr.io: no such host', 'NETWORK_ERROR'),
            (b'toomanyrequests: retry later', 'REGISTRY_RATE_LIMIT'),
        ]
        for stderr, expected in cases:
            with self.subTest(reason=expected):
                self.assertIn(expected, self.failure(['docker', 'pull', self.PINNED], stderr))

    def test_raw_streams_arguments_credentials_and_workflow_commands_never_leak(self):
        private = (b'Authorization: Bearer synthetic-registry-token\n'
                   b'https://user:synthetic-password@registry.invalid/?token=synthetic-query-token\n'
                   b'-----BEGIN OPENSSH PRIVATE KEY-----\nsynthetic-key\n'
                   b'::error::synthetic-workflow-injection\n')
        for stderr in [private, b'denied: ' + private]:
            with self.subTest(known_reason=stderr.startswith(b'denied')):
                error = self.failure(['docker', 'image', 'save', '--output', '/private/synthetic-path',
                                      self.PINNED, '--password=synthetic-command-secret'], stderr, private)
                self.assertIn(self.PINNED, error)
                for secret in ['synthetic-', 'PRIVATE KEY', 'Authorization', '::error::', 'registry.invalid']:
                    self.assertNotIn(secret, error)
        self.assertIn('UNCLASSIFIED', self.failure(['docker', 'pull', self.PINNED], private))
        self.assertIn('ACCESS_DENIED', self.failure(['docker', 'pull', self.PINNED], b'', b'denied: ' + private))

    def test_timeout_and_start_failure_include_context_without_private_exception(self):
        command = ['docker', 'image', 'inspect', self.PINNED]
        for exception, expected in [
            (subprocess.TimeoutExpired(command, 17, output=b'synthetic-private', stderr=b'synthetic-private'), 'timeout=17s'),
            (OSError('synthetic-private'), 'START_FAILED'),
        ]:
            with self.subTest(failure=expected), patch.object(prepare.subprocess, 'run', side_effect=exception):
                with self.assertRaises(DeploymentError) as caught:
                    prepare.run(command, timeout=17)
                error = str(caught.exception)
                self.assertIn('docker image inspect', error)
                self.assertIn(self.PINNED, error)
                self.assertIn(expected, error)
                self.assertNotIn('synthetic-private', error)

    def test_success_preserves_binary_stdout_and_subprocess_options(self):
        command = ['docker', 'image', 'inspect', self.PINNED]
        output = b'[{"Id":"sha256:synthetic"}]\n'
        with patch.object(prepare.subprocess, 'run', return_value=subprocess.CompletedProcess(command, 0, output, b'')) as run, \
             contextlib.redirect_stderr(io.StringIO()) as stderr:
            self.assertEqual(prepare.run(command, input=b'synthetic-input', timeout=17), output)
        run.assert_called_once_with(command, input=b'synthetic-input', capture_output=True, timeout=17)
        self.assertEqual(stderr.getvalue(), '')

    def test_deploy_entrypoint_keeps_diagnostic_in_actions_stderr_and_exit_two(self):
        import run_production_deploy as pipeline
        command = ['docker', 'image', 'inspect', self.PINNED]
        argv = ['run_production_deploy.py', '--output', '/unused']
        result = subprocess.CompletedProcess(command, 125, b'', b'unknown flag: --platform')
        with patch.object(sys, 'argv', argv), patch.object(pipeline, 'validate_manual'), \
             patch.object(pipeline, 'deploy', side_effect=lambda args: prepare.run(command)), \
             patch.object(prepare.subprocess, 'run', return_value=result), \
             contextlib.redirect_stderr(io.StringIO()) as stderr, contextlib.redirect_stdout(io.StringIO()) as stdout:
            self.assertEqual(pipeline.main(), 2)
        self.assertEqual(stdout.getvalue(), '')
        self.assertIn('docker image inspect', stderr.getvalue())
        self.assertIn('PLATFORM_OPTION_UNSUPPORTED', stderr.getvalue())


class TransportTest(unittest.TestCase):
    ENV = {'VPS_HOST': 'vps.example.invalid', 'VPS_PORT': '2222', 'VPS_USERNAME': 'policydeploy',
           'VPS_SSH_KEY': 'synthetic-test-not-a-key',
           'VPS_HOST_KEY': 'ssh-ed25519 ' + base64.b64encode(b'\x00\x00\x00\x0bssh-ed25519\x00\x00\x00\x20' + b'\x01' * 32).decode(),
           'VPS_DEPLOY_PATH': '/opt/ai-policy-investigator', 'VPS_ENV_FILE': '/opt/ai-policy-investigator/production.env'}

    def test_pinned_host_keys_batch_mode_nonroot_and_secret_file_permissions(self):
        with tempfile.TemporaryDirectory() as temporary:
            ssh, scp, target = transport.connection(Path(temporary), self.ENV)
            self.assertIn('StrictHostKeyChecking=yes', ssh); self.assertIn('IdentitiesOnly=yes', scp)
            self.assertIn('BatchMode=yes', ssh)
            self.assertEqual((Path(temporary) / 'identity').stat().st_mode & 0o777, 0o600)
            self.assertNotIn(self.ENV['VPS_SSH_KEY'], ' '.join(ssh))
            self.assertEqual(target, 'policydeploy@vps.example.invalid')

    def test_invalid_ssh_inputs_and_missing_secrets_rejected_before_network(self):
        with tempfile.TemporaryDirectory() as temporary:
            for key, value in [('VPS_HOST', '-oProxyCommand=bad'), ('VPS_USERNAME', 'user;bad'),
                               ('VPS_PORT', '22;bad'), ('VPS_HOST_KEY', '')]:
                with self.assertRaises(DeploymentError): transport.connection(Path(temporary), {**self.ENV, key: value})

    def test_rollback_transports_no_images_and_never_applies_migrations(self):
        with patch.dict(os.environ, self.ENV), patch.object(transport, 'execute', return_value=json.dumps({'id': 'r123-1', 'result': 'VALIDATED'})) as execute:
            with contextlib.redirect_stdout(io.StringIO()):
                transport.transfer('rollback', 'r123-1')
            self.assertEqual(execute.call_count, 1)
            self.assertEqual(execute.call_args.args[0][-1], 'python3 /opt/ai-policy-investigator/releases/r123-1/scripts/production_release.py rollback r123-1 --env-file /opt/ai-policy-investigator/production.env')
        with self.assertRaises(DeploymentError): transport.transfer('rollback', 'r123-1', allow_migrations=True)

    def test_network_failure_does_not_echo_private_ssh_diagnostics(self):
        with patch.object(transport.subprocess, 'run', side_effect=OSError('private-marker')):
            with self.assertRaisesRegex(DeploymentError, '^SSH_NETWORK_FAILED$'): transport.execute(['ssh'], 'SSH_NETWORK_FAILED')

    def test_dispatch_validates_explicit_pair_and_exclusive_rollback(self):
        dispatch.validate({'OPERATION': 'deploy', 'BACKEND_SHA': BACK, 'FRONTEND_SHA': FRONT})
        dispatch.validate({'OPERATION': 'rollback', 'ROLLBACK_RELEASE': 'r123-1', 'ALLOW_MIGRATIONS': 'false'})
        for env in [{'OPERATION': 'deploy', 'BACKEND_SHA': 'main', 'FRONTEND_SHA': FRONT},
                    {'OPERATION': 'rollback', 'ROLLBACK_RELEASE': '../x', 'ALLOW_MIGRATIONS': 'false'},
                    {'OPERATION': 'rollback', 'ROLLBACK_RELEASE': 'r123-1', 'ALLOW_MIGRATIONS': 'true'}]:
            with self.assertRaises(DeploymentError): dispatch.validate(env)


class ControllerTest(unittest.TestCase):
    def test_corrupted_compose_is_rejected_before_docker(self):
        with self.assertRaisesRegex(DeploymentError, 'CONFIGURATION_DIGEST_MISMATCH'): controller.reviewed_configuration(manifest())

    def test_unrelated_existing_database_image_is_never_recreated(self):
        with patch.object(controller, 'execute', return_value='abc\n'), patch.object(controller, 'json_command', return_value=[{'Image': 'wrong'}]):
            with self.assertRaisesRegex(DeploymentError, 'POSTGRES_IMAGE_CHANGE_FORBIDDEN'):
                controller.verify_existing_postgres('sha256:' + 'd' * 64)

    def test_public_network_tls_and_unexpected_http_fail(self):
        with patch.object(controller.urllib.request, 'build_opener') as build:
            build.return_value.open.side_effect = urllib.error.URLError('private')
            with self.assertRaisesRegex(DeploymentError, 'TLS_FAILED'): controller.check_url('https://example.invalid/', 200)
            build.return_value.open.side_effect = urllib.error.HTTPError('url', 502, '', {}, None)
            with self.assertRaisesRegex(DeploymentError, 'STATUS_FAILED'): controller.check_url('https://example.invalid/', 200)

    def _activation(self, directory, fail=None, rollback=False, expected_previous='UNSET'):
        data = manifest()
        if expected_previous != 'UNSET': data['expectedPrevious'] = expected_previous
        applied = [{**migration(), 'success': True, 'type': 'SQL'}]
        def execute(command, *args, **kwargs):
            if command[:2] == ['back', 'ps']: return 'a' * 64
            if command[:2] == ['docker', 'wait']: return '0'
            if fail and fail in command: raise DeploymentError('SIMULATED_' + fail.upper() + '_FAILED')
            return ''
        with patch.object(controller, 'reviewed_configuration'), patch.object(controller, 'commands', return_value=(['back'], ['front'], {}, {})), \
             patch.object(controller, 'verify_archives', return_value={k: {'diffIds': [], 'imageConfig': {}} for k in artifacts.KEYS}), patch.object(controller, 'execute', side_effect=execute) as run, \
             patch.object(controller, 'inspect_image', return_value={'platform': 'linux/amd64'}), \
             patch.object(controller, 'json_command', return_value=[{'Id': 'sha256:' + 'd' * 64, 'RootFS': {'Layers': []}, 'Os': 'linux', 'Architecture': 'amd64', 'Config': {}}]), \
             patch.object(controller, 'check_runtime'), patch.object(controller, 'verify_existing_postgres'), \
             patch.object(controller, 'history', return_value=applied), patch.object(controller, 'routing'), \
             patch.object(controller, 'healthy_service'):
            result = controller.activate(directory, data, {'envFile': 'unused', 'publicUrl': 'https://example.invalid'}, rollback, base=directory)
            return result, run.call_args_list

    def test_success_requires_health_checks_and_only_replaces_app_services(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            result, calls = self._activation(directory)
            self.assertEqual(result['result'], 'VALIDATED')
            self.assertTrue((directory / 'last-successful.json').is_file())
            for call in calls:
                command = call.args[0]
                self.assertNotIn('pull', command); self.assertNotIn('build', command)
                if 'up' in command and command[-1] == 'postgres':
                    self.assertIn('--no-recreate', command); self.assertNotIn('--force-recreate', command)

    def test_backend_or_frontend_health_failure_never_marks_release_successful(self):
        for fail in ['backend', 'frontend']:
            with tempfile.TemporaryDirectory() as temporary:
                directory = Path(temporary)
                with self.assertRaises(DeploymentError): self._activation(directory, fail)
                self.assertFalse((directory / 'last-successful.json').exists())
                self.assertFalse((directory / 'validated.json').exists())

    def test_never_validated_rollback_is_rejected_before_loading_images(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(DeploymentError, 'NEVER_VALIDATED'): self._activation(Path(temporary), rollback=True)

class AdditionalSafetyTest(unittest.TestCase):
    def test_missing_config_or_layer_is_a_content_error_even_with_plausible_size(self):
        with tempfile.TemporaryDirectory() as temporary:
            for missing in ['config.json', 'layer.tar']:
                path, ref, digest, content = fixture(Path(temporary)); del content[missing]; write_tar(path, content)
                with self.assertRaisesRegex(DeploymentError, 'ARCHIVE_CONTENT_MISSING'): artifacts.archive_image(path, ref, digest)

    def test_health_failure_preserves_last_validated_release_marker(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            old = {'id': 'r122-1', 'migrations': [migration()]}
            (directory / 'last-successful.json').write_text(json.dumps(old))
            with self.assertRaises(DeploymentError): ControllerTest()._activation(directory, 'backend')
            self.assertEqual(json.loads((directory / 'last-successful.json').read_text()), old)

    def test_previously_validated_rollback_rechecks_health_and_records_previous(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            (directory / 'validated.json').write_text('{}')
            (directory / 'last-successful.json').write_text(json.dumps({'id': 'r124-1', 'migrations': [migration()]}))
            result, _ = ControllerTest()._activation(directory, rollback=True)
            self.assertTrue(result['rollback']); self.assertEqual(result['previous'], 'r124-1')

    def test_existing_database_isolation_and_persistent_volume_checked(self):
        row = {'Image': 'sha256:' + 'd' * 64, 'NetworkSettings': {'Networks': {'ai-policy-investigator_database': {}}},
               'HostConfig': {'PortBindings': {}}, 'Mounts': [{'Name': 'ai-policy-investigator_investigator_data',
                                                           'Destination': '/var/lib/postgresql/data'}]}
        with patch.object(controller, 'execute', return_value='abc'), patch.object(controller, 'json_command', return_value=[row]):
            self.assertTrue(controller.verify_existing_postgres([row['Image']]))
            row['HostConfig']['PortBindings'] = None
            self.assertTrue(controller.verify_existing_postgres([row['Image']]))
            row['NetworkSettings']['Networks']['nginx-proxy-manager_default'] = {}
            with self.assertRaisesRegex(DeploymentError, 'ISOLATION'): controller.verify_existing_postgres([row['Image']])

    def test_production_overlay_resolves_without_daemon_or_real_secrets(self):
        import shutil
        if not shutil.which('docker'):
            self.skipTest('Docker Compose CLI is required; no Docker daemon is used')
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); data = manifest()
            for name in artifacts.CONFIG_FILES:
                source = controller.ROOT / ('.ci/frontend/compose.yaml' if name == 'frontend/compose.yaml' else name)
                target = root / name; target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(source.read_bytes())
            env_file = root / 'private.env'
            env_file.write_text('\n'.join(k + '=synthetic-configuration-test-at-least-32-bytes' for k in
                                         ['MODEL_API_KEY', 'JWT_SECRET', 'APP_DB_PASSWORD', 'OWNER_DB_PASSWORD', 'POSTGRES_ADMIN_PASSWORD']))
            env_file.chmod(0o600)
            # Docker Desktop's CLI plugin lives in the test user's home; the VPS controller uses /root.
            real_execute = controller.execute
            def local_execute(command, env=None, *args, **kwargs):
                return real_execute(command, {**(env or {}), 'HOME': os.environ.get('HOME', '')}, *args, **kwargs)
            with patch.object(controller, 'execute', side_effect=local_execute), \
                 patch('deploy_local_images.execute', side_effect=local_execute):
                back, front, env, config = controller.commands(data, env_file, root)
            self.assertEqual(config['services']['postgres']['image'], data['images']['POSTGRES_IMAGE_REF']['localRef'])
            self.assertTrue(all(row['pull_policy'] == 'never' and not row.get('ports') and not row.get('build')
                                for row in config['services'].values()))


class PreparationFlowTest(unittest.TestCase):
    def test_full_runner_preparation_accepts_docker29_manifest_ids_and_verifies_all_archives(self):
        import shutil
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sources, metadata = {}, {}
            for key in artifacts.KEYS:
                directory = root / key; directory.mkdir()
                revision = FRONT if key == 'FRONTEND_IMAGE_REF' else BACK
                path, ref, config_digest, content = fixture(directory, key, revision=revision)
                registry = json.dumps({'schemaVersion': 2, 'config': {'digest': config_digest}}).encode()
                digest = 'sha256:' + artifacts.sha(registry) if key == 'POSTGRES_IMAGE_REF' else 'sha256:' + 'c' * 64
                if key == 'POSTGRES_IMAGE_REF':
                    content['manifest.json'] = content['manifest.json'].replace(('c' * 64).encode(), digest[7:].encode())
                    write_tar(path, content)
                sources[key] = path
                metadata[key] = {'manifestDigest': digest, 'configDigest': config_digest, 'indexDigest': digest, 'raw': registry}
            def registry(repository, tag):
                key = next(k for k, value in REPOSITORIES.items() if value == repository)
                return {k: v for k, v in metadata[key].items() if k != 'raw'}
            def docker(command, **kwargs):
                if command[:3] == ['docker', 'buildx', 'imagetools']:
                    pg = metadata['POSTGRES_IMAGE_REF']
                    return pg['raw'] if '--raw' in command else json.dumps({'digest': pg['manifestDigest']}).encode()
                if command[:3] == ['docker', 'image', 'inspect']:
                    pinned = command[-1]
                    key = next((k for k, repo in REPOSITORIES.items() if pinned.startswith(repo + '@')), 'POSTGRES_IMAGE_REF')
                    return json.dumps([{'Os': 'linux', 'Architecture': 'amd64', 'Id': metadata[key]['manifestDigest']}]).encode()
                if command[:3] == ['docker', 'image', 'save']:
                    destination = Path(command[command.index('--output') + 1])
                    key = destination.name.removesuffix('.raw')
                    shutil.copyfile(sources[key], destination)
                return b''
            with patch.object(prepare, 'ghcr_manifest', side_effect=registry), patch.object(prepare, 'run', side_effect=docker):
                data = prepare.prepare(root / 'output', BACK, FRONT, BACK, 'r123-1')
            self.assertEqual(data['migrations'], [migration()])
            self.assertNotEqual(data['images']['BACKEND_IMAGE_REF']['configDigest'], data['images']['BACKEND_IMAGE_REF']['manifestDigest'])
            proofs = controller.verify_archives(root / 'output', data)
            self.assertEqual(set(proofs), set(artifacts.KEYS))
            self.assertEqual(data['backendSha'], BACK); self.assertEqual(data['frontendSha'], FRONT)

    def test_gzip_layer_diffid_is_verified_on_uncompressed_content(self):
        import gzip
        with tempfile.TemporaryDirectory() as temporary:
            path, ref, digest, content = fixture(Path(temporary))
            content['layer.tar'] = gzip.compress(content['layer.tar']); write_tar(path, content)
            self.assertEqual(artifacts.archive_image(path, ref, digest, BACK, True), [migration()])

    def test_missing_or_unhealthy_container_is_never_accepted(self):
        for row in [{'State': {'Running': True}}, {'State': {'Running': True, 'Health': {'Status': 'unhealthy'}}},
                    {'State': {'Running': False, 'Health': {'Status': 'healthy'}}}]:
            with patch.object(controller, 'execute', return_value='a' * 64), patch.object(controller, 'json_command', return_value=[row]):
                with self.assertRaisesRegex(DeploymentError, 'NOT_HEALTHY'): controller.healthy_service(['back'], 'backend', {})


if __name__ == '__main__':
    unittest.main()
