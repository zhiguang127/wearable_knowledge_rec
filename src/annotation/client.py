"""Cache-only SilverClient: no network, credentials, live SDK or paid transport.

Legacy prices/authorizations remain historical records and confer no new budget.
"""
from pathlib import Path
from ..common import Blocked, ROOT, digest, inside, read, require
from .validation import validate


def request_options(messages, max_tokens=4096, schema=None, *, model="qwen-max"):
    require(isinstance(model, str) and bool(model.strip()), "explicit model identity required")
    require(isinstance(max_tokens, int) and not isinstance(max_tokens, bool) and max_tokens > 0, "invalid output ceiling")
    request = {"model": model, "messages": messages, "temperature": 0,
               "max_tokens": max_tokens, "response_format": {"type": "json_object"}, "stream": False}
    if schema is not None:
        del request["response_format"]
        request["tools"] = [{"type": "function", "function": {"name": "record_silver_audit",
            "description": "Return the complete structured Silver audit. This declarative record function is never executed.",
            "parameters": schema}}]
        request["tool_choice"] = {"type": "function", "function": {"name": "record_silver_audit"}}
    return request


class SilverClient:
    def __init__(self, root=None, *, model="qwen-max"):
        self.root = Path(root or ROOT / "local/archive/experiment_a/silver_annotations/v1").resolve()
        self.model = model

    def call(self, messages, *, tag=None, max_tokens=4096, schema=None, retry_invalid_once=False):
        require(not retry_invalid_once, "offline replay never retries or replaces malformed responses")
        request = request_options(messages, max_tokens, schema, model=self.model)
        key = digest(request)
        path = inside(self.root, "cache/" + key + ".json")
        if not path.exists():
            raise Blocked("BLOCKED_OFFLINE_CACHE_MISS: no new model calls authorized")
        cached = read(path)
        require(cached["request_sha256"] == key and digest(cached["response"]) == cached["response_sha256"],
                "Silver cache integrity mismatch")
        value = self.decode(cached["response"])
        if schema is not None:
            require(not validate(value, schema), "cached output fails declared schema; raw response retained")
        return value, {**cached["metadata"], "cache_hit": True, "request_sha256": key,
                       "label_provenance": "QWEN_MAX_SILVER", "human_gold": False, "new_requests": 0}

    @staticmethod
    def decode(body):
        import json
        choice = body["choices"][0]
        if choice["finish_reason"] == "tool_calls":
            calls = choice["message"].get("tool_calls") or []
            require(len(calls) == 1 and calls[0]["function"]["name"] == "record_silver_audit", "unexpected declarative output function")
            return json.loads(calls[0]["function"]["arguments"])
        require(choice["finish_reason"] == "stop", "incomplete cached output; not a label")
        return json.loads(choice["message"]["content"])


def audit_budget(path):
    """Inspect the original pessimistic ledger; never spend or transfer its balance."""
    b = read(path)
    attempts = b["attempts"]
    used = sum(a.get("charged_estimate_cny", a["reserved_cny"]) for a in attempts)
    require(len(attempts) <= b["max_calls"] and used <= b["cap_cny"] + 1e-9, "historical budget ceiling violated")
    return {"model": b["model"], "historical_attempts": len(attempts), "historical_accounted_cny": used,
            "historical_cap_cny": b["cap_cny"], "actual_invoice_cny": None,
            "new_calls_authorized": False, "new_calls": 0}
