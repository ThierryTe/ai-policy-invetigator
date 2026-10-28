"""Demo setup guards, secret handling and deterministic fixtures; no real DB/provider."""
import base64
import contextlib
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import setup_demo as demo


class DemoSetupTest(unittest.TestCase):
    def env(self):
        return {'APP_ENVIRONMENT': 'local', 'DEMO_USER_ENABLED': 'true',
                'DEMO_PASSWORD': 'synthetic-fixture-password-only'}

    def test_default_disabled_and_production_refused_before_subprocess(self):
        for env in ({}, {**self.env(), 'DEMO_USER_ENABLED': 'false'},
                    {**self.env(), 'APP_ENVIRONMENT': 'production'}):
            with patch.object(demo.subprocess, 'run') as run:
                with self.assertRaisesRegex(demo.DemoSetupError, 'DEMO_SEED_DISABLED'):
                    demo.setup(env)
                run.assert_not_called()

    def test_missing_short_placeholder_multibyte_overflow_and_control_passwords_fail(self):
        for password in ('', 'short', 'replace-with-private-password', 'é' * 37, 'x' * 16 + '\n'):
            with self.assertRaisesRegex(demo.DemoSetupError, 'DEMO_PASSWORD_REQUIRED'):
                demo.validate_environment({**self.env(), 'DEMO_PASSWORD': password})

    def test_password_is_copy_data_not_sql_literal(self):
        password = "synthetic'\\password-only"
        sql = demo.sql_input(password)
        self.assertNotIn(password, sql)
        self.assertIn('COPY pg_temp.demo_seed_input FROM STDIN;', sql)
        line = sql.split('COPY pg_temp.demo_seed_input FROM STDIN;\n', 1)[1].splitlines()[0]
        self.assertEqual(base64.b64decode(line.split('\t')[2]).decode(), password)
        self.assertNotIn(base64.b64encode(password.encode()).decode(), sql.split('DO $$', 1)[1])

    def test_docker_failure_does_not_expose_subprocess_output_or_secret(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); (root / '.env').write_text('# synthetic only\n')
            (root / 'scripts').mkdir()
            (root / 'scripts/seed_demo.sql').write_text((demo.ROOT / 'scripts/seed_demo.sql').read_text())
            secret = self.env()['DEMO_PASSWORD']
            with patch.object(demo, 'ROOT', root), patch.dict(demo.os.environ, self.env(), clear=True), \
                 patch.object(demo.subprocess, 'run', return_value=SimpleNamespace(returncode=1, stdout=secret, stderr=secret)) as run:
                output = io.StringIO()
                with contextlib.redirect_stderr(output):
                    self.assertEqual(demo.main(), 2)
                self.assertNotIn(secret, output.getvalue())
                self.assertIn('DEMO_SEED_FAILED', output.getvalue())
                self.assertNotIn(secret, repr(run.call_args.args))
                self.assertTrue(run.call_args.kwargs['capture_output'])
                self.assertIn('-X', run.call_args.args[0])

    def test_exports_existing_synthetic_golden_pdfs_reproducibly(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            self.assertEqual(demo.write_fixtures(output), 4)
            original = {p.name: p.read_bytes() for p in output.iterdir()}
            self.assertTrue(all(data.startswith(b'%PDF-') for data in original.values()))
            demo.write_fixtures(output)
            self.assertEqual({p.name: p.read_bytes() for p in output.iterdir()}, original)


if __name__ == '__main__':
    unittest.main()
