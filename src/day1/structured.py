"""Declarative, exactly-one function output; functions never execute model code."""
from copy import deepcopy
import json

from ..common import require
from ..annotation.validation import validate
from .schemas import SELECTION

ANNOTATION_FUNCTION = "record_day1_annotation"
SMOKE_FUNCTION = "record_evidence_id_check"
SOURCE_FUNCTION = "record_knowledge_source_review"


def strict_json(text):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "duplicate JSON key")
            result[key] = value
        return result
    def invalid_constant(value):
        raise ValueError("nonfinite JSON constant")
    return json.loads(text, object_pairs_hook=pairs, parse_constant=invalid_constant)


def selection_schema(query, item, provider):
    # Schema helpers share STR/STRINGS objects. deepcopy preserves those aliases;
    # JSON round-trip creates independent field nodes before adding ID enums.
    schema = json.loads(json.dumps(SELECTION))
    props = schema["properties"]
    props["query_id"]["enum"] = [query["query_id"]]
    props["knowledge_id"]["enum"] = [item["knowledge_id"]]
    required = sorted({pid for c in item["conditions"] for p in c["predicates"] for pid in p["probe_ids"]})
    ids = [provider.get(pid)["evidence_id"] for pid in required]
    for field, allowed in (("evidence_ids", ids), ("condition_ids", [c["condition_id"] for c in item["conditions"]])):
        props[field].update(minItems=len(allowed), maxItems=len(allowed), uniqueItems=True)
        if allowed:
            props[field]["items"]["enum"] = allowed
    return schema


def build_request(messages, config, schema, function_name):
    require(function_name in (ANNOTATION_FUNCTION, SMOKE_FUNCTION, SOURCE_FUNCTION), "unknown declarative output function")
    return {"model": config["model"], "messages": deepcopy(messages), "temperature": 0,
            "enable_thinking": False, "stream": False, "max_tokens": config["max_tokens"],
            "tools": [{"type": "function", "function": {"name": function_name,
                       "description": "Record structured research output only; no action is executed.",
                       "parameters": deepcopy(schema)}}],
            "tool_choice": {"type": "function", "function": {"name": function_name}},
            "parallel_tool_calls": False}


def decode_response(body, *, function_name, schema):
    require(isinstance(body, dict) and len(body.get("choices", [])) == 1, "exactly one response choice required")
    choice = body["choices"][0]
    # Observed Qwen endpoint can use stop alongside a complete tool_calls payload.
    # Never accept length/null, missing calls, free text or invalid arguments.
    require(choice.get("finish_reason") in ("tool_calls", "stop"), "incomplete or non-function output")
    message = choice["message"]
    require(message.get("content") in (None, ""), "unexpected mixed free-text output")
    require(not message.get("refusal"), "model refusal is not an annotation")
    calls = message.get("tool_calls") or []
    require(len(calls) == 1 and calls[0].get("type") == "function" and
            calls[0]["function"]["name"] == function_name, "exactly one expected declarative function required")
    output = strict_json(calls[0]["function"]["arguments"])
    require(not validate(output, schema), "function arguments violate schema/ID allowlist")
    return output
