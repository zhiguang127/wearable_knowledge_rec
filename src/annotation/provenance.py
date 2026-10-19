"""Frozen Silver, raw caches and underlying label provenance; never repairs labels."""
from collections import Counter
from pathlib import Path
from ..common import digest, inside, read, rows, sha, require
from ..datasets.releases import verify_release
from .client import audit_budget


def audit(root, cases):
    root = Path(root)
    release = root / "data/releases/qwen-max-silver-v1"
    freeze = verify_release(release, "silver")
    provenance = read(release / "provenance.json")
    records = rows(release / "annotations.jsonl")
    archive = root / "local/archive/experiment_a/silver_annotations/v1"
    require(provenance["human_gold"] is False and provenance["semantic_correctness_human_verified"] is False,
            "Silver/human boundary changed")
    require(provenance["model_requested"] == "qwen-max" and provenance["label_provenance"] == "QWEN_MAX_SILVER", "Silver model attribution changed")
    require(sha(archive / "budget.json") == provenance["budget_ledger_sha256"], "Silver budget provenance mismatch")
    plan = read(archive / "plan.json")
    require(plan["plan_id"] == digest({k: v for k, v in plan.items() if k != "plan_id"}), "Silver plan identity mismatch")
    require(plan["plan_id"] == provenance["plan_id"] == freeze["plan_id"], "Silver plan chain mismatch")
    for relative, expected in provenance["underlying_label_files"].items():
        require(sha(inside(archive, relative)) == expected, "underlying Silver label file changed")
    for method, expected in provenance["original_baseline_predictions"].items():
        path = inside(root / "local/archive/experiment_a/runs", plan["baseline_runs"][method] + "/predictions.jsonl")
        require(sha(path) == expected, "Silver prediction provenance mismatch")
    bycase = {c["case_id"]: c for c in cases}
    keys, accepted = set(), 0
    for record in records:
        key = (record["case_id"], record["knowledge_id"], record["scope"], record["round"])
        require(key not in keys and record["case_id"] in bycase, "duplicate or unknown Silver record")
        keys.add(key)
        require(record["knowledge_id"] in bycase[record["case_id"]]["candidate_ids"], "Silver outside P1 candidate panel")
        require(record["label_provenance"] == "QWEN_MAX_SILVER" and record["annotation_model"] == "qwen-max", "Silver record relabelled")
        accepted += record["accepted"] is True
    require(len(records) == freeze["records"] == provenance["records"] == 160, "Silver record count differs")
    require(accepted == provenance["reference_schema_accepted_records"] == 119, "Silver accepted/rejected history changed")
    for scope, ids in [("smoke", plan["smoke_case_ids"]), ("heldout", plan["heldout_case_ids"])]:
        expected = {(cid, kid, scope, rnd) for cid in ids for kid in bycase[cid]["candidate_ids"] for rnd in ("A", "B")}
        require({k for k in keys if k[2] == scope} == expected, "Silver A/B coverage differs")
    caches = list((archive / "cache").glob("*.json")) + list((archive / "malformed_cache").glob("*.json"))
    for path in caches:
        cache = read(path)
        require(digest(cache["response"]) == cache["response_sha256"], "Silver cached response hash mismatch")
    requests = list((archive / "requests").glob("*.json"))
    for path in requests:
        request = read(path)
        require(digest(request) in path.stem, "Silver request hash mismatch")
        require(request["model"] == "qwen-max", "legacy request model differs")
    source_snapshots = 0
    for path in (archive / "sources").glob("*.json"):
        source = read(path)
        if source.get("status") == "FETCHED_PRIMARY_TEXT":
            require(digest(source["paragraphs"]) == source["text_sha256"], "Silver source paragraph hash mismatch")
            html = path.with_suffix(".html")
            if source.get("html_sha256"):
                require(html.exists() and sha(html) == source["html_sha256"], "Silver source HTML hash mismatch")
            source_snapshots += 1
    return {"status": "PASS_PROVENANCE_ONLY", "release_id": freeze["release_id"], "records": len(records),
            "unique_case_knowledge_pairs": len({(r["case_id"], r["knowledge_id"]) for r in records}),
            "accepted_by_historical_reference_schema": accepted, "not_accepted": len(records) - accepted,
            "model_requested": "qwen-max", "label_provenance": "QWEN_MAX_SILVER", "human_gold": False,
            "caches_including_malformed_verified": len(caches), "requests_verified": len(requests),
            "source_snapshots_verified": source_snapshots,
            "budget": audit_budget(archive / "budget.json"), "new_model_calls": 0}
