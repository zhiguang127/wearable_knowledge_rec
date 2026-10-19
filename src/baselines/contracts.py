"""Historical B0 output contract and mechanical evidence audit; not a clinical validator."""

def validate(value, case):
    ids = case["candidate_ids"]
    errors = []
    if not isinstance(value, dict):
        return ["output_not_object"]
    groups = value.get("ranking", [])
    flat = [k for group in groups if isinstance(group, list) for k in group]
    if len(flat) != len(ids) or set(flat) != set(ids) or any(not isinstance(g, list) or not g for g in groups):
        errors.append("ranking_must_partition_all_candidates")
    items = value.get("items", [])
    if not isinstance(items, list) or len(items) != len(ids) or any(not isinstance(x, dict) for x in items):
        return errors + ["candidate_item_set_invalid"]
    if {x.get("id") for x in items} != set(ids):
        errors.append("candidate_item_set_invalid")
    for x in items:
        if x.get("applicability") not in ("applicable", "not_applicable", "insufficient_information"):
            errors.append("invalid_applicability")
        if not isinstance(x.get("explanation"), str) or not x["explanation"]:
            errors.append("missing_explanation")
        if not isinstance(x.get("evidence"), list):
            errors.append("evidence_array_missing")
    return errors

def evidence_audit(value, case):
    from ..evaluation.evidence import resolve
    result = {"citations": 0, "invalid_reference": 0, "invalid_value": 0,
              "unusable_physiology": 0, "missing_evidence_items": 0, "valid_citations": 0}
    for x in value.get("items", []):
        refs = x.get("evidence", [])
        if not refs:
            result["missing_evidence_items"] += 1
        for e in refs:
            result["citations"] += 1
            if not isinstance(e, dict) or e.get("purpose") not in ("physiology", "missingness", "context"):
                result["invalid_reference"] += 1
                continue
            try:
                actual, phase = resolve(case, e["ref"])
            except (ValueError, KeyError, TypeError, IndexError):
                result["invalid_reference"] += 1
                continue
            expected = e.get("value")
            same = (isinstance(actual, (float, int)) and not isinstance(actual, bool) and
                    isinstance(expected, (float, int)) and not isinstance(expected, bool) and abs(actual - expected) <= .011)
            if not same and actual != expected:
                result["invalid_value"] += 1
            elif (actual is None or (e["ref"].endswith("resting_heart_rate_bpm") and actual == 0)) and e["purpose"] == "physiology":
                result["unusable_physiology"] += 1
            else:
                result["valid_citations"] += 1
    return result
