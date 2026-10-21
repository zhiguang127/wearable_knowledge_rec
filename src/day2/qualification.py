"""Versioned post-run review sidecar; never rewrite labels or upgrade model Gold."""
from collections import Counter
from copy import deepcopy
from pathlib import Path
import argparse

from ..common import digest, read, require, rows, write
from ..datasets.v2_sources import freeze, verify


def validate_findings(review,records):
    require(review["reviewer_kind"]=="model" and review["human_gold"] is False,"this sidecar is model review, not human Gold")
    keys=[]
    for f in review["findings"]:
        record=records[f["task_id"]]
        row=next(j for j in record["output"]["judgments"] if j["knowledge_id"]==f["knowledge_id"])
        require(f["original_response_hash"]==record["response_hash"] and f["judgment_hash"]==digest(row),"review does not reference the unchanged original response")
        require(f["annotation_status"]=="REVIEW_REQUIRED","model review cannot fabricate accepted or human judgments")
        keys.append((f["task_id"],f["knowledge_id"]))
    require(len(keys)==len(set(keys)),"duplicate review finding")
    return {task for task,kid in keys}


def qualify(run,analysis,review_dir,output):
    run,analysis,review_dir,output=map(Path,(run,analysis,review_dir,output))
    require(not output.exists(),"fresh qualified report directory required")
    verify(run);original=verify(analysis);review_manifest=verify(review_dir)
    review=read(review_dir/"review.json")
    records={r["task_id"]:r for r in rows(run/"silver_judgments.jsonl")}
    flagged=validate_findings(review,records)
    assignments={(a["query_id"],a["arm"]):a["task_id"] for a in rows(run/"task_assignments.jsonl")}
    raw=read(analysis/"report.json");report=deepcopy(raw)
    deltas=rows(analysis/"PRIVATE_utility_diagnostics.jsonl")
    positive_review=sum(d["sign"]=="positive" and assignments[d["query_id"],"F"] in flagged for d in deltas if d["arm"]=="C")
    qualified_signs={}
    for arm in ("C","D"):
        qualified_signs[arm]=dict(Counter("reference_semantics_pending" if assignments[d["query_id"],"F"] in flagged else d["sign"] for d in deltas if d["arm"]==arm))
    report["raw_diagnostic_analysis_id"]=original["release_id"]
    report["semantic_sidecar_id"]=review_manifest["release_id"]
    report["semantic_model_review"]={"human_gold":False,"personal_rationales_inspected":review["personal_judgments_inspected"],
          "pending_findings":len(review["findings"]),"pending_tasks":len(flagged),
          "reason_counts":dict(Counter(f["reason_code"] for f in review["findings"])),
          "scope":"Conservative source/measurement review flags, not adjudicated error prevalence; other rows are not certified"}
    report["V"]["original_positive_proxy_requires_reference_review"]=positive_review
    report["V"]["proxy_signs_after_pending_reference_flags"]=qualified_signs
    report["V"]["positive_proxy_not_flagged_for_reference_review"]=sum(d["arm"]=="C" and d["sign"]=="positive" and assignments[d["query_id"],"F"] not in flagged for d in deltas)
    report["V"]["formal_gold_ndcg"]=None;report["V"]["formal_gold_gain"]=None
    report["conclusion"]={"true_personal_evidence_dependent_relevance":"NOT_ESTABLISHED",
          "true_acquisition_utility_improvement":"NOT_EVALUABLE_WITHOUT_INDEPENDENT_REFERENCE",
          "exploratory_signal_threshold_met":False,
          "negative_control_warning":"Unrelated-probe B-to-D changes exceed B-to-C changes; no strict pairwise reversal observed",
          "scope_of_conditional_go":"Proceed only to independent source/relevance adjudication; not formal Benchmark freeze or algorithm comparison"}
    write(output/"report.json",report)
    write(output/"qa.json",{**read(analysis/"qa.json"),"model_semantic_findings_bound_to_raw":len(review["findings"]),
          "original_labels_and_reports_edited":False,"model_review_is_human_gold":False})
    freeze(output,{"version":"day2-review-qualified-diagnostics-v01","status":"CONDITIONAL_GO_FOR_HUMAN_REVIEW_ONLY"})
    print({"status":report["status"],"semantic_findings":len(review["findings"]),"positive_proxy_requiring_review":positive_review})


if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--run",required=True);p.add_argument("--analysis",required=True)
    p.add_argument("--review",required=True);p.add_argument("--output",required=True);a=p.parse_args()
    qualify(a.run,a.analysis,a.review,a.output)
