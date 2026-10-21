"""Source-screening and production wire-protocol regressions; no network."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from src.common import Blocked, digest, read
from src.annotation.validation import validate
from src.day1.catalog_audit import audit_items, REASONS
from src.day1.client import Day1Client
from src.day1.structured import (build_request, decode_response, selection_schema, strict_json,
                                 SMOKE_FUNCTION, ANNOTATION_FUNCTION)
from src.day1.id_smoke import smoke_schema, validate_selection, KINDS
from src.day1.annotation import finalize
from src.day1.evidence import EvidenceProvider
from src.datasets.probes import make_probe
from tests.test_day1 import fixture, label_fixture


def budget(scope="EVIDENCE_ID_SMOKE_ONLY"):
    config = read("configs/c1_day1_id_smoke_v02.json")
    return {**config, "scope": scope, "authorization_status": "AUTHORIZED", "authorization_ref": "fixture-only-no-network",
            "authorized_cap_cny": 1, "max_calls": 2}


def response(output, function=SMOKE_FUNCTION, *, model="qwen3.8-max"):
    return {"model": model, "choices": [{"finish_reason": "tool_calls", "message": {"content": None,
             "tool_calls": [{"id": "fixture-call", "type": "function", "function": {"name": function, "arguments": json.dumps(output)}}]}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 20}}


def smoke_fixture():
    case, probes, *_ = fixture()
    evidence = EvidenceProvider(case, probes).all()
    targets = [probes[0]["probe_id"]]
    schema = smoke_schema("check-fixture", targets, evidence)
    output = {"check_id": "check-fixture", "selections": [{"probe_id": targets[0], "evidence_id": evidence[0]["evidence_id"],
              "status": evidence[0]["status"], "measurement_kind": KINDS["steps"]}]}
    return probes, evidence, targets, schema, output


class AllCatalogReviewTests(unittest.TestCase):
    def test_explicit_reviews_cover_all_204_public_ids_exactly_once(self):
        decisions = read("configs/c1_day1_catalog_review_v02.json")
        records = decisions["reviews"]
        public = [json.loads(line) for line in Path("docs/c1_v2_2_artifacts/knowledge_metadata.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(records), 204)
        self.assertEqual({r["knowledge_id"] for r in records}, {r["knowledge_id"] for r in public if r["active_candidate"]})
        self.assertTrue(all(r["rationale"] and r["admission"] == "NOT_ADMITTED" for r in records))
        self.assertFalse(decisions["expert_or_human_gold"])

    def test_catalog_audit_requires_exact_coverage_and_preserves_pending(self):
        _, probes, source, _, _ = fixture()
        source.update(title="Nonmedical fixture", conditions=[])
        decision = {"knowledge_id": source["knowledge_id"], "item_hash": digest(source),
                    "reason_codes": [REASONS["E"]], "rationale": "Fixture disposition only.", "admission": "NOT_ADMITTED"}
        records = audit_items([source], probes, [decision])
        self.assertIsNone(records[0]["applicability_label"])
        self.assertEqual(records[0]["predicate_semantic_status"], "REVIEW_REQUIRED")
        with self.assertRaises(Blocked): audit_items([source], probes, [])
        with self.assertRaises(Blocked): audit_items([source], probes, [decision, decision])

    def test_text_drift_or_admission_flag_cannot_certify_a_predicate(self):
        _, probes, source, _, _ = fixture()
        source.update(title="Nonmedical fixture", conditions=[])
        decision = {"knowledge_id": source["knowledge_id"], "item_hash": digest(source),
                    "reason_codes": [REASONS["E"]], "rationale": "Fixture.", "admission": "VERIFIED"}
        with self.assertRaises(Blocked): audit_items([source], probes, [decision])
        decision["admission"] = "NOT_ADMITTED"
        source["text"] += "changed"
        with self.assertRaises(Blocked): audit_items([source], probes, [decision])


class StructuredWireTests(unittest.TestCase):
    def test_qwen_stop_with_complete_tool_call_passes_but_stop_without_call_fails(self):
        _, _, _, schema, output = smoke_fixture()
        body = response(output)
        body["choices"][0]["finish_reason"] = "stop"
        self.assertEqual(decode_response(body, function_name=SMOKE_FUNCTION, schema=schema), output)
        body["choices"][0]["message"]["tool_calls"] = []
        with self.assertRaises(Blocked): decode_response(body, function_name=SMOKE_FUNCTION, schema=schema)
    def test_forced_single_function_request_has_no_json_text_fallback(self):
        _, _, _, schema, _ = smoke_fixture()
        req = build_request([], budget(), schema, SMOKE_FUNCTION)
        self.assertEqual(req["tool_choice"]["function"]["name"], SMOKE_FUNCTION)
        self.assertFalse(req["parallel_tool_calls"])
        self.assertNotIn("response_format", req)

    def test_decoder_rejects_missing_multiple_wrong_or_truncated_function_calls(self):
        _, _, _, schema, output = smoke_fixture()
        good = response(output)
        self.assertEqual(decode_response(good, function_name=SMOKE_FUNCTION, schema=schema), output)
        variants = []
        no_calls = copy.deepcopy(good); no_calls["choices"][0]["message"]["tool_calls"] = []; variants.append(no_calls)
        multiple = copy.deepcopy(good); multiple["choices"][0]["message"]["tool_calls"] *= 2; variants.append(multiple)
        wrong = response(output, ANNOTATION_FUNCTION); variants.append(wrong)
        truncated = copy.deepcopy(good); truncated["choices"][0]["finish_reason"] = "length"; variants.append(truncated)
        mixed = copy.deepcopy(good); mixed["choices"][0]["message"]["content"] = "unstructured prose"; variants.append(mixed)
        for bad in variants:
            with self.assertRaises(Blocked): decode_response(bad, function_name=SMOKE_FUNCTION, schema=schema)

    def test_duplicate_json_keys_nonfinite_and_unknown_ids_are_rejected(self):
        with self.assertRaises(Blocked): strict_json('{"id":"first","id":"second"}')
        with self.assertRaises(ValueError): strict_json('{"value":NaN}')
        _, _, _, schema, output = smoke_fixture()
        output["selections"][0]["evidence_id"] = "not-an-allowed-id"
        with self.assertRaises(Blocked): decode_response(response(output), function_name=SMOKE_FUNCTION, schema=schema)

    def test_dynamic_annotation_schema_locks_query_knowledge_and_evidence_ids(self):
        selection, kwargs = label_fixture()
        schema = selection_schema(kwargs["query"], kwargs["item"], kwargs["provider"])
        self.assertFalse(validate(selection, schema))
        self.assertNotIn("enum", schema["properties"]["rationale"])
        for key, value in (("query_id", "other-query"), ("knowledge_id", "other-knowledge"), ("evidence_ids", ["invented"])):
            changed = {**selection, key: value}
            self.assertTrue(validate(changed, schema))

    def test_real_format_function_output_is_bound_without_modifying_the_response(self):
        selection, kwargs = label_fixture()
        schema = selection_schema(kwargs["query"], kwargs["item"], kwargs["provider"])
        kwargs["request"] = build_request(kwargs["request"]["messages"], budget("VERIFIED_APPLICABILITY_PILOT"), schema, ANNOTATION_FUNCTION)
        kwargs["response"] = response(selection, ANNOTATION_FUNCTION)
        original = copy.deepcopy(kwargs["response"])
        label = finalize(selection, **kwargs)
        self.assertEqual(label["annotation_status"], "ACCEPTED", label["validation_errors"])
        self.assertEqual(kwargs["response"], original)
        self.assertEqual(label["response_hash"], digest(original))

    def test_returned_snapshot_identity_is_preserved_and_requires_allowlist(self):
        selection, kwargs = label_fixture()
        kwargs["response"]["model"] = "qwen3.8-max-0902"
        self.assertEqual(finalize(selection, **kwargs)["annotation_status"], "REVIEW_REQUIRED")
        label = finalize(selection, **kwargs, allowed_returned_models=["qwen3.8-max", "qwen3.8-max-0902"])
        self.assertEqual(label["annotation_status"], "ACCEPTED")
        self.assertEqual(label["model_id"], "qwen3.8-max-0902")


class BoundedTransportTests(unittest.TestCase):
    def test_explicit_unlimited_authorization_has_no_call_or_cost_ceiling(self):
        _, _, _, schema, output = smoke_fixture()
        config = {**budget(), "scope":"DAY1_RESEARCH", "budget_mode":"UNLIMITED", "authorized_cap_cny":None, "max_calls":None}
        calls = []
        def transport(req): calls.append(req); return response(output)
        with tempfile.TemporaryDirectory() as temp:
            client = Day1Client(temp, config, transport=transport)
            for i in range(4): client.call([], schema=schema, function_name=SMOKE_FUNCTION, prompt_version="fixture-"+str(i))
            self.assertEqual(len(calls), 4)
            self.assertIsNone(client.report()["cap_cny"])
    def test_zero_or_pending_authorization_creates_no_ledger_and_calls_nothing(self):
        with tempfile.TemporaryDirectory() as temp:
            calls = []
            config = read("configs/c1_day1_id_smoke_v02.json")
            target = Path(temp) / "must-not-exist"
            with self.assertRaises(Blocked): Day1Client(target, config, transport=lambda req: calls.append(req))
            self.assertFalse(target.exists())
            self.assertEqual(calls, [])

    def test_raw_request_response_hashes_and_success_cache_replay(self):
        _, _, _, schema, output = smoke_fixture()
        calls = []
        def transport(req): calls.append(req); return response(output)
        with tempfile.TemporaryDirectory() as temp:
            client = Day1Client(temp, budget(), transport=transport)
            first, meta = client.call([], schema=schema, function_name=SMOKE_FUNCTION, prompt_version="fixture")
            second, replay = client.call([], schema=schema, function_name=SMOKE_FUNCTION, prompt_version="fixture")
            self.assertEqual(first, second)
            self.assertEqual(len(calls), 1)
            self.assertTrue(replay["cache_hit"])
            self.assertEqual(meta["request_sha256"], digest(calls[0]))
            self.assertEqual(meta["response_sha256"], digest(response(output)))
            self.assertEqual(client.report()["attempts"], 1)

    def test_invalid_raw_response_is_retained_and_not_retried(self):
        _, _, _, schema, output = smoke_fixture()
        output["selections"][0]["evidence_id"] = "invented"
        calls = []
        def transport(req): calls.append(req); return response(output)
        with tempfile.TemporaryDirectory() as temp:
            client = Day1Client(temp, budget(), transport=transport)
            for _ in range(2):
                with self.assertRaises(Blocked): client.call([], schema=schema, function_name=SMOKE_FUNCTION, prompt_version="fixture")
            self.assertEqual(len(calls), 1)
            raw = read(next((Path(temp) / "cache").glob("*.json")))
            self.assertEqual(raw["response"], response(output))
            self.assertGreater(client.report()["reserved_cny"], 0)
            self.assertEqual(len(list((Path(temp) / "failures").glob("*.json"))), 1)

    def test_unexpected_model_cannot_be_accepted_from_cache_on_second_try(self):
        _, _, _, schema, output = smoke_fixture()
        calls = []
        def transport(req): calls.append(req); return response(output, model="different-model")
        with tempfile.TemporaryDirectory() as temp:
            client = Day1Client(temp, budget(), transport=transport)
            for _ in range(2):
                with self.assertRaises(Blocked): client.call([], schema=schema, function_name=SMOKE_FUNCTION, prompt_version="fixture")
            self.assertEqual(len(calls), 1)

    def test_call_and_input_limits_block_before_a_second_request(self):
        _, _, _, schema, output = smoke_fixture()
        config = {**budget(), "max_calls": 1}
        calls = []
        def transport(req): calls.append(req); return response(output)
        with tempfile.TemporaryDirectory() as temp:
            client = Day1Client(temp, config, transport=transport)
            client.call([], schema=schema, function_name=SMOKE_FUNCTION, prompt_version="fixture")
            with self.assertRaises(Blocked): client.call([{"role":"user","content":"changed"}], schema=schema, function_name=SMOKE_FUNCTION, prompt_version="fixture")
            with self.assertRaises(Blocked): client.call([{"role":"user","content":"x" * 60001}], schema=schema, function_name=SMOKE_FUNCTION, prompt_version="fixture")
            self.assertEqual(len(calls), 1)

    def test_smoke_authorization_cannot_be_used_for_applicability_calls(self):
        _, _, _, schema, _ = smoke_fixture()
        with tempfile.TemporaryDirectory() as temp:
            client = Day1Client(temp, budget(), transport=lambda request: self.fail("must not send"))
            with self.assertRaises(Blocked): client.call([], schema=schema, function_name=ANNOTATION_FUNCTION, prompt_version="fixture")
            self.assertEqual(client.report()["attempts"], 0)

    def test_tampered_stored_request_is_not_silently_reconstructed_as_original(self):
        _, _, _, schema, output = smoke_fixture()
        with tempfile.TemporaryDirectory() as temp:
            client = Day1Client(temp, budget(), transport=lambda request: response(output))
            client.call([], schema=schema, function_name=SMOKE_FUNCTION, prompt_version="fixture")
            next((Path(temp) / "requests").glob("*.json")).write_text('{}', encoding="utf-8")
            with self.assertRaises(Blocked): client.call([], schema=schema, function_name=SMOKE_FUNCTION, prompt_version="fixture")


class SmokeMeaningTests(unittest.TestCase):
    def test_id_exists_but_points_to_another_probe_is_a_substantive_failure(self):
        case, probes, *_ = fixture()
        probes += [make_probe("steps", 7, "sd")]
        evidence = EvidenceProvider(case, probes).all()
        target = probes[0]["probe_id"]
        wrong = next(e for e in evidence if e["probe_id"] != target)
        output = {"check_id":"check", "selections":[{"probe_id":target,"evidence_id":wrong["evidence_id"],
                  "status":wrong["status"],"measurement_kind":KINDS["steps"]}]}
        errors, _ = validate_selection(output, check_id="check", targets=[target], evidence=evidence, probes=probes)
        self.assertIn("substantive_probe_id_status_or_measurement_semantics_mismatch", errors)

    def test_missing_measurement_does_not_become_not_applicable(self):
        case, probes, *_ = fixture(None)
        evidence = EvidenceProvider(case, probes).all()
        output = {"check_id":"check", "selections":[{"probe_id":probes[0]["probe_id"],"evidence_id":evidence[0]["evidence_id"],
                  "status":"INSUFFICIENT_INFORMATION","measurement_kind":KINDS["steps"]}]}
        errors, bound = validate_selection(output, check_id="check", targets=[probes[0]["probe_id"]], evidence=evidence, probes=probes)
        self.assertFalse(errors)
        self.assertIsNone(bound[0]["value"])
        self.assertNotIn("verdict", output)


if __name__ == "__main__":
    unittest.main()
