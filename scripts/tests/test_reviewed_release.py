"""Synthetic files and subprocesses only; no registry, SSH or production access."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import stat
from types import SimpleNamespace
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import reviewed_v8_release as reviewed
import run_reviewed_release as runner
import v7_backup_restore as backup
import production_release as controller
import release_safety as safety
import release_artifacts as artifacts
import prepare_production_release as preparation
from deploy_local_images import DeploymentError
from test_production_release import manifest, fixture, write_tar, BACK, FRONT
from test_release_safety import attestations


def candidate():
    data = manifest()
    data.update(migrations=safety.qualified_migrations(), expectedPrevious='r122-1')
    for key, digest in reviewed.APPROVED.items():
        row = data['images'][key]
        row.update(manifestDigest=digest, indexDigest=digest,
                   localRef=row['localRef'].split(':deploy-')[0] + ':deploy-' + digest[7:])
    data['images']['POSTGRES_IMAGE_REF']['configDigest'] = backup.PG_CONFIG
    data['runtime'] = {}
    from release_artifacts import RUNTIME_FILES
    data['runtime'] = dict.fromkeys(RUNTIME_FILES, 'e' * 64)
    data['v7Preparation'] = {'expected_previous': 'r122-1', 'env_file': str(backup.ENV_FILE),
                             'demo_id': '11111111-2222-3333-4444-555555555555', 'backup_root': '/private/backups'}
    return data


def inputs(operation='prepare-reviewed'):
    return {'OPERATION': operation, 'EXPECTED_PREVIOUS': 'r122-1', 'VPS_ENV_FILE': str(backup.ENV_FILE),
            'ALLOW_MIGRATIONS': 'false', 'V7_DEMO_INVESTIGATION_ID': '11111111-2222-3333-4444-555555555555',
            'V7_BACKUP_DIR': '/private/backups', 'GITHUB_EVENT_NAME': 'workflow_dispatch',
            'GITHUB_REPOSITORY': 'ThierryTe/ai-policy-invetigator', 'GITHUB_REF': 'refs/heads/main',
            'GITHUB_RUN_ID': '123', 'GITHUB_RUN_ATTEMPT': '1', 'CONFIGURATION_SHA': BACK}


class CandidateTest(unittest.TestCase):
    def test_original_sql_and_initializer_hashes_are_preserved(self):
        root = Path(__file__).resolve().parents[2]
        expected = json.loads((root / 'docs/verification/v7-backup-restore-preparation.json').read_text())['tools']
        for name, digest in expected.items():
            self.assertEqual(artifacts.file_sha(root / name), digest)
        self.assertEqual({Path(k).name: v for k, v in expected.items() if k.endswith('.sql')}, backup.SQL_SHA256)

    def test_pinned_preparation_reuses_images_and_checks_exported_content(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); sources = {}; metadata = {}
            for key in artifacts.KEYS:
                folder = root / key; folder.mkdir()
                revision = FRONT if key == 'FRONTEND_IMAGE_REF' else BACK
                path, _, config, content = fixture(folder, key, revision=revision)
                raw = json.dumps({'schemaVersion': 2, 'config': {'digest': config}}).encode()
                digest = 'sha256:' + artifacts.sha(raw) if key == 'POSTGRES_IMAGE_REF' else 'sha256:' + 'c' * 64
                if key == 'POSTGRES_IMAGE_REF':
                    content['manifest.json'] = content['manifest.json'].replace(('c' * 64).encode(), digest[7:].encode())
                    write_tar(path, content)
                metadata[key] = {'manifestDigest': digest, 'configDigest': config, 'indexDigest': digest, 'raw': raw}
                sources[key] = path
            pins = {key: metadata[key]['indexDigest'] for key in reviewed.APPROVED}
            calls = []; lookups = []
            def registry(repository, tag):
                lookups.append((repository, tag))
                key = next(k for k, repo in preparation.REPOSITORIES.items() if repo == repository)
                return {k: v for k, v in metadata[key].items() if k != 'raw'}
            def docker(command, **kwargs):
                calls.append(command)
                if command[:3] == ['docker', 'buildx', 'imagetools']: return metadata['POSTGRES_IMAGE_REF']['raw']
                if command[:3] == ['docker', 'image', 'inspect']:
                    return json.dumps([{'Os': 'linux', 'Architecture': 'amd64', 'Id': 'store-id'}]).encode()
                if command[:3] == ['docker', 'image', 'save']:
                    target = Path(command[command.index('--output') + 1])
                    shutil.copyfile(sources[target.name.removesuffix('.raw')], target)
                return b''
            with patch.object(preparation, 'ghcr_manifest', side_effect=registry), patch.object(preparation, 'run', side_effect=docker):
                data = preparation.prepare(root / 'prepared', BACK, FRONT, BACK, 'r123-1', approved_images=pins)
            self.assertEqual(data['migrations'], controller.verify_archives(root / 'prepared', data)['BACKEND_IMAGE_REF']['migrations'])
            for key in ['BACKEND_IMAGE_REF', 'FRONTEND_IMAGE_REF']:
                self.assertIn((preparation.REPOSITORIES[key], pins[key]), lookups)
                self.assertEqual(data['images'][key]['sourceRef'], preparation.REPOSITORIES[key] + '@' + pins[key])
            self.assertFalse(any('build' in c or 'push' in c for c in calls))

    def test_only_the_two_approved_images_and_trusted_postgres_pass(self):
        reviewed.validate_candidate(candidate())
        for key in reviewed.APPROVED:
            data = candidate(); data['images'][key]['indexDigest'] = 'sha256:' + '0' * 64
            with self.assertRaises(DeploymentError): reviewed.validate_candidate(data)
        for change in [lambda d: d['migrations'][0].update(checksum=0),
                       lambda d: d['v7Preparation'].update(env_file='/opt/ai-policy-investigator/.env'),
                       lambda d: d['v7Preparation'].update(expected_previous='r120-1'),
                       lambda d: d['v7Preparation'].update(restore_start_timeout_seconds=901),
                       lambda d: d['images']['POSTGRES_IMAGE_REF'].update(configDigest='sha256:' + '0' * 64)]:
            data = candidate(); change(data)
            with self.assertRaises(DeploymentError): reviewed.validate_candidate(data)

    def test_prepare_has_no_migration_permission_and_requires_real_demo_identifier(self):
        runner.validate(inputs())
        for change in [{'ALLOW_MIGRATIONS': 'true'}, {'V7_DEMO_INVESTIGATION_ID': ''},
                       {'VPS_ENV_FILE': '/opt/ai-policy-investigator/other.env'}, {'EXPECTED_PREVIOUS': ''},
                       {'BACKEND_SHA': BACK}, {'PREPARED_RELEASE': 'r123-1'}]:
            with self.assertRaises(DeploymentError): runner.validate({**inputs(), **change})

    def test_restore_timeout_is_bounded_before_remote_access_and_retained_in_manifest(self):
        for value in ['59', '901', '-1', '1.5', 'unbounded', '300\n']:
            with self.subTest(value=value), patch.object(runner, 'current_release') as remote:
                with self.assertRaisesRegex(DeploymentError, 'RESTORE_START_TIMEOUT_INVALID'):
                    runner.run({**inputs(), 'V7_RESTORE_START_TIMEOUT_SECONDS': value}, Path('/unused'))
                remote.assert_not_called()
        for value, expected in [('', 300), ('60', 60), ('900', 900)]:
            with self.subTest(value=value), tempfile.TemporaryDirectory() as temp:
                def prepare(directory, *args, **kwargs):
                    directory.mkdir()
                    data = candidate(); data['id'] = args[3]
                    return data
                with patch.object(runner, 'current_release', return_value='r122-1'), \
                        patch.object(runner, 'reviewed_revisions', return_value=(BACK, FRONT)), \
                        patch.object(runner, 'prepare', side_effect=prepare), patch.object(runner, 'transfer') as transfer:
                    runner.run({**inputs(), 'V7_RESTORE_START_TIMEOUT_SECONDS': value}, Path(temp))
                directory = transfer.call_args.args[2]
                retained = json.loads((directory / 'release.json').read_text())
                self.assertEqual(retained['v7Preparation']['restore_start_timeout_seconds'], expected)

    def test_migration_requires_retained_release_and_explicit_human_approvals(self):
        env = {**inputs('deploy-reviewed'), **attestations(), 'PREPARED_RELEASE': 'r123-1',
               'ALLOW_MIGRATIONS': 'true'}
        runner.validate(env)
        for key in ['PREPARED_RELEASE', 'ALLOW_MIGRATIONS', 'RELEASE_PHASE', 'CONFIRM_GITHUB_PROTECTION',
                    'CONFIRM_WRITE_FREEZE', 'CONFIRM_IMAGE_QUALIFICATION', 'EVIDENCE_REF']:
            with self.assertRaises(DeploymentError): runner.validate({**env, key: ''})

    def test_missing_or_malformed_demo_stops_before_remote_access(self):
        for demo in [None, '', 'not-a-uuid', inputs()['V7_DEMO_INVESTIGATION_ID'] + '\n']:
            env = inputs()
            env.pop('V7_DEMO_INVESTIGATION_ID')
            if demo is not None:
                env['V7_DEMO_INVESTIGATION_ID'] = demo
            with self.subTest(demo=demo), patch.object(runner, 'current_release') as current, \
                    patch.object(runner, 'reviewed_revisions') as registry, patch.object(runner, 'transfer') as transfer:
                with self.assertRaisesRegex(DeploymentError, 'COMPLETED_PRODUCTION_DEMO_UUID_REQUIRED'):
                    runner.run(env, Path('/unused'))
                current.assert_not_called(); registry.assert_not_called(); transfer.assert_not_called()

    def test_runner_never_rebuilds_and_stale_base_stops_before_registry(self):
        with patch.object(runner, 'current_release', return_value='r120-1'), \
                patch.object(runner, 'reviewed_revisions') as lookup, patch.object(runner, 'transfer') as transfer:
            with self.assertRaisesRegex(DeploymentError, 'BASE_CHANGED'): runner.run(inputs(), Path('/unused'))
            lookup.assert_not_called(); transfer.assert_not_called()


class ReviewedWorkflowTest(unittest.TestCase):
    def test_prod_configuration_reaches_both_python_steps_after_environment_approval(self):
        workflow = (Path(__file__).resolve().parents[2] / '.github/workflows/deploy-production.yml').read_text()
        job, steps = workflow.split('    steps:\n', 1)
        self.assertIn('    environment:\n      name: prod\n', job)
        for name in ['V7_DEMO_INVESTIGATION_ID', 'V7_BACKUP_DIR', 'V7_RESTORE_START_TIMEOUT_SECONDS']:
            self.assertNotIn('${{ vars.' + name + ' }}', job)
        for title in ['Validate reviewed preparation or migration approval',
                      'Prepare or deploy the retained approved image pair']:
            step = steps.split('      - name: ' + title + '\n', 1)[1].split('      - name:', 1)[0]
            environment = step.split('        env:\n', 1)[1].split('        run:', 1)[0]
            for name in ['V7_DEMO_INVESTIGATION_ID', 'V7_BACKUP_DIR', 'V7_RESTORE_START_TIMEOUT_SECONDS']:
                self.assertRegex(environment, re.escape('          ' + name + ': ${{ vars.' + name + ' }}'))
            self.assertIn('python3 -B scripts/run_reviewed_release.py', step)
        self.assertLess(steps.index('scripts/run_reviewed_release.py --validate-only'), steps.index('GHCR_TOKEN:'))


class BackupTest(unittest.TestCase):
    def test_source_content_compares_even_additional_runtime_config_keys(self):
        proof = {'diffIds': ['sha256:synthetic'], 'imageConfig': {'Cmd': ['postgres'], 'AdditionalField': 'expected'}}
        row = {'Os': 'linux', 'Architecture': 'amd64', 'RootFS': {'Type': 'layers', 'Layers': proof['diffIds']},
               'Config': dict(proof['imageConfig'])}
        backup.verify_source_content(row, proof)
        row['Config']['AdditionalField'] = 'changed'
        with self.assertRaisesRegex(DeploymentError, 'RUNTIME_CONFIG_MISMATCH'): backup.verify_source_content(row, proof)

    def test_post_migration_conservation_checks_every_data_table_and_the_completed_demo(self):
        source = [{'table': 'flyway_schema_history', 'rows': 7}, {'table': 'accounts', 'sha256': 'same'},
                  {'table': 'investigation_assessments', 'sha256': 'completed-result'}, {'policies': ['V7']},
                  {'routines': ['V7']}, {'demo': 'approved-id', 'state': 'COMPLETED'},
                  {'result': 'V7_BACKUP_DATA_CHECK_PASS', 'passwordHashFingerprintVerified': False}]
        import copy
        for corruption in [None, 'accounts', 'investigation_assessments', 'demo']:
            with self.subTest(corruption=corruption), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                (root / 'source.out').write_text(''.join(json.dumps(r) + '\n' for r in source))
                restored = copy.deepcopy(source); restored[0]['rows'] = 8
                restored[3]['policies'] = ['V8']; restored[4]['routines'] = ['V8']
                for row in restored:
                    if corruption and (row.get('table') == corruption or (corruption == 'demo' and 'demo' in row)):
                        row['changed'] = True
                def run(*args):
                    (root / 'post-v8.out').write_text(''.join(json.dumps(r) + '\n' for r in restored))
                with patch.object(reviewed, 'private_run', side_effect=run):
                    if corruption:
                        with self.assertRaisesRegex(DeploymentError, 'CONSERVATION_FAILED'): reviewed.conservation('cid', root, 'approved-id')
                    else:
                        reviewed.conservation('cid', root, 'approved-id')
                original = (backup.TOOLS / 'qualification_v7_backup.sql').read_text()
                self.assertIn(original.split('-- Same representation', 1)[1], (root / 'conservation.sql').read_text())

    def test_isolation_rejects_shared_volume_ports_or_network_and_external_routes(self):
        row = {'State': {'Running': True}, 'Image': 'image', 'Config': {'Labels': {'purpose': 'investigator-v7-restore'},
               'Env': ['POSTGRES_PASSWORD=synthetic']}, 'HostConfig': {'NetworkMode': 'none', 'Privileged': False,
               'PidMode': '', 'IpcMode': '', 'RestartPolicy': {'Name': 'no'}},
               'NetworkSettings': {'Networks': {'none': {}}}, 'Mounts': [
                   {'Destination': '/var/lib/postgresql/data', 'Name': 'isolated'},
                   {'Destination': '/docker-entrypoint-initdb.d/01-investigator.sh', 'Source': '/private/evidence/init.sh', 'RW': False}]}
        def check(candidate, routes='header\n'):
            with patch.object(backup, 'json_command', return_value=[candidate]), \
                    patch.object(backup, 'execute', side_effect=['lo 0x9\n', routes, '0 0 0 lo\n']):
                backup.isolation('name', 'isolated', 'image', Path('/private/evidence'))
        check(row)
        import copy
        for mutate in [lambda r: r['HostConfig'].update(PortBindings={'5432/tcp': [{}]}),
                       lambda r: r['HostConfig'].update(NetworkMode='host'),
                       lambda r: r['HostConfig'].update(Privileged=True),
                       lambda r: r['Mounts'][0].update(Name='ai-policy-investigator_investigator_data'),
                       lambda r: r['Config']['Env'].append('JWT_SECRET=synthetic')]:
            changed = copy.deepcopy(row); mutate(changed)
            with self.assertRaises(DeploymentError): check(changed)
        with self.assertRaisesRegex(DeploymentError, 'EXTERNAL_ROUTE'): check(row, 'header\nexternal\n')

    def run_backup(self, root, fail=None, startup_failure=None, cleanup_failure=False):
        release = root / 'old'; (release / 'configuration/deploy/postgres').mkdir(parents=True)
        (release / 'configuration/deploy/postgres/init.sh').write_text('unchanged synthetic initializer')
        evidence = root / 'evidence'; evidence.mkdir(mode=0o700)
        pg = {'Id': 'a' * 64, 'Image': 'sha256:' + 'b' * 64}
        apps = [{'State': {'Running': False}}, {'State': {'Running': False}}]
        events = []
        @contextmanager
        def snapshot(*args):
            events.append('snapshot-open'); yield '00000001-00000002-1'; events.append('snapshot-close')
        rows = json.dumps({'table': 'accounts', 'rows': 2, 'sha256': 'synthetic'}) + '\n' + json.dumps({'result': 'V7_BACKUP_DATA_CHECK_PASS'}) + '\n'
        def private(command, directory, name, input_path=None, output_path=None, **kwargs):
            events.append(name)
            if name == fail: raise DeploymentError('SYNTHETIC_DATABASE_FAILURE')
            value = b'dump' if name == 'pg_dump' else (rows.encode() if name in ['source', 'restored'] else b'archive')
            if name == 'restored' and fail == 'mismatch': value += b'changed'
            (output_path or directory / (name + '.out')).write_bytes(value)
        def execute(command, *args, **kwargs):
            events.append(command)
            if command[:2] == ['docker', 'run'] and fail == 'launch':
                raise DeploymentError('RESTORE_POSTGRES_LAUNCH_FAILED')
            if command[:2] == ['docker', 'stop'] and cleanup_failure:
                raise DeploymentError('ISOLATED_RESTORE_STOP_FAILED')
            if '--format' in command:
                return json.dumps({'Status': 'running', 'ExitCode': 0, 'OOMKilled': False})
            return '1024' if 'SELECT pg_database_size(current_database());' in command else ''
        def inspect(command, *args, **kwargs):
            name = command[-1]
            return [{'Name': '/' + name, 'Id': 'c' * 64, 'Config': {'Labels': {'purpose': 'investigator-v7-restore'}},
                     'Mounts': [{'Destination': '/var/lib/postgresql/data', 'Type': 'volume', 'Name': name + '-data'}]}]
        def probe(command, **kwargs):
            if fail == 'collision':
                return SimpleNamespace(returncode=0)
            return SimpleNamespace(returncode=1 if command[1] in ['container', 'volume'] else 0)
        request = candidate()['v7Preparation']
        with patch.object(backup, 'private_env'), patch.object(backup, 'source', return_value=(release, pg, apps)), \
                patch.object(backup, 'evidence_directory', return_value=evidence), patch.object(backup, 'execute', side_effect=execute), \
                patch.object(backup, 'preflight'), patch.object(backup, 'snapshot', side_effect=snapshot), \
                patch.object(backup, 'private_run', side_effect=private), patch.object(backup.subprocess, 'run', side_effect=probe), \
                patch.object(backup, 'json_command', side_effect=inspect), \
                patch.object(backup, 'wait_for_restore', wraps=backup.wait_for_restore,
                             side_effect=DeploymentError(startup_failure) if startup_failure else None), \
                patch.object(backup, 'isolation') as isolation:
            try:
                result = backup.verify_backup(root, request, frozen=True)
                self.assertEqual(isolation.call_count, 2)
                return result, events
            finally:
                self.events = events

    def test_dump_and_source_share_snapshot_and_restore_preserves_roles_acls_and_data(self):
        with tempfile.TemporaryDirectory() as temp:
            evidence, events = self.run_backup(Path(temp))
            report = json.loads((evidence / 'report.json').read_text())
            self.assertEqual(report['result'], 'V7_BACKUP_AND_ISOLATED_RESTORE_VERIFIED')
            self.assertTrue(report['applicationWritersStopped'])
            self.assertFalse(report['deploymentAuthorized'])
            self.assertLess(events.index('snapshot-open'), events.index('pg_dump'))
            self.assertLess(events.index('source'), events.index('snapshot-close'))
            self.assertLess(events.index('snapshot-close'), events.index('restore'))
            commands = [e for e in events if isinstance(e, list)]
            run = next(c for c in commands if c[:2] == ['docker', 'run'])
            self.assertEqual(run[run.index('--network') + 1], 'none')
            self.assertIn('listen_addresses=', run)
            self.assertTrue(any(c[:2] == ['docker', 'stop'] and c[-1] == 'c' * 64 for c in commands))
            self.assertFalse(any('rm' in c or 'prune' in c or 'up' in c for c in commands))

    def test_failed_restore_or_fingerprint_mismatch_never_produces_success_and_stops_only_rehearsal(self):
        for failure in ['restore', 'mismatch']:
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                with self.assertRaises(DeploymentError): self.run_backup(root, failure)
                self.assertFalse((root / 'evidence/report.json').exists())
                stops = [c for c in self.events if isinstance(c, list) and c[:2] == ['docker', 'stop']]
                self.assertEqual(len(stops), 1)
                self.assertEqual(stops[0][-1], 'c' * 64)

    def test_private_umask_keeps_initializer_readable_without_exposing_secrets(self):
        previous = os.umask(0o077)
        try:
            with tempfile.TemporaryDirectory() as temp:
                evidence, _ = self.run_backup(Path(temp))
                self.assertEqual(stat.S_IMODE((evidence / 'init.sh').stat().st_mode), 0o644)
                self.assertEqual((evidence / 'init.sh').read_bytes(),
                                 (Path(temp) / 'old/configuration/deploy/postgres/init.sh').read_bytes())
                self.assertEqual(stat.S_IMODE(evidence.stat().st_mode), 0o700)
                self.assertEqual(stat.S_IMODE((evidence / 'restore.env').stat().st_mode), 0o600)
                self.assertEqual(stat.S_IMODE((evidence / 'investigator-v7.dump').stat().st_mode), 0o400)
        finally:
            os.umask(previous)

    def test_startup_failure_blocks_restore_and_cleanup_does_not_mask_it(self):
        for cleanup_failure in [False, True]:
            with self.subTest(cleanup_failure=cleanup_failure), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                with self.assertRaisesRegex(DeploymentError, '^RESTORE_POSTGRES_INITIALIZER_FAILED$'):
                    self.run_backup(root, startup_failure='RESTORE_POSTGRES_INITIALIZER_FAILED',
                                    cleanup_failure=cleanup_failure)
                self.assertNotIn('restore', self.events)
                self.assertFalse((root / 'evidence/report.json').exists())
                failed = json.loads((root / 'evidence/rehearsal-failed.json').read_text())
                self.assertFalse(failed['backupAndRestoreVerified'])
                self.assertFalse(failed['deploymentAuthorized'])
                self.assertEqual((root / 'evidence/cleanup-failed.json').exists(), cleanup_failure)

    def test_cleanup_failure_after_verification_still_blocks_success_report(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with self.assertRaisesRegex(DeploymentError, 'ISOLATED_RESTORE_STOP_FAILED'):
                self.run_backup(root, cleanup_failure=True)
            self.assertFalse((root / 'evidence/report.json').exists())

    def test_failed_run_still_attempts_only_guarded_rehearsal_cleanup(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with self.assertRaisesRegex(DeploymentError, '^RESTORE_POSTGRES_LAUNCH_FAILED$'):
                self.run_backup(root, fail='launch', cleanup_failure=True)
            self.assertFalse((root / 'evidence/report.json').exists())
            self.assertNotIn('restore', self.events)
            stops = [c for c in self.events if isinstance(c, list) and c[:2] == ['docker', 'stop']]
            self.assertEqual(stops, [['docker', 'stop', 'c' * 64]])

    def test_existing_target_is_never_started_or_cleaned_up(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with self.assertRaisesRegex(DeploymentError, '^RESTORE_TARGET_ALREADY_EXISTS$'):
                self.run_backup(root, fail='collision')
            self.assertFalse((root / 'evidence/report.json').exists())
            commands = [c for c in self.events if isinstance(c, list)]
            self.assertFalse(any(c[:2] in [['docker', 'run'], ['docker', 'stop'], ['docker', 'volume']] for c in commands))

    def test_snapshot_session_is_held_until_explicit_rollback(self):
        # Real pipe/process behavior catches buffered-output and stdin lifecycle errors.
        script = ('import sys\nfor line in sys.stdin:\n'
                  ' if "pg_export_snapshot" in line: print("00000001-00000002-1", flush=True)\n'
                  ' if "ROLLBACK" in line: break\n')
        with tempfile.TemporaryDirectory() as temp, patch.object(backup, 'psql', return_value=[sys.executable, '-u', '-c', script]):
            with backup.snapshot('synthetic', Path(temp)) as token:
                self.assertEqual(token, '00000001-00000002-1')

    def test_private_stderr_blocks_and_never_appears_in_exception(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            with self.assertRaisesRegex(DeploymentError, '^PRIVATE_DATABASE_STDERR_REQUIRES_REVIEW$'):
                backup.private_run([sys.executable, '-c', 'import sys; print("synthetic-private-detail", file=sys.stderr)'], root, 'check')
            self.assertIn('synthetic-private-detail', (root / 'check.err').read_text())


class ReviewBoundaryTest(unittest.TestCase):
    def setup_release(self, root):
        data = candidate()
        directory = root / 'releases' / data['id']; directory.mkdir(parents=True)
        (directory / 'release.json').write_text(json.dumps(data))
        return data, directory

    @contextmanager
    def gates(self, data):
        from contextlib import ExitStack
        with ExitStack() as stack:
            stack.enter_context(patch.dict(os.environ, dict(os.environ)))
            for p in [patch.object(reviewed, 'validate_candidate', return_value=data['v7Preparation']),
                      patch.object(reviewed, 'file_sha', return_value='e' * 64),
                      patch.object(reviewed, 'private_env'), patch.object(reviewed, 'reviewed_configuration'),
                      patch.object(reviewed, 'verify_archives')]: stack.enter_context(p)
            yield

    def test_preparation_never_calls_activation_or_stops_application_containers(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve(); data, directory = self.setup_release(root)
            with self.gates(data), patch.object(reviewed, 'verify_backup', return_value=root / 'private') as backup_check, \
                    patch.object(reviewed, 'activate') as activate, patch.object(reviewed, 'execute') as execute:
                result = reviewed.run('prepare-reviewed', data['id'], base=root)
                self.assertEqual(result['result'], 'PREPARED_AWAITING_V8_APPROVAL')
                backup_check.assert_called_once_with(root, data['v7Preparation'])
                activate.assert_not_called(); execute.assert_not_called()
            self.assertFalse((directory / 'attempt.json').exists())

    def test_failed_startup_never_marks_release_prepared_or_allows_activation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve(); data, directory = self.setup_release(root)
            with self.gates(data), patch.object(reviewed, 'verify_backup',
                    side_effect=DeploymentError('RESTORE_POSTGRES_INITIALIZER_NOT_READABLE')), \
                    patch.object(reviewed, 'activate') as activate, patch.object(reviewed, 'execute') as execute:
                with self.assertRaisesRegex(DeploymentError, 'INITIALIZER_NOT_READABLE'):
                    reviewed.run('prepare-reviewed', data['id'], base=root)
                activate.assert_not_called(); execute.assert_not_called()
            self.assertFalse((directory / 'prepared.json').exists())
            self.assertFalse((directory / 'attempt.json').exists())

    def test_unapproved_or_changed_preparation_cannot_stop_containers(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve(); data, directory = self.setup_release(root)
            with self.gates(data), patch.object(reviewed, 'execute') as execute, patch.object(reviewed, 'activate') as activate:
                with self.assertRaisesRegex(DeploymentError, 'APPROVAL_REQUIRED'):
                    reviewed.run('deploy-reviewed', data['id'], base=root)
                (directory / 'prepared.json').write_text(json.dumps({'result': 'PREPARED_AWAITING_V8_APPROVAL',
                    'id': data['id'], 'releaseManifestSha256': 'changed'}))
                with self.assertRaisesRegex(DeploymentError, 'PREPARED_RELEASE_CHANGED'):
                    reviewed.run('deploy-reviewed', data['id'], {'expected_previous': 'r122-1'}, base=root)
                execute.assert_not_called(); activate.assert_not_called()

    def test_frozen_backup_failure_blocks_migration_after_only_project_apps_are_stopped(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve(); data, directory = self.setup_release(root)
            (directory / 'prepared.json').write_text(json.dumps({'result': 'PREPARED_AWAITING_V8_APPROVAL',
                'id': data['id'], 'releaseManifestSha256': 'e' * 64}))
            env = attestations(); env['APPROVED_BACKEND_DIGEST'] = data['images']['BACKEND_IMAGE_REF']['manifestDigest']
            apps = [{'Id': 'backend-exact'}, {'Id': 'frontend-exact'}]
            with self.gates(data), patch.object(reviewed, 'source', return_value=(None, None, apps)), \
                    patch.object(controller, 'commands'), patch.object(reviewed, 'execute') as execute, \
                    patch.object(reviewed, 'verify_backup', side_effect=DeploymentError('RESTORE_FAILED')), \
                    patch.object(reviewed, 'activate') as activate:
                with self.assertRaisesRegex(DeploymentError, 'RESTORE_FAILED'):
                    reviewed.run('deploy-reviewed', data['id'], {'expected_previous': 'r122-1', 'environment': env}, base=root)
                self.assertEqual([c.args[0][-1] for c in execute.call_args_list], ['frontend-exact', 'backend-exact'])
                activate.assert_not_called()
                self.assertTrue((directory / 'attempt.json').exists())
                with self.assertRaisesRegex(DeploymentError, 'ALREADY_ATTEMPTED'):
                    reviewed.run('deploy-reviewed', data['id'], {}, base=root)


if __name__ == '__main__':
    unittest.main()
