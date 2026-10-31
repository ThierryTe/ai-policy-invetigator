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
                           {'status': 'behind', 'files': [{'filename': 'pom.xml'}]},
                           {'status': 'ahead', 'files': [{'filename': 'x'}] * 300}]:
            with self.assertRaises(DeploymentError):
                classify({'before': 'a' * 40, 'after': 'b' * 40}, Mock(return_value=comparison))

    def test_pull_request_divergence_is_valid_and_runtime_inputs_are_still_detected(self):
        event = {'pull_request': {'base': {'sha': 'a' * 40}, 'head': {'sha': 'b' * 40}}}
        lookup = Mock(return_value={'status': 'diverged', 'files': [{'filename': 'pom.xml'}]})
        self.assertTrue(classify(event, lookup))
        lookup.assert_called_once_with('a' * 40, 'b' * 40)

    def test_diverged_tooling_only_push_checks_both_sides_and_reuses_images(self):
        lookup = Mock(side_effect=[
            {'status': 'diverged', 'files': [{'filename': 'scripts/reviewed_v8_release.py'}]},
            {'status': 'diverged', 'files': [{'filename': 'docs/DEPLOYMENT.md'}]},
        ])
        self.assertFalse(classify({'before': 'a' * 40, 'after': 'b' * 40}, lookup))
        self.assertEqual(lookup.call_args_list, [(('a' * 40, 'b' * 40),), (('b' * 40, 'a' * 40),)])

    def test_diverged_push_detects_runtime_inputs_on_either_side_including_renames(self):
        tooling = {'status': 'diverged', 'files': [{'filename': 'docs/DEPLOYMENT.md'}]}
        for runtime_file in [{'filename': 'pom.xml'},
                             {'filename': 'docs/removed.txt', 'previous_filename': 'src/removed.txt'}]:
            runtime = {'status': 'diverged', 'files': [runtime_file]}
            for comparisons in [[runtime, tooling], [tooling, runtime]]:
                with self.subTest(comparisons=comparisons):
                    lookup = Mock(side_effect=comparisons)
                    self.assertTrue(classify({'before': 'a' * 40, 'after': 'b' * 40}, lookup))
                    self.assertEqual(lookup.call_count, 2)

    def test_diverged_push_rejects_incomplete_invalid_or_inconsistent_reverse_comparison(self):
        for comparison in [{}, {'status': 'diverged'}, {'status': 'diverged', 'files': []},
                           {'status': 'diverged', 'files': [{}]},
                           {'status': 'diverged', 'files': [{'filename': 'x', 'previous_filename': None}]},
                           {'status': 'diverged', 'files': [{'filename': 'x'}] * 300},
                           {'status': 'ahead', 'files': [{'filename': 'x'}]},
                           {'status': 'identical', 'files': []}]:
            with self.subTest(comparison=comparison):
                lookup = Mock(side_effect=[
                    {'status': 'diverged', 'files': [{'filename': 'pom.xml'}]}, comparison])
                with self.assertRaises(DeploymentError):
                    classify({'before': 'a' * 40, 'after': 'b' * 40}, lookup)

    def test_diverged_push_reverse_api_failure_is_not_ignored(self):
        lookup = Mock(side_effect=[
            {'status': 'diverged', 'files': [{'filename': 'docs/DEPLOYMENT.md'}]}, OSError('API unavailable')])
        with self.assertRaises(OSError):
            classify({'before': 'a' * 40, 'after': 'b' * 40}, lookup)


if __name__ == '__main__':
    unittest.main()
