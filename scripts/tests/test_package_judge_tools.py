import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
import package_judge_tools as bundle
import provision_judge as judge


class JudgePackageTest(unittest.TestCase):
    def test_package_contains_only_public_tools_metadata_and_guide(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'judge-tools.tar.gz'
            self.assertEqual(bundle.package(output), 5)
            self.assertEqual(output.with_name(output.name + '.sha256').read_text(),
                             hashlib.sha256(output.read_bytes()).hexdigest() + '  ' + output.name + '\n')
            with tarfile.open(output) as archive:
                names = set(archive.getnames())
                self.assertEqual(names, {*bundle.FILES, judge.MIGRATION_INVENTORY, 'FILES.sha256'})
                for entry in archive.getmembers():
                    self.assertTrue(entry.isfile())
                    self.assertEqual(entry.mode, 0o644)
                    self.assertEqual(entry.uid, 0)
                    self.assertNotIn('.env', entry.name)
                    self.assertNotIn('compose', entry.name)
                    self.assertNotIn('V7__', entry.name)
                for line in archive.extractfile('FILES.sha256').read().decode().splitlines():
                    digest, name = line.split('  ', 1)
                    self.assertEqual(hashlib.sha256(archive.extractfile(name).read()).hexdigest(), digest)
                self.assertEqual(json.load(archive.extractfile(judge.MIGRATION_INVENTORY)), judge.expected_migrations())
                root = Path(directory) / 'tools'
                archive.extractall(root, filter='data')
            self.assertEqual(judge.expected_migrations(root), judge.expected_migrations())
            # Isolated packaged module: no source tree, private config or extra deployment dependencies.
            spec = importlib.util.spec_from_file_location('packaged_judge', root / 'scripts/provision_judge.py')
            module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
            self.assertEqual(module.expected_migrations(), judge.expected_migrations())

    def test_existing_outputs_and_symlinks_are_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'tools.tar.gz'
            output.write_bytes(b'existing')
            with self.assertRaises(judge.JudgeError): bundle.package(output)
            self.assertEqual(output.read_bytes(), b'existing')
            link = Path(directory) / 'link.tar.gz'; link.symlink_to(output)
            with self.assertRaises(judge.JudgeError): bundle.package(link)

    def test_missing_sources_and_invalid_or_symlinked_inventory_are_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / 'root'; root.mkdir()
            with self.assertRaises(judge.JudgeError): bundle.package(Path(directory) / 'tools.tar.gz', root)
            inventory = root / judge.MIGRATION_INVENTORY
            inventory.parent.mkdir(parents=True)
            for rows in ([], [{'version': '7', 'script': 'wrong.sql', 'checksum': 0}], judge.expected_migrations() * 2):
                inventory.write_text(json.dumps(rows))
                with self.assertRaises(judge.JudgeError): judge.expected_migrations(root)
            inventory.unlink(); inventory.symlink_to(root / 'missing')
            with self.assertRaises(judge.JudgeError): judge.expected_migrations(root)


if __name__ == '__main__':
    unittest.main()
