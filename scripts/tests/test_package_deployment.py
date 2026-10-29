"""The deploy bundle must contain only the fixed public-file allowlist."""
import hashlib
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import package_deployment as bundle


class PackageDeploymentTest(unittest.TestCase):
    def test_archive_has_exact_allowlist_and_portable_checksum(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'source'; root.mkdir()
            for name in bundle.FILES:
                path = root / name; path.parent.mkdir(parents=True, exist_ok=True); path.write_text('# public fixture\n')
            (root / '.env').write_text('PRIVATE_SENTINEL=never-export\n')
            (root / '.ci/frontend').mkdir(parents=True)
            (root / '.ci/frontend/compose.yaml').write_text('# public frontend contract\n')
            front = Path(directory) / 'front'; front.mkdir(); (front / 'compose.yaml').write_text('# public frontend contract\n')
            release = bundle.ROOT / 'deploy/release.images.json'; output = Path(directory) / 'release.tar.gz'
            bundle.package(front, release, output, root=root)
            with tarfile.open(output) as archive:
                self.assertEqual(set(archive.getnames()), set(bundle.FILES) | {'frontend/compose.yaml', 'deploy/release.images.json'})
                self.assertFalse(any(b'never-export' in archive.extractfile(m).read() for m in archive.getmembers()))
            digest = hashlib.sha256(output.read_bytes()).hexdigest()
            self.assertEqual(Path(str(output) + '.sha256').read_text(), digest + '  release.tar.gz\n')
            with self.assertRaises(bundle.DeploymentError): bundle.package(front, release, output, root=root)

    def test_changed_frontend_contract_is_not_silently_packaged(self):
        with tempfile.TemporaryDirectory() as directory:
            front = Path(directory); (front / 'compose.yaml').write_text('changed contract\n')
            with self.assertRaises(bundle.DeploymentError):
                bundle.package(front, bundle.ROOT / 'deploy/release.images.json', front / 'output.tar.gz')


if __name__ == '__main__':
    unittest.main()
