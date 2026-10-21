"""C1 V2 Audit & Repair: offline provenance, repaired views, full evidence and attribution.

No API transport is constructed. Old labels are never reinterpreted as new-evidence labels.
"""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import re
from time import perf_counter

from ..common import ROOT, digest, read, require, rows, sha, write
from ..datasets.v2_sources import jsonl, freeze, verify, verify_sources
from ..datasets.probes import relation_index
from ..datasets.probes import execute
from ..knowledge.dedup import model_suggestions, exact_deduplicate
from ..knowledge.c1_v2 import norm
from .c1_v2_pipeline import recertify, assemble, source_payload, messages, LABEL_TASK
from . import c1_v2_schemas as schemas
from .client import SilverClient
from .dependencies import audit_legacy_condition
from .personal_evidence import EvidenceProvider, compact_evidence, compact_catalog, balanced_pairs


def legacy_dedup_audit(knowledge, canonical):
    byid = {k["knowledge_id"]: k for k in knowledge}
    groups = defaultdict(list)
    for kid, representative in canonical.items():
        groups[representative].append(kid)
    details = []
    for representative, ids in sorted(groups.items()):
        if len(ids) < 2:
            continue
        members = [byid[k] for k in ids]
        details.append({"representative_id": representative, "member_ids": sorted(ids),
            "members": len(ids), "topics": sorted({k["topic"] for k in members}),
            "distinct_texts": len({norm(k["text"]) for k in members}),
            "distinct_condition_variants": len({digest(k["conditions"]) for k in members}),
            "member_supported_ids": [k["knowledge_id"] for k in members if any(c["dataset_support"] == "supported" for c in k["conditions"])],
            "representative_has_supported": any(c["dataset_support"] == "supported" for c in byid[representative]["conditions"])})
    return details


def failure_attribution(labels):
    """Multi-label text screens are transparent descriptors, not a new semantic Gold."""
    records = []
    for label in labels:
        second = (label.get("stage2") or {}).get("output") or {}
        first = (label.get("stage1") or {}).get("output") or {}
        issues = second.get("issues", [])
        text = " ".join(issues).casefold()
        tags = []
        for tag, pattern in (
            ("mentions_missing_background", r"\b(age|goals?|preferences?|symptoms?|diagnos\w*|wear.time|timezone|context|intent)\b"),
            ("mentions_clinical_indication_or_threshold", r"\b(clinical|diagnos\w*|contraindicat\w*|calibrat\w*|threshold|medical|risk)\b"),
            ("mentions_source_or_citation_support", r"\b(source|citation|quote|anchor|unsupported)\b"),
            ("mentions_no_provided_personal_evidence", r"\b(no evidence|no deterministic|no personal|no probe|no computed|absen\w*|not provided)\b")):
            if re.search(pattern, text): tags.append(tag)
        records.append({"case_id": label["case_id"], "knowledge_id": label["knowledge_id"],
                        "evidence_count_supplied": len(label["evidence"]),
                        "stage1_applicability": first.get("applicability"),
                        "stage2_applicability": second.get("applicability"), "stage2_verdict": second.get("verdict"),
                        "stage2_issues": issues, "stage1_rationale": first.get("rationale"),
                        "stage2_rationale": second.get("rationale"), "program_errors": label["validation_errors"],
                        "issue_screen_tags": tags, "screen_is_semantic_gold": False,
                        "input_reference": label["input_sha256"]})
    summary = {"records": len(records),
        "stage2_verdicts": dict(Counter(r["stage2_verdict"] for r in records)),
        "stage2_review_required_without_program_error": sum(r["stage2_verdict"] == "REVIEW_REQUIRED" and not r["program_errors"] for r in records),
        "records_with_program_error": sum(bool(r["program_errors"]) for r in records),
        "program_error_occurrences": dict(Counter(e for r in records for e in r["program_errors"])),
        "no_evidence_supplied": sum(r["evidence_count_supplied"] == 0 for r in records),
        "issue_screen_counts": dict(Counter(t for r in records for t in r["issue_screen_tags"])),
        "same_insufficient_judgment_but_review_required": sum(r["stage1_applicability"] == r["stage2_applicability"] == "insufficient_information" and r["stage2_verdict"] == "REVIEW_REQUIRED" for r in records),
        "interpretation": "Missing evidence in the old input and missing background demanded by Qwen are not proof that the dataset cannot contain relevant evidence. Issue categories are nonexclusive lexical screens, not adjudicated causes."}
    return records, summary


def request_chain_check(records, labels, ledger_dirs):
    count = 0
    for record in list(records) + list(labels):
        for key in ("stage1", "stage2"):
            stage = record.get(key)
            if not stage or stage.get("status") != "RETURNED": continue
            matches = []
            for directory in ledger_dirs:
                path = directory/"cache"/(stage["cache_key"]+".json")
                if path.exists() and read(path)["response_sha256"] == stage["response_sha256"]:
                    matches.append(directory)
            require(bool(matches), "historical stage cache absent")
            cache = read(matches[0]/"cache"/(stage["cache_key"]+".json"))
            request = read(matches[0]/"requests"/(stage["cache_key"]+".json"))
            require(digest(cache["response"]) == stage["response_sha256"], "historical response hash changed")
            require(digest(request) == cache["request_sha256"] == stage["request_sha256"], "historical request hash changed")
            require(SilverClient.decode(cache["response"]) == stage["output"], "saved model output differs from actual response")
            count += 1
    return count


def mapping_candidates(item, condition, probes):
    """Nonbinding lexical hints across the full catalog; no fabricated thresholds."""
    text = ((condition or {}).get("text", "") + " " + item["text"]).casefold()
    patterns = {"sleep_duration": r"sleep|night", "sleep_efficiency": r"sleep quality|sleep efficiency",
                "bed_time_std": r"bedtime|bed time|sleep schedule|wake time|sleep regular",
                "steps": r"steps?|walk|physical activ|exercise|active", "exercise_hours": r"exercise|physical activ|active",
                "exercise_count": r"exercise|physical activ|active", "rhr": r"resting heart|resting pulse",
                "hrv": r"heart.rate variab|hrv", "vo2_max": r"vo2|aerobic capacity",
                "avg_stress_level": r"stress", "deep_percentage": r"deep sleep", "rem_percentage": r"rem sleep",
                "active_burn": r"calori|energy expend", "calories_bmr": r"basal|metaboli",
                "exercise_avg_hr": r"exercise heart|exercise pulse", "exercise_mets": r"\bmets?\b"}
    metrics = {m for m,p in patterns.items() if re.search(p, text)}
    return {"knowledge_id": item["knowledge_id"], "condition_id": (condition or {}).get("condition_id"),
            "legacy_model_probe_ids": (condition or {}).get("probe_ids", []),
            "available_catalog_sha256": digest(probes), "available_probe_count": len(probes),
            "candidate_probe_ids": [p["probe_id"] for p in probes if p["metric"] in metrics],
            "suggested_metrics": sorted(metrics), "method": "LEXICAL_DISCOVERY_HINTS_NOT_APPLICABILITY_RULES",
            "semantic_status": "REVIEW_REQUIRED", "registry_access_restricted_to_hints": False,
            "empty_hints_mean": "No heuristic match; all registered probes still available, not not_applicable."}


def counts(knowledge):
    return {"knowledge": len(knowledge),
        "with_legacy_model_probe": sum(any(c.get("probe_ids") for c in k.get("conditions", [])) for k in knowledge),
        "with_model_claimed_supported_condition": sum(any(c.get("dataset_support") == "supported" for c in k.get("conditions", [])) for k in knowledge),
        "unique_legacy_model_probes": len({p for k in knowledge for c in k.get("conditions", []) for p in c.get("probe_ids", [])})}


def audit(config):
    """Recompute every saved statistic and compare repaired views to frozen parents."""
    output, source, legacy = (ROOT/config[k] for k in ("output_release", "source_release", "legacy_annotation"))
    frozen, sf, lf = verify(output), verify(source), verify(legacy)
    lineage = read(output/"source_release.json")
    require(lineage["release_id"] == sf["release_id"] and lineage["legacy_annotation_release_id"] == lf["release_id"], "parent release mismatch")
    require(lineage["cases_sha256"] == sha(source/"cases.jsonl") and lineage["splits_sha256"] == sha(source/"splits.json"), "cases or splits changed")
    probes = read(source/"probes.json"); pmap = {p["probe_id"]:p for p in probes}
    require(read(output/"probe_catalog.json") == probes, "admissible registry changed")
    items = rows(source/"knowledge_candidates.jsonl")
    raw_reviews = rows(legacy/"knowledge_reviews.jsonl")
    revised = recertify(raw_reviews, items, probes)
    reviewed, active, canonical = assemble(items, revised)
    require(rows(output/"knowledge_reviews.jsonl") == revised, "fresh recertification differs")
    require(rows(output/"knowledge_reviewed.jsonl") == reviewed and rows(output/"knowledge_active.jsonl") == active, "repaired knowledge differs")
    require(read(output/"canonical_duplicates.json") == canonical, "exact identity groups differ")
    require(all(not e["used_to_merge"] for e in rows(output/"dedup_suggestions.jsonl")), "semantic suggestion used to merge")
    item_map = {k["knowledge_id"]:k for k in items}
    expected_conditions = [{"knowledge_id":r["knowledge_id"], **audit_legacy_condition(c,item_map[r["knowledge_id"]],probes)}
        for r in raw_reviews for c in ((r["stage1"].get("output") or {}).get("conditions") or [])]
    require(rows(output/"condition_dependency_audits.jsonl") == expected_conditions, "a condition candidate was changed or lost")
    require(rows(output/"joint_candidates.jsonl") == [c for c in expected_conditions if c["is_joint_candidate"]], "joint candidate inventory differs")
    cases = {c["case_id"]:c for c in rows(source/"cases.jsonl")}
    plans = read(output/"matched_comparison_plan.json")["pairs"]
    old_labels = rows(legacy/"silver_labels.jsonl")
    require([(p["case_id"],p["knowledge_id"]) for p in plans] == [(p["case_id"],p["knowledge_id"]) for p in old_labels], "matched plan silently reselected pairs")
    evidence = rows(output/"independent_evidence.jsonl")
    require(len(evidence) == len(plans)*len(probes), "incomplete full evidence")
    bycase = defaultdict(list)
    for e in evidence:
        require(e["result_sha256"] == digest({k:v for k,v in e.items() if k not in {"result_sha256","elapsed_ns"}}), "result hash mismatch")
        rerun = execute(cases[e["case_id"]],pmap[e["probe_id"]])
        require({k:v for k,v in e.items() if k != "elapsed_ns"} == {k:v for k,v in rerun.items() if k != "elapsed_ns"}, "personal statistic differs")
        bycase[e["case_id"]].append(e)
    require(len(bycase) == len(plans), "comparison plan must contain unique cases")
    pending = rows(output/"pending_annotations.jsonl")
    require(len(pending) == len(plans), "pending pair count")
    for record in pending:
        require(record["applicability"] is None and record["label_provenance"] == "NOT_A_NEW_MODEL_LABEL", "unrun pair mislabelled")
        packet = read(output/"evidence_packets"/(record["packet_sha256"]+".json"))
        require(digest(packet) == record["packet_sha256"], "packet hash mismatch")
        require(packet == compact_evidence(cases[record["case_id"]],probes,bycase[record["case_id"]]), "full packet differs")
    attribution, summary = failure_attribution(old_labels)
    require(rows(output/"legacy_label_failure_attribution.jsonl") == attribution, "failure attribution differs")
    require(read(output/"report.json")["legacy_failure_attribution"] == summary, "failure denominator differs")
    chains = request_chain_check(raw_reviews, old_labels, [ROOT/p for p in config["ledger_directories"]])
    return {"status":"PASS_ARTIFACT_CONSISTENCY_ONLY", "release_id":frozen["release_id"],
        "statistics_recomputed":len(evidence), "packets_verified":len(pending), "condition_candidates_preserved":len(expected_conditions),
        "historical_request_response_chains":chains, "source_integrity":verify_sources(ROOT/"data/raw/c1-benchmark-v2",read(source/"sources.json")),
        "semantic_correctness_proven":False,"human_gold":False}


def export(config, destination, qa, pilot=None):
    """Publish allowlisted source/knowledge metadata and aggregate counts only."""
    output = ROOT/config["output_release"]; frozen = verify(output)
    destination = Path(destination)
    require(not destination.exists(), "public export exists; use a new version")
    require(qa["release_id"] == frozen["release_id"] and qa["status"] == "PASS_ARTIFACT_CONSISTENCY_ONLY", "QA missing or mismatched")
    report = read(output/"report.json")
    report["audit_release_id"] = frozen["release_id"]
    write(destination/"aggregate_report.json",report)
    write(destination/"quality_report.json",qa)
    reviewed = rows(output/"knowledge_reviewed.jsonl")
    active_ids = set(read(output/"canonical_duplicates.json"))
    jsonl(destination/"knowledge_metadata.jsonl", [{k:item[k] for k in ("knowledge_id","title","topic","subtopic","source_url","source_sha256","review_status","condition_review_status")} |
        {"active_candidate":item["knowledge_id"] in active_ids,
         "legacy_model_conditions":[{k:c[k] for k in ("condition_id","role","logic","use","probe_ids","dataset_support")} for c in item["conditions"]],
         "model_support_is_not_verified_applicability":True} for item in reviewed])
    jsonl(destination/"joint_candidates.jsonl",[{"knowledge_id":c["knowledge_id"],"condition_id":c["condition_id"],
        "probe_ids":c["original_condition"]["probe_ids"], "role":c["original_condition"]["role"],"logic":c["original_condition"]["logic"],
        "use":c["original_condition"]["use"],"semantic_status":c["semantic_status"],"confirmed_rule":False} for c in rows(output/"joint_candidates.jsonl")])
    write(destination/"historical_dedup_audit.json",read(output/"historical_dedup_audit.json"))
    if pilot is not None: write(destination/"bounded_qwen_pilot.json",pilot)
    # Exact actual identifiers plus obvious credential patterns, before any git staging.
    cases = rows(ROOT/config["source_release"]/"cases.jsonl")
    public_text = "\n".join(p.read_text(encoding="utf-8") for p in destination.rglob("*") if p.is_file())
    for value in {c[k] for c in cases for k in ("case_id","subject_id")}:
        require(value not in public_text, "private identity in public export")
    require(not re.search(r"sk-[A-Za-z0-9]{16,}|Bearer [A-Za-z0-9]",public_text), "credential pattern in export")
    return freeze(destination,{"version":config["version"],"audit_release_id":frozen["release_id"],"privacy":"ALLOWLISTED_NONPERSONAL_METADATA_AND_AGGREGATES","human_gold":False})


def build(config):
    source = ROOT/config["source_release"]; legacy = ROOT/config["legacy_annotation"]
    output = ROOT/config["output_release"]
    require(not output.exists(), "V2.2 output exists; use a new version, never overwrite")
    sf, lf = verify(source), verify(legacy)
    source_check = verify_sources(ROOT/"data/raw/c1-benchmark-v2", read(source/"sources.json"))
    items = rows(source/"knowledge_candidates.jsonl"); probes = read(source/"probes.json")
    raw_reviews = rows(legacy/"knowledge_reviews.jsonl"); old_labels = rows(legacy/"silver_labels.jsonl")
    old_knowledge = rows(legacy/"knowledge_reviewed.jsonl"); old_active = rows(legacy/"knowledge_active.jsonl")
    cases = rows(source/"cases.jsonl"); casebyid = {c["case_id"]: c for c in cases}
    sourcebyid = {k["knowledge_id"]: k for k in items}
    chain_count = request_chain_check(raw_reviews, old_labels, [ROOT/p for p in config["ledger_directories"]])
    revised = recertify(raw_reviews, items, probes)
    reviewed, active, canonical = assemble(items, revised)
    activebyid = {k["knowledge_id"]: k for k in active}
    output.mkdir(parents=True)
    jsonl(output/"knowledge_reviews.jsonl", revised)
    jsonl(output/"knowledge_reviewed.jsonl", reviewed)
    jsonl(output/"knowledge_active.jsonl", active)
    write(output/"canonical_duplicates.json", canonical)
    jsonl(output/"dedup_suggestions.jsonl", model_suggestions(raw_reviews))
    historical_groups = legacy_dedup_audit(old_knowledge, read(legacy/"canonical_duplicates.json"))
    write(output/"historical_dedup_audit.json", historical_groups)
    audits = []; mappings = []
    for record in raw_reviews:
        item = sourcebyid[record["knowledge_id"]]
        first = record["stage1"].get("output") or {}
        conditions = first.get("conditions") or []
        for condition in conditions:
            audits.append({"knowledge_id": item["knowledge_id"], **audit_legacy_condition(condition, item, probes)})
        mappings.extend(mapping_candidates(item, c, probes) for c in (conditions or [None]))
    jsonl(output/"condition_dependency_audits.jsonl", audits)
    joint = [a for a in audits if a["is_joint_candidate"]]
    jsonl(output/"joint_candidates.jsonl", joint)
    jsonl(output/"mapping_discovery.jsonl", mappings)
    write(output/"probe_catalog.json", probes)
    write(output/"mapping_policy.json", {"registry": compact_catalog(probes), "mapping_model_calls": 0,
        "legacy_mapping_seen_catalog": "Restricted V2.1 subset; never relabelled as a full-catalog Qwen mapping",
        "binding_semantic_support": "NOT_NEWLY_ESTABLISHED", "suggestions_are_nonbinding": True})
    index = relation_index(active, probes)
    index["semantic_status"] = "CANDIDATE_LINKS_NOT_CONFIRMED_PREDICATES"
    write(output/"dependency_index.json", index)
    attribution, attr_summary = failure_attribution(old_labels)
    jsonl(output/"legacy_label_failure_attribution.jsonl", attribution)
    partition = read(source/"splits.json")
    balanced = balanced_pairs(cases, active, partition, config["pair_count"], config["plan_salt"])
    write(output/"balanced_plan.json", {"salt": config["plan_salt"], "rule": "Round-robin topics and SHA256 subject/knowledge selection, no mapping/outcome gate",
        "pairs": [{"case_id":c["case_id"], "subject_id":c["subject_id"], "history_days":c["history_days"], "knowledge_id":k["knowledge_id"]} for c,k in balanced]})
    # Matched old pairs isolate the input intervention; the new balanced plan is reported separately.
    plans = [{"case_id":l["case_id"], "knowledge_id":l["knowledge_id"], "legacy_input_sha256":l["input_sha256"]} for l in old_labels]
    write(output/"matched_comparison_plan.json", {"pairs":plans, "outcomes_used_for_selection":False, "rule":"Exact original 120 pairs; retain all, including no-mapping records"})
    evidence_stats = []; pending = []; preflight = []; all_evidence = []; computed = Counter()
    began = perf_counter()
    for plan in plans:
        case = casebyid[plan["case_id"]]
        # Restoration must not discard an original pair even if its new review status is pending.
        item = activebyid.get(plan["knowledge_id"], sourcebyid[plan["knowledge_id"]])
        provider = EvidenceProvider(case, probes)
        evidence = provider.compute_all()
        all_evidence.extend(evidence)
        computed.update(e["status"] for e in evidence)
        packet = compact_evidence(case, probes, evidence)
        packet_sha = digest(packet)
        write(output/"evidence_packets"/(packet_sha+".json"), packet)
        payload = {"case_id":case["case_id"], "knowledge":source_payload(item),
                   "unverified_condition_hints":item.get("conditions",[]), "personal_evidence":packet}
        request = {"model":"qwen-plus", "messages":messages(LABEL_TASK,payload,schemas.LABEL), "temperature":0,
                   "enable_thinking":False, "stream":False, "max_tokens":3000, "response_format":{"type":"json_object"}}
        nbytes = len(json.dumps(request,ensure_ascii=False,separators=(",",":")).encode())
        preflight.append({"case_id":case["case_id"], "knowledge_id":item["knowledge_id"], "first_stage_request_bytes":nbytes,
                          "transport_cap_bytes":60000, "stage1_fits":nbytes<=60000,
                          "stage2_size_status":"CHECK_ACTUAL_RESPONSE_BEFORE_ANY_SEND; never truncate evidence",
                          "request_sha256":digest(request), "packet_sha256":packet_sha})
        evidence_stats.append({"case_id":case["case_id"], "history_days":case["history_days"], "catalog_count":len(evidence),
                               "statuses":dict(Counter(e["status"] for e in evidence)), "packet_sha256":packet_sha})
        pending.append({**plan,"status":"PENDING_REANNOTATION_WITH_INDEPENDENT_EVIDENCE", "applicability":None,
                        "packet_sha256":packet_sha,"label_provenance":"NOT_A_NEW_MODEL_LABEL","human_gold":False})
    evidence_seconds = perf_counter()-began
    jsonl(output/"independent_evidence.jsonl", all_evidence)
    jsonl(output/"independent_evidence_coverage.jsonl", evidence_stats)
    jsonl(output/"annotation_preflight.jsonl", preflight)
    jsonl(output/"pending_annotations.jsonl", pending)
    # Preserve the original, mapping-restricted inputs and outputs as references, not new labels.
    accepted_old = [k for k in old_knowledge if k["review_status"]=="SILVER_ACCEPTED"]
    no_merge, _ = exact_deduplicate(accepted_old)
    demoted = sum(a["review_status"]=="SILVER_ACCEPTED" and b["review_status"]!="SILVER_ACCEPTED" for a,b in zip(raw_reviews,revised))
    promoted = sum(a["review_status"]!="SILVER_ACCEPTED" and b["review_status"]=="SILVER_ACCEPTED" for a,b in zip(raw_reviews,revised))
    report = {"version":config["version"], "source_release_id":sf["release_id"], "legacy_annotation_release_id":lf["release_id"],
        "source_integrity":source_check, "verified_historical_request_response_chains":chain_count,
        "data_windows_unchanged":len(cases), "observed_participants_unchanged":len({c["subject_id"] for c in cases}),
        "old_accepted_before_dedup":counts(accepted_old), "old_active":counts(old_active),
        "dedup_only_repair":counts(no_merge), "fresh_validation_and_exact_dedup":counts(active),
        "current_review_statuses":dict(Counter(r["review_status"] for r in revised)),
        "revalidation_promoted":promoted, "revalidation_demoted":demoted,
        "old_multi_member_clusters":len(historical_groups), "old_cluster_members":sum(g["members"] for g in historical_groups),
        "old_cross_topic_clusters":sum(len(g["topics"])>1 for g in historical_groups),
        "old_largest_cluster":max(g["members"] for g in historical_groups),
        "new_similarity_edges_used_to_merge":0,
        "old_arity_blocked_records":sum("necessary_ALL_probe_group_has_no_grounded_per_probe_predicates" in r["validation_errors"] for r in raw_reviews),
        "joint_candidate_groups_preserved":len(joint), "joint_candidate_knowledge":len({a["knowledge_id"] for a in joint}),
        "joint_source_semantic_status":"TARGETED_SOURCE_REVIEW_PENDING_NOT_AN_ABSENCE_RESULT",
        "full_mapping_registry_count":len(probes), "full_mapping_horizons":sorted({p["window_days"] for p in probes}),
        "mapping_suggestions_count":len(mappings), "legacy_mapping_exposure_not_rewritten":True,
        "independent_case_evidence": {"pairs":len(plans), "probe_attempts":sum(computed.values()), "statuses":dict(computed),
            "all_cases_received_full_registry":all(s["catalog_count"]==len(probes) for s in evidence_stats),
            "cases_with_at_least_one_computed_result":sum(s["statuses"].get("COMPUTED",0)>0 for s in evidence_stats),
            "compute_and_packet_serialization_seconds":evidence_seconds,
            "stage1_requests_within_60000_bytes":sum(p["stage1_fits"] for p in preflight),
            "max_stage1_request_bytes":max(p["first_stage_request_bytes"] for p in preflight)},
        "legacy_failure_attribution":attr_summary,
        "balanced_plan_topic_counts":dict(Counter(k["topic"] for c,k in balanced)),
        "new_qwen_calls":0, "new_qwen_cost_cny":0, "new_applicability_labels":None,
        "new_label_status":"NOT_RUN; pending records are not insufficient_information labels",
        "historical_cost_not_new_cost":read(legacy/"report.json")["cost"],
        "research_interpretation": {"data_insufficiency_claim":"NOT_IDENTIFIABLE_FROM_MAPPING_RESTRICTED_V2_1_LABELS",
            "joint_dependency_absence_claim":"WITHDRAWN_AS_EMPIRICAL_INFERENCE; candidates await source review",
            "full_computation_cost":"Existing measured cheap-compute observation retained for its explicit workload; repair timings are a different 120-case workload",
            "KUV_decision":"DEFER; neither abandon nor validate the hypothesis from this offline repair",
            "delayed_discovery_gain":None, "clinical_benefit":None}, "human_gold":False}
    write(output/"report.json", report)
    write(output/"source_release.json", {"path":config["source_release"], "release_id":sf["release_id"], "config":config,
        "cases_sha256":sha(source/"cases.jsonl"), "splits_sha256":sha(source/"splits.json"),
        "legacy_annotation_release_id":lf["release_id"]})
    frozen=freeze(output,{"version":config["version"], "source_release_id":sf["release_id"],
                         "legacy_annotation_release_id":lf["release_id"], "new_model_calls":0,"human_gold":False})
    print(json.dumps({"release_id":frozen["release_id"],"report":report},ensure_ascii=False,indent=2))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config",default="configs/c1_v2_2_audit.json")
    parser.add_argument("--action",choices=("build","verify","export"),default="build")
    parser.add_argument("--output",help="New QA file or new public export directory")
    parser.add_argument("--pilot-report",help="Optional already frozen aggregate pilot report")
    args=parser.parse_args()
    config=read(ROOT/args.config)
    if args.action=="build": build(config)
    else:
        require(bool(args.output),"new --output required")
        result=audit(config)
        if args.action=="verify": write(ROOT/args.output,result)
        else: result=export(config,ROOT/args.output,result,read(ROOT/args.pilot_report) if args.pilot_report else None)
        print(json.dumps(result,indent=2))


if __name__=="__main__":main()
