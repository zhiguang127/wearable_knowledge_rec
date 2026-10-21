"""Day 1 boundary regressions. All threshold examples are nonmedical fixtures."""
import copy
import json
import math
import unittest
from datetime import date, timedelta

from src.common import Blocked, digest, read
from src.datasets.probes import make_probe, execute
from src.annotation.validation import validate
from src.day1.schemas import SELECTION, ANNOTATION, OBSERVATION
from src.day1.evidence import EvidenceProvider
from src.day1.contracts import validate_knowledge, expected_verdict, combine
from src.day1.annotation import prepare_messages, finalize
from src.day1.environment import AcquisitionEnvironment, ConditionRanker
from src.day1.evaluation import slate_metrics, measurement_metrics, participant_summary
from src.day1.prepare import candidate_plan, readiness


def fixture(value=10, kid="K-fixture", case_id="case-fixture"):
    probe = make_probe("steps", 7, "mean")
    case = {"case_id": case_id, "end_date": "2020-01-07", "days": [
        {"date": (date(2020, 1, 1) + timedelta(days=i)).isoformat(),
         "metrics": {"steps": value}, "quality_flags": []} for i in range(7)]}
    text = "Nonmedical fixture: mean seven-day step count is below 15."
    source = {"knowledge_id": kid, "topic": "fixture", "text": text,
              "source_url": "https://example.invalid/fixture", "source_sha256": digest("fixture-source"),
              "source_anchor": {"anchor_id": "fixture-anchor", "text": text, "text_sha256": digest(text)}}
    cite = {"source_url": source["source_url"], "source_sha256": source["source_sha256"],
            "anchor_id": "fixture-anchor", "anchor_sha256": digest(text), "quote": text}
    review = {"status": "VERIFIED", "reviewer_id": "fixture-only", "reviewer_kind": "model",
              "rationale": "Synthetic logic fixture, not source or clinical verification.", "review_artifact_sha256": digest("fixture-review")}
    predicate = {"predicate_id": "p1", "variable": "steps", "operator": "lt", "threshold": [15],
                 "unit": probe["unit"], "window_days": 7, "offset_days": 0,
                 "operation": "mean", "comparison": "none", "probe_ids": [probe["probe_id"]],
                 "source_citation": cite, "semantic_review": review}
    item = {"knowledge_id": kid, "topic": "fixture", "text": text, "criteria_kind": "MEASURABLE",
            "conditions": [{"knowledge_id": kid, "condition_id": "c1", "logic": "ALL", "predicates": [predicate],
                            "role": "necessary_and_sufficient", "role_rationale": "Synthetic single-condition equivalence.",
                            "source_citation": cite, "semantic_review": review}],
            "logic": "ALL", "role": "necessary_and_sufficient", "source_citation": cite, "semantic_review": review}
    query = {"query_id": "q-fixture", "case_id": case_id, "topic": "fixture", "goal": None, "candidate_ids": [kid]}
    return case, [probe], source, item, query


def label_fixture(value=10, kind="MEASURABLE"):
    case, probes, source, item, query = fixture(value)
    item = copy.deepcopy(item)
    if kind != "MEASURABLE":
        item.update(criteria_kind=kind, conditions=[])
    provider = EvidenceProvider(case, probes)
    verdict, reason = expected_verdict(item, provider.all())
    selection = {"query_id": query["query_id"], "knowledge_id": item["knowledge_id"], "verdict": verdict,
                 "reason_code": reason, "evidence_ids": [e["evidence_id"] for e in provider.all()] if item["conditions"] else [],
                 "condition_ids": [c["condition_id"] for c in item["conditions"]], "rationale": "Fixture judgment."}
    request = {"model": "qwen3.8-max", "messages": prepare_messages(query, item, source, probes, provider)}
    response = {"model": "qwen3.8-max", "choices": [{"message": {"content": json.dumps(selection)}}]}
    kwargs = dict(query=query, item=item, source_item=source, probes=probes, provider=provider,
                  model_id="qwen3.8-max", request=request, response=response)
    return selection, kwargs


class SchemaAndAnnotationTests(unittest.TestCase):
    def test_all_four_verdicts_are_independent_of_annotation_status(self):
        for value, kind, expected in [(10, "MEASURABLE", "applicable"), (20, "MEASURABLE", "not_applicable"),
                                     (None, "MEASURABLE", "insufficient_information"),
                                     (10, "UNMEASURABLE_HEALTH_CONTEXT", "not_assessable"),
                                     (10, "NO_PERSONAL_APPLICABILITY_CRITERION", "not_assessable")]:
            with self.subTest(expected=expected, kind=kind):
                selection, kwargs = label_fixture(value, kind)
                result = finalize(selection, **kwargs)
                self.assertEqual(result["validation_errors"], [])
                self.assertEqual(result["verdict"], expected)
                self.assertEqual(result["annotation_status"], "ACCEPTED")
                self.assertFalse(validate(result, ANNOTATION))
                self.assertFalse(result["human_gold"])
                self.assertEqual(result["label_tier"], "Silver / Pseudo-Gold")

    def test_not_yet_acquired_is_not_a_reference_label(self):
        selection, _ = label_fixture()
        selection["verdict"] = "not_yet_acquired"
        self.assertTrue(validate(selection, SELECTION))

    def test_numeric_copy_and_missing_schema_field_are_rejected(self):
        for change in (lambda s: s.update(value=10), lambda s: s.pop("reason_code")):
            selection, kwargs = label_fixture()
            change(selection)
            result = finalize(selection, **kwargs)
            self.assertEqual(result["annotation_status"], "REJECTED")
            self.assertIsNone(result["label"])

    def test_model_input_contains_complete_relevant_values_with_backend_only_hashes(self):
        _, kwargs = label_fixture()
        payload = json.loads(kwargs["request"]["messages"][1]["content"])
        self.assertEqual(len(payload["evidence"]), 1)
        self.assertEqual(payload["evidence"][0]["value"], 10)
        self.assertNotIn("source_ref", payload["evidence"][0])
        self.assertNotIn("result_hash", payload["evidence"][0])
        self.assertLess(len(json.dumps(kwargs["request"]).encode()), 60000)

    def test_wrong_window_or_unknown_id_is_not_accepted(self):
        selection, kwargs = label_fixture()
        case, probes, *_ = fixture(case_id="another-case")
        for ids in (["invented"], [EvidenceProvider(case, probes).all()[0]["evidence_id"]]):
            selection["evidence_ids"] = ids
            kwargs["response"]["choices"][0]["message"]["content"] = json.dumps(selection)
            result = finalize(selection, **kwargs)
            self.assertEqual(result["annotation_status"], "REVIEW_REQUIRED")
            self.assertIn("evidence_binding_failed", result["validation_errors"])

    def test_wrong_condition_and_wrong_verdict_remain_review_required(self):
        selection, kwargs = label_fixture()
        selection.update(condition_ids=["wrong"], verdict="not_applicable")
        kwargs["response"]["choices"][0]["message"]["content"] = json.dumps(selection)
        result = finalize(selection, **kwargs)
        self.assertEqual(result["annotation_status"], "REVIEW_REQUIRED")
        self.assertIn("condition_reference_inventory_mismatch", result["validation_errors"])

    def test_wrong_verdict_cannot_be_accepted_with_correct_evidence(self):
        selection, kwargs = label_fixture()
        selection.update(verdict="not_applicable", reason_code="VERIFIED_CONDITIONS_NEGATED")
        kwargs["response"]["choices"][0]["message"]["content"] = json.dumps(selection)
        result = finalize(selection, **kwargs)
        self.assertIn("verdict_or_reason_conflicts_with_verified_rule", result["validation_errors"])

    def test_unrelated_evidence_does_not_support_the_condition(self):
        selection, kwargs = label_fixture()
        case, probes, *_ = fixture()
        kwargs["probes"] = probes + [make_probe("steps", 7, "median")]
        kwargs["provider"] = EvidenceProvider(case, kwargs["probes"])
        selection["evidence_ids"] = [kwargs["provider"].get(kwargs["probes"][1]["probe_id"])["evidence_id"]]
        kwargs["request"]["messages"] = prepare_messages(kwargs["query"], kwargs["item"], kwargs["source_item"], kwargs["probes"], kwargs["provider"])
        kwargs["response"]["choices"][0]["message"]["content"] = json.dumps(selection)
        result = finalize(selection, **kwargs)
        self.assertIn("evidence_condition_semantics_mismatch", result["validation_errors"])

    def test_original_response_and_request_are_not_silently_repaired(self):
        selection, kwargs = label_fixture()
        before = copy.deepcopy(kwargs["response"])
        selection["rationale"] = "Edited after receiving the model response."
        result = finalize(selection, **kwargs)
        self.assertIn("selection_does_not_match_original_response", result["validation_errors"])
        self.assertEqual(kwargs["response"], before)
        kwargs["request"]["messages"] = []
        self.assertIn("request_payload_or_prompt_identity_mismatch", finalize(selection, **kwargs)["validation_errors"])

    def test_same_model_audit_never_promotes_to_human_gold(self):
        selection, kwargs = label_fixture()
        first = finalize(selection, **kwargs)
        second = finalize(selection, **kwargs)
        self.assertEqual(first["label_tier"], second["label_tier"])
        self.assertFalse(second["human_gold"])


class SemanticAdmissionTests(unittest.TestCase):
    def test_and_or_keep_unknown_distinct_from_false(self):
        self.assertIsNone(combine([True, None], "ALL"))
        self.assertIsNone(combine([False, None], "ANY"))
        self.assertFalse(combine([False, None], "ALL"))
        self.assertTrue(combine([True, None], "ANY"))

    def test_hash_matching_alone_does_not_verify_legacy_conditions(self):
        case, probes, source, item, query = fixture()
        item["semantic_review"]["status"] = "REVIEW_REQUIRED"
        self.assertIn("semantic_review_not_verified", validate_knowledge(item, probes, source))
        with self.assertRaises(Blocked):
            prepare_messages(query, item, source, probes, EvidenceProvider(case, probes))

    def test_unverified_conditions_cannot_become_not_assessable(self):
        selection, kwargs = label_fixture(kind="UNMEASURABLE_HEALTH_CONTEXT")
        kwargs["item"]["semantic_review"]["status"] = "REVIEW_REQUIRED"
        self.assertNotEqual(finalize(selection, **kwargs)["annotation_status"], "ACCEPTED")

    def test_units_time_operator_and_anchor_are_checked(self):
        _, probes, source, original, _ = fixture()
        changes = [("unit", "hours"), ("window_days", 14), ("operation", "sd"), ("threshold", []), ("threshold", [True])]
        for field, value in changes:
            item = copy.deepcopy(original)
            item["conditions"][0]["predicates"][0][field] = value
            self.assertTrue(validate_knowledge(item, probes, source))
        source["source_anchor"]["text"] += "tamper"
        self.assertIn("source_anchor_integrity_mismatch", validate_knowledge(original, probes, source))

    def test_each_predicate_and_connective_needs_its_own_review(self):
        _, probes, source, item, _ = fixture()
        item = copy.deepcopy(item)
        item["conditions"][0]["semantic_review"]["status"] = "REVIEW_REQUIRED"
        self.assertIn("semantic_review_not_verified", validate_knowledge(item, probes, source))

    def test_necessary_is_not_sufficient_and_sufficient_is_not_necessary(self):
        for value, role in [(10, "necessary"), (20, "sufficient")]:
            case, probes, _, item, _ = fixture(value)
            item["role"] = role
            verdict, reason = expected_verdict(item, EvidenceProvider(case, probes).all())
            self.assertIsNone(verdict)
            self.assertEqual(reason, "CONDITION_ROLE_NOT_DECISIVE")

    def test_incomplete_pool_is_not_a_full_record_insufficient_label(self):
        _, _, _, item, _ = fixture()
        with self.assertRaises(Blocked):
            expected_verdict(item, [])


class EvidenceAndEnvironmentTests(unittest.TestCase):
    def test_binding_is_exact_and_returns_copies(self):
        case, probes, *_ = fixture()
        provider = EvidenceProvider(case, probes)
        original = provider.all()[0]
        for field, value in [("unit", "hours"), ("value", 999), ("end_time", "2020-01-08"),
                             ("source_ref", {}), ("result_hash", "0" * 64), ("computation_hash", "0" * 64)]:
            changed = {**original, field: value}
            with self.assertRaises(Blocked):
                provider.verify_bound(changed)
        original["value"] = 999
        self.assertEqual(provider.all()[0]["value"], 10)

    def test_precomputed_corruption_is_rejected_even_with_a_new_content_hash(self):
        case, probes, *_ = fixture()
        result = execute(case, probes[0])
        result["value"] = 999
        result["result_sha256"] = digest({k: v for k, v in result.items() if k not in ("elapsed_ns", "result_sha256")})
        with self.assertRaises(Blocked):
            EvidenceProvider(case, probes, [result]).all()

    def test_future_data_outside_probe_is_rejected(self):
        case, probes, *_ = fixture()
        case["days"].append({"date": "2020-01-08", "metrics": {"steps": 10}})
        with self.assertRaises(Blocked):
            EvidenceProvider(case, probes)

    def test_query_provider_window_mismatch_is_rejected(self):
        case, probes, source, item, query = fixture()
        query["case_id"] = "another-window"
        provider = EvidenceProvider(case, probes)
        with self.assertRaises(Blocked): AcquisitionEnvironment(query, [item], provider, source_items={item["knowledge_id"]: source})
        with self.assertRaises(Blocked): prepare_messages(query, item, source, probes, provider)

    def test_only_acquired_probe_is_visible_and_partial_ranker_is_rerun(self):
        case, probes, source, item, query = fixture()
        probes += [make_probe("steps", 7, "median")]
        query["reference_labels"] = "must not be visible"
        env = AcquisitionEnvironment(query, [item], EvidenceProvider(case, probes), source_items={item["knowledge_id"]: source})
        initial = env.reset(query["query_id"], 2)
        self.assertEqual(initial["observed_evidence"], [])
        self.assertEqual(initial["ranking"][0][1], 0)
        self.assertNotIn("reference_labels", json.dumps(initial))
        self.assertEqual(len(env.available_actions(initial)), 2)
        self.assertFalse(validate(json.loads(json.dumps(initial)), OBSERVATION))
        state, cost, done = env.step(probes[0]["probe_id"])
        self.assertEqual(len(state["observed_evidence"]), 1)
        self.assertEqual(state["ranking"][0][1], 1)
        self.assertEqual(cost, 1)
        self.assertFalse(done)
        self.assertFalse(validate(json.loads(json.dumps(state)), OBSERVATION))
        self.assertEqual(env.available_actions(state), [probes[1]["probe_id"]])
        with self.assertRaises(Blocked):
            env.available_actions(initial)

    def test_missing_measurement_costs_one_and_is_not_a_negative_condition(self):
        case, probes, source, item, query = fixture(None)
        env = AcquisitionEnvironment(query, [item], EvidenceProvider(case, probes), source_items={item["knowledge_id"]: source})
        env.reset(query["query_id"], 1)
        state, cost, done = env.step(probes[0]["probe_id"])
        self.assertEqual(cost, 1)
        self.assertTrue(done)
        self.assertEqual(state["remaining_budget"], 0)
        self.assertEqual(state["ranking"][0][1], 0)
        self.assertEqual(state["observed_evidence"][0]["status"], "INSUFFICIENT_INFORMATION")

    def test_duplicate_illegal_and_over_budget_actions_leave_state_unchanged(self):
        case, probes, source, item, query = fixture()
        probes += [make_probe("steps", 7, "median")]
        env = AcquisitionEnvironment(query, [item], EvidenceProvider(case, probes), source_items={item["knowledge_id"]: source})
        initial = env.reset(query["query_id"], 2)
        with self.assertRaises(Blocked): env.step("illegal")
        self.assertEqual(len(env.available_actions(initial)), 2)
        state, _, _ = env.step(probes[0]["probe_id"])
        with self.assertRaises(Blocked): env.step(probes[0]["probe_id"])
        self.assertEqual(env.available_actions(state), [probes[1]["probe_id"]])
        env.reset(query["query_id"], 0)
        with self.assertRaises(Blocked): env.step(probes[1]["probe_id"])

    def test_ranker_is_deterministic_and_preserves_ties(self):
        case, probes, _, a, query = fixture(kid="A")
        _, _, _, b, _ = fixture(kid="B")
        query["candidate_ids"] = ["A", "B"]
        ranker = ConditionRanker()
        first = ranker.rank(query, [], [b, a])
        self.assertEqual(first, ranker.rank(query, [], [a, b]))
        self.assertEqual(first, [("A", 0, 1), ("B", 0, 1)])

    def test_unverified_or_extra_candidate_metadata_cannot_reach_policy(self):
        case, probes, source, item, query = fixture()
        item["reference_label"] = "applicable"
        with self.assertRaises(Blocked): AcquisitionEnvironment(query, [item], EvidenceProvider(case, probes), source_items={item["knowledge_id"]: source})

    def test_environment_revalidates_probe_units_against_frozen_source(self):
        case, probes, source, item, query = fixture()
        item = copy.deepcopy(item)
        item["conditions"][0]["predicates"][0]["unit"] = "hours"
        with self.assertRaises(Blocked):
            AcquisitionEnvironment(query, [item], EvidenceProvider(case, probes), source_items={item["knowledge_id"]: source})


class EvaluationAndGateTests(unittest.TestCase):
    def test_all_input_identities_are_explicit_and_budget_is_unassigned(self):
        config = read("configs/c1_day1_v01.json")
        for field in ("source_release", "knowledge_release", "result_store"):
            self.assertEqual(len(config[field + "_id"]), 64)
        self.assertEqual(read(config["qwen_budget_config"])["authorized_cap_cny"], 0)
        self.assertFalse(config["formal_baseline_execution"])

    def test_unknown_and_pending_labels_never_become_zero_gain(self):
        ranking = [("U", 4, 1), ("N", 3, 2), ("P", 2, 3), ("X", 1, 4)]
        labels = [{"knowledge_id": kid, "verdict": verdict, "annotation_status": status} for kid, verdict, status in
                  [("U", "insufficient_information", "ACCEPTED"), ("N", "not_applicable", "ACCEPTED"),
                   ("P", "applicable", "ACCEPTED"), ("X", "not_applicable", "REVIEW_REQUIRED")]]
        r = slate_metrics(ranking, labels, ["U", "N", "P", "X"], 3)
        self.assertAlmostEqual(r["ndcg"], 1 / math.log2(3))
        self.assertEqual(r["pair_count"], 1)
        self.assertEqual(r["binary_label_coverage"], .5)
        self.assertEqual(r["label_coverage"], .75)

    def test_tie_metrics_do_not_depend_on_knowledge_id(self):
        labels = [{"knowledge_id": "P", "verdict": "applicable", "annotation_status": "ACCEPTED"},
                  {"knowledge_id": "N", "verdict": "not_applicable", "annotation_status": "ACCEPTED"}]
        r = slate_metrics([("P", 0, 1), ("N", 0, 1)], labels, ["P", "N"], 1)
        self.assertEqual(r["ndcg"], .5)
        self.assertEqual(r["pairwise_accuracy"], .5)

    def test_no_relevant_items_or_pairs_is_null(self):
        r = slate_metrics([("N", 0, 1)], [{"knowledge_id": "N", "verdict": "not_applicable", "annotation_status": "ACCEPTED"}], ["N"], 5)
        self.assertIsNone(r["ndcg"])
        self.assertIsNone(r["pairwise_accuracy"])
        self.assertIsNone(measurement_metrics([])["missing_evidence_rate"])

    def test_participant_bootstrap_does_not_count_windows_as_people(self):
        records = [{"subject_id": "A", "metric": 1}] * 10 + [{"subject_id": "B", "metric": 0}]
        r = participant_summary(records, "metric", bootstrap_samples=100)
        self.assertEqual(r["mean"], .5)
        self.assertEqual(r["participants"], 2)
        self.assertEqual(r, participant_summary(records, "metric", bootstrap_samples=100))

    def test_candidate_plan_does_not_consult_values_or_labels(self):
        config = read("configs/c1_day1_v01.json")
        config = {**config, "topics": ["fixture"], "candidate_count_per_topic": 1}
        a = {"knowledge_id": "A", "topic": "fixture", "conditions": [], "label": "applicable", "value": 1}
        b = {**a, "knowledge_id": "B"}
        plan = candidate_plan([a, b], config)
        a.update(label="not_applicable", value=999)
        self.assertEqual(plan, candidate_plan([b, a], config))

    def test_preparation_alone_never_opens_baseline_gate(self):
        r = readiness([], [], [])
        self.assertFalse(r["formal_baseline_allowed"])
        self.assertEqual(r["contract_status"], "PENDING_FREEZE")

    def test_mixed_accepted_slates_and_verified_knowledge_are_separate_gates(self):
        items = [fixture(kid="K" + str(i))[3] for i in range(6)]
        slates = [{"query_id": "Q" + str(i), "candidate_ids": [k["knowledge_id"] for k in items]} for i in range(20)]
        labels = [{"query_id": s["query_id"], "knowledge_id": k["knowledge_id"],
                   "annotation_status": "ACCEPTED", "validation_errors": [],
                   "verdict": "applicable" if j == 0 else "not_applicable"} for s in slates for j, k in enumerate(items)]
        self.assertFalse(readiness(items, labels, slates)["formal_baseline_allowed"])
        self.assertTrue(readiness(items, labels, slates, protocol_frozen=True)["formal_baseline_allowed"])
        labels[0]["annotation_status"] = "REVIEW_REQUIRED"
        self.assertFalse(readiness(items, labels, slates, protocol_frozen=True)["formal_baseline_allowed"])

    def test_duplicate_slates_or_labels_cannot_inflate_gate_counts(self):
        slate = {"query_id": "Q", "candidate_ids": ["K"]}
        with self.assertRaises(Blocked): readiness([], [], [slate, slate])
        label = {"query_id": "Q", "knowledge_id": "K", "verdict": "applicable", "annotation_status": "REVIEW_REQUIRED"}
        with self.assertRaises(Blocked): readiness([], [label, label], [slate])


if __name__ == "__main__":
    unittest.main()
