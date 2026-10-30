"""Public deployment probe regressions; no network, Docker, SSH or credentials."""
import contextlib
from pathlib import Path
import ssl
import subprocess
import sys
import unittest
import urllib.error
from unittest.mock import Mock, call, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import production_release as controller
import transfer_production_release as transport
from deploy_local_images import DeploymentError


BASE = 'https://example.invalid'
AGENT = 'AI-Policy-Investigator-Deployment/1.0'


class PublicRoutingTest(unittest.TestCase):
    def test_identified_get_avoids_generic_python_agent_rejection(self):
        def edge(request, timeout):
            status = 200 if request.get_header('User-agent') == AGENT else 403
            return contextlib.nullcontext(Mock(status=status))

        with patch.object(controller.urllib.request, 'build_opener') as build:
            build.return_value.open.side_effect = edge
            controller.check_url(BASE + '/healthz', 200)
            build.return_value.open.assert_called_once()
            args, kwargs = build.return_value.open.call_args
            request = args[0]
            self.assertEqual(request.full_url, BASE + '/healthz')
            self.assertEqual(request.get_method(), 'GET')
            self.assertIsNone(request.data)
            self.assertFalse(request.has_header('Authorization'))
            self.assertFalse(request.has_header('Cookie'))
            self.assertEqual(kwargs, {'timeout': 20})

    def test_exact_public_status_contract(self):
        for path, expected in [('/healthz', 200), ('/', 200), ('/api/auth/me', 401)]:
            with self.subTest(path=path), patch.object(controller.urllib.request, 'build_opener') as build:
                if expected == 401:
                    build.return_value.open.side_effect = urllib.error.HTTPError(
                        BASE + path, expected, 'Unauthorized', {}, None)
                else:
                    build.return_value.open.return_value = contextlib.nullcontext(Mock(status=expected))
                controller.check_url(BASE + path, expected)

    def test_redirects_denials_rate_limits_and_outages_still_fail(self):
        for path, expected, probe in [('/healthz', 200, 'HEALTHZ'), ('/', 200, 'ROOT'),
                                      ('/api/auth/me', 401, 'AUTH_ME')]:
            for actual in [200, 204, 301, 302, 307, 308, 401, 403, 404, 429, 500, 502, 503, 504]:
                if actual == expected:
                    continue
                with self.subTest(path=path, actual=actual), \
                     patch.object(controller.urllib.request, 'build_opener') as build:
                    build.return_value.open.side_effect = urllib.error.HTTPError(
                        BASE + path, actual, 'private-response-marker',
                        {'Location': 'https://login.example.invalid/private'}, None)
                    with self.assertRaisesRegex(DeploymentError,
                            f'^PUBLIC_ROUTING_STATUS_FAILED_GET_{probe}_EXPECTED_{expected}_GOT_{actual}$'):
                        controller.check_url(BASE + path, expected)
                    build.return_value.open.assert_called_once()

    def test_default_tls_verification_and_redirect_rejection_are_preserved(self):
        real_build = controller.urllib.request.build_opener
        with patch.object(controller.urllib.request, 'build_opener') as build:
            build.return_value.open.return_value = contextlib.nullcontext(Mock(status=200))
            controller.check_url(BASE + '/', 200)
            handler_type, = build.call_args.args
            handler = handler_type()
            self.assertIsNone(handler.redirect_request(
                controller.urllib.request.Request(BASE), None, 302, 'Found', {},
                'https://login.example.invalid/'))
            opener = real_build(handler)
            https = next(h for h in opener.handlers if isinstance(h, controller.urllib.request.HTTPSHandler))
            # Older supported Python versions defer creating the default context.
            context = https._context or ssl.create_default_context()
            self.assertTrue(context.check_hostname)
            self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)

    def test_network_timeout_and_invalid_tls_fail_without_private_diagnostics(self):
        for error in [urllib.error.URLError('private-host'), TimeoutError('private-host'),
                      urllib.error.URLError(ssl.SSLCertVerificationError('private-certificate'))]:
            with self.subTest(error=type(error)), \
                 patch.object(controller.urllib.request, 'build_opener') as build:
                build.return_value.open.side_effect = error
                with self.assertRaisesRegex(DeploymentError, '^PUBLIC_ROUTING_NETWORK_OR_TLS_FAILED$'):
                    controller.check_url(BASE + '/', 200)
                build.return_value.open.assert_called_once()

    def test_internal_checks_precede_separate_public_gets(self):
        with patch.object(controller, 'execute', side_effect=['', 'HTTP/1.1 401 Unauthorized']) as execute, \
             patch.object(controller, 'check_url') as check:
            controller.routing(['compose'], {}, BASE)
            self.assertIn('http://127.0.0.1:8080/healthz', execute.call_args_list[0].args[0])
            self.assertIn('--spider', execute.call_args_list[0].args[0])
            self.assertIn('http://127.0.0.1:8080/api/auth/me', execute.call_args_list[1].args[0][-1])
            self.assertEqual(check.call_args_list, [call(BASE + '/healthz', 200),
                             call(BASE + '/', 200), call(BASE + '/api/auth/me', 401)])
        for output in ['HTTP/1.1 200 OK', 'HTTP/1.1 302 Found', 'HTTP/1.1 502 Bad Gateway', '']:
            with self.subTest(output=output), \
                 patch.object(controller, 'execute', side_effect=['', output]), \
                 patch.object(controller, 'check_url') as check:
                with self.assertRaisesRegex(DeploymentError, 'NOT_PROTECTED_OR_UNREACHABLE'):
                    controller.routing(['compose'], {}, BASE)
                check.assert_not_called()

    def test_safe_status_detail_survives_ssh_error_filter(self):
        code = 'PUBLIC_ROUTING_STATUS_FAILED_GET_AUTH_ME_EXPECTED_401_GOT_403'
        result = subprocess.CompletedProcess(['ssh'], 2, '', 'private diagnostic\n' + code + '\n')
        with patch.object(transport.subprocess, 'run', return_value=result):
            with self.assertRaisesRegex(DeploymentError, '^SSH_RELEASE_FAILED: ' + code + '$'):
                transport.execute(['ssh'], 'SSH_RELEASE_FAILED')


if __name__ == '__main__':
    unittest.main()
