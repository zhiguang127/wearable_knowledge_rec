"""Replay explicit model-authored source reviews; never infer rules from keywords.

Decisions are a review artifact, not human Gold or clinical validation. No case
values, model applicability labels or acquisition results enter catalog screening.
"""
import argparse
from collections import Counter
from pathlib import Path

from ..common import ROOT, digest, read, require, rows, sha, write
from ..datasets.probes import validate_probe
from ..datasets.v2_sources import freeze, verify, verify_sources, jsonl

VERSION = "day1-all-204-source-measurement-audit-v02"
REASONS = {
    "E": "GENERAL_EDUCATION_NO_EXPLICIT_PERSONAL_RULE",
    "C": "REQUIRED_CONTEXT_OUTSIDE_ALLOWED_MEASUREMENTS",
    "M": "PROBE_DOES_NOT_MEASURE_SOURCE_CONSTRUCT",
    "S": "THRESHOLD_TIME_OR_APPLICABILITY_ROLE_NOT_ESTABLISHED",
    "F": "FRAGMENT_OR_RESOURCE_POINTER_NOT_INDEPENDENT_CRITERION",
    "N": "FOOD_INTAKE_OR_PRODUCT_COMPOSITION_NOT_MEASURED",
    "H": "CLINICAL_OR_EMERGENCY_SCOPE_NOT_IN_FIRST_TASK",
}


def audit_items(knowledge, probes, decisions):
    require(len(knowledge) == len({k["knowledge_id"] for k in knowledge}), "duplicate knowledge")
    byid = {r["knowledge_id"]: r for r in decisions}
    require(len(byid) == len(decisions) and set(byid) == {k["knowledge_id"] for k in knowledge},
            "review must explicitly cover every knowledge item exactly once")
    for probe in probes:
        validate_probe(probe)
    legal = {p["probe_id"] for p in probes}
    results = []
    for item in knowledge:
        review = byid[item["knowledge_id"]]
        anchor = item["source_anchor"]
        require(digest(anchor["text"]) == anchor["text_sha256"] and item["text"] in anchor["text"], "source text/anchor integrity")
        require(review["item_hash"] == digest(item), "review was written for different knowledge bytes")
        require(bool(review["reason_codes"]) and set(review["reason_codes"]) <= set(REASONS.values()) and
                bool(review["rationale"].strip()), "explicit review rationale required")
        legacy_probes = sorted({pid for c in item["conditions"] for pid in c["probe_ids"]})
        require(set(legacy_probes) <= legal, "unknown legacy probe reference")
        # This version records screened-out items only. Admission needs a separate
        # source-bound KNOWLEDGE schema, predicate and connective semantic reviews.
        require(review["admission"] == "NOT_ADMITTED", "screening artifact cannot certify predicates")
        results.append({**review, "topic": item["topic"], "title": item["title"],
                        "source_url": item["source_url"], "source_sha256": item["source_sha256"],
                        "anchor_id": anchor["anchor_id"], "anchor_sha256": anchor["text_sha256"],
                        "legacy_probe_ids": legacy_probes, "citation_integrity": "PASS_NOT_ENTAILMENT",
                        "audit_status": "COMPLETED_MODEL_SOURCE_AND_MEASUREMENT_AUDIT",
                        "predicate_semantic_status": "REVIEW_REQUIRED", "applicability_label": None,
                        "human_gold": False})
    return results


def build(output, decisions_path):
    config = read(ROOT / "configs/c1_day1_v01.json")
    output = Path(output).resolve()
    require(output.is_relative_to(ROOT / "local") and not output.exists(), "use a new private output directory")
    source = ROOT / config["source_release"]
    catalog = ROOT / config["knowledge_release"]
    require(verify(source)["release_id"] == config["source_release_id"], "source release changed")
    require(verify(catalog)["release_id"] == config["knowledge_release_id"], "knowledge release changed")
    closure = verify_sources(ROOT / "data/raw/c1-benchmark-v2", read(source / "sources.json"))
    decisions = read(decisions_path)
    require(decisions["version"] == VERSION and decisions["knowledge_release_id"] == config["knowledge_release_id"], "review release/version mismatch")
    knowledge = rows(catalog / "knowledge_active.jsonl")
    probes = read(source / "probes.json")
    records = audit_items(knowledge, probes, decisions["reviews"])
    require(len(records) == 204 and len(probes) == 288, "wrong catalog/registry scope")
    known_source_hashes = {v["sha256"] for v in read(source / "sources.json").values() if v["status"] == "FETCHED"}
    require(all(r["source_sha256"] in known_source_hashes for r in records), "citation lacks frozen source closure")
    output.mkdir(parents=True)
    jsonl(output / "screening.jsonl", records)
    jsonl(output / "source_contexts.jsonl", [{"knowledge_id": k["knowledge_id"], "text": k["text"],
           "source_anchor": k["source_anchor"], "legacy_conditions": k["conditions"]} for k in knowledge])
    write(output / "verified_measurable_knowledge.json", [])
    report = {"version": VERSION, "status": "AUDIT_COMPLETE_MEASURABLE_PANEL_BLOCKED",
              "reviewer_kind": "model", "human_gold": False, "items_reviewed": len(records),
              "unique_source_anchors": len({r["anchor_id"] for r in records}),
              "topic_counts": dict(Counter(r["topic"] for r in records)),
              "reason_counts_nonexclusive": dict(Counter(code for r in records for code in r["reason_codes"])),
              "source_closure": closure, "citation_integrity_passed": len(records),
              "registry_probes": len(probes), "verified_measurable_knowledge": 0,
              "new_applicability_labels": 0, "new_model_api_calls": 0,
              "contract_frozen": False, "formal_baseline_allowed": False,
              "blockers": ["NO_SIX_SOURCE_VERIFIED_MEASURABLE_APPLICABILITY_RULES",
                           "REAL_QWEN_ID_SMOKE_AWAITING_AUTHORIZATION",
                           "NO_TWENTY_TRUSTWORTHY_MIXED_SLATES"],
              "review_decisions_sha256": sha(decisions_path),
              "scope": "Frozen 204-item catalog and existing 288 probes only; not a statement that wearable personalization is impossible."}
    write(output / "report.json", report)
    freeze(output, {"version": VERSION, "status": "AUDIT_SNAPSHOT_NOT_EXPERIMENT_FREEZE", "human_gold": False})
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--decisions", default="configs/c1_day1_catalog_review_v02.json")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    import json
    print(json.dumps(build(args.output, args.decisions), ensure_ascii=False, indent=2))
