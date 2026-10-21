"""Unrestricted-run source-rule admission and immutable-trace checks."""
import copy
from pathlib import Path
import tempfile
import unittest

from src.common import Blocked, digest, read, sha, write
from src.day1.client import revalidate_trace
from src.day1.contracts import validate_knowledge
from src.day1.structured import SMOKE_FUNCTION
from src.day1.source_review import proposal_errors, audit_errors, verified_item
from tests.test_day1 import fixture
from tests.test_day1_v02 import smoke_fixture, response


def source_fixture():
    _, probes, source, item, _ = fixture()
    condition = copy.deepcopy(item["conditions"][0])
    condition.pop("knowledge_id"); condition.pop("semantic_review")
    condition["source_quote"] = condition.pop("source_citation")["quote"]
    for p in condition["predicates"]:
        p.pop("semantic_review")
        p["source_quote"] = p.pop("source_citation")["quote"]
    proposal = {"knowledge_id": item["knowledge_id"], "decision": "CANDIDATE_MEASURABLE_RULE", "reason_codes": [],
                "conditions": [condition], "logic": "ALL", "role": "necessary_and_sufficient", "source_quote": source["text"],
                "missing_context": [], "rationale": "Nonmedical test fixture only."}
    audit = {"knowledge_id": item["knowledge_id"], "verdict": "SUPPORTED_MEASURABLE_PERSONAL_APPLICABILITY_RULE",
             "applicability_not_merely_recommendation": True, "source_roles_complete": True,
             "condition_checks": [{"condition_id":"c1","role_supported":True,"connective_supported":True,
              "predicate_checks":[{"predicate_id":"p1","source_entails":True,"measurement_equivalent":True,
                                   "threshold_and_time_supported":True,"rationale":"Synthetic test."}],"rationale":"Synthetic."}],
             "missing_context":[],"source_quote":source["text"],"rationale":"Synthetic, not a real clinical rule."}
    return probes, source, proposal, audit


class SourceAdmissionTests(unittest.TestCase):
    def test_rule_requires_both_structural_and_independent_call_semantic_checks(self):
        probes, source, proposal, audit = source_fixture()
        self.assertFalse(proposal_errors(proposal, source, probes))
        self.assertFalse(audit_errors(proposal, audit, source))
        item = verified_item(source, proposal, {"audit":audit})
        self.assertFalse(validate_knowledge(item, probes, source))
        self.assertEqual(item["semantic_review"]["reviewer_kind"], "model")

    def test_unknown_context_and_wrong_probe_meanings_block_admission(self):
        probes, source, proposal, audit = source_fixture()
        proposal["missing_context"] = ["age"]
        self.assertIn("unobserved_required_context", proposal_errors(proposal, source, probes))
        proposal["conditions"][0]["predicates"][0]["unit"] = "hours"
        self.assertIn("probe_construct_or_unit_or_time_mismatch", proposal_errors(proposal, source, probes))

    def test_citation_match_does_not_override_failed_entailment_or_recommendation_role(self):
        _, source, proposal, audit = source_fixture()
        audit["applicability_not_merely_recommendation"] = False
        audit["condition_checks"][0]["predicate_checks"][0]["source_entails"] = False
        errors = audit_errors(proposal, audit, source)
        self.assertIn("source_role_or_context_unresolved", errors)
        self.assertIn("predicate_semantics_not_supported", errors)

    def test_unreviewed_leaf_or_invented_quote_does_not_pass(self):
        probes, source, proposal, audit = source_fixture()
        proposal["source_quote"] = "not in the source"
        self.assertIn("quote_not_in_frozen_source", proposal_errors(proposal, source, probes))
        audit["condition_checks"][0]["predicate_checks"] = []
        self.assertIn("audit_predicate_inventory_mismatch", audit_errors(proposal, audit, source))


class ImmutableTraceRevalidationTests(unittest.TestCase):
    def test_stop_compatibility_creates_no_edits_to_old_response_or_request(self):
        _, _, _, schema, output = smoke_fixture()
        body = response(output); body["choices"][0]["finish_reason"] = "stop"
        request = {"model":"qwen3.8-max","test":"original request"}
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            write(root/"requests/key.json",request)
            write(root/"cache/key.json",{"request_sha256":digest(request),"response_sha256":digest(body),"response":body})
            before = {str(p):sha(p) for p in root.rglob("*.json")}
            selected, trace = revalidate_trace(root,request,schema=schema,function_name=SMOKE_FUNCTION,allowed_models=["qwen3.8-max"])
            self.assertEqual(selected, output)
            self.assertFalse(trace["new_model_call"])
            self.assertEqual(before,{str(p):sha(p) for p in root.rglob("*.json")})

    def test_tampered_original_hash_is_rejected(self):
        _, _, _, schema, output = smoke_fixture()
        body=response(output); request={"model":"qwen3.8-max"}
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            write(root/"requests/key.json",request)
            write(root/"cache/key.json",{"request_sha256":digest(request),"response_sha256":"0"*64,"response":body})
            with self.assertRaises(Blocked):
                revalidate_trace(root,request,schema=schema,function_name=SMOKE_FUNCTION,allowed_models=["qwen3.8-max"])


if __name__=="__main__":
    unittest.main()
