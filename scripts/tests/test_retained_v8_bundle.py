"""Offline retained bytes and independent anchors; no SSH, registry, Git or workers."""
import copy
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import verify_retained_v8_bundle as verifier
from deploy_local_images import DeploymentError
from test_release_safety import release

IDENTITY = 'r041243000818-11'
REVISION = 'a5b867b79504a59292cd52190908b51ec8c22080'


class RetainedV8BundleTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.bundle, self.record = self.root / 'retained.tar.gz', self.root / 'validated.json'
        self.files = {**{'configuration/' + name: b'original config\n' for name in verifier.CONFIG_FILES},
                      **{name: b'original runtime\n' for name in verifier.RUNTIME_FILES}}
        self.data = release('migrate-v8')
        self.data.update(id=IDENTITY, result='VALIDATED', rollback=False, configurationSha=REVISION,
                         targetPreflightVerified=True, qualifiedMigrationInventoryVerified=True)
        self.data['configuration'] = {name: verifier.sha(self.files['configuration/' + name])
                                      for name in verifier.CONFIG_FILES}
        self.data['runtime'] = {name: verifier.sha(self.files[name]) for name in verifier.RUNTIME_FILES}
        self.write_record()
        self.write_bundle()

    def write_record(self):
        self.record.write_text(json.dumps(self.data))
        self.record_digest = verifier.sha(self.record.read_bytes())

    def write_bundle(self, entries=None):
        with tarfile.open(self.bundle, 'w:gz') as archive:
            for name, payload in self.files.items() if entries is None else entries:
                info = tarfile.TarInfo(name)
                if isinstance(payload, tarfile.TarInfo):
                    archive.addfile(payload)
                else:
                    info.size = len(payload)
                    archive.addfile(info, io.BytesIO(payload))
        self.bundle_digest = verifier.sha(self.bundle.read_bytes())

    def verify(self, **kwargs):
        return verifier.verify(kwargs.get('bundle', self.bundle), kwargs.get('bundle_sha256', self.bundle_digest),
                               kwargs.get('migration_record', self.record),
                               kwargs.get('migration_record_sha256', self.record_digest),
                               kwargs.get('identity', IDENTITY))

    def test_exact_retained_bytes_are_verified_without_modification_extraction_or_execution(self):
        script = b'raise RuntimeError("BUNDLED_SCRIPT_MUST_NOT_RUN")\n'
        self.files['scripts/production_release.py'] = script
        self.data['runtime']['scripts/production_release.py'] = verifier.sha(script)
        self.write_record()
        self.write_bundle()
        before = {p.name: p.read_bytes() for p in self.root.iterdir()}
        with patch.object(subprocess, 'run', side_effect=AssertionError('No subprocess permitted')):
            result = self.verify()
        self.assertEqual(result['configurationSha'], REVISION)
        self.assertEqual(result['release'], IDENTITY)
        self.assertEqual(result['configurationFiles'], len(verifier.CONFIG_FILES))
        self.assertFalse(result['activationAuthorized'])
        self.assertFalse(result['provenanceAuthenticated'])
        self.assertFalse(result['imagesVerified'])
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.root.iterdir()})

    def test_both_independent_digest_anchors_are_required_before_archive_parsing(self):
        for field in ['bundle_sha256', 'migration_record_sha256']:
            for value in ['', 'invalid', '0' * 64]:
                with self.subTest(field=field, value=value), patch.object(verifier.tarfile, 'open') as opened:
                    with self.assertRaises(DeploymentError):
                        self.verify(**{field: value})
                    opened.assert_not_called()

    def test_replacing_only_revision_metadata_fails_the_independently_pinned_record(self):
        original_digest = self.record_digest
        self.data['configurationSha'] = 'b' * 40
        self.write_record()
        with self.assertRaisesRegex(DeploymentError, 'MIGRATION_RECORD_DIGEST_MISMATCH'):
            self.verify(migration_record_sha256=original_digest)

    def test_rehashed_new_checkout_bytes_cannot_use_the_original_migration_hashes(self):
        for name in ['configuration/compose.yaml', 'scripts/release_safety.py']:
            original = self.files[name]
            self.files[name] = b'new checkout content\n'
            self.write_bundle()  # Even knowing a new archive checksum cannot change the migration record.
            with self.subTest(name=name), self.assertRaisesRegex(DeploymentError, 'CONTENT_DIGEST_MISMATCH'):
                self.verify()
            self.files[name] = original

    def test_archive_changed_after_digest_approval_is_rejected(self):
        digest = self.bundle_digest
        self.files['scripts/release_safety.py'] = b'changed'
        self.write_bundle()
        with self.assertRaisesRegex(DeploymentError, 'RETAINED_BUNDLE_DIGEST_MISMATCH'):
            self.verify(bundle_sha256=digest)

    def test_missing_files_duplicates_paths_and_unexpected_secret_files_are_rejected(self):
        entries = list(self.files.items())
        cases = [entries[:-1], entries + [entries[0]], entries + [('../escape', b'private')],
                 entries + [('/tmp/escape', b'private')], entries + [('.env.production', b'private')],
                 entries + [('SHA256SUMS', b'self-supplied checksums are not trusted')]]
        for index, items in enumerate(cases):
            self.write_bundle(items)
            with self.subTest(case=index), self.assertRaises(DeploymentError):
                self.verify()

    def test_links_devices_and_oversized_members_are_rejected(self):
        name = next(iter(self.files))
        for kind in [tarfile.SYMTYPE, tarfile.LNKTYPE, tarfile.CHRTYPE, tarfile.FIFOTYPE]:
            info = tarfile.TarInfo(name)
            info.type, info.linkname = kind, '/private/secret'
            self.write_bundle([(name, info), *list(self.files.items())[1:]])
            with self.subTest(kind=kind), self.assertRaisesRegex(DeploymentError, 'FILE_NOT_ALLOWLISTED'):
                self.verify()
        self.write_bundle()
        with patch.object(verifier, 'MAX_FILE', 1), self.assertRaisesRegex(DeploymentError, 'MEMBER_SIZE_INVALID'):
            self.verify()

    def test_only_a_successful_matching_disabled_worker_migration_record_is_accepted(self):
        original = copy.deepcopy(self.data)
        for field, value in [('id', 'r999-1'), ('result', 'PREPARED_AWAITING_V8_APPROVAL'),
                             ('rollback', True), ('targetPreflightVerified', False),
                             ('qualifiedMigrationInventoryVerified', False), ('configurationSha', 'main')]:
            self.data = {**copy.deepcopy(original), field: value}
            self.write_record()
            with self.subTest(field=field), self.assertRaises(DeploymentError):
                self.verify()
        self.data = copy.deepcopy(original)
        self.data['releaseSafety'] = release('activate-v8')['releaseSafety']
        self.write_record()
        with self.assertRaisesRegex(DeploymentError, 'DISABLED_WORKER_MIGRATION_RECORD_REQUIRED'):
            self.verify()

    def test_incomplete_or_arbitrary_digest_tables_and_migration_inventory_are_rejected(self):
        original = copy.deepcopy(self.data)
        for field in ['configuration', 'runtime']:
            for replacement in [{}, {'../secret': 'a' * 64}, dict.fromkeys(original[field], 'bad-digest')]:
                self.data = {**copy.deepcopy(original), field: replacement}
                self.write_record()
                with self.subTest(field=field, replacement=replacement), self.assertRaises(DeploymentError):
                    self.verify()
        self.data = {**original, 'migrations': []}
        self.write_record()
        with self.assertRaisesRegex(DeploymentError, 'NOT_QUALIFIED_V8'):
            self.verify()

    def test_record_and_archive_symlinks_are_not_followed(self):
        for field, target in [('bundle', self.bundle), ('migration_record', self.record)]:
            link = self.root / (field + '.link')
            link.symlink_to(target)
            with self.subTest(field=field), self.assertRaisesRegex(DeploymentError, 'FILE_INVALID'):
                self.verify(**{field: link})

    def test_real_cli_reports_verification_and_never_leaks_private_json_on_failure(self):
        script = Path(verifier.__file__)
        args = [sys.executable, '-B', str(script), '--bundle', str(self.bundle),
                '--bundle-sha256', self.bundle_digest, '--migration-record', str(self.record),
                '--migration-record-sha256', self.record_digest, '--release-id', IDENTITY]
        result = subprocess.run(args, text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['configurationSha'], REVISION)
        self.assertEqual(result.stderr, '')
        private = b'{"PRIVATE-MARKER": "never print"}\n'
        self.record.write_bytes(private)
        args[args.index('--migration-record-sha256') + 1] = verifier.sha(private)
        result = subprocess.run(args, text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stderr, 'SUCCESSFUL_MIGRATION_RECORD_REQUIRED\n')
        self.assertNotIn('PRIVATE-MARKER', result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
