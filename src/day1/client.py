"""Fresh authorized ledger for real Day 1 function-argument calls; no retries."""
from datetime import datetime, timezone
from time import perf_counter_ns
import json
import os
from pathlib import Path

from ..common import Blocked, digest, read, require, write
from ..annotation.c1_v2_client import V2Client, ledger_lock, label_provenance, validate_model_config
from .structured import build_request, decode_response, SMOKE_FUNCTION, ANNOTATION_FUNCTION, SOURCE_FUNCTION

TRANSPORT_VERSION = "day1-forced-function-id-transport-v3-qwen-stop-compatible"


def revalidate_trace(directory, request, *, schema, function_name, allowed_models):
    """Produce a new validation result from unchanged original request/response bytes."""
    directory = Path(directory)
    matches = [p for p in (directory / "cache").glob("*.json") if read(p).get("request_sha256") == digest(request)]
    require(len(matches) <= 1, "ambiguous original response for revalidation")
    if not matches:
        return None
    path = matches[0]
    record = read(path)
    require(read(directory / "requests" / path.name) == request and record["response_sha256"] == digest(record["response"]),
            "original response/request hash mismatch")
    require(record["response"].get("model") in allowed_models, "unexpected original model")
    decoded = decode_response(record["response"], function_name=function_name, schema=schema)
    return decoded, {**record, "request": request, "revalidated_original_trace": str(path), "new_model_call": False}


class Day1Client(V2Client):
    def __init__(self, directory, config, *, api_key=None, transport=None):
        require(config.get("authorization_status") == "AUTHORIZED" and
                bool(config.get("authorization_ref", "").strip()), "explicit new call authorization required")
        require(config.get("scope") in ("EVIDENCE_ID_SMOKE_ONLY", "VERIFIED_APPLICABILITY_PILOT", "DAY1_RESEARCH"), "unapproved Day 1 scope")
        require(config["model"] == "qwen3.8-max", "Day 1 model mismatch")
        if config.get("budget_mode") == "UNLIMITED":
            require(config.get("authorized_cap_cny") is None and config.get("max_calls") is None,
                    "unlimited authorization must have null cost and call ceilings")
            validate_model_config(config)
            self.directory, self.config = Path(directory), config
            self.api_key = api_key or os.environ.get("DASHSCOPE_API_KEY")
            self.transport = transport or self._send
            self.directory.mkdir(parents=True, exist_ok=True)
            with ledger_lock(self.directory):
                budget = self.directory / "budget.json"
                if budget.exists():
                    require(read(budget) == config, "authorization changed; use a new ledger")
                else:
                    write(budget, config)
        else:
            super().__init__(directory, config, api_key=api_key, transport=transport)

    def call(self, messages, *, schema, function_name, prompt_version):
        allowed = ({SMOKE_FUNCTION, ANNOTATION_FUNCTION, SOURCE_FUNCTION} if self.config["scope"] == "DAY1_RESEARCH" else
                   {SMOKE_FUNCTION} if self.config["scope"] == "EVIDENCE_ID_SMOKE_ONLY" else {ANNOTATION_FUNCTION})
        require(function_name in allowed, "function exceeds authorized call scope")
        request = build_request(messages, self.config, schema, function_name)
        key = digest({"endpoint": self.config["base_url"], "version": TRANSPORT_VERSION,
                      "prompt_version": prompt_version, "request": request})
        cache = self.directory / "cache" / (key + ".json")
        attempt = self.directory / "attempts" / (key + ".json")
        with ledger_lock(self.directory):
            if cache.exists():
                record = read(cache)
                require(record["request_sha256"] == digest(request) and record["response_sha256"] == digest(record["response"]) and
                        record["cache_key"] == key and record["prompt_version"] == prompt_version, "Day 1 cache identity/hash mismatch")
                require(read(self.directory / "requests" / (key + ".json")) == request, "stored request differs from original")
                require(isinstance(record["response"], dict) and record["returned_model"] == record["response"].get("model") and
                        record["returned_model"] in self.config.get("allowed_returned_models", [self.config["model"]]),
                        "unexpected cached model identity")
                return decode_response(record["response"], function_name=function_name, schema=schema), {**record, "request": request, "cache_hit": True}
            require(not attempt.exists(), "prior failed/uncertain attempt retained; no automatic retry")
            require(bool(self.api_key) or self.transport != self._send, "API key required")
            size = len(json.dumps(request, ensure_ascii=False, separators=(",", ":")).encode())
            require(size <= self.config["max_input_bytes"], "input cap exceeded; no truncation")
            reserve = ((size + 1024) * self.config["input_cny_per_million"] +
                       self.config["max_tokens"] * self.config["output_cny_per_million"]) / 1e6
            attempts = [read(p) for p in (self.directory / "attempts").glob("*.json")]
            if self.config.get("budget_mode") != "UNLIMITED":
                require(len(attempts) < self.config["max_calls"] and
                        sum(a["reserved_cny"] for a in attempts) + reserve <= self.config["authorized_cap_cny"], "authorized request or CNY cap exhausted")
            write(attempt, {"cache_key": key, "request_sha256": digest(request), "reserved_cny": reserve,
                            "status": "RESERVED_MAY_HAVE_BEEN_CHARGED", "prompt_version": prompt_version,
                            "created_at": datetime.now(timezone.utc).isoformat()})
            write(self.directory / "requests" / (key + ".json"), request)
        started = perf_counter_ns()
        try:
            body = self.transport(request)
            # Save every raw response before attempting to parse/accept it.
            record = {"cache_key": key, "request_sha256": digest(request), "response_sha256": digest(body),
                      "prompt_version": prompt_version, "transport_version": TRANSPORT_VERSION,
                      "requested_model": self.config["model"],
                      "returned_model": body.get("model") if isinstance(body, dict) else None,
                      "usage": body.get("usage") if isinstance(body, dict) else None,
                      "response": body, "reserved_cny": reserve, "request_latency_ns": perf_counter_ns() - started,
                      "label_provenance": label_provenance(self.config["model"]), "human_gold": False}
            write(cache, record)
            allowed_models = self.config.get("allowed_returned_models", [self.config["model"]])
            require(record["returned_model"] in allowed_models, "unexpected returned model identity")
            output = decode_response(body, function_name=function_name, schema=schema)
            return output, {**record, "request": request, "cache_hit": False}
        except Exception as exc:
            write(self.directory / "failures" / (key + ".json"),
                  {"cache_key": key, "exception_type": type(exc).__name__, "http_status": getattr(exc, "code", None),
                   "reserved_cny": reserve, "retry_authorized": False, "raw_response_retained": cache.exists()})
            raise Blocked("Day 1 call rejected/failed; original attempt retained: " + type(exc).__name__) from None
