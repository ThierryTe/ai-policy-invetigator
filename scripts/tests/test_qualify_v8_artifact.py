import io
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import qualify_v8_artifact as qualification


class V8ArtifactTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.jar = Path(self.temp.name) / 'synthetic.jar'
        self.baseline = qualification.ROOT / 'docs/verification/v7-migrations.sha256'

    def archive(self, omit=None, tamper=None):
        with zipfile.ZipFile(self.jar, 'w') as archive:
            for source in (qualification.ROOT / 'src/main/resources/db/migration').glob('V*.sql'):
                if source.name.startswith(omit or 'NONE'):
                    continue
                body = source.read_bytes()
                if source.name.startswith(tamper or 'NONE'):
                    body += b'\n-- synthetic drift\n'
                archive.writestr('BOOT-INF/classes/db/migration/' + source.name, body)

    def test_eight_migrations_match_sources_and_historical_baseline(self):
        self.archive()
        self.assertEqual(qualification.audit(self.jar, self.baseline)['artifact_verdict'], 'PASS')

    def test_missing_v8_is_rejected(self):
        self.archive(omit='V8__')
        with self.assertRaisesRegex(ValueError, 'EXACTLY_EIGHT'):
            qualification.audit(self.jar, self.baseline)

    def test_changed_jar_bytes_are_rejected(self):
        self.archive(tamper='V7__')
        with self.assertRaisesRegex(ValueError, 'JAR_SOURCE_BYTES'):
            qualification.audit(self.jar, self.baseline)

    def test_historical_drift_is_rejected(self):
        self.archive()
        baseline = Path(self.temp.name) / 'baseline.sha256'
        text = self.baseline.read_text()
        baseline.write_text('0' * 64 + text[64:])
        with self.assertRaisesRegex(ValueError, 'V1_V7_CHANGED'):
            qualification.audit(self.jar, baseline)

    def test_incomplete_baseline_is_rejected(self):
        self.archive()
        baseline = Path(self.temp.name) / 'baseline.sha256'
        baseline.write_text('\n'.join(self.baseline.read_text().splitlines()[:-1]) + '\n')
        with self.assertRaisesRegex(ValueError, 'BASELINE_INCOMPLETE'):
            qualification.audit(self.jar, baseline)


if __name__ == '__main__':
    unittest.main()
