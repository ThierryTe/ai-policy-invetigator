"""Local preflight validation tests. No HTTP mocking or successful live-API claims."""
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('verify_meta_access', Path(__file__).resolve().parents[1] / 'verify_meta_access.py')
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


class MetaPreflightTest(unittest.TestCase):
    def fixture(self):
        return {'model': 'fixture-only', 'choices': [{'finish_reason': 'stop', 'message': {'content': '{"check":"meta-access-ok"}'}}],
                'usage': {'prompt_tokens': 3, 'completion_tokens': 4, 'total_tokens': 7}}

    def test_missing_credential_stops_before_any_request(self):
        evidence = probe.verify({})
        self.assertEqual(evidence['blocker'], 'MISSING_MODEL_API_KEY')
        self.assertEqual(evidence['requests'], [])
        self.assertFalse(evidence['authenticated_inference_verified'])

    def test_rejects_malformed_structured_output(self):
        for text in ['not JSON', '{"check":"wrong"}', '{"check":"meta-access-ok","extra":"fabricated"}']:
            response = self.fixture(); response['choices'][0]['message']['content'] = text
            with self.assertRaises(probe.ProbeBlocked): probe.validate_completion(response)

    def test_incomplete_output_and_missing_usage_do_not_pass(self):
        response = self.fixture(); response['choices'][0]['finish_reason'] = 'length'
        with self.assertRaises(probe.ProbeBlocked): probe.validate_completion(response)
        response = self.fixture(); del response['usage']
        with self.assertRaises(probe.ProbeBlocked): probe.validate_completion(response)
        response = self.fixture(); response['usage']['total_tokens'] = 999
        with self.assertRaises(probe.ProbeBlocked): probe.validate_completion(response)

    def test_validates_usage_shape_without_claiming_real_access(self):
        self.assertEqual(probe.validate_completion(self.fixture())['total_tokens'], 7)


if __name__ == '__main__':
    unittest.main()
