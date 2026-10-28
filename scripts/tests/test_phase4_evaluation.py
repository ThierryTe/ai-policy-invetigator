"""Protect evaluation reporting against scoring outages as successful abstention."""
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from evaluate_phase4 import case_result


class EvaluationReportingTest(unittest.TestCase):
    def test_provider_failure_is_an_error_even_for_insufficient_evidence(self):
        result = case_result({'expected': 'ABSTAIN'}, {'state': 'PARTIAL', 'error_code': 'PROVIDER_TIMEOUT'}, [])
        self.assertEqual(result['observed'], 'ERROR')
        self.assertFalse(result['matched'])

    def test_incomplete_coverage_is_not_no_conflict(self):
        result = case_result({'expected': 'ABSTAIN'}, {'state': 'PARTIAL', 'error_code': 'INCOMPLETE_ASSESSMENT'}, [])
        self.assertEqual(result['observed'], 'ABSTAIN')
        self.assertTrue(result['matched'])

    def test_extra_contradiction_is_not_hidden_by_a_no_conflict_label(self):
        result = case_result({'expected': 'NO_CONFLICT'}, {'state': 'COMPLETED'},
                             [{'classification': 'NO_CONFLICT'}, {'classification': 'CONTRADICTION'}])
        self.assertEqual(result['observed'], 'CONTRADICTION')
        self.assertFalse(result['matched'])

    def test_golden_cases_have_unique_ids_and_required_categories(self):
        dataset = json.loads((Path(__file__).resolve().parents[2] / 'evaluation/phase4-golden.json').read_text())
        cases = [c for group in dataset['groups'] for c in group['cases']]
        self.assertEqual(len(cases), 10)
        self.assertEqual(len({c['id'] for c in cases}), 10)
        self.assertTrue({'contradiction', 'non-conflict', 'exception', 'different-scope', 'ambiguity',
                         'insufficient-evidence', 'missing-requirement'} <= {c['category'] for c in cases})
