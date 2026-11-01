"""Synthetic contracts and failure injection. Never connects to a server or starts containers."""
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ci_images as ci
import simple_deploy as deploy
import simple_ssh as ssh

ROOT = Path(__file__).resolve().parents[2]
SHA = 'a' * 40
PROJECT_NETWORK = 'existing-application'
IMAGES = {key: package + '@sha256:' + 'b' * 64 for key, package in ci.PACKAGES.items()}


def manifest():
    return {'repository': ci.REPOSITORY, 'run_id': 30, 'backend_sha': SHA, 'frontend_sha': 'c' * 40, 'images': IMAGES.copy()}


def run_fixture(**changes):
    data = {'id': 30, 'run_number': 10, 'run_attempt': 1, 'path': '.github/workflows/ci.yml',
            'head_repository': {'full_name': ci.REPOSITORY}, 'head_branch': 'main', 'event': 'push',
            'status': 'completed', 'conclusion': 'success', 'head_sha': SHA}
    return {**data, **changes}


class ImageSelectionTest(unittest.TestCase):
    def test_selects_newest_successful_ci_run_not_newest_failed_run(self):
        runs = [run_fixture(id=10, run_number=1), run_fixture(id=40, run_number=11, conclusion='failure'), run_fixture()]
        self.assertEqual(ci.select(runs)['id'], 30)

    def test_rejects_pr_fork_nonmain_incomplete_wrong_workflow_and_failed_runs(self):
        for changes in [{'event': 'pull_request'}, {'head_branch': 'develop'}, {'status': 'in_progress'},
                        {'head_repository': {'full_name': 'other/repo'}}, {'path': '.github/workflows/verify.yml'},
                        {'conclusion': 'cancelled'}, {'head_sha': 'main'}]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                ci.select([run_fixture(**changes)])

    def test_rerunning_old_commit_does_not_outrank_a_newer_successful_run(self):
        self.assertEqual(ci.select([run_fixture(id=99, run_number=1, run_attempt=5), run_fixture()])['id'], 30)

    def test_accepts_coordinated_ci_requested_by_frontend_main_push(self):
        self.assertEqual(ci.select([run_fixture(event='repository_dispatch')])['id'], 30)

    def test_valid_digest_pair_and_source_provenance(self):
        self.assertEqual(ci.validate(manifest(), 30, SHA)['images'], IMAGES)

    def test_rejects_tags_foreign_registries_missing_images_and_shell_input(self):
        for ref in ['latest', ci.PACKAGES['backend'] + ':sha-' + SHA,
                    'evil.example/backend@sha256:' + 'b' * 64, IMAGES['backend'] + '\n--privileged']:
            data = manifest()
            data['images']['backend'] = ref
            with self.subTest(ref=ref), self.assertRaises(ValueError):
                ci.validate(data)
        data = manifest()
        del data['images']['frontend']
        with self.assertRaises(ValueError):
            ci.validate(data)

    def test_rejects_artifact_run_or_revision_mismatch(self):
        for run, sha in [(31, SHA), (30, 'd' * 40)]:
            with self.assertRaises(ValueError):
                ci.validate(manifest(), run, sha)

    def test_missing_latest_artifact_fails_without_selecting_an_older_run(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'GITHUB_OUTPUT': directory + '/output'}), \
                patch.object(ci, 'api', side_effect=[{'workflow_runs': [run_fixture()]}, {'artifacts': []}]), \
                patch.object(sys, 'argv', ['ci_images.py', 'select']), self.assertRaises(SystemExit):
            ci.main()


class SshValidationTest(unittest.TestCase):
    def setUp(self):
        import base64
        blob = b'\x00\x00\x00\x0bssh-ed25519\x00\x00\x00\x20' + b'x' * 32
        self.env = {'VPS_HOST': 'vps.example.org', 'VPS_USERNAME': 'deployer', 'VPS_PORT': '22',
                    'VPS_DEPLOY_PATH': ssh.BASE, 'VPS_SSH_KEY': 'synthetic-private-key',
                    'VPS_HOST_KEY': 'ssh-ed25519 ' + base64.b64encode(blob).decode()}

    def test_accepts_pinned_host_with_default_port(self):
        self.env['VPS_PORT'] = ''
        self.assertEqual(ssh.settings(self.env)[:3], ('vps.example.org', 'deployer', '22'))

    def test_rejects_missing_or_malformed_secrets_before_network_access(self):
        for key, value in [('VPS_HOST', '-oProxyCommand=bad'), ('VPS_USERNAME', 'root;bad'), ('VPS_PORT', '0'),
                           ('VPS_DEPLOY_PATH', '/opt/another-project'), ('VPS_HOST_KEY', ''),
                           ('VPS_HOST_KEY', 'ssh-ed25519 eA=='), ('VPS_SSH_KEY', '')]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                ssh.settings({**self.env, key: value})

    def test_remote_error_does_not_expose_stderr_or_secret_values(self):
        result = MagicMock(returncode=1, stderr='synthetic-secret-value\nDEPLOY_FAILED_ROLLBACK_SUCCEEDED_DATABASE_UNCHANGED\n')
        with patch.object(ssh.subprocess, 'run', return_value=result), self.assertRaisesRegex(ValueError, '^DEPLOY_FAILED_ROLLBACK_SUCCEEDED_DATABASE_UNCHANGED$'):
            ssh.execute(['ssh'])


class DeploymentTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.bundle = self.root / 'bundle'
        self.bundle.mkdir()
        (self.bundle / 'images.json').write_text(json.dumps(manifest()))
        self.state = self.root / 'state'
        self.state.mkdir()
        self.env_file = self.root / 'production.env'
        self.env_file.write_text('APP_WORKER_ENABLED=true\n')
        self.images = {**IMAGES, 'postgres': 'sha256:' + 'd' * 64}
        self.previous = {'bundle': str(self.bundle), 'env_file': str(self.env_file),
                         'images': self.images, 'history': [{'version': '8', 'success': True}]}

    def test_no_application_update_if_pull_fails(self):
        with patch.object(deploy, 'container', return_value={'Image': self.images['postgres']}), \
                patch.object(deploy, 'check_topology', return_value=(['backend-compose'], ['frontend-compose'], {})), \
                patch.object(deploy, 'public_check'), patch.object(deploy, 'run', side_effect=deploy.DeployError('PULL_FAILED')), \
                patch.object(deploy, 'snapshot') as snapshot, self.assertRaisesRegex(deploy.DeployError, 'PULL_FAILED'):
            deploy.deploy(self.bundle, self.env_file, self.state)
        snapshot.assert_not_called()

    def attempt(self, update_error=None, rollback_error=None, changed_history=False):
        calls = []
        def command(args, *unused, **kwargs):
            calls.append(args)
            if update_error and args[0] == 'backend-compose':
                raise deploy.DeployError(update_error)
            return ''
        with patch.object(deploy, 'container', return_value={'Image': self.images['postgres']}), \
                patch.object(deploy, 'check_topology', return_value=(['backend-compose'], ['frontend-compose'], {})), \
                patch.object(deploy, 'public_check'), patch.object(deploy, 'snapshot', return_value=self.previous), \
                patch.object(deploy, 'run', side_effect=command), patch.object(deploy, 'verify'), \
                patch.object(deploy, 'history', return_value=[] if changed_history else self.previous['history']), \
                patch.object(deploy, 'restore', side_effect=rollback_error) as restore:
            try:
                deploy.deploy(self.bundle, self.env_file, self.state)
            except deploy.DeployError as error:
                return str(error), calls, restore.call_count
        return 'OK', calls, restore.call_count

    def test_success_updates_only_application_services_and_records_previous(self):
        result, calls, rollbacks = self.attempt()
        self.assertEqual(result, 'OK')
        self.assertEqual(rollbacks, 0)
        self.assertTrue((self.state / 'current.json').is_file())
        self.assertTrue((self.state / 'previous.json').is_file())
        updates = [call for call in calls if 'up' in call]
        self.assertEqual([call[-1] for call in updates], ['backend', 'frontend'])
        self.assertTrue(all('--no-deps' in c and '--no-build' in c and '--wait' in c for c in updates))
        self.assertEqual(len([c for c in calls if c[:2] == ['docker', 'pull']]), 2)

    def test_failed_update_restores_previous_and_leaves_failure_status(self):
        result, _, rollbacks = self.attempt(update_error='HEALTH_TIMEOUT')
        self.assertEqual(result, 'DEPLOY_FAILED_ROLLBACK_SUCCEEDED_DATABASE_UNCHANGED')
        self.assertEqual(rollbacks, 1)
        self.assertFalse((self.state / 'current.json').exists())

    def test_failed_rollback_blocks_further_automatic_changes(self):
        result, _, _ = self.attempt(update_error='HEALTH_TIMEOUT', rollback_error=deploy.DeployError('SCHEMA_CHANGED_ROLLBACK_BLOCKED'))
        self.assertIn('ROLLBACK_FAILED_OR_BLOCKED', result)
        self.assertTrue((self.state / 'blocked.json').is_file())

    def test_unexpected_schema_change_is_a_failed_deployment(self):
        result, _, rollbacks = self.attempt(changed_history=True, rollback_error=deploy.DeployError('SCHEMA_CHANGED_ROLLBACK_BLOCKED'))
        self.assertIn('ROLLBACK_FAILED_OR_BLOCKED', result)
        self.assertEqual(rollbacks, 1)

    def test_restore_stops_before_compose_when_history_changed_or_unreadable(self):
        for effect in [[], deploy.DeployError('DATABASE_UNAVAILABLE')]:
            with patch.object(deploy, 'history', **({'side_effect': effect} if isinstance(effect, Exception) else {'return_value': effect})), \
                    patch.object(deploy, 'run') as command, self.assertRaises(deploy.DeployError):
                deploy.restore(self.previous)
            command.assert_not_called()

    def test_restore_health_failure_is_not_reported_as_success(self):
        with patch.object(deploy, 'history', return_value=self.previous['history']), \
                patch.object(deploy, 'run'), patch.object(deploy, 'verify', side_effect=deploy.DeployError('CONTAINER_UNHEALTHY')), \
                self.assertRaisesRegex(deploy.DeployError, 'CONTAINER_UNHEALTHY'):
            deploy.restore(self.previous)

    def test_rejects_running_but_unhealthy_or_stopped_container(self):
        for state in [{'Running': True, 'Health': {'Status': 'unhealthy'}}, {'Running': False, 'Health': {'Status': 'healthy'}}, {'Running': True}]:
            with self.assertRaises(deploy.DeployError):
                deploy.healthy({'State': state})

    def test_verify_rejects_unexpected_running_image(self):
        row = {'Id': 'test-id', 'Image': 'wrong', 'State': {'Running': True, 'Health': {'Status': 'healthy'}}}
        with patch.object(deploy, 'container', return_value=row), \
                patch.object(deploy, 'run', return_value='[{"Id":"expected"}]'), self.assertRaisesRegex(deploy.DeployError, 'RUNNING_IMAGE_MISMATCH'):
            deploy.verify(self.images)

    def test_verify_requires_successful_backend_and_worker_health_body(self):
        row = {'Id': 'test-id', 'Image': 'expected', 'State': {'Running': True, 'Health': {'Status': 'healthy'}}}
        with patch.object(deploy, 'container', return_value=row), \
                patch.object(deploy, 'run', side_effect=['[{"Id":"expected"}]', '[{"Id":"expected"}]', '{"status":"DOWN"}']), \
                self.assertRaisesRegex(deploy.DeployError, 'BACKEND_OR_WORKERS_NOT_READY'):
            deploy.verify(self.images)

    def test_snapshots_preserve_actual_flags_literal_dollars_and_private_permissions(self):
        row = {'Image': 'sha256:' + 'd' * 64, 'State': {'Running': True, 'Health': {'Status': 'healthy'}},
               'Config': {'Env': ['APP_WORKER_ENABLED=false', 'MODEL_API_KEY=synthetic-${literal}'],
                          'Healthcheck': {'Test': ['CMD', 'wget', 'test'], 'Interval': 1000000000, 'Retries': 3}}}
        with patch.object(deploy, 'container', return_value=row), patch.object(deploy, 'history', return_value=self.previous['history']), \
                patch.object(deploy, 'run', return_value='[{"RepoDigests":[]}]'):
            previous = deploy.snapshot(self.bundle, self.env_file, self.state)
        runtime = json.loads((Path(previous['bundle']) / 'runtime.json').read_text())['services']['backend']
        self.assertEqual(runtime['environment']['APP_WORKER_ENABLED'], 'false')
        self.assertEqual(runtime['environment']['MODEL_API_KEY'], 'synthetic-$${literal}')
        self.assertEqual(runtime['environment']['SPRING_FLYWAY_ENABLED'], 'false')
        self.assertEqual(runtime['healthcheck']['interval'], '1000000000ns')
        self.assertEqual(Path(previous['env_file']).stat().st_mode & 0o777, 0o600)

    def test_concurrent_deployment_is_rejected(self):
        with deploy.deployment_lock(self.state), self.assertRaisesRegex(deploy.DeployError, 'ANOTHER_DEPLOYMENT_IS_RUNNING'):
            with deploy.deployment_lock(self.state):
                pass

    def test_manual_rollback_failure_records_blocked_state(self):
        state = self.root / 'simple-deploy'
        incoming = state / 'incoming' / '1-1'
        incoming.mkdir(parents=True)
        env_file = self.root / '.env.production'
        env_file.write_text('synthetic-setting=value\n')
        env_file.chmod(0o600)
        deploy.save(state / 'previous.json', self.previous)
        with patch.object(deploy, 'BASE', self.root), patch.object(sys, 'argv', ['simple_deploy.py', 'rollback', '--bundle', str(incoming)]), \
                patch.object(deploy, 'restore', side_effect=deploy.DeployError('SCHEMA_CHANGED_ROLLBACK_BLOCKED')):
            self.assertEqual(deploy.main(), 1)
        self.assertTrue((state / 'blocked.json').is_file())


class TopologyValidationTest(unittest.TestCase):
    def setUp(self):
        self.back = {'services': {'backend': {'environment': {'APP_WORKER_ENABLED': 'true', 'APP_INVESTIGATION_WORKER_ENABLED': 'true',
                                                            'MODEL_API_KEY': 'synthetic-key'}, 'networks': {'application': {}, 'database': {}}},
                                  'postgres': {'networks': {'database': {}}, 'volumes': [{'type': 'volume', 'source': 'data', 'target': '/var/lib/postgresql/data'}]}},
                     'networks': {'application': {'name': PROJECT_NETWORK}, 'database': {'name': 'private-db'}},
                     'volumes': {'data': {'name': 'existing-db-volume'}}}
        self.front = {'services': {'frontend': {'networks': {'application': {}, 'proxy': {}}}},
                      'networks': {'application': {'name': PROJECT_NETWORK}, 'proxy': {'name': 'existing-proxy'}}}
        self.rows = {}
        for service, networks in [('backend', [PROJECT_NETWORK, 'private-db']), ('postgres', ['private-db']), ('frontend', [PROJECT_NETWORK, 'existing-proxy'])]:
            self.rows[service] = {'State': {'Running': True, 'Health': {'Status': 'healthy'}}, 'HostConfig': {'PortBindings': {}},
                                  'NetworkSettings': {'Networks': {n: {} for n in networks}}, 'Mounts': []}
        self.rows['postgres']['Mounts'] = [{'Type': 'volume', 'Name': 'existing-db-volume', 'Destination': '/var/lib/postgresql/data', 'RW': True}]

    def check(self):
        with patch.object(deploy, 'commands', return_value=(['back'], ['front'], {})), \
                patch.object(deploy, 'run', side_effect=[json.dumps(self.back), json.dumps(self.front)]), \
                patch.object(deploy, 'container', side_effect=lambda project, service: self.rows[service]):
            return deploy.check_topology(Path('/synthetic'), Path('/synthetic.env'), IMAGES)

    def test_current_topology_with_explicit_workers_is_accepted(self):
        self.assertEqual(self.check()[:2], (['back'], ['front']))

    def test_workers_must_be_explicitly_enabled_and_key_configured(self):
        environment = self.back['services']['backend']['environment']
        for key, value in [('APP_WORKER_ENABLED', 'false'), ('APP_INVESTIGATION_WORKER_ENABLED', ''), ('MODEL_API_KEY', '')]:
            original = environment[key]
            environment[key] = value
            with self.subTest(key=key), self.assertRaises(deploy.DeployError):
                self.check()
            environment[key] = original

    def test_network_volume_or_public_port_drift_stops_before_updates(self):
        for change in ['network', 'volume', 'port']:
            with self.subTest(change=change):
                self.setUp()
                if change == 'network':
                    self.rows['backend']['NetworkSettings']['Networks']['unrelated-network'] = {}
                elif change == 'volume':
                    self.rows['postgres']['Mounts'][0]['Name'] = 'empty-replacement'
                else:
                    self.rows['backend']['HostConfig']['PortBindings'] = {'8080/tcp': [{'HostPort': '8080'}]}
                with self.assertRaises(deploy.DeployError):
                    self.check()


class PublicHealthTest(unittest.TestCase):
    def test_checks_angular_health_and_authenticated_api_without_redirects(self):
        responses = []
        for code, body in [(200, b'<html><app-root></app-root></html>'), (200, b'ok\n')]:
            response = MagicMock()
            response.__enter__.return_value = MagicMock(status=code, read=MagicMock(return_value=body))
            responses.append(response)
        import urllib.error
        responses.append(urllib.error.HTTPError('test', 401, 'Unauthorized', {}, None))
        opener = MagicMock()
        opener.open.side_effect = responses
        with patch.object(deploy.urllib.request, 'build_opener', return_value=opener):
            deploy.public_check()
        self.assertEqual(opener.open.call_count, 3)

    def test_rejects_spa_fallback_wrong_status_and_wrong_health_body(self):
        for code, body in [(200, b'<html>proxy landing page</html>'), (302, b''), (503, b'')]:
            response = MagicMock()
            response.__enter__.return_value = MagicMock(status=code, read=MagicMock(return_value=body))
            opener = MagicMock()
            opener.open.return_value = response
            with patch.object(deploy.urllib.request, 'build_opener', return_value=opener), self.assertRaises(deploy.DeployError):
                deploy.public_check()

    def test_public_readiness_retries_temporary_proxy_errors(self):
        with patch.object(deploy, 'public_check', side_effect=[deploy.DeployError('PUBLIC_HTTP_CHECK_FAILED'), None]) as probe, \
                patch.object(deploy.time, 'sleep'):
            deploy.wait_for_public()
        self.assertEqual(probe.call_count, 2)

    def test_public_readiness_fails_after_bounded_retries(self):
        with patch.object(deploy, 'public_check', side_effect=deploy.DeployError('PUBLIC_HTTP_CHECK_FAILED')) as probe, \
                patch.object(deploy.time, 'sleep'), self.assertRaises(deploy.DeployError):
            deploy.wait_for_public()
        self.assertEqual(probe.call_count, 6)


@unittest.skipUnless(shutil.which('docker'), 'Docker Compose CLI required; daemon is never used')
class ComposeContractTest(unittest.TestCase):
    def test_resolved_production_config_preserves_volumes_networks_and_secrets_boundary(self):
        with tempfile.TemporaryDirectory() as directory:
            bundle = Path(directory)
            for source, destination in [(ROOT / 'compose.yaml', 'compose.yaml'), (ROOT / 'compose.production.yaml', 'compose.production.yaml'),
                                        (ROOT / 'deploy/simple/compose.images.yaml', 'compose.images.yaml'),
                                        (ROOT / 'deploy/simple/compose.frontend.yaml', 'compose.frontend.yaml')]:
                shutil.copyfile(source, bundle / destination)
            env_file = bundle / 'production.env'
            env_file.write_text('\n'.join(key + '=synthetic-marker' for key in ['POSTGRES_ADMIN_PASSWORD', 'OWNER_DB_PASSWORD', 'APP_DB_PASSWORD', 'JWT_SECRET'])
                                + '\nAPP_WORKER_ENABLED=true\nAPP_INVESTIGATION_WORKER_ENABLED=true\nMODEL_API_KEY=synthetic-key\n')
            back, front, env = deploy.commands(bundle, env_file, {**IMAGES, 'postgres': 'sha256:' + 'd' * 64})
            b = json.loads(deploy.run(back + ['config', '--format', 'json'], env))
            f = json.loads(deploy.run(front + ['config', '--format', 'json'], env))
            self.assertEqual(set(b['services']['backend']['depends_on']), {'postgres'})
            self.assertNotIn('build', b['services']['backend'])
            for service in ('backend', 'postgres'):
                self.assertFalse(b['services'][service].get('ports'))
            self.assertEqual(b['services']['backend']['environment']['APP_MIGRATIONS_VALIDATE_ONLY'], 'true')
            self.assertEqual(b['services']['backend']['environment']['APP_WORKER_HEALTH_ENABLED'], 'true')
            for name, definition in b['volumes'].items():
                self.assertTrue(definition['external'])
                self.assertEqual(definition['name'], 'ai-policy-investigator_' + name)
            self.assertNotIn('proxy', b['services']['backend']['networks'])
            self.assertEqual(set(f['services']['frontend']['environment']), {'BACKEND_UPSTREAM'})
            self.assertEqual(f['networks']['proxy']['name'], 'nginx-proxy-manager_default')


if __name__ == '__main__':
    unittest.main()
