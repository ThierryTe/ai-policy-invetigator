"""Operator-only bootstrap guards and secret transport; no real deployment."""
import base64
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import provision_initial_admin as bootstrap


class InitialAdminTest(unittest.TestCase):
    def env(self):
        return {'INVESTIGATOR_INITIAL_ADMIN_ENABLED': 'true',
                'INVESTIGATOR_INITIAL_EMAIL': 'Admin@test.invalid',
                'INVESTIGATOR_INITIAL_PASSWORD': "synthetic'\\bootstrap-test-password",
                'INVESTIGATOR_INITIAL_ORGANIZATION': 'Synthetic operations test',
                'INVESTIGATOR_INITIAL_DEPARTMENT': 'Policy analysis'}

    def test_disabled_before_invoking_docker(self):
        with patch.object(bootstrap.subprocess, 'run') as run:
            with self.assertRaisesRegex(bootstrap.BootstrapError, 'INITIAL_ADMIN_DISABLED'):
                bootstrap.provision(Path('/missing'), {})
            run.assert_not_called()

    def test_invalid_password_and_metadata_refused(self):
        for password in ['', 'short', 'replace-with-a-production-password', 'é' * 37, 'x' * 16 + '\n', '\ud800' * 20]:
            with self.assertRaises(bootstrap.BootstrapError):
                bootstrap.input_data({**self.env(), 'INVESTIGATOR_INITIAL_PASSWORD': password})
        for key, value in [('INVESTIGATOR_INITIAL_EMAIL', 'invalid'), ('INVESTIGATOR_INITIAL_ORGANIZATION', ''),
                           ('INVESTIGATOR_INITIAL_DEPARTMENT', 'bad\nname')]:
            with self.assertRaises(bootstrap.BootstrapError):
                bootstrap.input_data({**self.env(), key: value})

    def test_secret_is_copy_data_not_sql_literal(self):
        content = bootstrap.sql_input(self.env())
        self.assertNotIn(self.env()['INVESTIGATOR_INITIAL_PASSWORD'], content)
        line = content.split('COPY pg_temp.initial_admin_input FROM STDIN;\n', 1)[1].splitlines()[0]
        self.assertEqual(json.loads(base64.b64decode(line))['password'], self.env()['INVESTIGATOR_INITIAL_PASSWORD'])
        self.assertNotIn(line, content.split('DO $$', 1)[1])

    def test_subprocess_uses_only_stdin_and_redacts_diagnostics(self):
        with tempfile.TemporaryDirectory() as d:
            env_file = Path(d) / 'private.env'; env_file.write_text('# synthetic test only\n')
            env_file.chmod(0o600)
            for outcome in [SimpleNamespace(returncode=1, stdout=self.env()['INVESTIGATOR_INITIAL_PASSWORD'], stderr='private'),
                            subprocess.TimeoutExpired('synthetic', 45)]:
                with patch.object(bootstrap.subprocess, 'run', **({'side_effect': outcome} if isinstance(outcome, Exception) else {'return_value': outcome})) as run:
                    with self.assertRaises(bootstrap.BootstrapError) as error:
                        bootstrap.provision(env_file, self.env())
                    self.assertNotIn(self.env()['INVESTIGATOR_INITIAL_PASSWORD'], str(error.exception))
                    self.assertNotIn(self.env()['INVESTIGATOR_INITIAL_PASSWORD'], repr(run.call_args.args))
                    self.assertFalse(any(k.startswith('INVESTIGATOR_INITIAL_') for k in run.call_args.kwargs['env']))
                    self.assertTrue(run.call_args.kwargs['capture_output'])
                    self.assertIn('exec', run.call_args.args[0])
                    self.assertNotIn('up', run.call_args.args[0])


if __name__ == '__main__':
    unittest.main()
