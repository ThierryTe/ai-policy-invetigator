"""Offline follow-up regression tests; synthetic receipts are never approval evidence."""
import contextlib
import io
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
import warnings
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import verify_backend_qualification as gates
from deploy_local_images import DeploymentError


def jar(classes=b'qualified-class', extra=None, date=(2026, 1, 1, 0, 0, 0)):
    stream = io.BytesIO()
    entries = {'BOOT-INF/classes/Application.class': classes, 'BOOT-INF/lib/core-1.jar': b'core'}
    entries.update(extra or {})
    with zipfile.ZipFile(stream, 'w') as archive:
        for name, value in entries.items():
            archive.writestr(zipfile.ZipInfo(name, date), value)
    return stream.getvalue()


def tar(entries):
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode='w') as archive:
        for name, value in entries:
            member = tarfile.TarInfo(name)
            if value is None:
                member.type = tarfile.SYMTYPE
                member.linkname = 'untrusted-target'
                archive.addfile(member)
            else:
                member.size = len(value)
                archive.addfile(member, io.BytesIO(value))
    return stream.getvalue()


class JarComparisonTest(unittest.TestCase):
    def test_full_binary_identity_is_separate_from_zip_timestamp_equivalence(self):
        first = jar()
        self.assertTrue(gates.compare_jars(first, first)['binaryIdentityVerified'])
        comparison = gates.compare_jars(first, jar(date=(2026, 2, 1, 0, 0, 0)))
        self.assertFalse(comparison['binaryIdentityVerified'])
        self.assertTrue(comparison['allEntryPayloadsIdentical'])
        self.assertTrue(comparison['applicationPayloadIdentical'])
        self.assertFalse(comparison['productionBuildProfileQualified'])

    def test_class_drift_is_detected_even_with_unchanged_migrations(self):
        comparison = gates.compare_jars(jar(), jar(classes=b'other-class'))
        self.assertFalse(comparison['applicationPayloadIdentical'])
        self.assertEqual(comparison['entryDelta']['changed'], ['BOOT-INF/classes/Application.class'])

    def test_same_dependency_name_different_bytes_is_a_change(self):
        comparison = gates.compare_jars(jar(), jar(extra={'BOOT-INF/lib/core-1.jar': b'changed'}))
        self.assertEqual(comparison['dependencyDelta']['changed'], ['BOOT-INF/lib/core-1.jar'])

    def test_transformer_presence_never_proves_profile_qualification(self):
        libraries = {f'BOOT-INF/lib/{name}-1.jar': b'synthetic' for name in (
            'spring-ai-transformers', 'spring-ai-autoconfigure-model-transformers', 'onnxruntime', 'tokenizers')}
        comparison = gates.compare_jars(jar(), jar(extra=libraries))
        self.assertTrue(comparison['transformerLibrariesPresent'])
        self.assertFalse(comparison['productionBuildProfileQualified'])
        self.assertEqual(len(comparison['dependencyDelta']['added']), 4)

    def test_duplicate_zip_members_are_rejected(self):
        stream = io.BytesIO(jar())
        with warnings.catch_warnings(), zipfile.ZipFile(stream, 'a') as archive:
            warnings.simplefilter('ignore', UserWarning)
            archive.writestr('BOOT-INF/classes/Application.class', b'ambiguous')
        with self.assertRaisesRegex(DeploymentError, 'DUPLICATE_JAR_ENTRY'):
            gates.jar_inventory(stream.getvalue())


class EffectiveJarTest(unittest.TestCase):
    def extract(self, layers):
        with tempfile.TemporaryDirectory() as temporary:
            work = Path(temporary)
            config = json.dumps({'rootfs': {'diff_ids': [gates.sha(layer) for layer in layers]}}).encode()
            names = [str(n) + '.tar' for n in range(len(layers))]
            manifest = [{'RepoTags': ['synthetic-ref'], 'Config': 'config.json', 'Layers': names}]
            content = [('manifest.json', json.dumps(manifest).encode()), ('config.json', config)] + list(zip(names, layers))
            archive = work / 'image.tar'
            archive.write_bytes(tar(content))
            with patch.object(gates, 'CONFIG_DIGEST', 'sha256:' + gates.sha(config)):
                return gates.image_jar(archive, {'localRef': 'synthetic-ref',
                                               'layerDiffIds': [gates.sha(layer) for layer in layers]})

    def test_last_layer_replaces_jar(self):
        self.assertEqual(self.extract([tar([('app/investigator.jar', b'old')]),
                                       tar([('app/investigator.jar', b'new')])]), b'new')

    def test_whiteouts_remove_lower_jar(self):
        for marker in ('app/.wh.investigator.jar', 'app/.wh..wh..opq', '.wh.app', '.wh..wh..opq'):
            with self.subTest(marker=marker), self.assertRaisesRegex(DeploymentError, 'IMAGE_JAR_MISSING'):
                self.extract([tar([('app/investigator.jar', b'old')]), tar([(marker, b'')])])

    def test_whiteout_does_not_hide_same_layer_replacement_regardless_of_order(self):
        for entries in ([('app/investigator.jar', b'new'), ('app/.wh..wh..opq', b'')],
                        [('app/.wh..wh..opq', b''), ('app/investigator.jar', b'new')]):
            self.assertEqual(self.extract([tar([('app/investigator.jar', b'old')]), tar(entries)]), b'new')

    def test_links_and_duplicate_replacements_fail_closed(self):
        for entries in ([('app/investigator.jar', None)], [('app', None)],
                        [('app/investigator.jar', b'one'), ('app/investigator.jar', b'two')]):
            with self.subTest(entries=entries), self.assertRaises(DeploymentError):
                self.extract([tar(entries)])


class BundleTrustTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.work = self.root / 'work'
        self.work.mkdir()
        self.bundle = self.root / 'artifact.zip'

    def write_bundle(self, entries):
        with zipfile.ZipFile(self.bundle, 'w') as archive:
            for name, value in entries.items():
                archive.writestr(name, value)

    def test_outer_artifact_digest_is_checked_before_any_extraction(self):
        self.bundle.write_bytes(b'untrusted')
        with self.assertRaisesRegex(DeploymentError, 'GITHUB_ARTIFACT_ZIP_DIGEST_MISMATCH'):
            gates.unpack_verified_bundle(self.bundle, self.work)
        self.assertEqual(list(self.work.iterdir()), [])

    def test_path_traversal_is_rejected_even_if_outer_digest_matches(self):
        self.write_bundle({'../escape': b'bad', 'evidence.json': b'{}', 'SHA256SUMS': b''})
        with patch.object(gates, 'ARTIFACT_SHA256', gates.file_sha(self.bundle)), \
                self.assertRaisesRegex(DeploymentError, 'QUALIFICATION_BUNDLE_CONTENT_INVALID'):
            gates.unpack_verified_bundle(self.bundle, self.work)
        self.assertEqual(list(self.work.iterdir()), [])

    def test_checksum_must_cover_both_fixed_files_and_match_bytes(self):
        cases = ['', 'a' * 64 + '  ../escape\n', 'a' * 64 + '  evidence.json\n',
                 'a' * 64 + '  evidence.json\n' + 'b' * 64 + '  BACKEND_IMAGE_REF.tar\n']
        for index, checksums in enumerate(cases):
            work = self.root / str(index)
            work.mkdir()
            self.write_bundle({'BACKEND_IMAGE_REF.tar': b'archive', 'evidence.json': b'{}', 'SHA256SUMS': checksums})
            with patch.object(gates, 'ARTIFACT_SHA256', gates.file_sha(self.bundle)), self.assertRaises(DeploymentError):
                gates.unpack_verified_bundle(self.bundle, work)

    def test_mismatched_run_or_digest_cannot_be_reused(self):
        # A self-consistent checksum file alone is never sufficient evidence.
        evidence = b'{"result":"PASS"}'
        checksums = gates.sha(evidence) + '  evidence.json\n' + gates.sha(b'archive') + '  BACKEND_IMAGE_REF.tar\n'
        self.write_bundle({'BACKEND_IMAGE_REF.tar': b'archive', 'evidence.json': evidence, 'SHA256SUMS': checksums})
        with patch.object(gates, 'ARTIFACT_SHA256', gates.file_sha(self.bundle)), \
                self.assertRaisesRegex(DeploymentError, 'QUALIFICATION_EVIDENCE_BINDING_MISMATCH'):
            gates.unpack_verified_bundle(self.bundle, self.work)

    def valid_evidence(self):
        return {'format': 1, 'result': 'PASS', 'platform': 'linux/amd64',
                'sourceRevision': gates.SOURCE_REVISION, 'manifestDigest': gates.MANIFEST_DIGEST,
                'configDigest': gates.CONFIG_DIGEST, 'archive': 'BACKEND_IMAGE_REF.tar',
                'archiveSha256': gates.sha(b'archive'),
                'sourceRepository': 'https://github.com/ThierryTe/ai-policy-invetigator',
                'sourceRef': gates.REPOSITORY + '@' + gates.MANIFEST_DIGEST,
                'localRef': gates.REPOSITORY + ':deploy-' + gates.MANIFEST_DIGEST[7:],
                'qualifiedEvidenceSha256': gates.EVIDENCE_SHA256,
                'migrationEquivalenceVerified': True, 'binaryIdentityVerified': False,
                'productionBuildProfileQualified': False,
                'github': {'repository': 'ThierryTe/ai-policy-invetigator',
                           'toolingRevision': gates.TOOLING_REVISION, 'runId': gates.RUN_ID, 'runAttempt': '1'},
                'migrations': json.loads((gates.ROOT / 'docs/verification/v8-artifact.json').read_text())['migrations']}

    def pack_evidence(self, evidence):
        raw = json.dumps(evidence).encode()
        sums = gates.sha(raw) + '  evidence.json\n' + gates.sha(b'archive') + '  BACKEND_IMAGE_REF.tar\n'
        self.write_bundle({'BACKEND_IMAGE_REF.tar': b'archive', 'evidence.json': raw, 'SHA256SUMS': sums})

    def test_correct_receipt_is_reused_but_never_promoted_to_runtime_proof(self):
        evidence = self.valid_evidence()
        self.pack_evidence(evidence)
        with patch.object(gates, 'ARTIFACT_SHA256', gates.file_sha(self.bundle)):
            self.assertEqual(gates.unpack_verified_bundle(self.bundle, self.work), evidence)

    def test_changed_run_attempt_revision_and_boolean_type_are_rejected(self):
        for index, mutation in enumerate(('attempt', 'revision', 'boolean')):
            evidence = self.valid_evidence()
            if mutation == 'attempt':
                evidence['github']['runAttempt'] = '2'
            elif mutation == 'revision':
                evidence['sourceRevision'] = 'f' * 40
            else:
                evidence['migrationEquivalenceVerified'] = 1
            self.pack_evidence(evidence)
            work = self.root / ('mutation-' + str(index))
            work.mkdir()
            with patch.object(gates, 'ARTIFACT_SHA256', gates.file_sha(self.bundle)), self.assertRaises(DeploymentError):
                gates.unpack_verified_bundle(self.bundle, work)


class EvidenceAndCliTest(unittest.TestCase):
    def test_end_to_end_reuses_evidence_and_keeps_profile_gate_open(self):
        with patch.object(gates, 'baseline', return_value={'testsRerun': False}), \
                patch.object(gates, 'unpack_verified_bundle', return_value={}), \
                patch.object(gates, 'image_jar', return_value=jar()), \
                tempfile.TemporaryDirectory() as temporary:
            historical = Path(temporary) / 'historical.jar'
            historical.write_bytes(jar())
            report = gates.verify(Path('synthetic-bundle'), historical, Path('unused'))
        self.assertTrue(report['binaryIdentityVerified'])
        self.assertEqual(report['binaryIdentityStatus'], 'MATCH')
        self.assertTrue(report['migrationEquivalenceReused'])
        self.assertFalse(report['registryOrMigrationChecksRerun'])
        self.assertEqual(report['blockers'], ['PRODUCTION_PROFILE_RUNTIME_EVIDENCE_REQUIRED'])

    def test_missing_artifact_has_explicit_blockers_and_never_compares_jars(self):
        with patch.object(gates, 'baseline', return_value={'testsRerun': False}), \
                patch.object(gates, 'compare_jars') as compare:
            report = gates.verify(None, Path('unused'), Path('unused'))
        compare.assert_not_called()
        self.assertEqual(report['result'], 'BLOCKED')
        self.assertFalse(report['productionBuildProfileQualified'])
        self.assertIn('APPROVED_PREPARATION_ARTIFACT_REQUIRED', report['blockers'])
        self.assertEqual(report['binaryIdentityStatus'], 'NOT_CHECKED')

    def test_existing_or_repository_output_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'existing.json'
            path.write_text('preserve')
            for output in (path, gates.ROOT / 'must-not-create.json'):
                with patch.object(gates, 'verify') as verify, contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(gates.main(['--output', str(output)]), 1)
                verify.assert_not_called()
            self.assertEqual(path.read_text(), 'preserve')

    def test_blocked_report_has_nonzero_exit_status_and_no_overclaim(self):
        with patch.object(gates, 'verify', return_value={'result': 'BLOCKED'}), \
                contextlib.redirect_stdout(io.StringIO()) as stdout:
            self.assertEqual(gates.main([]), 2)
        self.assertEqual(json.loads(stdout.getvalue())['result'], 'BLOCKED')


class HistoricalEvidenceTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        evidence = self.root / 'docs/verification'
        evidence.mkdir(parents=True)
        self.jar = self.root / 'historical.jar'
        self.jar.write_bytes(b'synthetic-jar')
        self.report = self.root / 'TEST-example.Suite.xml'
        self.report.write_text('<testsuite name="example.Suite" tests="2" failures="0" errors="0" skipped="0"/>')
        artifact = evidence / 'v8-artifact.json'
        artifact.write_text(json.dumps({'jar_sha256': gates.file_sha(self.jar)}))
        qualification = evidence / 'v8-qualification.json'
        qualification.write_text(json.dumps({'java_tests': 2, 'suites': [{'suite': 'example.Suite',
            'tests': 2, 'failures': 0, 'errors': 0, 'skipped': 0, 'report_sha256': gates.file_sha(self.report)}]}))
        for name, value in (('ROOT', self.root), ('EVIDENCE_SHA256', gates.file_sha(artifact)),
                            ('QUALIFICATION_SHA256', gates.file_sha(qualification))):
            patcher = patch.object(gates, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_historical_hashes_and_counts_are_reused_without_execution(self):
        result = gates.baseline(self.jar, self.root)
        self.assertEqual(result['javaTests'], 2)
        self.assertEqual(result['reportHashesVerified'], 1)
        self.assertFalse(result['testsRerun'])

    def test_changed_historical_jar_is_rejected(self):
        self.jar.write_bytes(b'changed')
        with self.assertRaisesRegex(DeploymentError, 'HISTORICAL_JAR_CHANGED'):
            gates.baseline(self.jar, self.root)

    def test_changed_historical_report_is_rejected(self):
        self.report.write_text('<testsuite failures="1"/>')
        with self.assertRaisesRegex(DeploymentError, 'HISTORICAL_REPORT_CHANGED'):
            gates.baseline(self.jar, self.root)


if __name__ == '__main__':
    unittest.main()
