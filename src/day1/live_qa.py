"""Offline raw-transport and deterministic-binding QA, with no new model calls."""
from collections import Counter
from pathlib import Path
import json

from ..common import ROOT, digest, read, require, rows, write
from ..datasets.v2_sources import verify
from .structured import decode_response, SOURCE_FUNCTION, SMOKE_FUNCTION
from .source_review import schema_for, PROPOSAL, AUDIT, proposal_errors, audit_errors
from .evidence import EvidenceProvider
from .id_smoke import validate_selection


def validate_all(output):
    config=read(ROOT/"configs/c1_day1_v01.json")
    for name in ("source_release","knowledge_release","result_store"):
        require(verify(ROOT/config[name])["release_id"]==config[name+"_id"],"frozen input changed")
    source=ROOT/"local/day1/qwen-source-review-v03"
    smoke=ROOT/"local/day1/id-smoke-live-v03-r1"
    plan=ROOT/"local/day1/id-smoke-plan-v03-r1"
    for p in (source,smoke,plan,ROOT/"local/day1/id-smoke-live-v03"):
        verify(p)
    ledgers=[ROOT/"local/day1/id-smoke-ledger-v03",ROOT/"local/day1/id-smoke-ledger-v03-r1",ROOT/"local/day1/qwen-source-ledger-v03"]
    traces={};usage=Counter();model_names=set();reason_counts=Counter();calls_by_ledger={}
    for ledger in ledgers:
        budget=read(ledger/"budget.json")
        require(budget["budget_mode"]=="UNLIMITED" and budget["max_calls"] is None and budget["authorized_cap_cny"] is None,"usage ceiling was not removed")
        paths=list((ledger/"cache").glob("*.json"));calls_by_ledger[ledger.name]=len(list((ledger/"attempts").glob("*.json")))
        require(calls_by_ledger[ledger.name]==len(paths),"response missing for a charged/uncertain request")
        for p in paths:
            trace=read(p);request=read(ledger/"requests"/p.name);body=trace["response"]
            require(digest(request)==trace["request_sha256"] and digest(body)==trace["response_sha256"],"raw hash mismatch")
            require(trace["requested_model"]==request["model"] and trace["returned_model"]==body["model"] and body["model"] in budget["allowed_returned_models"],"raw model mismatch")
            require(trace["request_sha256"] not in traces,"duplicate original request counted twice")
            traces[trace["request_sha256"]]=(trace,request)
            model_names.add(body["model"])
            reason_counts.update(c["finish_reason"] for c in body["choices"])
            usage.update({"prompt_tokens":body["usage"]["prompt_tokens"],"completion_tokens":body["usage"]["completion_tokens"]})
    knowledge={k["knowledge_id"]:k for k in rows(ROOT/config["knowledge_release"]/"knowledge_active.jsonl")}
    probes=read(ROOT/config["source_release"]/"probes.json")
    reviews=rows(source/"reviews.jsonl")
    require(len(reviews)==204 and {r["knowledge_id"] for r in reviews}==set(knowledge),"incomplete source review")
    review_chains=0
    for record in reviews:
        item=knowledge[record["knowledge_id"]]
        require("proposal" in record,"failed source extraction is not a completed review")
        for stage,field,schema in ((1,"proposal",PROPOSAL),(2,"audit",AUDIT)):
            if field not in record:
                continue
            trace,request=traces[record[f"stage{stage}_request_hash"]]
            require(record[f"stage{stage}_response_hash"]==trace["response_sha256"],"saved review is not original response")
            decoded=decode_response(trace["response"],function_name=SOURCE_FUNCTION,schema=schema_for(schema,item["knowledge_id"]))
            require(decoded==record[field],"historical model output edited")
            payload=json.loads(request["messages"][1]["content"])
            expected={k:item[k] for k in ("knowledge_id","topic","title","text","source_url","source_anchor")}
            require(payload["knowledge"]==expected and payload["full_probe_registry"]["count"]==288,"source or probe scope differs")
            if stage==1:
                require("first_review" not in payload,"prior judgment leaked into first source review")
            else:
                require(payload["first_review"]==record["proposal"],"second reviewer saw edited first review")
            review_chains+=1
        require(proposal_errors(record["proposal"],item,probes)==record["proposal_errors"],"proposal validation drift")
        if "audit" in record:
            require(audit_errors(record["proposal"],record["audit"],item)==record["audit_errors"],"semantic check validation drift")
    cases={c["case_id"]:c for c in rows(ROOT/config["source_release"]/"cases.jsonl")}
    smoke_plan=read(plan/"plan.json")
    provider=EvidenceProvider(cases[smoke_plan["case_id"]],probes)
    binding=read(plan/"evidence_binding.json")
    checks=0;bound_count=0;statuses=Counter()
    for check in smoke_plan["checks"]:
        record=read(smoke/(check["check_id"]+".json"))
        trace,request=traces[record["request_hash"]]
        require(record["response_hash"]==trace["response_sha256"],"smoke trace edited")
        decoded=decode_response(trace["response"],function_name=SMOKE_FUNCTION,schema=request["tools"][0]["function"]["parameters"])
        require(decoded==record["original_selection"],"smoke output edited")
        errors,bound=validate_selection(decoded,check_id=check["check_id"],targets=check["targets"],evidence=binding,probes=probes)
        require(not errors and bound==record["bound_evidence"],"smoke reference binding mismatch")
        for e in bound:
            provider.verify_bound(e)
            statuses[e["status"]]+=1
        checks+=1;bound_count+=len(bound)
    source_report=read(source/"report.json")
    admitted=read(source/"verified_measurable_knowledge.json")
    require(len(admitted)==source_report["verified_measurable_knowledge"],"admitted count differs")
    result={"status":"PASS_RAW_CHAINS_AND_MECHANICAL_BINDING_ONLY","original_model_requests":sum(calls_by_ledger.values()),
            "calls_by_ledger":calls_by_ledger,"source_review_items":len(reviews),"source_request_response_chains":review_chains,
            "source_statuses":dict(Counter(r["status"] for r in reviews)),"candidate_proposals":source_report["candidate_proposals"],
            "second_source_reviews":source_report["second_stage_reviews"],"verified_measurable_knowledge":len(admitted),
            "real_id_checks":checks,"bound_evidence_recomputed":bound_count,"bound_statuses":dict(statuses),
            "raw_finish_reasons":dict(reason_counts),"models_returned":sorted(model_names),"usage":dict(usage),
            "usage_priced_cny":(usage["prompt_tokens"]*12+usage["completion_tokens"]*36)/1e6,
            "actual_invoice_cny":None,"cost_ceiling_cny":None,"call_ceiling":None,
            "historical_failures_retained":True,"new_applicability_labels":0,"mixed_slates":0,
            "human_gold":False,"clinical_validity":None,"decision_accuracy":None,
            "contract_frozen":False,"formal_baseline_allowed":False,
            "blocker":"SOURCE_AND_MEASUREMENT_COMPATIBILITY_REQUIREMENT_UNMET" if len(admitted)<6 else "LABEL_PILOT_NOT_YET_VALIDATED"}
    write(output,result)
    return result


if __name__=="__main__":
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",required=True)
    args=parser.parse_args()
    print(json.dumps(validate_all(args.output),ensure_ascii=False,indent=2))
