"""Real migrated artifacts, with network forbidden for the entire validation."""
import unittest
from unittest.mock import patch
from src.validate import validate, privacy_check
from src.common import ROOT


class MigratedReleaseIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with patch("socket.socket", side_effect=AssertionError("network forbidden")):
            cls.report = validate(ROOT)

    def test_all_engineering_stages_complete(self):
        self.assertEqual(self.report["blocked_stages"], [])

    def test_raw_data_source_chain(self):
        s = self.report["stages"]["raw_source_chain"]
        self.assertEqual((s["participants"], s["windows"], s["daily_rows"]), (16, 48, 2016))
        self.assertEqual(s["numeric_source_fields_checked"], 10080)
        self.assertEqual(s["sleep_source_fields_checked"], 14112)

    def test_silver_rejected_records_preserved(self):
        s = self.report["stages"]["silver"]
        self.assertEqual((s["records"], s["accepted_by_historical_reference_schema"], s["not_accepted"]), (160, 119, 41))
        self.assertFalse(s["human_gold"])

    def test_c0_replays_original_content_including_failures(self):
        s = self.report["stages"]["baseline_and_c0_replay"]
        self.assertEqual((s["total_records"], s["c0_explanation_cards"], s["c0_failure_slots"]), (200, 140, 21))
        self.assertIsNone(s["decision_accuracy"])

    def test_no_inference_or_training(self):
        self.assertEqual((self.report["new_model_calls"], self.report["training_runs"], self.report["new_methods_implemented"]), (0, 0, 0))

    def test_private_records_excluded_from_git(self):
        self.assertEqual(privacy_check(ROOT)["private_paths_in_index"], 0)


if __name__ == "__main__": unittest.main()
