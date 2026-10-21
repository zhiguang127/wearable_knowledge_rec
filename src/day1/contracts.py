"""Fail-closed semantic admission and role-aware applicability checks.

    String/hash checks establish integrity only. A separate recorded review
    is required at knowledge, condition/connective and predicate levels.
"""
from ..common import digest, require
from ..annotation.validation import validate
from .schemas import KNOWLEDGE, QUERY


def public_query(query):
    result = {k: query[k] for k in QUERY["properties"]}
    require(not validate(result, QUERY), "invalid query schema")
    require(bool(result["query_id"]) and bool(result["case_id"]) and bool(result["candidate_ids"]) and
            len(result["candidate_ids"]) == len(set(result["candidate_ids"])), "invalid query identity or candidates")
    return result


def validate_knowledge(item, probes, source_item):
    errors = validate(item, KNOWLEDGE)
    if errors:
        return errors
    pmap = {p["probe_id"]: p for p in probes}
    anchor = source_item["source_anchor"]

    def review(record):
        if record["status"] != "VERIFIED":
            errors.append("semantic_review_not_verified")
        if not record["reviewer_id"].strip() or not record["rationale"].strip():
            errors.append("semantic_review_record_incomplete")

    def citation(cite):
        if (cite["source_url"] != source_item["source_url"] or
            cite["source_sha256"] != source_item["source_sha256"] or
            cite["anchor_id"] != anchor["anchor_id"] or
            cite["anchor_sha256"] != anchor["text_sha256"] or
            digest(anchor["text"]) != anchor["text_sha256"] or
            not cite["quote"].strip() or cite["quote"] not in anchor["text"]):
            errors.append("source_anchor_integrity_mismatch")

    if item["knowledge_id"] != source_item["knowledge_id"] or item["text"] != source_item["text"] or item["topic"] != source_item["topic"]:
        errors.append("knowledge_source_identity_mismatch")
    review(item["semantic_review"])
    citation(item["source_citation"])
    cids, pids = [], []
    if (item["criteria_kind"] == "MEASURABLE") != bool(item["conditions"]):
        errors.append("criteria_kind_condition_inventory_mismatch")
    for condition in item["conditions"]:
        cids.append(condition["condition_id"])
        if condition["knowledge_id"] != item["knowledge_id"] or not condition["predicates"]:
            errors.append("condition_identity_or_predicates_missing")
        if not condition["role_rationale"].strip():
            errors.append("condition_role_rationale_missing")
        review(condition["semantic_review"])
        citation(condition["source_citation"])
        for p in condition["predicates"]:
            pids.append(p["predicate_id"])
            review(p["semantic_review"])
            citation(p["source_citation"])
            thresholds = p["threshold"]
            if len(thresholds) != (2 if p["operator"] == "between" else 1) or (len(thresholds) == 2 and thresholds[0] > thresholds[1]):
                errors.append("invalid_threshold")
            if not p["probe_ids"] or len(p["probe_ids"]) != len(set(p["probe_ids"])):
                errors.append("invalid_predicate_probe_inventory")
            # Multiple IDs are permitted only as exact equivalent definitions.
            for pid in p["probe_ids"]:
                probe = pmap.get(pid)
                if probe is None or any(probe[k] != p[f] for k, f in
                    (("metric", "variable"), ("unit", "unit"), ("window_days", "window_days"),
                     ("offset_days", "offset_days"), ("operation", "operation"), ("comparison", "comparison"))):
                    errors.append("predicate_probe_semantics_mismatch")
    if len(cids) != len(set(cids)) or len(pids) != len(set(pids)):
        errors.append("duplicate_condition_or_predicate_id")
    return sorted(set(errors))


def truth(predicate, observed):
    """None includes unacquired and insufficient; neither is false."""
    results = [observed[pid] for pid in predicate["probe_ids"] if pid in observed]
    valid = [e for e in results if e["status"] == "COMPUTED"]
    if not valid:
        return None
    require(all(e["unit"] == predicate["unit"] for e in valid), "predicate evidence unit mismatch")
    value = valid[0]["value"]
    require(all(e["value"] == value for e in valid), "inconsistent equivalent probes")
    t = predicate["threshold"]
    return {"lt": lambda: value < t[0], "le": lambda: value <= t[0], "eq": lambda: value == t[0],
            "ge": lambda: value >= t[0], "gt": lambda: value > t[0],
            "between": lambda: t[0] <= value <= t[1]}[predicate["operator"]]()


def combine(values, logic):
    require(bool(values), "empty logical expression")
    if logic == "ALL":
        return False if False in values else None if None in values else True
    return True if True in values else None if None in values else False


def condition_truth(condition, observed):
    return combine([truth(p, observed) for p in condition["predicates"]], condition["logic"])


def expected_verdict(item, complete_evidence):
    """Annotation uses the full available record, never acquisition state."""
    if item["criteria_kind"] != "MEASURABLE":
        return "not_assessable", item["criteria_kind"]
    observed = {e["probe_id"]: e for e in complete_evidence}
    required = {pid for c in item["conditions"] for p in c["predicates"] for pid in p["probe_ids"]}
    require(required <= set(observed), "annotation requires the complete allowed measurement pool")
    if any(observed[pid]["status"] != "COMPUTED" for pid in required):
        return "insufficient_information", "MISSING_VALID_MEASUREMENTS"
    state = combine([condition_truth(c, observed) for c in item["conditions"]], item["logic"])
    if state is True and item["role"] in ("sufficient", "necessary_and_sufficient"):
        return "applicable", "VERIFIED_CONDITIONS_SATISFIED"
    if state is False and item["role"] in ("necessary", "necessary_and_sufficient"):
        return "not_applicable", "VERIFIED_CONDITIONS_NEGATED"
    return None, "CONDITION_ROLE_NOT_DECISIVE"
