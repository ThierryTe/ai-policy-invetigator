"""Restore startup regression tests: fake Docker, real files, no remote access."""
import copy
import json
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import v7_backup_restore as backup
from deploy_local_images import DeploymentError

NAME = 'investigator-v7-restore-' + '1' * 24
RUNNING = {'Status': 'running', 'ExitCode': 0, 'OOMKilled': False, 'Error': ''}
SECRET = 'synthetic-password-and-database-content'


class RestoreStartupTest(unittest.TestCase):
    def wait(self, evidence, probes=(0,), states=None, log='', timeout=300):
        self.elapsed = 0
        self.calls = []
        self.inspections = 0
        pending = iter(probes)
        remaining_states = iter(states or [RUNNING])
        state = RUNNING
        last_probe = 0

        def execute(command, env, **kwargs):
            nonlocal state
            self.calls.append(command)
            self.inspections += 1
            state = next(remaining_states, state)
            self.assertGreater(kwargs['timeout'], 0)
            self.assertLessEqual(kwargs['timeout'], 10)
            return json.dumps(state)

        def run(command, **kwargs):
            nonlocal last_probe
            self.calls.append(command)
            if command[:2] == ['docker', 'logs']:
                kwargs['stdout'].write(log.encode())
                return subprocess.CompletedProcess(command, 0)
            self.assertEqual(command[:5], ['docker', 'exec', '--user', 'postgres', NAME])
            self.assertIs(kwargs['stdout'], subprocess.DEVNULL)
            self.assertIs(kwargs['stderr'], subprocess.DEVNULL)
            self.assertLessEqual(kwargs['timeout'], 10)
            last_probe = next(pending, last_probe)
            if isinstance(last_probe, Exception):
                self.elapsed += kwargs['timeout']
                raise last_probe
            return subprocess.CompletedProcess(command, last_probe)

        def sleep(seconds):
            self.elapsed += seconds

        with patch.object(backup, 'execute', side_effect=execute), \
                patch.object(backup.subprocess, 'run', side_effect=run), \
                patch.object(backup.time, 'monotonic', side_effect=lambda: self.elapsed), \
                patch.object(backup.time, 'sleep', side_effect=sleep):
            backup.wait_for_restore(NAME, evidence, timeout)

    def test_slow_initialization_beyond_old_sixty_attempt_limit_succeeds(self):
        with tempfile.TemporaryDirectory() as temp:
            self.wait(Path(temp), probes=[10] * 90 + [1, 2, 0])
            self.assertEqual(self.elapsed, 92)
            self.assertFalse((Path(temp) / 'restore-startup-failure.json').exists())

    def test_running_timeout_identifies_phase_and_has_a_wall_clock_bound(self):
        for probe, phase in [(10, 'INITIALIZING'), (1, 'REJECTING_CONNECTIONS'), (2, 'NO_RESPONSE'),
                             (subprocess.TimeoutExpired('private-command', 10), 'PROBE_TIMEOUT')]:
            with self.subTest(phase=phase), tempfile.TemporaryDirectory() as temp:
                evidence = Path(temp)
                with self.assertRaisesRegex(DeploymentError, '^RESTORE_POSTGRES_START_TIMEOUT_' + phase + '$'):
                    self.wait(evidence, probes=[probe], log=SECRET, timeout=60)
                self.assertEqual(self.elapsed, 60)
                public = (evidence / 'restore-startup-failure.json').read_text()
                self.assertNotIn(SECRET, public)
                self.assertFalse(json.loads(public)['backupAndRestoreVerified'])
                self.assertEqual(stat.S_IMODE((evidence / 'restore-startup.log').stat().st_mode), 0o600)

    def test_container_failure_is_immediate_and_reason_does_not_leak_logs_or_state_error(self):
        cases = [
            ({'OOMKilled': True, 'ExitCode': 137}, '', 'OOM_KILLED'),
            ({'ExitCode': 1}, 'No space left on device', 'DISK_FULL'),
            ({'ExitCode': 1}, 'Cannot allocate memory', 'MEMORY_EXHAUSTED'),
            ({'ExitCode': 1}, 'fork: Resource temporarily unavailable', 'PROCESS_RESOURCE_EXHAUSTED'),
            ({'ExitCode': 1}, '/docker-entrypoint-initdb.d/01-investigator.sh\nERROR: bad SQL', 'INITIALIZER_FAILED'),
            ({'ExitCode': 1}, '/docker-entrypoint-initdb.d/01-investigator.sh: Permission denied', 'INITIALIZER_NOT_READABLE'),
            ({'ExitCode': 2}, '', 'CONTAINER_EXITED_2'),
            ({'ExitCode': 0}, '', 'CONTAINER_EXITED_0'),
            ({'ExitCode': 1}, '/docker-entrypoint-initdb.d/01-investigator.sh\nPostgreSQL init process complete', 'CONTAINER_EXITED_1'),
        ]
        for changes, log, reason in cases:
            state = {**RUNNING, 'Status': 'exited', 'Error': SECRET, **changes}
            with self.subTest(reason=reason), tempfile.TemporaryDirectory() as temp:
                with self.assertRaisesRegex(DeploymentError, '^RESTORE_POSTGRES_' + reason + '$') as error:
                    self.wait(Path(temp), states=[state], log=log + '\n' + SECRET)
                self.assertEqual(self.elapsed, 0)
                self.assertFalse(any(c[:2] == ['docker', 'exec'] for c in self.calls))
                self.assertNotIn(SECRET, str(error.exception))
                self.assertNotIn(SECRET, (Path(temp) / 'restore-startup-failure.json').read_text())

    def test_exit_during_probe_is_reinspected_and_not_misreported_as_timeout(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(DeploymentError, 'CONTAINER_EXITED_1'):
                self.wait(Path(temp), probes=[126], states=[RUNNING, {**RUNNING, 'Status': 'exited', 'ExitCode': 1}])
            self.assertEqual(self.inspections, 2)

    def test_invalid_readiness_probe_and_nonrunning_states_fail_early(self):
        for probe in [3, 126, 127, OSError(SECRET)]:
            with self.subTest(probe=probe), tempfile.TemporaryDirectory() as temp:
                with self.assertRaisesRegex(DeploymentError, '^RESTORE_POSTGRES_READINESS_PROBE_FAILED$'):
                    self.wait(Path(temp), probes=[probe])
                self.assertLessEqual(self.elapsed, 10)
        for status in ['paused', 'dead', 'restarting', 'created']:
            with self.subTest(status=status), tempfile.TemporaryDirectory() as temp:
                with self.assertRaises(DeploymentError):
                    self.wait(Path(temp), states=[{**RUNNING, 'Status': status}])
                self.assertEqual(self.elapsed, 0)

    def test_probe_requires_final_postgres_process_and_checks_only_local_socket(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.wait(root)
            command = next(c[-1] for c in self.calls if c[:2] == ['docker', 'exec'])
            (root / 'cat').write_text('#!/bin/sh\nprintf "%s\\n" "$PID_NAME"\n')
            (root / 'pg_isready').write_text('#!/bin/sh\nprintf "%s\\n" "$@"\nexit "$PROBE_EXIT"\n')
            for name in ['cat', 'pg_isready']:
                (root / name).chmod(0o755)
            for pid, probe_exit, expected in [('bash', '0', 10), ('postgres', '0', 0), ('postgres', '3', 3)]:
                result = subprocess.run(['/bin/sh', '-c', command], capture_output=True, text=True,
                                        env={'PATH': temp, 'PID_NAME': pid, 'PROBE_EXIT': probe_exit})
                self.assertEqual(result.returncode, expected)
                if pid == 'bash':
                    self.assertEqual(result.stdout, '')
                else:
                    self.assertEqual(result.stdout.splitlines(),
                                     ['-q', '-h', '/var/run/postgresql', '-p', '5432', '-t', '2', '-U', 'postgres', '-d', 'investigator'])

    def test_state_inspection_failure_is_specific_and_sanitized(self):
        for result in ['bad json ' + SECRET, '{}', 'null']:
            with self.subTest(result=result), patch.object(backup, 'execute', return_value=result):
                with self.assertRaisesRegex(DeploymentError, '^RESTORE_STATE_INSPECTION_FAILED$'):
                    backup.restore_state(NAME)

    def test_diagnostic_collection_failure_preserves_container_failure(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(backup.subprocess, 'run', side_effect=OSError(SECRET)):
            with self.assertRaisesRegex(DeploymentError, '^RESTORE_POSTGRES_CONTAINER_EXITED_1$'):
                backup.restore_start_failure(NAME, Path(temp), {**RUNNING, 'Status': 'exited', 'ExitCode': 1}, 'START_TIMEOUT', 300)

    def test_full_evidence_filesystem_does_not_mask_specific_resource_failure(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(Path, 'write_text', side_effect=OSError('disk full')):
            with self.assertRaisesRegex(DeploymentError, '^RESTORE_POSTGRES_DISK_FULL$'):
                self.wait(Path(temp), states=[{**RUNNING, 'Status': 'exited', 'ExitCode': 1}],
                          log='No space left on device\n' + SECRET)


class RestoreCleanupTest(unittest.TestCase):
    def row(self):
        return {'Name': '/' + NAME, 'Id': 'a' * 64,
                'Config': {'Labels': {'purpose': 'investigator-v7-restore'}},
                'Mounts': [{'Destination': '/var/lib/postgresql/data', 'Type': 'volume', 'Name': NAME + '-data'}]}

    def test_stop_uses_only_verified_immutable_rehearsal_id(self):
        with patch.object(backup, 'json_command', return_value=[self.row()]), patch.object(backup, 'execute') as execute:
            backup.stop_restore(NAME, NAME + '-data')
            execute.assert_called_once_with(['docker', 'stop', 'a' * 64], backup.DOCKER_ENV,
                                            code='ISOLATED_RESTORE_STOP_FAILED', timeout=60)

    def test_cleanup_rejects_production_names_and_ownership_or_volume_mismatch(self):
        for name, volume in [('ai-policy-investigator-postgres-1', NAME + '-data'),
                             (NAME, 'ai-policy-investigator_investigator_data')]:
            with patch.object(backup, 'json_command') as inspect, patch.object(backup, 'execute') as execute:
                with self.assertRaisesRegex(DeploymentError, 'CLEANUP_TARGET_INVALID'):
                    backup.stop_restore(name, volume)
                inspect.assert_not_called(); execute.assert_not_called()
        for mutate in [lambda r: r.update(Name='/production'), lambda r: r.update(Id='production'),
                       lambda r: r['Config'].update(Labels={}),
                       lambda r: r['Mounts'][0].update(Name='ai-policy-investigator_investigator_data')]:
            row = copy.deepcopy(self.row()); mutate(row)
            with patch.object(backup, 'json_command', return_value=[row]), patch.object(backup, 'execute') as execute:
                with self.assertRaisesRegex(DeploymentError, 'CLEANUP_OWNERSHIP_MISMATCH'):
                    backup.stop_restore(NAME, NAME + '-data')
                execute.assert_not_called()


if __name__ == '__main__':
    unittest.main()
