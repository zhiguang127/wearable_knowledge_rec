"""A frozen, bounded repair pilot. No outcome-based re-selection or automatic retries."""
import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path

from ..common import ROOT, digest, read, require, rows, write
from ..datasets.v2_sources import freeze, jsonl, verify
from ..datasets.probes import execute
from .c1_v2_client import V2Client, combined_report
from .c1_v2_pipeline import review_one, label_one, check_label, check_review, candidate_probes
from .c1_v22_audit import request_chain_check
from .personal_evidence import compact_evidence

SALT = "c1-v2.2-repair-matched-pilot-v1"


def make_plan(config):
    source, legacy, repair = (ROOT/config[k] for k in ("source_release","legacy_annotation","output_release"))
    sf, lf, rf = verify(source), verify(legacy), verify(repair)
    cases = {c["case_id"]:c for c in rows(source/"cases.jsonl")}
    knowledge = {k["knowledge_id"]:k for k in rows(legacy/"knowledge_active.jsonl")}
    grouped = defaultdict(list)
    for label in rows(legacy/"silver_labels.jsonl"):
        case = cases[label["case_id"]]
        grouped[(case["subject_id"],label["knowledge_id"])].append(label)
    eligible = [ls for ls in grouped.values() if {cases[l["case_id"]]["history_days"] for l in ls} == {14,42} and len(ls)==2]
    eligible.sort(key=lambda ls:digest([SALT,ls[0]["knowledge_id"],cases[ls[0]["case_id"]]["subject_id"]]))
    chosen=[]
    for topic in sorted({k["topic"] for k in knowledge.values()}):
        options=[ls for ls in eligible if knowledge[ls[0]["knowledge_id"]]["topic"]==topic]
        require(bool(options),"matched pilot topic unavailable")
        chosen.append(options[0])
    # A declared mapping stratum exercises both legacy empty and nonempty inputs.
    extra=[ls for ls in eligible if ls not in chosen and any(l["evidence"] for l in ls)]
    require(bool(extra),"mapped comparison stratum unavailable")
    chosen.append(extra[0])
    pairs=[{"case_id":l["case_id"],"knowledge_id":l["knowledge_id"],"history_days":cases[l["case_id"]]["history_days"],
            "legacy_evidence_count":len(l["evidence"])} for group in chosen for l in sorted(group,key=lambda l:cases[l["case_id"]]["history_days"])]
    kids=sorted({p["knowledge_id"] for p in pairs})
    joint_ids=sorted({c["knowledge_id"] for c in rows(repair/"joint_candidates.jsonl")},key=lambda k:digest([SALT,k]))
    for kid in joint_ids:
        if len(kids)>=12: break
        if kid not in kids:kids.append(kid)
    require(len(pairs)==12 and len(kids)<=12,"pilot workload changed")
    return {"salt":SALT,"source_release_id":sf["release_id"],"legacy_release_id":lf["release_id"],"repair_release_id":rf["release_id"],
        "selection":"One exact old 14/42 pair group per topic, SHA256 within topic, plus one declared mapped stratum; six additional joint-candidate knowledge reviews. No labels/values used.",
        "pairs":pairs,"knowledge_ids":kids,"max_calls":2*(len(pairs)+len(kids)),
        "case_knowledge_inputs":"Original V2.1 active knowledge and conditions retained as fallible hints; new mapping reviews do not gate case annotation.",
        "comparison_limits":"Evidence access and prompts both change. Not a single-factor causal estimate or a representative accuracy estimate."}


def verify_pilot(config, directory, ledger):
    directory, ledger = Path(directory), Path(ledger)
    frozen=verify(directory); plan=read(directory/"plan.json")
    require(plan==make_plan(config),"pilot plan changed")
    source, legacy = ROOT/config["source_release"], ROOT/config["legacy_annotation"]
    cases={c["case_id"]:c for c in rows(source/"cases.jsonl")}
    items={k["knowledge_id"]:k for k in rows(source/"knowledge_candidates.jsonl")}
    active={k["knowledge_id"]:k for k in rows(legacy/"knowledge_active.jsonl")}
    probes=read(source/"probes.json"); pmap={p["probe_id"]:p for p in probes}
    reviews=rows(directory/"knowledge_reviews.jsonl"); labels=rows(directory/"silver_labels.jsonl")
    require({r["knowledge_id"] for r in reviews}==set(plan["knowledge_ids"]),"pilot review coverage")
    require({(l["case_id"],l["knowledge_id"]) for l in labels}=={(l["case_id"],l["knowledge_id"]) for l in plan["pairs"]},"pilot pair coverage")
    count=0
    for r in reviews:
        require(r["input_sha256"] == digest(items[r["knowledge_id"]]),"pilot source input changed")
        if r["stage1"]["status"]=="RETURNED" and r["stage2"] and r["stage2"]["status"]=="RETURNED":
            errors,_=check_review(r["stage1"]["output"],r["stage2"]["output"],items[r["knowledge_id"]],candidate_probes(items[r["knowledge_id"]],probes))
            require(set(errors)<=set(r["validation_errors"]),"pilot review errors dropped")
    for label in labels:
        case=cases[label["case_id"]]; item=active[label["knowledge_id"]]
        require(label["input_sha256"] == digest([case,item]),"pilot case/knowledge input changed")
        require(len(label["evidence"])==len(probes) and len({e["probe_id"] for e in label["evidence"]})==len(probes),"pilot evidence pruned")
        for e in label["evidence"]:
            rerun=execute(cases[label["case_id"]],pmap[e["probe_id"]])
            require({k:v for k,v in rerun.items() if k!="elapsed_ns"}=={k:v for k,v in e.items() if k!="elapsed_ns"},"pilot statistic mismatch")
            count+=1
        for stage in (label["stage1"],label["stage2"]):
            if not stage or stage["status"]!="RETURNED":continue
            request=read(ledger/"requests"/(stage["cache_key"]+".json"))
            supplied=json.loads(request["messages"][1]["content"])["payload"]
            require(supplied["personal_evidence"]==compact_evidence(case,probes,label["evidence"]),"actual model request pruned or changed evidence")
        if label["stage1"]["status"]=="RETURNED" and label["stage2"] and label["stage2"]["status"]=="RETURNED":
            errors,_=check_label(label["stage1"]["output"],label["stage2"]["output"],active[label["knowledge_id"]],cases[label["case_id"]],label["evidence"])
            require(errors==label["validation_errors"],"pilot label errors changed")
            if label["status"]=="SILVER_ACCEPTED":require(not errors and label["stage2"]["output"]["verdict"]=="SUPPORTED","invalid accepted pilot label")
        elif label["status"]!="SILVER_ACCEPTED":require(label["applicability"] is None,"unrun label misclassified")
    chains=request_chain_check(reviews,labels,[ledger])
    return {"status":"PASS_ARTIFACT_CONSISTENCY_ONLY","release_id":frozen["release_id"],"statistics_recomputed":count,
        "request_response_chains":chains,"semantic_correctness_proven":False,"human_gold":False}


def run(config,args):
    plan=make_plan(config)
    records=ROOT/args.records; planpath=records/"plan.json"
    if planpath.exists():require(read(planpath)==plan,"pilot plan changed")
    else:write(planpath,plan)
    budget=read(ROOT/args.budget)
    require(budget["max_calls"]<=48 and budget["authorized_cap_cny"]<=3,"pilot exceeds declared sub-budget")
    combined=combined_report([ROOT/p for p in config["ledger_directories"]])
    require(combined["reserved_cny"]+budget["authorized_cap_cny"]<=200,"task-level budget exceeded")
    print(json.dumps({"plan_sha256":digest(plan),"knowledge":len(plan["knowledge_ids"]),"pairs":len(plan["pairs"]),"max_calls":plan["max_calls"],"sub_budget_cny":budget["authorized_cap_cny"]}),flush=True)
    if args.plan_only:return
    require(not (ROOT/args.output).exists(),"pilot release exists; never overwrite")
    credentials=read(ROOT/args.credentials) if args.credentials else {}
    client=V2Client(ROOT/args.ledger,budget,api_key=credentials.get("api_key"))
    require(bool(client.api_key),"BLOCKED_API_KEY_REQUIRED")
    source, legacy=ROOT/config["source_release"],ROOT/config["legacy_annotation"]
    items=rows(source/"knowledge_candidates.jsonl"); byid={k["knowledge_id"]:k for k in items}
    active={k["knowledge_id"]:k for k in rows(legacy/"knowledge_active.jsonl")}
    cases={c["case_id"]:c for c in rows(source/"cases.jsonl")}; probes=read(source/"probes.json")
    with ThreadPoolExecutor(max_workers=4) as pool:
        reviews=list(pool.map(lambda kid:review_one(client,byid[kid],items,probes,records/"knowledge"),plan["knowledge_ids"]))
    print("knowledge pilot complete",dict(Counter(r["review_status"] for r in reviews)),flush=True)
    with ThreadPoolExecutor(max_workers=4) as pool:
        labels=list(pool.map(lambda p:label_one(client,cases[p["case_id"]],active[p["knowledge_id"]],probes,records/"labels"),plan["pairs"]))
    old={(l["case_id"],l["knowledge_id"]):l for l in rows(legacy/"silver_labels.jsonl")}
    report={"version":budget["version"],"plan_sha256":digest(plan),"knowledge_reviews":len(reviews),"case_pairs":len(labels),
        "knowledge_statuses":dict(Counter(r["review_status"] for r in reviews)),
        "knowledge_program_errors":dict(Counter(e for r in reviews for e in r["validation_errors"])),
        "full_catalog_mapping_calls":True,"full_mapping_registry_count":len(probes),
        "reviewed_knowledge_with_probe":sum(any(c["probe_ids"] for c in (r["stage1"].get("output") or {}).get("conditions",[])) for r in reviews),
        "label_statuses":dict(Counter(l["status"] for l in labels)),
        "accepted_applicability":dict(Counter(l["applicability"] for l in labels if l["status"]=="SILVER_ACCEPTED")),
        "raw_stage1_applicability":dict(Counter((l["stage1"].get("output") or {}).get("applicability","NOT_RETURNED") for l in labels)),
        "second_stage_verdicts":dict(Counter(((l.get("stage2") or {}).get("output") or {}).get("verdict","NOT_RETURNED") for l in labels)),
        "label_program_errors":dict(Counter(e for l in labels for e in l["validation_errors"])),
        "stage_disagreements":sum("stage_applicability_disagreement" in l["validation_errors"] for l in labels),
        "old_matched_statuses":dict(Counter(old[(l["case_id"],l["knowledge_id"])]["status"] for l in labels)),
        "old_matched_empty_evidence":sum(not old[(l["case_id"],l["knowledge_id"])]["evidence"] for l in labels),
        "all_pairs_received_full_registry":all(len(l["evidence"])==len(probes) for l in labels),
        "cases_with_computed_statistics":sum(any(e["status"]=="COMPUTED" for e in l["evidence"]) for l in labels),
        "new_cost":client.report(),"combined_task_cost":combined_report([ROOT/p for p in config["ledger_directories"]]+[ROOT/args.ledger]),
        "condition_semantics":"Targeted per-predicate/connective review still pending; global knowledge audits do not certify necessary AND rules.",
        "limits":[plan["comparison_limits"],"Qwen self-audit is exploratory Silver, not independent human or clinical verification.",
                  "Do not use this finite nonrepresentative pilot as full-library recall Gold or evidence of KUV value."]}
    output=ROOT/args.output
    write(output/"plan.json",plan);jsonl(output/"knowledge_reviews.jsonl",reviews);jsonl(output/"silver_labels.jsonl",labels)
    write(output/"report.json",report)
    freeze(output,{"source_release_id":plan["source_release_id"],"repair_release_id":plan["repair_release_id"],"human_gold":False})
    print(json.dumps(report,indent=2),flush=True)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config",default="configs/c1_v2_2_audit.json")
    p.add_argument("--budget",default="configs/c1_v2_2_pilot_budget.json")
    p.add_argument("--ledger",default="local/c1-v2-audit-repair/qwen-ledger-pilot-v1")
    p.add_argument("--records",default="local/c1-v2-audit-repair/qwen-records-pilot-v1")
    p.add_argument("--output",default="local/c1-v2-audit-repair/qwen-pilot-v1")
    p.add_argument("--credentials",help="Ignored local JSON, or use DASHSCOPE_API_KEY")
    p.add_argument("--plan-only",action="store_true")
    p.add_argument("--verify-only",action="store_true")
    args=p.parse_args();config=read(ROOT/args.config)
    if args.verify_only:print(json.dumps(verify_pilot(config,ROOT/args.output,ROOT/args.ledger),indent=2))
    else:run(config,args)


if __name__=="__main__":main()
