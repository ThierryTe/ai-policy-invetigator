"""Preparation-only safety checks using real synthetic archives and mocked Docker/registry."""
import contextlib
import errno
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tarfile
import tempfile
import unittest
import urllib.error
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import prepare_backend_qualification as preparation
import prepare_production_release as runner
import release_artifacts as artifacts
import release_safety as safety
from deploy_local_images import DeploymentError
from test_production_release import write_tar

REVISION = 'a' * 40
MANIFEST = 'sha256:' + 'c' * 64


def fixture(architecture='amd64', revision=REVISION, source=preparation.SOURCE, change_sql=False):
    jar = io.BytesIO()
    with zipfile.ZipFile(jar, 'w') as output:
        for row in safety.qualified_migrations():
            sql = (safety.ROOT / 'src/main/resources/db/migration' / row['script']).read_bytes()
            if change_sql and row['version'] == '8':
                sql += b'\n-- changed migration\n'
            output.writestr('BOOT-INF/classes/db/migration/' + row['script'], sql)
    layer = io.BytesIO()
    with tarfile.open(fileobj=layer, mode='w:') as output:
        member = tarfile.TarInfo('app/investigator.jar')
        member.size = len(jar.getvalue())
        output.addfile(member, io.BytesIO(jar.getvalue()))
    raw = layer.getvalue()
    config = json.dumps({
        'os': 'linux', 'architecture': architecture,
        'config': {'Env': ['SYNTHETIC_PRIVATE_VALUE=do-not-log'], 'Labels': {
            'org.opencontainers.image.revision': revision, 'org.opencontainers.image.source': source}},
        'rootfs': {'diff_ids': ['sha256:' + artifacts.sha(raw)]},
    }).encode()
    ref = preparation.REPOSITORY + ':deploy-' + MANIFEST[7:]
    return 'sha256:' + artifacts.sha(config), {
        'manifest.json': json.dumps([{'Config': 'config.json', 'RepoTags': [ref], 'Layers': ['layer.tar']}]).encode(),
        'config.json': config, 'layer.tar': raw, 'index.json': b'{}',
    }


class PreparationTest(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, {}, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.output = Path(self.temporary.name) / 'evidence'
        self.config_digest, self.content = fixture()
        self.commands = []

    def arguments(self, **changes):
        return dict(output=self.output, revision=REVISION, manifest_digest=MANIFEST,
                    config_digest=self.config_digest, evidence_ref='CHG-V8-TEST', authorized=True, **changes)

    def docker(self, command):
        self.commands.append(command)
        if command[:3] == ['docker', 'image', 'inspect']:
            return json.dumps([{'Os': 'linux', 'Architecture': 'amd64'}]).encode()
        if command[:3] == ['docker', 'image', 'save']:
            write_tar(Path(command[4]), self.content)
            return b''
        if command[:2] == ['docker', 'pull'] or command[:3] == ['docker', 'image', 'tag']:
            return b''
        self.fail('Unexpected Docker operation: ' + repr(command[:3]))

    def prepare(self, metadata=None, **changes):
        values = self.arguments()
        values.update(changes)
        metadata = metadata or {'manifestDigest': MANIFEST, 'indexDigest': MANIFEST,
                                'configDigest': self.config_digest}
        with patch.object(preparation, 'ghcr_manifest', return_value=metadata) as registry, \
                patch.object(preparation, 'run', side_effect=self.docker):
            report = preparation.prepare(**values)
            registry.assert_called_once_with(preparation.REPOSITORY, MANIFEST)
            return report

    def cli(self):
        argv = ['--revision', REVISION, '--manifest-digest', MANIFEST, '--config-digest', self.config_digest,
                '--evidence-ref', 'CHG-V8-TEST', '--confirm-authorized', '--output', str(self.output)]
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            status = preparation.main(argv)
        return status, stdout.getvalue(), stderr.getvalue()

    def assert_failed(self, result, stage, category):
        status, stdout, stderr = result
        self.assertEqual(status, 2)
        expected = (f'BACKEND_PREPARATION_FAILED stage={stage} category={category}; '
                    'no qualification artifact should be used.\n')
        # stdout goes to the existing Step Summary; stderr goes to Actions logs.
        self.assertEqual(stdout, expected)
        self.assertEqual(stderr, expected)
        self.assertNotIn('PASS', stdout + stderr)
        self.assertEqual(list(Path(self.temporary.name).iterdir()), [])

    def test_success_verifies_real_archive_and_publishes_only_scoped_evidence(self):
        report = self.prepare()
        self.assertEqual(report['migrations'], safety.qualified_migrations())
        self.assertTrue(report['migrationEquivalenceVerified'])
        self.assertFalse(report['binaryIdentityVerified'])
        self.assertFalse(report['productionBuildProfileQualified'])
        self.assertEqual(report['qualifiedEvidenceSha256'], safety.EVIDENCE_SHA256)
        self.assertEqual({p.name for p in self.output.iterdir()},
                         {'BACKEND_IMAGE_REF.tar', 'evidence.json', 'SHA256SUMS'})
        with tarfile.open(self.output / report['archive']) as archive:
            self.assertEqual(set(archive.getnames()), {'manifest.json', 'config.json', 'layer.tar'})
        for line in (self.output / 'SHA256SUMS').read_text().splitlines():
            checksum, name = line.split('  ')
            self.assertEqual(checksum, artifacts.file_sha(self.output / name))
        self.assertNotIn('do-not-log', (self.output / 'evidence.json').read_text())
        pinned = preparation.REPOSITORY + '@' + MANIFEST
        self.assertEqual(self.commands[0], ['docker', 'pull', '--platform', 'linux/amd64', pinned])
        self.assertEqual(len(self.commands), 4)

    def test_missing_authorization_or_malformed_input_never_contacts_registry_or_docker(self):
        for key, value in [('authorized', False), ('revision', 'main'), ('manifest_digest', 'latest'),
                           ('config_digest', 'sha256:bad'), ('evidence_ref', 'secret\nINJECTION')]:
            with self.subTest(key=key), patch.object(preparation, 'ghcr_manifest') as registry, \
                    patch.object(preparation, 'run') as docker, self.assertRaises(DeploymentError):
                values = self.arguments(); values[key] = value
                try:
                    preparation.prepare(**values)
                finally:
                    registry.assert_not_called(); docker.assert_not_called()
        self.assertFalse(self.output.exists())

    def test_changed_historical_inventory_fails_before_network(self):
        with patch.object(safety, 'EVIDENCE_SHA256', '0' * 64), \
                patch.object(preparation, 'ghcr_manifest') as registry, self.assertRaisesRegex(DeploymentError, 'EVIDENCE_CHANGED'):
            try:
                preparation.prepare(**self.arguments())
            finally:
                registry.assert_not_called()

    def test_index_other_manifest_or_config_digest_rejected_before_docker(self):
        for key in ('indexDigest', 'manifestDigest', 'configDigest'):
            metadata = {'manifestDigest': MANIFEST, 'indexDigest': MANIFEST, 'configDigest': self.config_digest}
            metadata[key] = 'sha256:' + '0' * 64
            with self.subTest(key=key), self.assertRaises(preparation.PreparationFailure) as caught:
                self.prepare(metadata=metadata)
            self.assertEqual(caught.exception.stage, 'APPROVED_DIGESTS')
            self.assertEqual(caught.exception.category, 'APPROVED_CONFIG_DIGEST_MISMATCH'
                             if key == 'configDigest' else 'APPROVED_DIGEST_MUST_BE_PLATFORM_MANIFEST')
            self.assertEqual(self.commands, [])
            self.assertFalse(self.output.exists())

    def test_rejects_wrong_runner_platform_before_save(self):
        with patch.object(preparation, 'verify_runner_platform',
                          side_effect=DeploymentError('RUNNER_IMAGE_PLATFORM_MISMATCH')):
            with self.assertRaisesRegex(DeploymentError, 'PLATFORM'):
                self.prepare()
        self.assertEqual(len(self.commands), 2)
        self.assertFalse((self.output / 'evidence.json').exists())

    def test_archive_platform_revision_source_migrations_and_layer_tampering_fail_closed(self):
        cases = [({'architecture': 'arm64'}, 'ARCHIVE_VERIFICATION', 'ARCHIVE_PLATFORM_MISMATCH'),
                 ({'revision': 'b' * 40}, 'ARCHIVE_VERIFICATION', 'ARCHIVE_SOURCE_REVISION_MISMATCH'),
                 ({'source': 'https://example.invalid'}, 'SOURCE_REPOSITORY', 'ARCHIVE_SOURCE_REPOSITORY_MISMATCH'),
                 ({'change_sql': True}, 'MIGRATION_EQUIVALENCE', 'IMAGE_MIGRATIONS_NOT_QUALIFIED_V8'),
                 ({'tamper': True}, 'ARCHIVE_VERIFICATION', 'ARCHIVE_LAYER_DIGEST_MISMATCH'),
                 ({'config': True}, 'ARCHIVE_VERIFICATION', 'ARCHIVE_CONFIG_DIGEST_MISMATCH')]
        for change, stage, category in cases:
            with self.subTest(change=change), tempfile.TemporaryDirectory() as temporary:
                values = {k: v for k, v in change.items() if k not in ('tamper', 'config')}
                self.config_digest, self.content = fixture(**values)
                if change.get('tamper'):
                    self.content['layer.tar'] += b'tampered'
                if change.get('config'):
                    self.content['config.json'] += b' '
                target = Path(temporary) / 'evidence'
                with self.assertRaises(preparation.PreparationFailure) as caught:
                    self.prepare(output=target)
                self.assertEqual(caught.exception.stage, stage)
                self.assertEqual(caught.exception.category, category)
                self.assertFalse((target / 'evidence.json').exists())
                self.assertFalse((target / 'SHA256SUMS').exists())
                self.assertEqual(list(Path(temporary).iterdir()), [])

    def test_existing_output_or_repository_output_is_not_overwritten(self):
        self.output.mkdir()
        marker = self.output / 'existing-file'
        marker.write_text('preserve existing output')
        for output in (self.output, preparation.ROOT / 'target' / 'forbidden-evidence'):
            with self.subTest(output=output), patch.object(preparation, 'ghcr_manifest') as registry, \
                    self.assertRaises(DeploymentError):
                try:
                    values = self.arguments(); values['output'] = output
                    preparation.prepare(**values)
                finally:
                    registry.assert_not_called()
        self.assertEqual(marker.read_text(), 'preserve existing output')

    def test_actions_guard_refuses_push_wrong_repository_and_non_main(self):
        valid = {'GITHUB_ACTIONS': 'true', 'GITHUB_EVENT_NAME': 'workflow_dispatch',
                 'GITHUB_REF': 'refs/heads/main', 'GITHUB_REPOSITORY': 'ThierryTe/ai-policy-invetigator',
                 'GITHUB_SHA': 'b' * 40, 'GITHUB_RUN_ID': '123', 'GITHUB_RUN_ATTEMPT': '1'}
        for key, value in [('GITHUB_EVENT_NAME', 'push'), ('GITHUB_REF', 'refs/heads/feature'),
                           ('GITHUB_REPOSITORY', 'untrusted/fork'), ('GITHUB_SHA', ''), ('GITHUB_RUN_ID', '')]:
            with self.subTest(key=key), patch.dict(os.environ, {**valid, key: value}, clear=True), \
                    patch.object(preparation, 'ghcr_manifest') as registry, self.assertRaises(DeploymentError):
                try:
                    preparation.prepare(**self.arguments())
                finally:
                    registry.assert_not_called()
        with patch.dict(os.environ, valid, clear=True):
            report = self.prepare()
        self.assertEqual(report['github']['toolingRevision'], valid['GITHUB_SHA'])
        self.assertEqual(report['github']['runId'], '123')

    def test_cli_withholds_raw_exceptions_and_returns_failure(self):
        argv = ['--revision', REVISION, '--manifest-digest', MANIFEST, '--config-digest', self.config_digest,
                '--evidence-ref', 'CHG-V8-TEST', '--confirm-authorized', '--output', str(self.output)]
        stderr, stdout = io.StringIO(), io.StringIO()
        with patch.object(preparation, 'prepare', side_effect=DeploymentError('synthetic-private-marker')), \
                contextlib.redirect_stderr(stderr), contextlib.redirect_stdout(stdout):
            self.assertEqual(preparation.main(argv), 2)
        self.assertNotIn('synthetic-private-marker', stderr.getvalue() + stdout.getvalue())

    def test_stages_and_categories_are_safe_in_logs_and_summary_and_leave_no_artifacts(self):
        private = ('/private/synthetic-path Authorization: Bearer synthetic-token '
                   'https://user:synthetic-password@registry.invalid SYNTHETIC_PRIVATE_VALUE=do-not-log\n'
                   '::error::synthetic-workflow-command')
        cases = [
            ('validate_inputs', DeploymentError('FULL_SOURCE_SHA_REQUIRED'),
             'INPUT_VALIDATION', 'FULL_SOURCE_SHA_REQUIRED'),
            ('qualified_migrations', DeploymentError('V8_QUALIFICATION_EVIDENCE_CHANGED'),
             'QUALIFIED_MIGRATIONS', 'V8_QUALIFICATION_EVIDENCE_CHANGED'),
            ('ghcr_manifest', DeploymentError('REGISTRY_AUTH_OR_REFERENCE_FAILED'),
             'REGISTRY_MANIFEST', 'REGISTRY_AUTH_OR_REFERENCE_FAILED'),
            ('ghcr_manifest', DeploymentError('REGISTRY_NETWORK_RETRIES_EXHAUSTED'),
             'REGISTRY_MANIFEST', 'REGISTRY_NETWORK_RETRIES_EXHAUSTED'),
            ('ghcr_manifest', KeyError(private), 'REGISTRY_MANIFEST', 'INVALID_METADATA'),
            ('verify_runner_platform', DeploymentError('RUNNER_IMAGE_PLATFORM_MISMATCH'),
             'RUNNER_PLATFORM', 'RUNNER_IMAGE_PLATFORM_MISMATCH'),
            ('normalized_archive', tarfile.ReadError(private), 'ARCHIVE_NORMALIZATION', 'INVALID_ARCHIVE'),
            ('archive_image', DeploymentError('ARCHIVE_LAYER_DIGEST_MISMATCH'),
             'ARCHIVE_VERIFICATION', 'ARCHIVE_LAYER_DIGEST_MISMATCH'),
            ('archive_image', zipfile.BadZipFile(private), 'ARCHIVE_VERIFICATION', 'INVALID_ARCHIVE'),
            ('archive_image', OSError(errno.ENOSPC, private), 'ARCHIVE_VERIFICATION', 'DISK_FULL'),
            ('archive_image', DeploymentError('ARCHIVE_CONFIG_DIGEST_MISMATCH ' + private),
             'ARCHIVE_VERIFICATION', 'UNCLASSIFIED_DEPLOYMENT_ERROR'),
            ('archive_image', RuntimeError(private), 'ARCHIVE_VERIFICATION', 'INTERNAL_ERROR'),
            ('_write_evidence', PermissionError(errno.EACCES, private), 'EVIDENCE_WRITE', 'PERMISSION_DENIED'),
        ]
        metadata = {'manifestDigest': MANIFEST, 'indexDigest': MANIFEST, 'configDigest': self.config_digest}
        for function, error, stage, category in cases:
            with self.subTest(stage=stage, category=category), \
                    patch.object(preparation, 'ghcr_manifest', return_value=metadata), \
                    patch.object(preparation, 'run', side_effect=self.docker), \
                    patch.object(preparation, function, side_effect=error):
                self.assert_failed(self.cli(), stage, category)

    def test_actual_registry_request_failure_is_reported_without_http_details(self):
        error = urllib.error.HTTPError('https://private.invalid/token', 403, 'synthetic-token', {}, None)
        with patch.dict(os.environ, {'GITHUB_ACTOR': 'synthetic-actor', 'GHCR_TOKEN': 'synthetic-token'}), \
                patch.object(runner.urllib.request, 'urlopen', side_effect=error), \
                patch.object(preparation, 'run') as docker:
            self.assert_failed(self.cli(), 'REGISTRY_MANIFEST', 'REGISTRY_AUTH_OR_REFERENCE_FAILED')
        docker.assert_not_called()

    def test_each_docker_operation_preserves_helper_category_without_raw_streams(self):
        metadata = {'manifestDigest': MANIFEST, 'indexDigest': MANIFEST, 'configDigest': self.config_digest}
        operations = [('DOCKER_PULL', ['docker', 'pull']), ('DOCKER_INSPECT', ['docker', 'image', 'inspect']),
                      ('DOCKER_TAG', ['docker', 'image', 'tag']), ('DOCKER_SAVE', ['docker', 'image', 'save'])]
        reasons = [(b'denied: synthetic-token /private/synthetic-path\n::error::injected', 'ACCESS_DENIED'),
                   (b'no space left on device: synthetic-token', 'DISK_FULL'),
                   (b'unknown flag: --platform synthetic-token', 'PLATFORM_OPTION_UNSUPPORTED'),
                   (b'requires API version 1.49 synthetic-token', 'API_VERSION_UNSUPPORTED'),
                   (b'synthetic-token /private/synthetic-path', 'UNCLASSIFIED')]
        for stage, prefix in operations:
            for raw, category in reasons:
                def docker(command):
                    if command[:len(prefix)] == prefix:
                        result = subprocess.CompletedProcess(command, 125, raw, raw)
                        with patch.object(runner.subprocess, 'run', return_value=result):
                            return runner.run(command)
                    return self.docker(command)
                with self.subTest(stage=stage, category=category), \
                        patch.object(preparation, 'ghcr_manifest', return_value=metadata), \
                        patch.object(preparation, 'run', side_effect=docker):
                    self.assert_failed(self.cli(), stage, category)

    def test_docker_timeout_start_failure_and_malformed_inspection_are_sanitized(self):
        metadata = {'manifestDigest': MANIFEST, 'indexDigest': MANIFEST, 'configDigest': self.config_digest}
        for error, category in [(subprocess.TimeoutExpired(['docker', 'pull', 'synthetic-private'], 600,
                                                         stderr=b'synthetic-token'), 'DOCKER_TIMEOUT'),
                                (OSError('synthetic-private-path'), 'DOCKER_START_FAILED')]:
            with self.subTest(category=category), \
                    patch.object(preparation, 'ghcr_manifest', return_value=metadata), \
                    patch.object(runner.subprocess, 'run', side_effect=error):
                self.assert_failed(self.cli(), 'DOCKER_PULL', category)
        for data in [b'synthetic-token /private/path', b'[]', b'[null]']:
            def docker(command):
                return data if command[:3] == ['docker', 'image', 'inspect'] else self.docker(command)
            with self.subTest(data=data), patch.object(preparation, 'ghcr_manifest', return_value=metadata), \
                    patch.object(preparation, 'run', side_effect=docker):
                self.assert_failed(self.cli(), 'RUNNER_PLATFORM' if data == b'[null]' else 'DOCKER_INSPECT',
                                   'INVALID_METADATA')

    def test_checksum_failure_removes_staged_pass_evidence_and_archive(self):
        metadata = {'manifestDigest': MANIFEST, 'indexDigest': MANIFEST, 'configDigest': self.config_digest}
        observed = []
        def checksum(path):
            if path.name == 'evidence.json':
                observed.append(json.loads(path.read_text())['result'])
                self.assertTrue((path.parent / 'BACKEND_IMAGE_REF.tar').exists())
                self.assertTrue((path.parent / 'SHA256SUMS').exists())
                self.assertFalse(self.output.exists())
                raise OSError(errno.ENOSPC, '/private/synthetic-path synthetic-token')
            return artifacts.file_sha(path)
        with patch.object(preparation, 'ghcr_manifest', return_value=metadata), \
                patch.object(preparation, 'run', side_effect=self.docker), \
                patch.object(preparation, 'file_sha', side_effect=checksum):
            self.assert_failed(self.cli(), 'CHECKSUMS_WRITE', 'DISK_FULL')
        self.assertEqual(observed, ['PASS'])

    def test_output_commit_failure_removes_all_staged_artifacts(self):
        metadata = {'manifestDigest': MANIFEST, 'indexDigest': MANIFEST, 'configDigest': self.config_digest}
        with patch.object(preparation, 'ghcr_manifest', return_value=metadata), \
                patch.object(preparation, 'run', side_effect=self.docker), \
                patch.object(Path, 'rename', side_effect=PermissionError(errno.EACCES, 'synthetic-private-path')):
            self.assert_failed(self.cli(), 'OUTPUT_COMMIT', 'PERMISSION_DENIED')

    def test_cli_success_preserves_all_three_outputs_and_reports_pass_only_after_commit(self):
        metadata = {'manifestDigest': MANIFEST, 'indexDigest': MANIFEST, 'configDigest': self.config_digest}
        with patch.object(preparation, 'ghcr_manifest', return_value=metadata), \
                patch.object(preparation, 'run', side_effect=self.docker):
            status, stdout, stderr = self.cli()
        self.assertEqual(status, 0)
        self.assertTrue(stdout.startswith('PASS: image integrity and V1-V8 migration equivalence.'))
        self.assertEqual(stderr, '')
        self.assertEqual(list(Path(self.temporary.name).iterdir()), [self.output])
        self.assertEqual({path.name for path in self.output.iterdir()},
                         {'BACKEND_IMAGE_REF.tar', 'evidence.json', 'SHA256SUMS'})


class WorkflowTest(unittest.TestCase):
    def test_artifact_identity_inputs_have_no_stale_defaults(self):
        text = (preparation.ROOT / '.github/legacy-workflows/prepare-backend-qualification.yml').read_text()
        for key in ['backend_sha', 'approved_backend_digest', 'approved_config_digest']:
            block = re.search(r'^      ' + key + r':\n(.*?)(?=^      \w+:|^permissions:)', text, re.M | re.S)
            self.assertIsNotNone(block)
            self.assertIn('required: true', block[1])
            self.assertNotIn('default:', block[1])

    def test_manual_read_only_no_environment_secrets_or_production_operations(self):
        text = (preparation.ROOT / '.github/legacy-workflows/prepare-backend-qualification.yml').read_text()
        self.assertEqual(re.findall(r'^  (workflow_dispatch|push|pull_request|workflow_call|schedule):', text, re.M),
                         ['workflow_dispatch'])
        for value in ("github.event_name == 'workflow_dispatch'", "github.ref == 'refs/heads/main'",
                      "github.repository == 'ThierryTe/ai-policy-invetigator'", 'default: false',
                      'run: test "$CONFIRM_AUTHORIZED" = true', 'contents: read', 'packages: read'):
            self.assertIn(value, text)
        self.assertNotRegex(text, r'(?m)^\s+environment:|VPS_|SSH|packages: write|deploy-production|run_production_deploy')
        self.assertEqual(set(re.findall(r'secrets\.([A-Z_]+)', text)), {'GITHUB_TOKEN'})
        self.assertLess(text.index('run: test'), text.index('secrets.GITHUB_TOKEN'))
        for use in re.findall(r'uses: ([^\s]+)', text):
            self.assertRegex(use, r'@[0-9a-f]{40}$')
        upload = text[text.index('      - name: Upload verified'):]
        self.assertNotIn('always()', upload)
        self.assertNotIn('include-hidden-files: true', upload)
        self.assertNotIn('overwrite: true', upload)
        for name in ('BACKEND_IMAGE_REF.tar', 'evidence.json', 'SHA256SUMS'):
            self.assertIn('/backend-qualification/' + name, upload)
        self.assertIn('retention-days: 7', upload)
        self.assertIn('if-no-files-found: error', upload)


if __name__ == '__main__':
    unittest.main()
