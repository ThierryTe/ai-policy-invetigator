"""Guard real resolved Compose topology; never creates networks or contacts the daemon."""
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import verify_production_compose as config


class ProductionComposeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        front = Path(os.environ.get('POLICY_FRONTEND_DIRECTORY', config.ROOT.parent / 'ai-policy-investigator-frontend'))
        if not shutil.which('docker') or not (front / 'compose.yaml').is_file():
            raise unittest.SkipTest('Requires Compose CLI and the separate frontend checkout; no Docker Engine needed.')
        # CI uses the reviewed contract; local runs also catch drift in the real frontend checkout.
        if (config.ROOT / '.ci/frontend/compose.yaml').read_bytes() != (front / 'compose.yaml').read_bytes():
            raise AssertionError('Frontend Compose contract changed; review and update .ci/frontend/compose.yaml.')
        cls.backend = config.resolved('ai-policy-investigator', config.ROOT,
                                      [config.ROOT / 'compose.yaml', config.ROOT / 'compose.production.yaml'])
        cls.frontend = config.resolved('ai-policy-investigator-ui', front,
                                       [front / 'compose.yaml', config.ROOT / 'deploy/frontend/compose.production.yaml'])

    def setUp(self):
        self.b = copy.deepcopy(self.backend)
        self.f = copy.deepcopy(self.frontend)

    def rejects(self):
        with self.assertRaises(ValueError):
            config.validate(self.b, self.f)

    def test_resolved_topology_is_secure(self):
        self.assertEqual(config.validate(self.b, self.f)['result'], 'PASS')

    def test_completion_budget_default_and_override_reach_production_backend(self):
        for limit in [None, '8192']:
            with self.subTest(limit=limit), patch.dict(os.environ):
                os.environ.pop('META_MAX_COMPLETION_TOKENS', None)
                if limit is not None:
                    os.environ['META_MAX_COMPLETION_TOKENS'] = limit
                backend = config.resolved('ai-policy-investigator', config.ROOT,
                                          [config.ROOT / 'compose.yaml', config.ROOT / 'compose.production.yaml'])
                self.assertEqual(backend['services']['backend']['environment']['META_MAX_COMPLETION_TOKENS'],
                                 limit or '4096')
                self.assertEqual(config.validate(backend, self.f)['result'], 'PASS')

    def test_completion_budget_survives_image_only_release_overlay(self):
        with patch.dict(os.environ, {
            'META_MAX_COMPLETION_TOKENS': '8192',
            'BACKEND_IMAGE_REF': 'synthetic-backend:local',
            'MODEL_INIT_IMAGE_REF': 'synthetic-model-init:local',
        }):
            backend = config.resolved('ai-policy-investigator', config.ROOT,
                                      [config.ROOT / 'compose.yaml', config.ROOT / 'compose.production.yaml',
                                       config.ROOT / 'deploy/backend/compose.ghcr.yaml'])
        self.assertEqual(backend['services']['backend']['environment']['META_MAX_COMPLETION_TOKENS'], '8192')
        self.assertEqual(config.validate(backend, self.f)['result'], 'PASS')

    def test_completion_budget_from_runtime_env_file_survives_automated_release(self):
        # The production controller clears inherited variables and uses --env-file.
        # Exercise that path with an isolated non-secret fixture and all backend overlays.
        with tempfile.TemporaryDirectory() as directory:
            env_file = Path(directory) / 'runtime.env'
            env_file.write_text('META_MAX_COMPLETION_TOKENS=8192\n')
            env_file.chmod(0o600)
            env = {'PATH': os.environ['PATH'],
                   **{key: 'synthetic-configuration-validation-only' for key in
                      ['POSTGRES_ADMIN_PASSWORD', 'APP_DB_PASSWORD', 'OWNER_DB_PASSWORD', 'JWT_SECRET', 'MODEL_API_KEY']},
                   'BACKEND_IMAGE_REF': 'synthetic-backend:local',
                   'MODEL_INIT_IMAGE_REF': 'synthetic-model-init:local',
                   'POSTGRES_IMAGE_REF': 'synthetic-postgres:local'}
            args = ['docker', 'compose', '--project-directory', str(config.ROOT),
                    '--env-file', str(env_file), '-p', 'ai-policy-investigator']
            for file in ['compose.yaml', 'compose.production.yaml', 'deploy/backend/compose.ghcr.yaml',
                         'deploy/automation/compose.yaml']:
                args += ['-f', str(config.ROOT / file)]
            result = subprocess.run(args + ['--profile', 'app', 'config', '--format', 'json'],
                                    capture_output=True, text=True, env=env, timeout=30)
            self.assertEqual(result.returncode, 0, 'Synthetic release Compose configuration failed')
            backend = json.loads(result.stdout)
        self.assertEqual(backend['services']['backend']['environment']['META_MAX_COMPLETION_TOKENS'], '8192')
        self.assertEqual(config.validate(backend, self.f)['result'], 'PASS')

    def test_rejects_any_host_port(self):
        for services, key in [(self.b['services'], 'postgres'), (self.b['services'], 'backend'), (self.f['services'], 'frontend')]:
            services[key]['ports'] = [{'target': 8080, 'published': '8080'}]
            self.rejects(); services[key]['ports'] = []

    def test_rejects_backend_or_database_on_proxy(self):
        self.b['networks']['default']['name'] = config.PROXY
        self.rejects()

    def test_rejects_non_internal_application_or_database_network(self):
        for key in ['application', 'database']:
            self.b['networks'][key]['internal'] = False
            self.rejects(); self.b['networks'][key]['internal'] = True

    def test_rejects_missing_unique_alias_and_wrong_backend(self):
        self.f['services']['frontend']['networks']['proxy']['aliases'] = []
        self.rejects()
        self.f = copy.deepcopy(self.frontend)
        for upstream in ['http://unrelated-service:8080', 'http://backend:8080']:
            self.f['services']['frontend']['environment']['BACKEND_UPSTREAM'] = upstream
            self.rejects()

    def test_rejects_frontend_secrets(self):
        self.f['services']['frontend']['environment']['MODEL_API_KEY'] = 'synthetic-test-marker'
        self.rejects()

    def test_rejects_changed_persistence_or_writable_models(self):
        self.b['volumes']['investigator_data']['name'] = 'wrong-volume'
        self.rejects()
        self.b = copy.deepcopy(self.backend)
        next(v for v in self.b['services']['backend']['volumes'] if v['target'] == '/models')['read_only'] = False
        self.rejects()


if __name__ == '__main__':
    unittest.main()
