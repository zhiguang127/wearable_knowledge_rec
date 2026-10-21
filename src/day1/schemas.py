"""Versioned declarations; selecting evidence IDs never copies measurements."""
from ..annotation.schemas import obj, arr, enum, STR, BOOL, STRINGS

SHA = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
REVIEW = enum("VERIFIED", "REVIEW_REQUIRED", "REJECTED")
VERDICT = enum("applicable", "not_applicable", "insufficient_information", "not_assessable")
REASONS = enum("VERIFIED_CONDITIONS_SATISFIED", "VERIFIED_CONDITIONS_NEGATED",
               "MISSING_VALID_MEASUREMENTS", "UNMEASURABLE_HEALTH_CONTEXT",
               "NO_PERSONAL_APPLICABILITY_CRITERION")
SELECTION = obj({"query_id": STR, "knowledge_id": STR, "verdict": VERDICT,
                 "reason_code": REASONS, "evidence_ids": STRINGS,
                 "condition_ids": STRINGS, "rationale": STR})
CITATION = obj({"source_url": STR, "source_sha256": SHA, "anchor_id": STR,
                "anchor_sha256": SHA, "quote": STR})
REVIEW_RECORD = obj({"status": REVIEW, "reviewer_id": STR, "reviewer_kind":
                    enum("human", "model"), "rationale": STR, "review_artifact_sha256": SHA})
PREDICATE = obj({"predicate_id": STR, "variable": STR, "operator":
                 enum("lt", "le", "eq", "ge", "gt", "between"),
                 "threshold": arr({"type": "number"}), "unit": STR,
                 "window_days": {"type": "integer"}, "offset_days": {"type": "integer"},
                 "operation": STR, "comparison": STR, "probe_ids": STRINGS,
                 "source_citation": CITATION, "semantic_review": REVIEW_RECORD})
CONDITION = obj({"knowledge_id": STR, "condition_id": STR, "logic": enum("ALL", "ANY"),
                 "role": enum("necessary", "sufficient", "necessary_and_sufficient", "other"),
                 "role_rationale": STR,
                 "predicates": arr(PREDICATE), "source_citation": CITATION,
                 "semantic_review": REVIEW_RECORD})
KNOWLEDGE = obj({"knowledge_id": STR, "topic": STR, "text": STR,
                 "criteria_kind": enum("MEASURABLE", "UNMEASURABLE_HEALTH_CONTEXT",
                                       "NO_PERSONAL_APPLICABILITY_CRITERION"),
                 "conditions": arr(CONDITION), "logic": enum("ALL", "ANY"),
                 "role": enum("necessary", "sufficient", "necessary_and_sufficient", "other"),
                 "source_citation": CITATION, "semantic_review": REVIEW_RECORD})
ANNOTATION = obj({**SELECTION["properties"], "annotation_status":
                  enum("ACCEPTED", "REVIEW_REQUIRED", "REJECTED"),
                  "model_id": STR, "prompt_version": STR, "schema_version": STR,
                  "request_hash": SHA, "response_hash": SHA,
                  "label_tier": enum("Silver / Pseudo-Gold"), "human_gold": {"type": "boolean", "enum": [False]},
                  "bound_evidence": arr({"type": "object"}), "validation_errors": STRINGS})
EVIDENCE = obj({"evidence_id": STR, "case_id": STR, "probe_id": STR,
                "status": enum("COMPUTED", "INSUFFICIENT_INFORMATION"),
                "value": {"type": ["number", "null"]}, "unit": STR,
                "start_time": STR, "end_time": STR, "missing_reason": {"type": ["string", "null"]},
                "source_ref": {"type": "object"}, "result_hash": SHA, "computation_hash": SHA})
QUERY = obj({"query_id": STR, "case_id": STR, "topic": STR,
             "goal": {"type": ["string", "null"]}, "candidate_ids": STRINGS})
OBSERVATION = obj({"query": QUERY, "observed_evidence": arr(EVIDENCE),
                   "candidates": arr({"type": "object"}),
                   "ranking": arr(arr({"anyOf": [STR, {"type": "number"}]})),
                   "remaining_budget": {"type": "integer"}, "spent_probes": {"type": "integer"},
                   "unobserved_state": enum("not_yet_acquired"), "ranker_version": STR,
                   "last_acquisition_latency_ns": {"type": "integer"}})
OBSERVATION["required"].remove("last_acquisition_latency_ns")
