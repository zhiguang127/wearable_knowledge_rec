"""Research-validity regressions. Fixtures are not clinical labels or real participants."""
import copy
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from src.common import ROOT, digest, read, rows, write, Blocked
from src.datasets.probes import make_probe, catalog
from src.annotation import c1_v2_pipeline as pipeline
from src.annotation.dependencies import validate_dependency, citation_integrity, audit_legacy_condition
from src.annotation.personal_evidence import EvidenceProvider, balanced_pairs, compact_evidence, compact_catalog
from src.annotation.c1_v22_audit import failure_attribution
from src.knowledge.dedup import exact_deduplicate, model_suggestions
from src.datasets.v2_sources import verify


def item(kid="K-FIXTURE", text="Fixture education statement.", topic="physical_activity"):
    return {"knowledge_id": kid, "title": "Fixture only", "text": text, "topic": topic, "subtopic": "fixture",
            "source_url": "https://example.invalid/fixture", "source_sha256": digest(text),
            "source_anchor": {"anchor_id": "fixture", "text": text, "text_sha256": digest(text)},
            "conditions": [], "review_status": "REVIEW_REQUIRED", "condition_review_status": "REVIEW_REQUIRED"}


def cite(k):
    return {"anchor_id": k["source_anchor"]["anchor_id"], "source_sha256": k["source_sha256"], "quote": k["text"]}


def review(k, conditions=None):
    first = {"knowledge_id": k["knowledge_id"], "source_supported": True, "independently_recommendable": True,
             "education_only": True, "normalized_text": k["text"], "conditions": conditions or [],
             "duplicate_ids": [], "conflict_ids": [], "source_citations": [cite(k)],
             "unsupported_and": False, "uncertainties": [], "rationale": "Fixture, not medical validation"}
    second = {"knowledge_id": k["knowledge_id"], "verdict": "SUPPORTED", "unsupported_and": False,
              "issues": [], "source_citations": [cite(k)], "rationale": "Fixture only"}
    return {"knowledge_id": k["knowledge_id"], "input_sha256": digest(k), "prompt_version": pipeline.PROMPT_VERSION,
            "stage1": {"status": "RETURNED", "output": first}, "stage2": {"status": "RETURNED", "output": second},
            "review_status": "SILVER_ACCEPTED", "validation_errors": []}


def case(subject="fixture-subject", length=42):
    end = date(2020, 4, 1)
    return {"case_id": subject + "-" + str(length), "subject_id": subject, "end_date": end.isoformat(),
            "history_days": length, "block": 0, "context": {},
            "days": [{"date": (end - timedelta(days=length-i-1)).isoformat(),
                      "metrics": {"steps": float(i)}, "quality_flags": []} for i in range(length)]}


class JointSourceTests(unittest.TestCase):
    def test_anchor_integrity_is_checked_independently_of_quote_presence(self):
        k = item(); c = cite(k)
        k["source_anchor"]["text"] += " Altered after freeze."
        self.assertEqual(citation_integrity([c], k)[0], ["citation_anchor_text_hash_mismatch"])
    def grounded_fixture(self):
        k = item(text="Fixture comparison requires average below 10 and variability above 2.")
        ps = [make_probe("steps", 7, "mean"), make_probe("steps", 28, "sd")]
        predicates = [{"predicate_id": str(i), "claim": claim, "probe_id": p["probe_id"], "operator": op,
                       "threshold": [threshold], "unit": p["unit"], "source_citations": [cite(k)]}
                      for i, (p, claim, op, threshold) in enumerate(zip(ps, ["average below 10", "variability above 2"], ["lt", "gt"], [10, 2]))]
        dep = {"predicates": predicates, "relation": {"logic": "ALL", "predicate_ids": ["0", "1"], "source_citations": [cite(k)]}}
        return k, ps, dep

    def test_source_bound_ALL_is_not_rejected_for_multiple_probes(self):
        k, ps, dep = self.grounded_fixture()
        result = validate_dependency(dep, k, ps)
        self.assertEqual(result["structural_errors"], [])
        self.assertTrue(result["structurally_auditable"])
        self.assertTrue(result["candidate_preserved"])
        self.assertFalse(result["confirmed_rule"])

    def test_missing_leaf_or_connective_support_is_audited_without_erasing_candidate(self):
        for target in ("leaf", "relation"):
            k, ps, dep = self.grounded_fixture()
            (dep["predicates"][0] if target == "leaf" else dep["relation"])["source_citations"] = []
            result = validate_dependency(dep, k, ps)
            self.assertTrue(result["structural_errors"])
            self.assertTrue(result["candidate_preserved"])
            self.assertEqual(result["semantic_status"], "REVIEW_REQUIRED")

    def test_wrong_units_and_unknown_predicate_members_cannot_be_certified(self):
        k, ps, dep = self.grounded_fixture()
        dep["predicates"][0]["unit"] = "hours"
        dep["relation"]["predicate_ids"] = ["unknown", "1"]
        result = validate_dependency(dep, k, ps)
        self.assertIn("predicate_unit_mismatch", result["structural_errors"])
        self.assertIn("relation_must_reference_each_predicate_once", result["structural_errors"])

    def test_old_arity_error_can_be_reassessed_and_promoted_without_altering_history(self):
        k, ps, dep = self.grounded_fixture()
        condition = {"condition_id": "c", "text": "Fixture statistical comparison", "role": "necessary", "logic": "ALL",
                     "probe_ids": [p["probe_id"] for p in ps], "dataset_support": "supported",
                     "source_citations": [cite(k)], "insufficient_information": [], "use": "applicability"}
        old = review(k, [condition]); old.update(review_status="REVIEW_REQUIRED", validation_errors=["necessary_ALL_probe_group_has_no_grounded_per_probe_predicates"])
        before = copy.deepcopy(old)
        updated = pipeline.recertify([old], [k], ps)[0]
        self.assertEqual(updated["review_status"], "SILVER_ACCEPTED")
        self.assertEqual(updated["validation_errors"], [])
        self.assertEqual(old, before)
        self.assertEqual(updated["prior_validation_errors"], before["validation_errors"])

    def test_quote_inside_unrelated_context_is_not_treated_as_entailment(self):
        k = item(text="Fixture A needs review.")
        k["source_anchor"]["text"] += " Unrelated fixture B."
        k["source_anchor"]["text_sha256"] = digest(k["source_anchor"]["text"])
        c = {**cite(k), "quote": "Unrelated fixture B."}
        errors, spans = citation_integrity([c], k, "Fixture A")
        self.assertFalse(errors)
        self.assertFalse(spans[0]["candidate_text_overlap"])
        self.assertEqual(spans[0]["semantic_support"], "NOT_ESTABLISHED_BY_STRING_OR_HASH_CHECK")


class LosslessDedupTests(unittest.TestCase):
    def test_unilateral_similarity_and_transitive_chain_cannot_merge_distinct_advice(self):
        ks = [item("A", "Start gradually."), item("B", "Track progress."), item("C", "Recognize another person's effort.", "stress")]
        rr = [review(k) for k in ks]
        rr[0]["stage1"]["output"]["duplicate_ids"] = ["B"]
        rr[1]["stage1"]["output"]["duplicate_ids"] = ["C"]
        _, active, canonical = pipeline.assemble(ks, rr)
        self.assertEqual(len(active), 3)
        self.assertEqual(canonical, {"A": "A", "B": "B", "C": "C"})
        self.assertTrue(all(not edge["used_to_merge"] for edge in model_suggestions(rr)))

    def test_same_text_different_source_or_conditions_preserves_variants(self):
        a = item("A"); b = item("B"); c = item("C")
        b["conditions"] = [{"dataset_support": "supported", "probe_ids": ["probe-fixture"]}]
        c["source_url"] += "/other-scope"
        active, _ = exact_deduplicate([a, b, c])
        self.assertEqual(len(active), 3)
        self.assertTrue(any(v["conditions"] == b["conditions"] for k in active for v in k["member_variants"]))

    def test_exact_identity_still_retains_all_original_provenance(self):
        a = item("A"); b = item("B")
        active, canonical = exact_deduplicate([b, a])
        self.assertEqual(len(active), 1)
        self.assertEqual(canonical, {"A": "A", "B": "A"})
        self.assertEqual([v["knowledge_id"] for v in active[0]["member_variants"]], ["A", "B"])


class IndependentEvidenceTests(unittest.TestCase):
    def test_factored_registry_preserves_every_definition(self):
        probes = catalog() + [make_probe("steps", 8, "mean", offset=3, min_coverage=0.9)]
        for ps in (catalog(), probes):
            packed = compact_catalog(ps)
            unpacked = []
            for row in packed["rows"]:
                p = {**dict(zip(packed["schema"], row)), **packed["constants"]}
                restored = make_probe(packed["metrics"][p["metric_index"]], p["window_days"],
                    packed["operations"][p["operation_index"]], p["offset_days"], p["min_coverage"])
                self.assertEqual(restored["probe_id"], p["probe_id"])
                self.assertEqual(restored["unit"], packed["units_by_metric_operation"][p["metric_index"]][restored["operation"]])
                self.assertEqual(restored["comparison"], packed["comparisons"][p["comparison_index"]])
                unpacked.append(restored)
            self.assertEqual(unpacked, ps)

    def test_label_path_receives_full_evidence_without_a_mapping(self):
        k = item(); c = case(); ps = catalog()
        client = SimpleNamespace(config={"model": "fixture"})
        payloads = []
        def stage(client, task, payload, schema, name):
            payloads.append(payload)
            return {"status": "BLOCKED", "reason": "Fixture only; no network"}
        with tempfile.TemporaryDirectory() as d, patch.object(pipeline, "call_stage", side_effect=stage):
            result = pipeline.label_one(client, c, k, ps, d)
        self.assertEqual(len(result["evidence"]), 288)
        self.assertEqual(len(payloads[0]["personal_evidence"]["results"]), 288)
        self.assertIsNone(result["applicability"], "A blocked call is not an insufficient_information label")
        self.assertEqual(payloads[0]["unverified_condition_hints"], [])

    def test_packet_rejects_duplicate_results_and_preserves_exact_intervals(self):
        c = case(); ps = catalog(); evidence = EvidenceProvider(c, ps).compute_all()
        with self.assertRaises(Blocked): compact_evidence(c, ps, evidence + [evidence[0]])
        packet = compact_evidence(c, ps, evidence)
        for interval in packet["exact_time_intervals"]:
            self.assertLessEqual(interval["end_date"], c["end_date"])
            self.assertEqual((date.fromisoformat(interval["end_date"]) - date.fromisoformat(interval["start_date"])).days + 1, interval["window_days"])

    def test_empty_mapping_can_discover_any_registered_evidence(self):
        ps = [make_probe("steps", 7, "mean"), make_probe("steps", 28, "sd")]
        provider = EvidenceProvider(case(), ps)
        evidence = provider.compute_all()
        self.assertEqual(len(evidence), 2)
        self.assertTrue(all(e["status"] == "COMPUTED" for e in evidence))
        self.assertEqual(provider.execute_probe(ps[0]["probe_id"])["value"], 38)
        packet = compact_evidence(case(), ps, evidence)
        self.assertEqual(packet["registry"]["count"], 2)
        self.assertEqual(len(packet["results"]), 2)

    def test_all_topics_offer_all_metrics_horizons_and_operations(self):
        ps = catalog()
        for topic in ("sleep", "nutrition", "stress"):
            offered = pipeline.candidate_probes(item(topic=topic), ps)
            self.assertEqual({p["probe_id"] for p in offered}, {p["probe_id"] for p in ps})
            self.assertEqual({p["window_days"] for p in offered}, {7, 14, 28})
            self.assertEqual(len({p["operation"] for p in offered}), 6)

    def test_cold_start_and_future_boundaries_remain_enforced(self):
        p = make_probe("steps", 14, "mean_difference")
        self.assertEqual(EvidenceProvider(case(length=14), [p]).compute_all()[0]["status"], "INSUFFICIENT_INFORMATION")
        bad = case(); bad["days"].append({"date": "2099-01-01", "metrics": {"steps": 1}})
        with self.assertRaises(Blocked): EvidenceProvider(bad, [p])

    def test_sampling_is_balanced_and_unchanged_when_mapping_changes(self):
        cs = [case("s"+str(i), h) for i in range(5) for h in (14, 42)]
        ks = [item("k"+str(i), topic=t) for i,t in enumerate(("sleep", "stress", "nutrition", "physical_activity", "healthy_aging"))]
        partitions = {"partitions": {"train": {"subject_ids": ["s"+str(i) for i in range(5)]}}}
        before = [(c["case_id"], k["knowledge_id"]) for c,k in balanced_pairs(cs, ks, partitions, 10)]
        for k in ks: k["conditions"] = [{"probe_ids": ["arbitrary"]}]
        after = [(c["case_id"], k["knowledge_id"]) for c,k in balanced_pairs(cs, ks, partitions, 10)]
        self.assertEqual(before, after)
        self.assertEqual(len({kid for _,kid in after}), 5)


class ReviewCacheContextTests(unittest.TestCase):
    def test_label_cache_changes_with_registry_even_when_item_has_no_mapping(self):
        k = item(); c = case(); ps = [make_probe("steps",7,"mean")]
        client = SimpleNamespace(config={"model":"fixture"})
        calls=[]
        def stage(*args):
            calls.append(1)
            return {"status":"BLOCKED","reason":"Fixture only"}
        with tempfile.TemporaryDirectory() as d, patch.object(pipeline,"call_stage",side_effect=stage):
            a=pipeline.label_one(client,c,k,ps,d)
            pipeline.label_one(client,c,k,ps,d)
            b=pipeline.label_one(client,c,k,ps+[make_probe("steps",28,"mean")],d)
        self.assertEqual(len(calls),2)
        self.assertNotEqual(a["annotation_context_sha256"],b["annotation_context_sha256"])
    def test_probe_and_neighbor_changes_invalidate_local_reuse_without_version_change(self):
        k = item(); ps = [make_probe("steps", 7, "mean")]
        client = SimpleNamespace(config={"model": "fixture", "base_url": "https://example.invalid", "max_tokens": 40})
        calls = []
        def stage(client, task, payload, schema, name):
            calls.append(name)
            result = review(k)
            return result["stage1" if name == "knowledge-extract" else "stage2"]
        with tempfile.TemporaryDirectory() as d, patch.object(pipeline, "call_stage", side_effect=stage):
            legacy = Path(d)/(k["knowledge_id"]+".json"); write(legacy, {"obsolete": True})
            a = pipeline.review_one(client, k, [k], ps, d)
            pipeline.review_one(client, k, [k], ps, d)
            self.assertEqual(len(calls), 2)
            b = pipeline.review_one(client, k, [k], ps+[make_probe("steps",28,"median")], d)
            c = pipeline.review_one(client, k, [k,item("neighbor","Different fixture text.")], ps, d)
            self.assertEqual(len(calls), 6)
            self.assertNotEqual(a["review_context_sha256"], b["review_context_sha256"])
            self.assertNotEqual(a["review_context_sha256"], c["review_context_sha256"])
            self.assertEqual(read(legacy), {"obsolete": True})


class RealAuditRegressions(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.artifact_root = ROOT/"local/c1-v2/qwen-final-v3"
        if not cls.artifact_root.exists(): raise unittest.SkipTest("Private historical artifacts absent; no synthetic replacement")

    def test_unique_legacy_supported_condition_survives_exact_dedup(self):
        ks = [k for k in rows(self.artifact_root/"knowledge_reviewed.jsonl") if k["review_status"] == "SILVER_ACCEPTED"]
        active, _ = exact_deduplicate(ks)
        self.assertEqual(len(active), 201)
        before = {k["knowledge_id"] for k in ks if any(c["dataset_support"]=="supported" for c in k["conditions"])}
        after = {v["knowledge_id"] for k in active for v in k["member_variants"] if any(c["dataset_support"]=="supported" for c in v["conditions"])}
        self.assertEqual(len(before), 1)
        self.assertEqual(before, after)

    def test_actual_failure_denominators_distinguish_records_and_occurrences(self):
        _, summary = failure_attribution(rows(self.artifact_root/"silver_labels.jsonl"))
        self.assertEqual(summary["stage2_verdicts"], {"REVIEW_REQUIRED":119, "SUPPORTED":1})
        self.assertEqual(summary["stage2_review_required_without_program_error"], 118)
        self.assertEqual(summary["records_with_program_error"], 1)
        self.assertEqual(summary["program_error_occurrences"], {"citation_quote_not_in_source":2})
        self.assertEqual(summary["no_evidence_supplied"], 98)

    def test_all_11_historical_arity_candidates_are_preserved_for_source_audit(self):
        ks = {k["knowledge_id"]:k for k in rows(self.artifact_root/"knowledge_reviewed.jsonl")}
        rr = [r for r in rows(self.artifact_root/"knowledge_reviews.jsonl") if "necessary_ALL_probe_group_has_no_grounded_per_probe_predicates" in r["validation_errors"]]
        self.assertEqual(len(rr), 11)
        preserved = []
        for r in rr:
            for c in r["stage1"]["output"]["conditions"]:
                if c["logic"] == "ALL" and len(c["probe_ids"]) > 1:
                    result = audit_legacy_condition(c, ks[r["knowledge_id"]], catalog())
                    self.assertTrue(result["candidate_preserved"])
                    self.assertFalse(result["confirmed_rule"])
                    preserved.append(result)
        self.assertGreaterEqual(len(preserved), 11)


class PublicRepairMetadata(unittest.TestCase):
    def test_public_metadata_freeze_and_no_private_identity(self):
        directory=ROOT/"docs/c1_v2_2_artifacts"
        if not directory.exists():self.skipTest("Public repaired export not generated yet")
        verify(directory)
        text="\n".join(p.read_text(encoding="utf-8") for p in directory.rglob("*") if p.is_file())
        self.assertNotIn('"subject_id"',text)
        self.assertNotIn('"case_id"',text)
        self.assertNotIn('"api_key"',text)
        source=ROOT/"data/releases/c1-benchmark-v2.1/cases.jsonl"
        if source.exists():
            self.assertFalse(any(c[k] in text for c in rows(source) for k in ("subject_id","case_id")))
        summary=read(directory/"aggregate_report.json")
        self.assertEqual(summary["new_applicability_labels"],None)
        self.assertFalse(summary["human_gold"])


if __name__ == "__main__": unittest.main()
