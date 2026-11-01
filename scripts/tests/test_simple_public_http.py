"""Public HTTP and recovery regressions: no network, SSH, Docker daemon or real waits."""
from contextlib import nullcontext, redirect_stderr
import io
import json
from pathlib import Path
import ssl
import subprocess
import sys
import unittest
import urllib.error
from unittest.mock import Mock, call, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import simple_deploy as deploy
import simple_diagnostics as diagnostics
import simple_ssh as ssh
import test_simple_pipeline as fixtures


PROBES = [('/', 200, b'<html><app-root></app-root></html>'),
          ('/healthz', 200, b'ok\n'), ('/api/auth/me', 401, b'')]


def response(code, body):
    return nullcontext(Mock(status=code, read=Mock(return_value=body)))


def normal_response(request, timeout):
    path = request.full_url.removeprefix(deploy.PUBLIC)
    _, code, body = next(probe for probe in PROBES if probe[0] == path)
    if code == 401:
        raise urllib.error.HTTPError(request.full_url, code, 'private-message', {}, io.BytesIO(b'private-body'))
    return response(code, body)


class PublicRequestTest(unittest.TestCase):
    def test_exact_identified_anonymous_gets_and_socket_timeout(self):
        def edge(request, timeout):
            if request.get_header('User-agent') != 'AI-Policy-Investigator-Deployment/1.0':
                raise urllib.error.HTTPError(request.full_url, 403, 'Blocked', {}, None)
            return normal_response(request, timeout)

        with patch.object(deploy.urllib.request, 'build_opener') as build:
            build.return_value.open.side_effect = edge
            deploy.public_check()
        requests = build.return_value.open.call_args_list
        self.assertEqual([item.args[0].full_url for item in requests],
                         ['https://ai-policy.tewendelabs.com' + path for path, _, _ in PROBES])
        for item in requests:
            self.assertEqual(item.args[0].get_method(), 'GET')
            self.assertIsNone(item.args[0].get_header('Authorization'))
            self.assertIsNone(item.args[0].get_header('Cookie'))
            self.assertEqual(item.kwargs, {'timeout': 10})

    def test_each_route_rejects_every_wrong_status_including_spa_auth_fallback(self):
        for index, (path, expected, _) in enumerate(PROBES):
            for actual in (200, 204, 301, 302, 303, 307, 308, 401, 403, 404, 429, 500, 502, 503, 504):
                if actual == expected:
                    continue
                payload = io.BytesIO(b'private-body')
                error = urllib.error.HTTPError(deploy.PUBLIC + path, actual, 'private-message',
                                               {'Location': 'https://private.invalid/'}, payload)
                replies = [response(code, body) for _, code, body in PROBES[:index]] + [error]
                captured = io.StringIO()
                with self.subTest(path=path, status=actual), \
                        patch.object(deploy.urllib.request, 'build_opener') as build, redirect_stderr(captured):
                    build.return_value.open.side_effect = replies
                    with self.assertRaisesRegex(deploy.DeployError, '^PUBLIC_HTTP_CHECK_FAILED$'):
                        deploy.public_check()
                    self.assertEqual(build.return_value.open.call_count, index + 1)
                self.assertTrue(payload.closed)
                events = [json.loads(line.removeprefix(diagnostics.PREFIX)) for line in captured.getvalue().splitlines()]
                failed = events[-1]
                self.assertEqual(failed['step'], ['public.root', 'public.healthz', 'public.auth_me'][index])
                self.assertEqual(failed['http_status'], actual)
                self.assertEqual(failed['reason'], 'public_http')
                self.assertNotIn('private', captured.getvalue())

    def test_angular_and_health_content_checks_are_preserved(self):
        cases = [(0, b'<html>proxy page</html>', 'ANGULAR_APPLICATION_MISSING'),
                 (1, b'<app-root></app-root>', 'FRONTEND_HEALTH_BODY_INVALID'),
                 (1, b'UP', 'FRONTEND_HEALTH_BODY_INVALID'),
                 (1, b'', 'FRONTEND_HEALTH_BODY_INVALID')]
        for index, body, code in cases:
            replies = [response(status, content) for _, status, content in PROBES[:index]]
            replies.append(response(200, body))
            with self.subTest(code=code, body=body), patch.object(deploy.urllib.request, 'build_opener') as build:
                build.return_value.open.side_effect = replies
                with self.assertRaisesRegex(deploy.DeployError, '^' + code + '$'):
                    deploy.public_check()

    def test_tls_verification_and_redirect_rejection_are_preserved(self):
        real_build = deploy.urllib.request.build_opener
        with patch.object(deploy.urllib.request, 'build_opener') as build:
            build.return_value.open.side_effect = normal_response
            deploy.public_check()
        handler_type, = build.call_args.args
        handler = handler_type()
        for status in (301, 302, 303, 307, 308):
            for target in (deploy.PUBLIC + '/login', 'https://login.invalid/'):
                self.assertIsNone(handler.redirect_request(
                    deploy.urllib.request.Request(deploy.PUBLIC), None, status, 'Redirect', {}, target))
        opener = real_build(handler)
        https = next(item for item in opener.handlers if isinstance(item, deploy.urllib.request.HTTPSHandler))
        context = https._context or ssl.create_default_context()
        self.assertTrue(context.check_hostname)
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)

    def test_network_and_tls_failures_are_safe_and_retryable(self):
        for error in (urllib.error.URLError('private-host'), TimeoutError('private-timeout'),
                      ConnectionResetError('private-connection'),
                      urllib.error.URLError(ssl.SSLCertVerificationError('private-certificate'))):
            with self.subTest(error=type(error)), patch.object(deploy.urllib.request, 'build_opener') as build, \
                    patch.object(deploy.time, 'sleep') as sleep, redirect_stderr(io.StringIO()) as captured:
                build.return_value.open.side_effect = [error, *[response(code, body) for _, code, body in PROBES]]
                deploy.wait_for_public()
                sleep.assert_called_once_with(5)
                self.assertEqual(build.return_value.open.call_count, 4)
                self.assertNotIn('private', captured.getvalue())

    def test_retry_rechecks_all_routes_and_stops_immediately_after_success(self):
        error = urllib.error.HTTPError(deploy.PUBLIC + '/api/auth/me', 502, 'Bad Gateway', {}, None)
        replies = [response(code, body) for _, code, body in PROBES[:2]] + [error]
        replies += [response(code, body) for _, code, body in PROBES]
        with patch.object(deploy.urllib.request, 'build_opener') as build, patch.object(deploy.time, 'sleep') as sleep:
            build.return_value.open.side_effect = replies
            deploy.wait_for_public()
        self.assertEqual([item.args[0].full_url for item in build.return_value.open.call_args_list],
                         [deploy.PUBLIC + path for path, _, _ in PROBES] * 2)
        sleep.assert_called_once_with(5)

    def test_body_timeout_is_a_connection_failure_and_does_not_expose_exception(self):
        slow = Mock(status=200, read=Mock(side_effect=TimeoutError('private-body-timeout')))
        with patch.object(deploy.urllib.request, 'build_opener') as build, redirect_stderr(io.StringIO()) as captured:
            build.return_value.open.return_value = nullcontext(slow)
            with self.assertRaisesRegex(deploy.DeployError, '^PUBLIC_TLS_OR_CONNECTION_FAILED$'):
                deploy.public_check()
        self.assertNotIn('private', captured.getvalue())

    def test_public_verification_cannot_start_before_internal_readiness(self):
        ready = {'Id': 'test-id', 'Image': 'expected', 'State': {'Running': True, 'Health': {'Status': 'healthy'}}}
        unhealthy = {**ready, 'State': {'Running': True, 'Health': {'Status': 'starting'}}}
        cases = [(unhealthy, [], 'CONTAINER_UNHEALTHY'),
                 (ready, ['[{"Id":"expected"}]', '[{"Id":"expected"}]', '{"status":"DOWN"}'],
                  'BACKEND_OR_WORKERS_NOT_READY')]
        for row, replies, code in cases:
            with self.subTest(code=code), patch.object(deploy, 'container', return_value=row), \
                    patch.object(deploy, 'run', side_effect=replies), \
                    patch.object(deploy.urllib.request, 'build_opener') as build:
                with self.assertRaisesRegex(deploy.DeployError, '^' + code + '$'):
                    deploy.verify(fixtures.IMAGES)
                build.assert_not_called()


class PublicLifecycleTest(unittest.TestCase):
    setUp = fixtures.DeploymentTest.setUp

    def exercise(self, responder):
        self.trace = []
        self.public_calls = []
        self.previous['images'] = {'backend': 'sha256:old-backend', 'frontend': 'sha256:old-frontend',
                                   'postgres': self.images['postgres'], 'worker_probe': False}
        row = {'Id': 'synthetic-id', 'Image': self.images['postgres'],
               'State': {'Running': True, 'Health': {'Status': 'healthy'}}}

        def run(command, env=None, **kwargs):
            self.trace.append((diagnostics.PHASE.get(), kwargs['step'], command, env))
            if kwargs['step'].startswith('image.') and kwargs['step'].endswith('.inspect'):
                return json.dumps([{'Id': row['Image']}])
            return '{"status":"UP"}' if kwargs['step'] == 'workers.health' else ''

        def probe(request, timeout):
            current_phase = diagnostics.PHASE.get()
            self.public_calls.append((current_phase, request.full_url))
            self.trace.append((current_phase, 'public', request.full_url, None))
            return responder(current_phase, request, timeout)

        self.output = io.StringIO()
        with patch.object(deploy, 'container', return_value=row), \
                patch.object(deploy, 'check_topology', return_value=(['backend-compose'], ['frontend-compose'], {})), \
                patch.object(deploy, 'snapshot', return_value=self.previous) as snapshot, \
                patch.object(deploy, 'run', side_effect=run), \
                patch.object(deploy, 'history', return_value=self.previous['history']), \
                patch.object(deploy.urllib.request, 'build_opener') as build, \
                patch.object(deploy.time, 'sleep') as sleep, redirect_stderr(self.output):
            build.return_value.open.side_effect = probe
            try:
                deploy.deploy(self.bundle, self.env_file, self.state)
            except deploy.DeployError as error:
                result = str(error)
            else:
                result = 'OK'
        return result, sleep, snapshot

    def test_preflight_http_failure_retries_without_pull_snapshot_update_or_rollback(self):
        def responder(phase, request, timeout):
            return response(503, b'private-body')

        result, sleep, snapshot = self.exercise(responder)
        self.assertEqual(result, 'PUBLIC_HTTP_CHECK_FAILED')
        self.assertEqual(len(self.public_calls), 12)
        self.assertEqual(sleep.call_count, 11)
        snapshot.assert_not_called()
        self.assertTrue(all(item[1] == 'public' and item[0] == 'preflight' for item in self.trace))
        self.assertNotIn('ROLLBACK_STARTED', self.output.getvalue())
        self.assertFalse((self.state / 'previous.json').exists())
        self.assertFalse((self.state / 'current.json').exists())

    def test_transient_preflight_and_post_update_failures_recover_in_place(self):
        counts = {}

        def responder(phase, request, timeout):
            counts[phase] = counts.get(phase, 0) + 1
            return response(502, b'') if counts[phase] == 1 else normal_response(request, timeout)

        result, sleep, _ = self.exercise(responder)
        self.assertEqual(result, 'OK')
        self.assertEqual(sleep.call_args_list, [call(5), call(5)])
        self.assertEqual(counts, {'preflight': 4, 'verify': 4})
        self.assertTrue((self.state / 'current.json').is_file())
        self.assertNotIn('ROLLBACK_STARTED', self.output.getvalue())
        steps = [(item[0], item[1]) for item in self.trace]
        self.assertLess(steps.index(('update', 'compose.backend.up')), steps.index(('update', 'compose.frontend.up')))
        self.assertLess(steps.index(('update', 'compose.frontend.up')), steps.index(('verify', 'workers.health')))
        self.assertLess(steps.index(('verify', 'workers.health')), steps.index(('verify', 'public')))
        for _, step, command, _ in self.trace:
            if step.endswith('.up'):
                self.assertIn('--wait', command)
                self.assertEqual(command[command.index('--wait-timeout') + 1], '240')

    def test_exhausted_post_update_probe_restores_and_verifies_previous_images(self):
        def responder(phase, request, timeout):
            return response(502, b'') if phase == 'verify' else normal_response(request, timeout)

        result, sleep, _ = self.exercise(responder)
        self.assertEqual(result, 'DEPLOY_FAILED_ROLLBACK_SUCCEEDED_DATABASE_UNCHANGED')
        self.assertEqual(sleep.call_count, 11)
        self.assertEqual(len([p for p, _ in self.public_calls if p == 'verify']), 12)
        self.assertEqual([url for p, url in self.public_calls if p == 'rollback'],
                         [deploy.PUBLIC + path for path, _, _ in PROBES])
        restorations = [item for item in self.trace if item[0] == 'rollback' and item[1].endswith('.up')]
        self.assertEqual([item[2][-1] for item in restorations], ['backend', 'frontend'])
        for _, _, command, env in restorations:
            self.assertEqual(env['BACKEND_IMAGE_REF'], 'sha256:old-backend')
            self.assertEqual(env['FRONTEND_IMAGE_REF'], 'sha256:old-frontend')
            self.assertEqual(command[command.index('--pull') + 1], 'never')
        self.assertIn('ROLLBACK_STARTED', self.output.getvalue())
        self.assertIn('ROLLBACK_SUCCEEDED', self.output.getvalue())
        self.assertFalse((self.state / 'current.json').exists())
        self.assertFalse((self.state / 'blocked.json').exists())

    def test_failed_public_check_during_rollback_is_blocked_and_never_reported_as_success(self):
        def responder(phase, request, timeout):
            return normal_response(request, timeout) if phase == 'preflight' else response(503, b'')

        result, sleep, _ = self.exercise(responder)
        self.assertEqual(result, 'DEPLOY_FAILED_ROLLBACK_FAILED_OR_BLOCKED_REVIEW_PRIVATE_STATE')
        self.assertEqual(sleep.call_count, 22)
        self.assertTrue((self.state / 'blocked.json').is_file())
        self.assertIn('ROLLBACK_STARTED', self.output.getvalue())
        self.assertIn('ROLLBACK_FAILED', self.output.getvalue())
        self.assertNotIn('ROLLBACK_SUCCEEDED', self.output.getvalue())
        self.assertFalse((self.state / 'current.json').exists())

    def test_rollback_retries_its_own_transient_public_failure_before_success(self):
        rollback_requests = 0

        def responder(phase, request, timeout):
            nonlocal rollback_requests
            if phase == 'verify':
                return response(502, b'')
            if phase == 'rollback':
                rollback_requests += 1
                if rollback_requests == 1:
                    return response(503, b'')
            return normal_response(request, timeout)

        result, sleep, _ = self.exercise(responder)
        self.assertEqual(result, 'DEPLOY_FAILED_ROLLBACK_SUCCEEDED_DATABASE_UNCHANGED')
        self.assertEqual(rollback_requests, 4)
        self.assertEqual(sleep.call_count, 12)
        self.assertIn('ROLLBACK_SUCCEEDED', self.output.getvalue())
        self.assertFalse((self.state / 'blocked.json').exists())


class PublicDiagnosticTest(unittest.TestCase):
    def test_phase_route_expected_status_actual_status_and_attempt_survive_transport(self):
        remote = io.StringIO()
        with diagnostics.phase('verify'), redirect_stderr(remote):
            diagnostics.emit('public.auth_me', 'failed', 'public_http', http_status=403, attempt=12)
        result = subprocess.CompletedProcess(['ssh'], 1, 'private-stdout', remote.getvalue() + 'PUBLIC_HTTP_CHECK_FAILED\n')
        captured = io.StringIO()
        with patch.object(ssh.subprocess, 'run', return_value=result), redirect_stderr(captured), \
                self.assertRaisesRegex(ValueError, '^PUBLIC_HTTP_CHECK_FAILED$'):
            ssh.execute(['ssh'])
        for expected in ('phase=verify', 'step=public.auth_me', 'GET https://ai-policy.tewendelabs.com/api/auth/me',
                         'expected HTTP 401', 'http_status=403', 'attempt=12'):
            self.assertIn(expected, captured.getvalue())
        self.assertNotIn('private', captured.getvalue())

    def test_public_metadata_is_strictly_validated_before_forwarding(self):
        event = dict(phase='preflight', step='public.root', result='failed', reason='public_http',
                     exit_code=None, http_status=503, attempt=1)
        self.assertTrue(diagnostics.validated_event(event))
        invalid = [{**event, 'http_status': value} for value in ('secret', True, [], 99, 600)]
        invalid += [{**event, 'attempt': value} for value in ('secret', True, None, 0, 101)]
        invalid += [{**event, 'body': 'secret'}, {**event, 'url': 'secret'}, {**event, 'step': 'command'},
                    {key: value for key, value in event.items() if key != 'attempt'}]
        captured = io.StringIO()
        with redirect_stderr(captured):
            diagnostics.forward('\n'.join(diagnostics.PREFIX + json.dumps(value) for value in invalid))
        self.assertEqual(captured.getvalue(), '')


if __name__ == '__main__':
    unittest.main()
