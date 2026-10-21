"""Offline statistics and strict raw-payload replay. Gold metrics remain null."""
import argparse
from collections import Counter, defaultdict
from copy import deepcopy
import json
from pathlib import Path
from statistics import mean

from ..common import ROOT, digest, read, require, rows, sha, write
from ..datasets.v2_sources import verify, freeze, jsonl
from ..day1.evidence import EvidenceProvider
from ..day1.structured import decode_response, SOURCE_FUNCTION, ANNOTATION_FUNCTION
from ..day1.evaluation import participant_summary
from .knowledge import validate_units, model_unit
from .schemas import source_schema
from .core import (metric_for, validate_judgment, source_errors, graded_utility, pairs_from_grades,
                   DiagnosticRanker, find_probe, ranking_relations)
from .pilot import load_prepared, pool_for, judge_payload, RUBRIC, SOURCE_RULES, JUDGMENT_RULES
from .standard_schema import standard_errors,standard_schema


def grade_map(record):
    if record.get("annotation_status")!="ACCEPTED" or "output" not in record:return None
    return {j["knowledge_id"]:j["grade"] for j in record["output"]["judgments"]}


def pair_comparison(a,b):
    if a is None or b is None:return {"comparable_pairs":0,"changed_pairs":None,"tie_changes":None,"reversals":None}
    pa,pb=pairs_from_grades(a),pairs_from_grades(b)
    comparable=[p for p in pa if pa[p] is not None and pb[p] is not None]
    return {"comparable_pairs":len(comparable),"changed_pairs":sum(pa[p]!=pb[p] for p in comparable),
            "tie_changes":sum(pa[p]!=pb[p] and (pa[p]==0 or pb[p]==0) for p in comparable),
            "reversals":sum(pa[p]*pb[p]==-1 for p in comparable)}


def analyze(prepared,run,ledger,output):
    prepared,run,ledger,output=Path(prepared),Path(run),Path(ledger),Path(output)
    require(not output.exists(),"fresh analysis directory required")
    config,units,queries,protocol=load_prepared(prepared)
    executed=verify(run)
    source=ROOT/config["source_release"]
    probes=read(source/"probes.json")
    validate_units(units,config)
    query_by={q["query_id"]:q for q in queries}
    cases={c["case_id"]:c for c in rows(source/"cases.jsonl") if c["case_id"] in {q["case_id"] for q in queries}}
    providers={cid:EvidenceProvider(case,probes) for cid,case in cases.items()}
    backend=read(run/"backend_evidence.json")
    real_measurements=Counter()
    for cid,pool in backend.items():
        require(len(pool)==288 and pool==providers[cid].all(),"backend full pool differs from deterministic recomputation")
        for e in pool:
            providers[cid].verify_bound(e);real_measurements[e["status"]]+=1
    assignments=rows(run/"task_assignments.jsonl")
    assignment={(a["query_id"],a["arm"]):a["task_id"] for a in assignments}
    tasks={t["task_id"]:t for t in rows(run/"tasks.jsonl")}
    labels={r["task_id"]:r for r in rows(run/"silver_judgments.jsonl")}
    source_reviews={r["knowledge_id"]:r for r in rows(run/"source_reviews.jsonl")}
    # Rebuild every packet from the preregistered query and deterministic evidence.
    for query in queries:
        candidates=[u for u in units if u["knowledge_id"] in query["candidate_ids"]]
        for arm in ("A","B","C","D","F"):
            task_id=assignment[(query["query_id"],arm)]
            canonical,shown=pool_for(query,cases[query["case_id"]],providers[query["case_id"]],probes,arm)
            expected=judge_payload(query,candidates,shown,task_id,RUBRIC)
            require(tasks[task_id]["payload"]==expected,"arm payload leak/change")
            require(len(shown)==(288 if arm=="F" else {"A":0,"B":1,"C":2,"D":2}[arm]),"hidden results exposed online")
    raw_count=0;raw_failures=0;tokens=Counter();latencies=[]
    unit_by={u["knowledge_id"]:u for u in units}
    for p in (ledger/"cache").glob("*.json"):
        cache=read(p);request=read(ledger/"requests"/p.name)
        require(cache["request_sha256"]==digest(request) and cache["response_sha256"]==digest(cache["response"]),"raw trace differs")
        require(cache["response"]["model"]==cache["returned_model"]==request["model"]=="qwen3.8-max","model identity changed")
        payload=json.loads(request["messages"][1]["content"])
        fn=request["tools"][0]["function"]["name"]
        if fn==SOURCE_FUNCTION:
            unit=unit_by[payload["unit"]["knowledge_id"]];record=source_reviews[unit["knowledge_id"]]
            require(request["messages"][0]["content"]==SOURCE_RULES and payload["unit"]==model_unit(unit) and
                    payload["article_context"]==unit["article_context"] and
                    set(payload)=={"unit","article_context","permitted_metrics","permitted_operations","horizons"},"source call contains unexpected data")
            schema=source_schema(unit)
        else:
            require(fn==ANNOTATION_FUNCTION,"unexpected call function")
            task=tasks[payload["task_id"]];record=labels[task["task_id"]]
            require(request["messages"][0]["content"]==JUDGMENT_RULES and payload==task["payload"],"relevance request changed")
            schema=task["schema"]
        try:
            decoded=decode_response(cache["response"],function_name=fn,schema=schema)
        except Exception:
            require(record["status"]=="CALL_OR_SCHEMA_FAILURE","unrecorded raw schema failure")
            raw_failures+=1
        else:
            require(decoded==record["output"],"model output edited")
            require(not standard_errors(decoded,schema),"standards-valid equivalent schema rejected the original output")
            if fn==SOURCE_FUNCTION:
                require(source_errors(decoded,unit)==record["validation_errors"],"source validation changed")
            else:
                candidates=[unit_by[k] for k in [c["knowledge_id"] for c in payload["candidates"]]]
                errors=validate_judgment(decoded,payload["task_id"],candidates,payload["evidence"],metric_for(payload["query"]["topic"]))
                require(errors==record["validation_errors"],"relevance validator changed")
                require(bool(errors)==(record["annotation_status"]!="ACCEPTED"),"status/error inconsistency")
                canon={e["evidence_id"]:e for pool in backend.values() for e in pool}
                selected=sorted({eid for j in decoded["judgments"] for eid in j["evidence_ids"]})
                require(record["bound_evidence"]==[canon[eid] for eid in selected],"bound values differ from backend")
        tokens.update({k:cache.get("usage",{}).get(k,0) for k in ("prompt_tokens","completion_tokens")})
        latencies.append(cache["request_latency_ns"])
        raw_count+=1
    expected_requests=len(tasks)+len(units)
    require(raw_count==expected_requests==len(list((ledger/"attempts").glob("*.json"))),"unexpected/missing raw calls")
    observations=rows(run/"observations.jsonl")
    obs={(o["query_id"],o["arm"]):o for o in observations}
    for o in observations:
        q=query_by[o["query_id"]];state=o["state"]
        candidates=[unit_by[k] for k in q["candidate_ids"]]
        expected=DiagnosticRanker().rank(q,state["observed_evidence"],candidates,probes)
        require([list(t) for t in expected]==state["ranking"],"ranker output does not replay")
        require(set(state["query"])=={"query_id","case_id","topic","query_basis","goal","candidate_ids"},"online query metadata leak")
        require(set(state)=={"query","observed_evidence","remaining_budget","ranking","ranker_version"},"online hidden state leak")
    comparisons=[];signals=[];deltas=[];candidate_grades=Counter();basis_counts=Counter();arm_grades=defaultdict(Counter)
    for query in queries:
        qid=query["query_id"]
        maps={a:grade_map(labels[assignment[qid,a]]) for a in ("A","B","C","D","F")}
        for arm in maps:
            rec=labels[assignment[qid,arm]]
            if maps[arm] is not None:
                candidate_grades.update("unknown" if g is None else str(g) for g in maps[arm].values())
                arm_grades[arm].update("unknown" if g is None else str(g) for g in maps[arm].values())
                basis_counts.update(j["basis"] for j in rec["output"]["judgments"])
        entries={name:pair_comparison(maps[a],maps[b]) for name,a,b in (("A_B","A","B"),("B_C","B","C"),("B_D","B","D"),("A_F","A","F"))}
        comparison={"query_id":qid,"subject_id":query["subject_id"],"topic":query["topic"],"query_basis":query["query_basis"],**entries}
        comparison["changed_pair_fraction"]=entries["B_C"]["changed_pairs"]/entries["B_C"]["comparable_pairs"] if entries["B_C"]["comparable_pairs"] else None
        comparisons.append(comparison)
        # Candidate signal requires changed relative relation, cited new computed result and registered source link.
        new_evidence=[e for e in tasks[assignment[qid,"C"]]["payload"]["evidence"] if e["operation"]=="mean_difference" and e["metric"]==metric_for(query["topic"]) and e["status"]=="COMPUTED"]
        if maps["B"] is not None and maps["C"] is not None:
            pb,pc=pairs_from_grades(maps["B"]),pairs_from_grades(maps["C"])
            crows=labels[assignment[qid,"C"]]["output"]["judgments"]
            evidence_ids={e["evidence_id"] for e in new_evidence}
            affected={j["knowledge_id"] for j in crows if j["basis"]=="PERSONAL_EVIDENCE_CONTEXT" and set(j["evidence_ids"])&evidence_ids}
            changed=[p for p in pb if pb[p] is not None and pc[p] is not None and pb[p]!=pc[p] and any(k in affected for k in p.split("|"))]
            if changed:signals.append({"query_id":qid,"subject_id":query["subject_id"],"changed_pairs":changed,"status":"SILVER_CANDIDATE_SIGNAL_NOT_GOLD"})
        utilities={arm:graded_utility(obs[qid,arm]["state"]["ranking"],maps["F"]) if maps["F"] is not None else None for arm in ("A","B","C","D")}
        for arm in ("C","D"):
            before,after=utilities["B"],utilities[arm]
            delta=after-before if before is not None and after is not None else None
            deltas.append({"query_id":qid,"subject_id":query["subject_id"],"arm":arm,"kind":"SILVER_PROXY_ONLY",
                           "before":before,"after":after,"realized_proxy_delta":delta,
                           "sign":"undetermined" if delta is None else "positive" if delta>1e-12 else "negative" if delta< -1e-12 else "zero",
                           "formal_gold_delta":None,"expected_acquisition_value":None,"cost":1,
                           "reference_coverage":sum(g is not None for g in maps["F"].values())/len(query["candidate_ids"]) if maps["F"] is not None else 0,
                           "rank_changed":ranking_relations(obs[qid,"B"]["state"]["ranking"])!=ranking_relations(obs[qid,arm]["state"]["ranking"])})
    jsonl(output/"PRIVATE_matched_comparisons.jsonl",comparisons)
    jsonl(output/"PRIVATE_silver_candidate_signals.jsonl",signals)
    jsonl(output/"PRIVATE_utility_diagnostics.jsonl",deltas)
    cross=Counter()
    grouped=defaultdict(list)
    for q in queries:grouped[(q["topic"],q["query_basis"])].append(q)
    for group in grouped.values():
        for i,q in enumerate(group):
            for other in group[i+1:]:
                result=pair_comparison(grade_map(labels[assignment[q["query_id"],"C"]]),grade_map(labels[assignment[other["query_id"],"C"]]))
                cross["context_pairs"]+=1;cross["comparable_candidate_pairs"]+=result["comparable_pairs"]
                cross["changed_candidate_pairs"]+=result["changed_pairs"] or 0
                cross["preference_reversals"]+=result["reversals"] or 0
    all_facets=[f for r in source_reviews.values() if "output" in r for f in r["output"]["facets"]]
    compatibility={"source_units":len(units),"units_with_fixed_descriptive_link":sum(u["descriptive_context_link"] for u in units),
                   "fixed_descriptive_link_fraction":sum(u["descriptive_context_link"] for u in units)/len(units),
                   "source_facet_kinds_model_silver":dict(Counter(f["kind"] for f in all_facets)),
                   "source_facet_relations_model_silver":dict(Counter(f["relation"] for f in all_facets)),
                   "verified_hard_predicates":0,"exact_hard_predicate_compatibility_rate":None,
                   "rate_note":"No independent semantic adjudication; descriptive links must not be reported as exact predicate compatibility"}
    changed={name:sum(c[name]["changed_pairs"] or 0 for c in comparisons) for name in ("A_B","B_C","B_D","A_F")}
    online_evidence={e["evidence_id"]:e for o in observations for e in o["state"]["observed_evidence"]}
    measured=Counter(e["status"] for e in online_evidence.values())
    status="CONDITIONAL_GO" if any(e["status"]=="COMPUTED" for e in online_evidence.values()) and any(u["descriptive_context_link"] for u in units) else "NO_GO"
    report={"version":"day2-feasibility-results-v01","status":status,"protocol_id":protocol["release_id"],"run_id":executed["release_id"],
            "evidence_provenance":{"knowledge":"Frozen public source reconstruction","measurements":"REAL_WEARABLEQA_DETERMINISTIC_PROBES",
                                   "judgments":"QWEN_MODEL_SILVER","ranker":"PREREGISTERED_PROGRAM_DIAGNOSTIC","human_gold":"ABSENT","synthetic":"Explicit query goals and unit-test fixtures only"},
            "knowledge_units":len(units),"knowledge_by_topic":dict(Counter(u["topic"] for u in units)),
            "participants":len(cases),"contexts":len(queries),"fixed_slates":len(queries),"unique_topic_slates":len({tuple(q["candidate_ids"]) for q in queries}),
            "query_bases":dict(Counter(q["query_basis"] for q in queries)),"candidate_counts":dict(Counter(len(q["candidate_ids"]) for q in queries)),
            "raw_requests":raw_count,"source_requests":len(units),"unique_relevance_requests":len(tasks),"raw_schema_failures":raw_failures,
            "source_statuses":dict(Counter(r["status"] for r in source_reviews.values())),
            "silver_statuses":dict(Counter(r["status"] for r in labels.values())),
            "silver_validation_errors":dict(Counter(e for r in labels.values() for e in r.get("validation_errors",[]))),
            "arm_reference_assignments":len(assignments),"reused_A_assignments":len(assignments)-len(tasks),
            "silver_grade_distribution_by_assignment":dict(candidate_grades),"silver_grades_by_arm":{k:dict(v) for k,v in arm_grades.items()},
            "silver_basis_by_assignment":dict(basis_counts),"matched_changed_pair_counts_silver":changed,
            "matched_pair_comparisons":{n:{k:sum((c[n][k] or 0) for c in comparisons) for k in ("comparable_pairs","changed_pairs","tie_changes","reversals")} for n in changed},
            "cross_person_diagnostics_silver":dict(cross),"candidate_signal_contexts_silver":len(signals),
            "candidate_signal_participants_silver":len({s["subject_id"] for s in signals}),
            "preregistered_exploratory_signal_criterion_met":len(signals)>=2 and len({s["subject_id"] for s in signals})>=2,
            "source_probe_compatibility":compatibility,"full_backend_measurements":dict(real_measurements),
            "unique_online_measurements":dict(measured),"unique_online_measurement_count":len(online_evidence),
            "valid_measurement_rate":measured["COMPUTED"]/len(online_evidence) if online_evidence else None,
            "missing_evidence_rate":measured["INSUFFICIENT_INFORMATION"]/len(online_evidence) if online_evidence else None,
            "H":{"verified_measurable_hard_predicates":0,"personal_hard_verdicts":0,"status":"NOT_ESTABLISHED"},
            "R":{"accuracy_gold":None,"independent_human_agreement":None,"status":"SILVER_EXPLORATORY_ONLY",
                 "candidate_assignments":sum(len(q["candidate_ids"])*5 for q in queries),
                 "mechanically_accepted_candidate_assignments":sum(candidate_grades.values()),
                 "unknown_grade_assignments":candidate_grades["unknown"]},
            "V":{"expected_value":None,"formal_gold_ndcg":None,"formal_gold_gain":None,
                 "status":"COMPUTATION_AND_SILVER_PROXY_ONLY", "delta_signs":{arm:dict(Counter(d["sign"] for d in deltas if d["arm"]==arm)) for arm in ("C","D")},
                 "rank_changes":{arm:sum(d["rank_changed"] for d in deltas if d["arm"]==arm) for arm in ("C","D")},
                 "acquisition_cost_per_C_or_D":1,"total_C_D_action_slots":sum(o["cost"] for o in observations),
                 "step_latency_ns":{"mean":mean(o["step_latency_ns"] for o in observations if o["cost"]),"max":max(o["step_latency_ns"] for o in observations)}},
            "exploratory_participant_bootstrap":{
                "B_C_changed_pair_fraction":participant_summary(comparisons,"changed_pair_fraction",**{"seed":20261020,"bootstrap_samples":2000}),
                **{arm+"_silver_proxy_delta":participant_summary([d for d in deltas if d["arm"]==arm],"realized_proxy_delta",seed=20261020,bootstrap_samples=2000) for arm in ("C","D")}},
            "tokens":dict(tokens),"usage_priced_cny":(tokens["prompt_tokens"]*12+tokens["completion_tokens"]*36)/1e6,"actual_invoice_cny":None,
            "model_request_latency_ns":{"mean":mean(latencies),"max":max(latencies)},
            "formal_baselines_run":False,"c2_training_run":False,"benchmark_frozen":False,
            "next_priority":"Independent double human review and source-link adjudication of the prepared blind packets, before interpreting evidence-dependent relevance or ranking benefit"}
    write(output/"report.json",report)
    write(output/"qa.json",{"status":"PASS_RAW_CHAINS_EVIDENCE_BINDING_MATCHED_INPUTS_RANKER_REPLAY_ONLY",
          "source_units_reconstructed":len(units),"raw_chains_verified":raw_count,"real_results_recomputed":sum(real_measurements.values()),
          "same_query_candidates_across_arms":True,"online_hidden_results_or_labels":False,"train_only":True,
          "independent_human_gold":0,"source_semantic_certification":False,"clinical_priority_validated":False,
          "standard_schema_check":"PASS_EQUIVALENT_EMPTY_EVIDENCE_ARRAY_DOMAIN; original request schemas untouched"})
    freeze(output,{"version":"day2-analysis-v01","status":"DIAGNOSTIC_ONLY_NOT_FORMAL_EVALUATION"})
    print(json.dumps(report,ensure_ascii=False),flush=True)


def export(prepared,analysis,output):
    prepared,analysis,output=Path(prepared),Path(analysis),Path(output)
    require(not output.exists(),"fresh public export")
    verify(prepared);verify(analysis)
    report=read(analysis/"report.json")
    write(output/"report.json",report);write(output/"qa.json",read(analysis/"qa.json"))
    write(output/"protocol.json",read(prepared/"config.json"));write(output/"rubric.json",read(prepared/"rubric.json"))
    units=rows(prepared/"knowledge_units.jsonl")
    jsonl(output/"knowledge_metadata.jsonl",[{"knowledge_id":u["knowledge_id"],"topic":u["topic"],"title":u["title"],
           "content_hash":u["content_hash"],"source_url":u["source"]["source_url"],"source_sha256":u["source"]["source_sha256"],
           "anchor_id":u["anchor_id"],"source_span_count":len(u["source_spans"]),"completeness":u["completeness"],
           "source_semantic_status":u["source_semantic_status"],"descriptive_context_link_hypothesis":u["descriptive_context_link"]} for u in units])
    templates={}
    for q in rows(prepared/"queries.jsonl"):
        templates[q["template_id"]]={k:q[k] for k in ("template_id","topic","query_basis","goal","candidate_ids")}
    jsonl(output/"query_templates.jsonl",sorted(templates.values(),key=lambda q:q["template_id"]))
    # No source rows with personal IDs, values, dates or per-person utility in the public directory.
    banned={"case_id","subject_id","participant_id","evidence_ids","bound_evidence","days","api_key"}
    def inspect(obj):
        if isinstance(obj,dict):
            require(not(set(obj)&banned),"private field in public export")
            for v in obj.values():inspect(v)
        elif isinstance(obj,list):
            for v in obj:inspect(v)
    for p in output.glob("*.json"):inspect(read(p))
    for p in output.glob("*.jsonl"):
        for row in rows(p):inspect(row)
    freeze(output,{"version":"day2-public-diagnostic-export-v01","status":"AGGREGATE_METADATA_ONLY_NO_PERSONAL_RECORDS"})


if __name__=="__main__":
    p=argparse.ArgumentParser();sub=p.add_subparsers(dest="command",required=True)
    a=sub.add_parser("analyze");a.add_argument("--prepared",required=True);a.add_argument("--run",required=True);a.add_argument("--ledger",required=True);a.add_argument("--output",required=True)
    a=sub.add_parser("export");a.add_argument("--prepared",required=True);a.add_argument("--analysis",required=True);a.add_argument("--output",required=True)
    args=p.parse_args()
    if args.command=="analyze":analyze(args.prepared,args.run,args.ledger,args.output)
    else:export(args.prepared,args.analysis,args.output)
