"""Controlled artifact/bootstrap failure tests; synthetic bytes are not an ONNX model."""
import contextlib
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
import urllib.error

spec = importlib.util.spec_from_file_location('fetch_embeddings', Path(__file__).resolve().parents[1] / 'fetch_embeddings.py')
fetch = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fetch)


class EmbeddingBootstrapTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.data = b'controlled artifact fixture'
        self.artifact = ('onnx/model.onnx', len(self.data), 'sha256', hashlib.sha256(self.data).hexdigest())

    def test_pins_match_the_previously_verified_model_provenance(self):
        provenance = json.loads((fetch.ROOT / 'docs/provenance/embedding-model.json').read_text())
        self.assertEqual(fetch.REVISION, provenance['revision'])
        self.assertEqual(fetch.ARTIFACTS['model.onnx'][3], provenance['model_sha256'])
        self.assertEqual(fetch.ARTIFACTS['tokenizer.json'][3], provenance['tokenizer_sha256'])
        self.assertEqual(provenance['dimensions'], 384)

    def test_valid_download_is_published_only_after_verification(self):
        result = fetch.ensure_artifact(self.directory, 'model.onnx', self.artifact,
                                      opener=lambda request, timeout: io.BytesIO(self.data))
        self.assertEqual(result, 'downloaded')
        self.assertEqual((self.directory / 'model.onnx').read_bytes(), self.data)
        self.assertEqual((self.directory / 'model.onnx').stat().st_mode & 0o777, 0o444)
        self.assertEqual(list(self.directory.glob('*.part')), [])

    def test_valid_cache_does_not_use_network(self):
        (self.directory / 'model.onnx').write_bytes(self.data)
        def offline(*args, **kwargs):
            raise AssertionError('Network must not be used for a verified cache')
        self.assertEqual(fetch.ensure_artifact(self.directory, 'model.onnx', self.artifact, opener=offline), 'cached')

    def test_invalid_cache_fails_without_overwrite_or_download(self):
        target = self.directory / 'model.onnx'; target.write_bytes(b'invalid')
        def offline(*args, **kwargs):
            raise AssertionError('Invalid cache must fail before any download')
        with self.assertRaises(fetch.ArtifactFailure) as error:
            fetch.ensure_artifact(self.directory, 'model.onnx', self.artifact, opener=offline)
        self.assertEqual(error.exception.code, 'INVALID_CACHED_ARTIFACT')
        self.assertEqual(target.read_bytes(), b'invalid')

    def test_bad_download_and_oversized_response_leave_no_artifact_or_partial(self):
        for data in [b'x' * len(self.data), self.data + b'oversized']:
            with self.assertRaises(fetch.ArtifactFailure):
                fetch.ensure_artifact(self.directory, 'model.onnx', self.artifact,
                                      opener=lambda request, timeout: io.BytesIO(data))
            self.assertFalse((self.directory / 'model.onnx').exists())
            self.assertEqual(list(self.directory.glob('*.part')), [])

    def test_network_retries_are_bounded(self):
        attempts = []
        def unavailable(*args, **kwargs):
            attempts.append(1)
            raise urllib.error.URLError('controlled offline fixture')
        with self.assertRaises(fetch.ArtifactFailure) as error:
            fetch.ensure_artifact(self.directory, 'model.onnx', self.artifact, opener=unavailable, pause=lambda delay: None)
        self.assertEqual(len(attempts), fetch.ATTEMPTS)
        self.assertEqual(error.exception.code, 'DOWNLOAD_NETWORK_OR_IO_FAILED')
        self.assertFalse((self.directory / 'model.onnx').exists())

    def test_cli_reports_corrupt_cache_with_safe_nonzero_exit(self):
        (self.directory / 'model.onnx').write_bytes(b'invalid')
        output = io.StringIO()
        with contextlib.redirect_stderr(output):
            code = fetch.main(['--directory', str(self.directory), '--no-env-file'])
        self.assertEqual(code, 2)
        self.assertIn('INVALID_CACHED_ARTIFACT (model.onnx)', output.getvalue())
        self.assertNotIn('Traceback', output.getvalue())


if __name__ == '__main__':
    unittest.main()
