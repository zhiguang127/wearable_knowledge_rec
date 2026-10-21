"""Explicit source-bound predicate/relation validation, independent of probe arity.

Citation integrity is necessary but never proves semantic entailment. Real legacy
conditions remain candidates pending per-predicate and relation-level semantic review.
"""
from ..common import digest
from .validation import validate
from .schemas import obj, arr, STR, enum
from .c1_v2_schemas import CITATION

PREDICATE = obj({"predicate_id": STR, "claim": STR, "probe_id": STR,
                 "operator": enum("lt", "le", "eq", "ge", "gt", "between"),
                 "threshold": {"type": "array", "items": {"type": "number"}},
                 "unit": STR, "source_citations": arr(CITATION)})
RELATION = obj({"logic": enum("ALL", "ANY"), "predicate_ids": arr(STR),
                "source_citations": arr(CITATION)})
DEPENDENCY = obj({"predicates": arr(PREDICATE), "relation": RELATION})


def citation_integrity(cites, item, claim=None):
    """Locate immutable bytes; record scope without pretending to infer entailment."""
    errors, spans = [], []
    anchor = item["source_anchor"]
    if digest(anchor["text"]) != anchor["text_sha256"]:
        return ["citation_anchor_text_hash_mismatch"], []
    for cite in cites:
        if cite["anchor_id"] != anchor["anchor_id"] or cite["source_sha256"] != item["source_sha256"]:
            errors.append("citation_source_identity_mismatch")
            continue
        quote = cite["quote"]
        if not quote.strip() or quote not in anchor["text"]:
            errors.append("citation_quote_not_in_source")
            continue
        start = anchor["text"].index(quote)
        spans.append({**cite, "start": start, "end": start + len(quote),
                      "anchor_text_sha256": anchor["text_sha256"],
                      "candidate_text_overlap": bool(item.get("text") and
                          (quote in item["text"] or item["text"] in quote)),
                      "claim_sha256": digest(claim) if claim is not None else None,
                      "semantic_support": "NOT_ESTABLISHED_BY_STRING_OR_HASH_CHECK"})
    return errors, spans


def validate_dependency(dependency, item, probes):
    """Validate each leaf and the relation, accepting ALL and ANY equally.

    Passing here means structurally auditable, not source-confirmed or medically true.
    No language model or guessed threshold is introduced by this function.
    """
    errors = validate(dependency, DEPENDENCY)
    spans = []
    if errors:
        return {"structural_errors": errors, "candidate_preserved": True,
                "semantic_status": "REVIEW_REQUIRED", "confirmed_rule": False}
    pmap = {p["probe_id"]: p for p in probes}
    ids = [p["predicate_id"] for p in dependency["predicates"]]
    if not ids or len(ids) != len(set(ids)):
        errors.append("predicate_inventory_empty_or_duplicated")
    relation = dependency["relation"]
    if set(relation["predicate_ids"]) != set(ids) or len(relation["predicate_ids"]) != len(ids):
        errors.append("relation_must_reference_each_predicate_once")
    for predicate in dependency["predicates"]:
        probe = pmap.get(predicate["probe_id"])
        if probe is None:
            errors.append("predicate_probe_not_executable")
        elif predicate["unit"] != probe["unit"]:
            errors.append("predicate_unit_mismatch")
        thresholds = predicate["threshold"]
        if len(thresholds) != (2 if predicate["operator"] == "between" else 1):
            errors.append("predicate_threshold_arity")
        if len(thresholds) == 2 and thresholds[0] > thresholds[1]:
            errors.append("predicate_range_reversed")
        if not predicate["source_citations"]:
            errors.append("predicate_source_missing")
        found, positions = citation_integrity(predicate["source_citations"], item, predicate["claim"])
        errors += found
        spans += positions
    if not relation["source_citations"]:
        errors.append("relation_source_missing")
    found, positions = citation_integrity(relation["source_citations"], item, relation["logic"])
    errors += found
    spans += positions
    return {"structural_errors": errors, "citation_spans": spans,
            "candidate_preserved": True, "structurally_auditable": not errors,
            "semantic_status": "REVIEW_REQUIRED", "confirmed_rule": False,
            "reason": "Per-predicate entailment and the connective require targeted source review; quote presence alone is insufficient."}


def audit_legacy_condition(condition, item, probes):
    """Keep all old conditions, including multi-probe ALL, with explicit audit gaps."""
    pids = {p["probe_id"] for p in probes}
    errors, spans = citation_integrity(condition.get("source_citations", []), item, condition.get("text"))
    missing = sorted(set(condition.get("probe_ids", [])) - pids)
    if missing:
        errors.append("condition_unknown_probe")
    return {"condition_id": condition["condition_id"], "original_condition": condition,
            "citation_integrity_errors": errors, "citation_spans": spans,
            "candidate_preserved": True,
            "is_joint_candidate": condition.get("logic") == "ALL" and len(condition.get("probe_ids", [])) > 1,
            "predicate_and_relation_audit": validate_dependency(condition["dependency"], item, probes)
                if condition.get("dependency") else {"semantic_status": "REVIEW_REQUIRED", "confirmed_rule": False,
                    "reason": "Legacy schema has no per-probe predicates or relation-specific support; preserved for targeted review."},
            "semantic_status": "REVIEW_REQUIRED", "confirmed_rule": False}
