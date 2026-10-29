"""Public SSH host pin validation; offline OpenSSH checks only, never connect."""
import base64
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import transfer_production_release as transport
from deploy_local_images import DeploymentError
import test_production_release as fixtures


class SshHostPinTest(unittest.TestCase):
    def test_missing_public_pin_has_specific_error_before_files_or_network(self):
        with tempfile.TemporaryDirectory() as temporary:
            env = {k: v for k, v in fixtures.TransportTest.ENV.items() if k != 'VPS_HOST_KEY'}
            with patch.object(transport.subprocess, 'run') as run:
                with self.assertRaisesRegex(DeploymentError, '^SSH_HOST_KEY_REQUIRED$'):
                    transport.connection(Path(temporary), env)
                run.assert_not_called()
            self.assertEqual(list(Path(temporary).iterdir()), [])

    def test_malformed_or_multiline_keys_cannot_inject_trusted_hosts(self):
        valid = fixtures.TransportTest.ENV['VPS_HOST_KEY']
        invalid = ['not-a-key', valid.replace('ssh-ed25519', 'ssh-rsa', 1),
                   'ssh-ed25519 !!!', 'ssh-ed25519 ' + base64.b64encode(b'invalid-wire-key').decode(),
                   valid + '\nother.example.invalid ' + valid, valid + '\r malicious',
                   valid + 'x' * 1024]
        # Correct algorithm but truncated key, wrong algorithm-length or extra wire data.
        blob = base64.b64decode(valid.split()[1])
        for data in [blob[:-1], b'\x00\x00\x00\x0a' + blob[4:], blob + b'extra']:
            invalid.append('ssh-ed25519 ' + base64.b64encode(data).decode())
        for value in invalid:
            with self.subTest(case=invalid.index(value)), tempfile.TemporaryDirectory() as temporary:
                with patch.object(transport.subprocess, 'run') as run:
                    with self.assertRaises(DeploymentError) as error:
                        transport.connection(Path(temporary), {**fixtures.TransportTest.ENV, 'VPS_HOST_KEY': value})
                    self.assertNotIn(value, str(error.exception))
                    run.assert_not_called()
                self.assertEqual(list(Path(temporary).iterdir()), [])

    def test_custom_port_binding_ignores_comment_and_uses_exact_public_pin(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            env = {**fixtures.TransportTest.ENV, 'VPS_HOST_KEY': fixtures.TransportTest.ENV['VPS_HOST_KEY'] + ' console-verified\n'}
            ssh, scp, _ = transport.connection(directory, env)
            expected = '[vps.example.invalid]:2222 ' + fixtures.TransportTest.ENV['VPS_HOST_KEY'] + '\n'
            self.assertEqual((directory / 'known_hosts').read_text(), expected)
            self.assertEqual((directory / 'known_hosts').stat().st_mode & 0o777, 0o600)
            for command in [ssh, scp]:
                self.assertEqual(command[1:3], ['-F', '/dev/null'])
                for option in ['StrictHostKeyChecking=yes', 'GlobalKnownHostsFile=/dev/null',
                               'HostKeyAlgorithms=ssh-ed25519', 'VerifyHostKeyDNS=no', 'UpdateHostKeys=no']:
                    self.assertIn(option, command)
                self.assertNotIn('StrictHostKeyChecking=no', command)
                self.assertNotIn('StrictHostKeyChecking=accept-new', command)
                self.assertNotIn(env['VPS_SSH_KEY'], ' '.join(command))
                self.assertNotIn(env['VPS_HOST_KEY'], ' '.join(command))

    def test_default_and_zero_padded_ports_use_canonical_host_binding(self):
        for selected in ['', '22', '022']:
            with self.subTest(port=selected), tempfile.TemporaryDirectory() as temporary:
                directory = Path(temporary)
                ssh, _, _ = transport.connection(directory, {**fixtures.TransportTest.ENV, 'VPS_PORT': selected})
                self.assertEqual((directory / 'known_hosts').read_text().split()[0], 'vps.example.invalid')
                self.assertEqual(ssh[ssh.index('-p') + 1], '22')

    def test_preexisting_client_authentication_secrets_remain_required(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(DeploymentError, '^SSH_SECRETS_REQUIRED$'):
                transport.connection(Path(temporary), {**fixtures.TransportTest.ENV, 'VPS_SSH_KEY': ''})

    def test_native_openssh_parses_pin_and_reports_strict_policy_without_connecting(self):
        if not shutil.which('ssh') or not shutil.which('ssh-keygen'):
            self.skipTest('Local OpenSSH tools required for offline parser/config verification')
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            ssh, _, _ = transport.connection(directory, fixtures.TransportTest.ENV)
            for command in [
                    ['ssh-keygen', '-l', '-E', 'sha256', '-f', str(directory / 'known_hosts')],
                    ['ssh-keygen', '-F', '[vps.example.invalid]:2222', '-f', str(directory / 'known_hosts')]]:
                result = subprocess.run(command, capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 0)
            unknown = subprocess.run(['ssh-keygen', '-F', '[other.example.invalid]:2222', '-f', str(directory / 'known_hosts')],
                                     capture_output=True, text=True, timeout=10)
            self.assertEqual(unknown.returncode, 1)
            # -G prints effective client configuration and exits; no DNS/SSH connection.
            result = subprocess.run([ssh[0], '-G', *ssh[1:]], capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0)
            effective = dict(line.split(' ', 1) for line in result.stdout.splitlines() if ' ' in line)
            self.assertEqual(effective['stricthostkeychecking'], 'true')
            self.assertEqual(effective['globalknownhostsfile'], '/dev/null')
            self.assertEqual(effective['userknownhostsfile'], str(directory / 'known_hosts'))
            self.assertEqual(effective['hostkeyalgorithms'], 'ssh-ed25519')
            self.assertEqual(effective['verifyhostkeydns'], 'false')
            self.assertEqual(effective['updatehostkeys'], 'false')


if __name__ == '__main__':
    unittest.main()
