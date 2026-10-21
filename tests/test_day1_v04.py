"""Semantic guard regressions for the corpus audit and proposed ranking labels."""
from copy import deepcopy
import unittest

from jsonschema import Draft202012Validator

from src.common import ROOT, read, rows
from src.day1.construction_audit import KNOWLEDGE, SOURCE, classify, construction_trace, facet_errors


class RankingAxesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = read(ROOT/"configs/c1_ranking_judgment_v04.schema.json")
        Draft202012Validator.check_schema(cls.schema)
        cls.validator = Draft202012Validator(cls.schema)

    def base(self):
        return {"query_id":"fixture", "knowledge_id":"fixture", "query_basis":"TOPIC_ONLY", "explicit_goal":None,
                "eligibility":{"criteria_status":"NO_HARD_GATE_DEFINED", "verdict":None,
                               "reason_code":"GENERAL_EDUCATION", "annotation_status":"ACCEPTED"},
                "relevance":{"target":"TOPIC_CONDITIONED_RELEVANCE", "grade":1,
                             "evidence_sufficiency":"NOT_REQUIRED_FOR_TOPIC_JUDGMENT", "reason_code":"TOPIC_BACKGROUND",
                             "rubric_version":"fixture", "annotation_status":"ACCEPTED"},
                "annotation_status":"ACCEPTED", "evidence_ids":[], "source_condition_ids":[],
                "provenance":{"kind":"MODEL_SILVER", "model_id":"fixture", "human_gold":False,
                              "prompt_version":"fixture", "schema_version":"c1-ranking-judgment-v04",
                              "request_hash":"fixture", "response_hash":"fixture"}}

    def test_general_education_can_have_relevance_without_hard_gate(self):
        self.validator.validate(self.base())

    def test_no_hard_gate_does_not_authorize_a_negative_verdict(self):
        record = self.base()
        record["eligibility"]["verdict"] = "not_applicable"
        self.assertFalse(self.validator.is_valid(record))

    def test_topic_cannot_be_silently_promoted_to_personal_goal(self):
        record = self.base()
        record["relevance"].update(target="GOAL_CONDITIONED_PERSONAL_RELEVANCE", evidence_sufficiency="FULL_ALLOWED_RECORD")
        self.assertFalse(self.validator.is_valid(record))
        record.update(query_basis="SYNTHETIC_BENCHMARK_GOAL", explicit_goal="Declared research question")
        self.validator.validate(record)

    def test_missing_evidence_has_null_grade_even_if_zero_would_be_convenient(self):
        record = self.base()
        record["relevance"].update(evidence_sufficiency="INSUFFICIENT", grade=0)
        self.assertFalse(self.validator.is_valid(record))
        record["relevance"]["grade"] = None
        self.validator.validate(record)

    def test_model_silver_cannot_self_promote_to_human_gold(self):
        record = self.base()
        record["provenance"]["human_gold"] = True
        self.assertFalse(self.validator.is_valid(record))

    def test_reference_goal_label_requires_full_allowed_record(self):
        record = self.base()
        record.update(query_basis="EXPLICIT_USER_GOAL", explicit_goal="Declared goal")
        record["relevance"]["target"] = "GOAL_CONDITIONED_PERSONAL_RELEVANCE"
        self.assertFalse(self.validator.is_valid(record))
        record["relevance"]["evidence_sufficiency"] = "FULL_ALLOWED_RECORD"
        self.validator.validate(record)


class ConstructionAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.item = next(k for k in rows(KNOWLEDGE/"knowledge_active.jsonl") if k["knowledge_id"]=="K2-a70ef9c51226a016b8bd")
        cls.probes = read(SOURCE/"probes.json")

    def record(self):
        return {"knowledge_id":self.item["knowledge_id"], "source_form":"CONDITIONAL_OR_POPULATION_SCOPED",
                "facets":[{"facet_id":"awake-event", "dimensions":["state","threshold","time"],
                           "purpose":"EXPLICIT_ADVICE_TRIGGER", "source_quote":self.item["text"], "scope":"ITEM",
                           "applies_to_item":True, "threshold_text":"more than 20 minutes", "time_text":"more than 20 minutes",
                           "measurement":"UNMEASURED_VARIABLE", "probe_ids":[], "measurement_reason":"No wake-in-bed event field",
                           "legacy_extraction":"REPRESENTED", "legacy_comparison_reason":"The old model extracted the trigger"}],
                "no_explicit_personal_trigger":False, "ranking_gate_mismatch":False,
                "ranking_gate_reason":"Event-specific advice", "rationale":"Fixture copied from frozen source"}

    def test_explicit_unmeasurable_source_condition_is_not_absent_or_omitted(self):
        r = self.record()
        self.assertEqual(facet_errors(r,self.item,self.probes),[])
        self.assertEqual(classify(r),["CONDITION_NOT_IN_PROBE_MEASUREMENT_SPACE"])

    def test_invented_cutoff_and_wrong_scope_are_rejected(self):
        r = self.record()
        r["facets"][0]["threshold_text"] = "30 minutes"
        self.assertIn("threshold_or_time_not_verbatim",facet_errors(r,self.item,self.probes))
        r = self.record()
        r["facets"][0]["source_quote"] = "Invented source condition"
        self.assertIn("quote_not_in_declared_frozen_scope",facet_errors(r,self.item,self.probes))

    def test_a_registered_probe_does_not_make_an_unmeasured_event_measurable(self):
        r = self.record()
        r["facets"][0]["probe_ids"] = [self.probes[0]["probe_id"]]
        self.assertIn("unmeasurable_facet_has_probe_claim",facet_errors(r,self.item,self.probes))

    def test_original_extraction_replays_and_short_list_leadins_are_auditable(self):
        trace = construction_trace()
        self.assertTrue(trace["extraction_replay_exact"])
        self.assertEqual((trace["source_blocks"],trace["extracted_candidates"],trace["active_items"]),(515,402,204))
        self.assertEqual(len(trace["excluded_short_leadins_before_lists"]),61)
        self.assertFalse(trace["active_acceptance_requires_measurable_condition"])


if __name__ == "__main__":
    unittest.main()
