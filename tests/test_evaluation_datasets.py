from __future__ import annotations

from unittest import TestCase

from app.evaluation import build_sample_evaluation_cases


class EvaluationDatasetTests(TestCase):
    def test_builds_sample_cases(self) -> None:
        cases = build_sample_evaluation_cases()

        self.assertGreaterEqual(len(cases), 4)
        for case in cases:
            self.assertIn("case_id", case)
            self.assertIn("symbol", case)
            self.assertIn("expected_action", case)
            self.assertIn("expected_quality", case)
            self.assertIn("review_focus", case)


if __name__ == "__main__":
    import unittest

    unittest.main()
