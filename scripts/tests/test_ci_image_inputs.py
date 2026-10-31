"""Build/publication gating without Git, network or image builds."""
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ci_image_inputs import classify, needs_images
from deploy_local_images import DeploymentError


class ImageInputsTest(unittest.TestCase):
    def test_tooling_only_change_keeps_tests_and_reuses_published_images(self):
        files = ['scripts/v7_backup_restore.py', 'scripts/ci_image_inputs.py', '.github/workflows/verify.yml',
                 '.github/workflows/deploy-production.yml', 'docs/V7_BACKUP_RESTORE.md', 'compose.production.yaml']
        self.assertFalse(needs_images(files))
        comparison = {'status': 'ahead', 'files': [{'filename': f} for f in files]}
        self.assertFalse(classify({'before': 'a' * 40, 'after': 'b' * 40}, Mock(return_value=comparison)))

    def test_all_docker_copy_inputs_and_both_dockerfiles_trigger_normal_build(self):
        for path in ['pom.xml', 'mvnw', '.mvn/wrapper/maven-wrapper.properties', 'src/main/resources/config.yml',
                     'src/main/java/App.java', '.dockerignore', 'deploy/backend/Dockerfile',
                     'deploy/embeddings/Dockerfile', 'scripts/fetch_embeddings.py']:
            self.assertTrue(needs_images([path]), path)

    def test_rename_out_of_runtime_and_initial_source_publication_require_images(self):
        comparison = {'status': 'ahead', 'files': [{'filename': 'docs/old.txt', 'previous_filename': 'src/removed.txt'}]}
        self.assertTrue(classify({'before': 'a' * 40, 'after': 'b' * 40}, Mock(return_value=comparison)))
        lookup = Mock()
        self.assertTrue(classify({'before': '0' * 40, 'after': 'b' * 40}, lookup))
        lookup.assert_not_called()

    def test_unknown_truncated_or_non_linear_push_fails_without_guessing_a_build(self):
        for comparison in [{}, {'status': 'ahead', 'files': []}, {'status': 'ahead', 'files': [{}]},
                           {'status': 'diverged', 'files': [{'filename': 'pom.xml'}]},
                           {'status': 'ahead', 'files': [{'filename': 'x'}] * 300}]:
            with self.assertRaises(DeploymentError):
                classify({'before': 'a' * 40, 'after': 'b' * 40}, Mock(return_value=comparison))

    def test_pull_request_divergence_is_valid_and_runtime_inputs_are_still_detected(self):
        event = {'pull_request': {'base': {'sha': 'a' * 40}, 'head': {'sha': 'b' * 40}}}
        self.assertTrue(classify(event, Mock(return_value={'status': 'diverged', 'files': [{'filename': 'pom.xml'}]})))


if __name__ == '__main__':
    unittest.main()
