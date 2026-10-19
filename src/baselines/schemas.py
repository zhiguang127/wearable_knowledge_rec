"""Typed output transport for Qwen's known null-array JSON-mode failure."""
def obj(properties, required=None):
    return {"type": "object", "properties": properties, "required": list(properties) if required is None else required, "additionalProperties": False}


def array(items):
    return {"type": "array", "items": items}


S = {"type": "string"}
B = {"type": "boolean"}
EVIDENCE = obj({"ref": S, "value": {"type": ["number", "string", "boolean", "null"]},
                "purpose": {"type": "string", "enum": ["physiology", "missingness", "context"]}})
ITEM = obj({"id": S, "applicability": {"type": "string", "enum": ["applicable", "not_applicable", "insufficient_information"]},
            "explanation": S, "evidence": array(EVIDENCE)})
PAIRS = array(obj({"higher": S, "lower": S, "reason": S}))
SCHEMAS = {
    "rank": obj({"ranking": array(array(S)), "priority_identifiable": B}),
    "items": obj({"items": array(ITEM), "pairwise_reasons": PAIRS}),
    "reason": obj({"reasoning": array(obj({"id": S, "reason": S})), "uncertainties": array(S)}),
    "feedback": obj({"feedback": array(S)}),
    "query": obj({"query": S}),
    "gate": obj({"reason": S, "agrees": B}),
}
SCHEMAS["full"] = obj({**SCHEMAS["rank"]["properties"], **SCHEMAS["items"]["properties"]})
