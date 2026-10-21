"""Offline raw-chain replay and public, non-personal audit export for v04."""
from collections import Counter
from pathlib import Path
import argparse
import json

from ..common import ROOT, digest, read, require, rows, sha, write
from ..datasets.v2_sources import freeze, verify, jsonl
from ..annotation.personal_evidence import compact_catalog
from .construction_audit import (VERSION, SOURCE, KNOWLEDGE, item_schema, facet_errors,
                                  classify, construction_trace, summarize)
from .structured import decode_response, SOURCE_FUNCTION


def run(directory, ledger, output):
    directory, ledger, output = Path(directory), Path(ledger), Path(output)
    require(not output.exists(), "fresh QA/export directory required")
    run_freeze = verify(directory)
    records = rows(directory/"reviews.jsonl")
    items = {k["knowledge_id"]: k for k in rows(KNOWLEDGE/"knowledge_active.jsonl")}
    probes = read(SOURCE/"probes.json")
    require({r["knowledge_id"] for r in records} == set(items) and len(records) == 204, "incomplete original corpus audit")
    hashes = read(directory/"implementation_hashes.json")
    # The exact implementation used by the live process is archived separately.
    require(sha(directory/"implementation/construction_audit.py") == hashes["src/day1/construction_audit.py"], "executed implementation archive differs")
    require(sha(ROOT/"src/day1/client.py") == hashes["src/day1/client.py"] and
            sha(ROOT/"src/day1/structured.py") == hashes["src/day1/structured.py"], "transport implementation changed")
    caches = {p.stem: read(p) for p in (ledger/"cache").glob("*.json")}
    requests = {k:read(ledger/"requests"/(k+".json")) for k in caches}
    by_item = {}
    for key, request in requests.items():
        kid = json.loads(request["messages"][1]["content"])["item"]["knowledge_id"]
        by_item.setdefault(kid,[]).append(key)
    public = []
    tokens = Counter()
    failed_decodes = 0
    all_facets, valid_facets, direct = 0, 0, []
    for r in records:
        item = items[r["knowledge_id"]]
        require(r["item_hash"] == digest(item) and r["source_sha256"] == item["source_sha256"] and
                r["anchor_sha256"] == item["source_anchor"]["text_sha256"], "item/source chain differs")
        matching = by_item.get(r["knowledge_id"],[])
        require(len(matching) == 1, "missing or duplicated original response")
        key = matching[0]
        cache = caches[key]
        request = requests[key]
        require(cache["request_sha256"] == digest(request) and cache["response_sha256"] == digest(cache["response"]), "raw chain hash differs")
        payload = json.loads(request["messages"][1]["content"])
        require(set(payload)=={"item","full_probe_registry","original_legacy_model_conditions"}, "unexpected data in source audit")
        require(payload["full_probe_registry"] == compact_catalog(probes) and
                payload["original_legacy_model_conditions"] == item["conditions"] and
                payload["item"] == {k:item[k] for k in ("knowledge_id","text","title","topic","source_url","source_anchor")}, "audit payload differs")
        require(request["model"] == cache["response"]["model"] == "qwen3.8-max", "model identity differs")
        tokens.update({k:cache.get("usage",{}).get(k,0) for k in ("prompt_tokens","completion_tokens")})
        entry = {"knowledge_id":r["knowledge_id"], "topic":item["topic"], "source_url":item["source_url"],
                 "source_sha256":item["source_sha256"], "anchor_id":item["source_anchor"]["anchor_id"],
                 "anchor_sha256":item["source_anchor"]["text_sha256"], "status":r["status"],
                 "annotation_status":"REVIEW_REQUIRED", "human_gold":False,
                 "request_sha256":cache["request_sha256"], "response_sha256":cache["response_sha256"], "facets":[]}
        try:
            decoded = decode_response(cache["response"], function_name=SOURCE_FUNCTION, schema=item_schema(r["knowledge_id"]))
        except Exception:
            require(r["status"]=="CALL_OR_SCHEMA_FAILURE", "unexpected rejected schema")
            failed_decodes += 1
            public.append(entry)
            continue
        require(decoded == r["output"] and facet_errors(decoded,item,probes) == r["quotation_errors"], "decoded audit/validation changed")
        entry.update(source_form_model_judgment=decoded["source_form"], diagnostic_codes_model_judgment=classify(decoded),
                     no_explicit_personal_trigger_model_judgment=decoded["no_explicit_personal_trigger"],
                     quotation_errors=r["quotation_errors"], rationale_model_judgment=decoded["rationale"])
        for facet in decoded["facets"]:
            all_facets += 1
            isolated = {**decoded,"facets":[facet]}
            errors = facet_errors(isolated,item,probes)
            text = item["text"] if facet["scope"]=="ITEM" else item["source_anchor"]["text"]
            start = text.find(facet["source_quote"])
            valid_facets += not bool(errors)
            if facet["measurement"]=="PROBE_MEASURABLE_AS_STATED":
                direct.append({"knowledge_id":r["knowledge_id"], "facet_id":facet["facet_id"], "probe_ids":facet["probe_ids"],
                               "semantic_review_status":"REVIEW_REQUIRED_NOT_ADMITTED"})
            entry["facets"].append({k:v for k,v in facet.items() if k not in ("source_quote", "threshold_text", "time_text")})
            entry["facets"][-1].update(source_quote_sha256=digest(facet["source_quote"]), quote_start=start,
                                      quote_end=start+len(facet["source_quote"]) if start>=0 else -1,
                                      quotation_errors=errors, semantic_review_status="REVIEW_REQUIRED")
        public.append(entry)
    require(len(caches)==len(records), "unexpected calls outside original scope")
    require(len(list((ledger/"attempts").glob("*.json")))==len(records), "unexpected request attempts")
    report = summarize(records)
    report.update(status="PASS_RAW_CHAINS_ONLY_SEMANTIC_REVIEWS_PENDING", original_corpus_items=204,
                  raw_model_requests=len(caches), original_responses=len(caches), decoded_schema_failures=failed_decodes,
                  total_model_facets=all_facets, facets_passing_quote_and_inventory_checks=valid_facets,
                  directly_measurable_model_claims=direct, admitted_direct_measurement_claims=0,
                  source_review_artifact_id=run_freeze["release_id"], tokens=dict(tokens),
                  usage_priced_cny=(tokens["prompt_tokens"]*12+tokens["completion_tokens"]*36)/1e6,
                  actual_invoice_cny=None,
                  limitation="Quote validity is not role/construct correctness; counts are nonexclusive model screens, not adjudicated causal failure rates")
    write(output/"construction_trace.json", construction_trace())
    write(output/"source_facet_audit_qa.json", report)
    jsonl(output/"per_item_diagnostic_summary.jsonl", public)
    write(output/"benchmark_decision.json", read(ROOT/"configs/c1_ranking_redesign_v04.json"))
    freeze(output,{"version":VERSION,"status":"DIAGNOSTIC_METADATA_ONLY_NOT_EXPERIMENT_FREEZE", "human_gold":False})
    print(json.dumps(report,ensure_ascii=False),flush=True)


if __name__ == "__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--directory",default="local/day1/construction-review-v04")
    parser.add_argument("--ledger",default="local/day1/construction-ledger-v04")
    parser.add_argument("--output",required=True)
    args=parser.parse_args()
    run(args.directory,args.ledger,args.output)
