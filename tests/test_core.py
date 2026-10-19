import copy
from datetime import date
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from src.common import Blocked, digest, inside, read, sha, write, ROOT
from src.datasets.releases import verify_release, load_cases
from src.datasets.splits import make_split, validate_split
from src.datasets.pmdata import number, sleep_metric, construct_cases, opaque
from src.annotation.client import SilverClient, request_options, audit_budget
from src.annotation.validation import validate
from src.baselines.adapter import validate_output, run
from src.evaluation.evidence import case_payload, resolve
from src.evaluation.review import top_pairs, make_cards, check_blinding


class ManifestTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "artifact.json").write_bytes(b'{"unchanged":true}\n')
        files = {"artifact.json": sha(self.root / "artifact.json")}
        write(self.root / "freeze.json", {"files": files, "release_id": digest(files, ascii=True)})

    def test_valid_original_p1_algorithm(self):
        self.assertEqual(verify_release(self.root, "p1")["files"].keys(), {"artifact.json"})

    def test_tampered_frozen_bytes_blocked(self):
        (self.root / "artifact.json").write_bytes(b'{}\n')
        with self.assertRaises(Blocked): verify_release(self.root, "p1")

    def test_extra_release_artifact_blocked(self):
        (self.root / "extra").touch()
        with self.assertRaises(Blocked): verify_release(self.root, "p1")

    def test_manifest_self_hash_tamper_blocked(self):
        f = read(self.root / "freeze.json"); f["release_id"] = "0" * 64
        (self.root / "freeze.json").write_text(json.dumps(f))
        with self.assertRaises(Blocked): verify_release(self.root, "p1")

    def test_artifact_write_is_exclusive(self):
        before = (self.root / "artifact.json").read_bytes()
        with self.assertRaises(FileExistsError): write(self.root / "artifact.json", {})
        self.assertEqual(before, (self.root / "artifact.json").read_bytes())

    def test_path_escape_blocked(self):
        with self.assertRaises(Blocked): inside(self.root, "../outside")


class DatasetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.cases = load_cases(ROOT)

    def test_split_counts_and_reproducibility(self):
        split = make_split(self.cases)
        self.assertEqual(split, make_split(list(reversed(self.cases))))
        counts = validate_split(self.cases, split)
        self.assertEqual([counts[s]["windows"] for s in ("train", "dev", "test")], [30, 9, 9])

    def test_participant_leakage_blocks(self):
        split = make_split(self.cases)
        split["partitions"]["test"]["subject_ids"].append(split["partitions"]["train"]["subject_ids"][0])
        split["id"] = digest({k: v for k, v in split.items() if k != "id"})
        with self.assertRaises(Blocked): validate_split(self.cases, split)

    def test_omitted_window_blocks(self):
        split = make_split(self.cases); split["partitions"]["train"]["case_ids"].pop()
        split["id"] = digest({k: v for k, v in split.items() if k != "id"})
        with self.assertRaises(Blocked): validate_split(self.cases, split)

    def test_duplicate_cases_block(self):
        with self.assertRaises(Blocked): make_split(self.cases + [self.cases[0]])

    def test_measurement_boolean_nan_and_negative_rejected(self):
        for value in (True, float("nan"), -1):
            with self.assertRaises(ValueError): number(value)

    def test_identical_and_conflicting_sleep(self):
        row = {"mainSleep": True, "startTime": "2019-11-01T23:00:00", "endTime": "2019-11-02T07:00:00",
               "dateOfSleep": "2019-11-02", "minutesAsleep": 450, "timeInBed": 480, "logId": 1, "type": "stages", "infoCode": 0}
        with tempfile.TemporaryDirectory() as temp:
            p = Path(temp) / "sleep.json"; p.write_text(json.dumps([row, row]))
            values = sleep_metric(p)[date(2019, 11, 2)]
            self.assertEqual(values["sleep_quality_flags"], ["repeated_identical_selected_sleep_fields"])
            p.write_text(json.dumps([row, {**row, "minutesAsleep": 400}]))
            self.assertEqual(sleep_metric(p)[date(2019, 11, 2)], {"sleep_quality_flags": ["ambiguous_main_sleep_all_sleep_fields_withheld"]})

    def test_importer_replays_all_frozen_cases(self):
        from src.datasets.pmdata import import_participant
        manifest = read(ROOT / "data/raw/pmdata/source_manifest.json")
        records = {p: import_participant(ROOT / "data/raw/pmdata" / p / "fitbit") for p in manifest["participants"]}
        cases, excluded, _ = construct_cases(records, read(ROOT / "data/releases/p1-v2/sampling_plan.json"),
            (ROOT / "local/identity/pseudonym.key").read_bytes())
        self.assertFalse(excluded)
        self.assertEqual(sorted(cases, key=lambda c: c["case_id"]), self.cases)

    def test_unknown_reference_rejected(self):
        for ref in ("d43.sleep_minutes", "daily_rows.2", "context.not_a_field"):
            with self.assertRaises(ValueError): resolve(self.cases[0], ref)

    def test_rhr_zero_excluded_from_summary(self):
        case = copy.deepcopy(self.cases[0])
        for d in case["days"]: d["metrics"]["resting_heart_rate_bpm"] = 0
        self.assertIsNone(resolve(case, "stats.current.resting_heart_rate_bpm.mean")[0])
        self.assertEqual(resolve(case, "d1.resting_heart_rate_bpm")[0], 0)


class AnnotationTests(unittest.TestCase):
    def test_cache_miss_cannot_call_network(self):
        with tempfile.TemporaryDirectory() as temp, patch("socket.socket", side_effect=AssertionError("network forbidden")):
            with self.assertRaises(Blocked): SilverClient(temp, model="qwen3.8-max").call([{"role": "user", "content": "test"}])

    def test_exact_cache_replay_and_model_separation(self):
        messages = [{"role": "user", "content": "Fixture only"}]
        request = request_options(messages, 40)
        response = {"choices": [{"finish_reason": "stop", "message": {"content": '{"fixture":true}'}}]}
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "cache" / (digest(request) + ".json")
            write(path, {"request_sha256": digest(request), "response_sha256": digest(response), "response": response, "metadata": {}})
            with patch("socket.socket", side_effect=AssertionError("network forbidden")):
                value, meta = SilverClient(temp).call(messages, max_tokens=40)
                self.assertTrue(value["fixture"]); self.assertFalse(meta["human_gold"])
                with self.assertRaises(Blocked): SilverClient(temp, model="qwen3.8-max").call(messages, max_tokens=40)

    def test_tampered_cache_blocked(self):
        messages = [{"role": "user", "content": "fixture"}]; request = request_options(messages)
        with tempfile.TemporaryDirectory() as temp:
            write(Path(temp) / "cache" / (digest(request) + ".json"), {"request_sha256": digest(request), "response_sha256": "bad", "response": {}})
            with self.assertRaises(Blocked): SilverClient(temp).call(messages)

    def test_incomplete_cached_output_not_label(self):
        with self.assertRaises(Blocked): SilverClient.decode({"choices": [{"finish_reason": "length"}]})

    def test_unexpected_function_blocked(self):
        with self.assertRaises(Blocked): SilverClient.decode({"choices": [{"finish_reason": "tool_calls", "message": {"tool_calls": [{"function": {"name": "other"}}]}}]})

    def test_no_retry_authorization_inherited(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(Blocked): SilverClient(temp).call([], retry_invalid_once=True)

    def test_original_budget_checked_without_new_calls(self):
        budget = audit_budget(ROOT / "local/archive/experiment_a/silver_annotations/v1/budget.json")
        self.assertEqual(budget["historical_attempts"], 91)
        self.assertFalse(budget["new_calls_authorized"])

    def test_schema_rejects_boolean_number_and_extra_fields(self):
        schema = {"type": "object", "properties": {"value": {"type": "number"}}, "required": ["value"], "additionalProperties": False}
        self.assertTrue(validate({"value": True}, schema)); self.assertTrue(validate({"value": 1, "extra": 0}, schema))
        self.assertFalse(validate({"value": 1.2}, schema))


class ReviewTests(unittest.TestCase):
    def test_ties_are_not_forced(self):
        self.assertEqual(top_pairs({"ranking": [["A", "B"]]}), [])
        self.assertEqual(top_pairs({"ranking": [["A", "B"], ["C"]]}), [("A", "C"), ("B", "C")])

    def test_duplicate_rank_candidates_rejected(self):
        with self.assertRaises(ValueError): top_pairs({"ranking": [["A"], ["A"]]})

    def test_method_identity_blocks_blinding(self):
        with self.assertRaises(ValueError): check_blinding([], [{"reason": "CRITIC produced this"}], [])

    def test_missing_runs_keep_failure_slots(self):
        case = {"case_id": "FIXTURE", "candidate_ids": ["A"], "packet": {"records": {"case_id": "FIXTURE"}, "candidates": []}}
        cards, explanations, _, missing = make_cards([case], [], methods=("fixture",))
        self.assertEqual(len(cards), 1); self.assertFalse(explanations)
        self.assertEqual(missing[0]["status"], "MISSING_RECORD")

    def test_malformed_baseline_output_is_structural_error(self):
        self.assertTrue(validate_output({"ranking": None}, {"candidate_ids": ["A"]}))

    def test_new_baseline_execution_disabled(self):
        with self.assertRaises(Blocked): run()


if __name__ == "__main__": unittest.main()
