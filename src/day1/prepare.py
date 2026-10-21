"""Read-only asset audit and exclusive-write Day 1 preparation, never a freeze."""
import argparse
import json
from collections import Counter
from pathlib import Path

from ..common import ROOT, Blocked, digest, inside, read, require, rows, sha, write
from ..datasets.v2_sources import freeze, verify, jsonl
from ..datasets.probes import validate_probe
from . import VERSION, schemas
from .annotation import PROMPT_VERSION, SCHEMA_VERSION
from .environment import RANKER_VERSION


def candidate_plan(knowledge, config):
    """Only topic and pre-existing mapping hints; no record/result/label input."""
    plan = {}
    for topic in config["topics"]:
        group = [k for k in knowledge if k["topic"] == topic]
        def key(k):
            coverage = len({p for c in k.get("conditions", []) for p in c.get("probe_ids", [])})
            return -coverage, digest([config["sampling_salt"], k["knowledge_id"]])
        group.sort(key=key)
        require(len(group) >= config["candidate_count_per_topic"], "insufficient topic candidates")
        plan[topic] = [k["knowledge_id"] for k in group[:config["candidate_count_per_topic"]]]
    return plan


def readiness(verified_items, labels, slates, *, protocol_frozen=False, verified_minimum=6, slate_minimum=20):
    """Inputs must already pass source/annotation validators; pending rows never count."""
    reviewed = {k["knowledge_id"] for k in verified_items if k["criteria_kind"] == "MEASURABLE" and
                k["semantic_review"]["status"] == "VERIFIED" and k["conditions"] and
                all(c["semantic_review"]["status"] == "VERIFIED" and c["predicates"] and
                    all(p["semantic_review"]["status"] == "VERIFIED" for p in c["predicates"]) for c in k["conditions"])}
    accepted, seen_labels = {}, set()
    require(len({s["query_id"] for s in slates}) == len(slates), "duplicate query in slate plan")
    slate_ids = {s["query_id"]: set(s["candidate_ids"]) for s in slates}
    for label in labels:
        key = (label["query_id"], label["knowledge_id"])
        require(key not in seen_labels, "duplicate query-knowledge label")
        require(key[0] in slate_ids and key[1] in slate_ids[key[0]], "label outside fixed slate plan")
        seen_labels.add(key)
        if label["annotation_status"] == "ACCEPTED" and not label.get("validation_errors") and key[1] in reviewed:
            accepted[key] = label["verdict"]
    mixed = 0
    for slate in slates:
        values = {accepted.get((slate["query_id"], kid)) for kid in slate["candidate_ids"]}
        mixed += {"applicable", "not_applicable"} <= values
    blockers = []
    if len(reviewed) < verified_minimum:
        blockers.append("VERIFIED_MEASURABLE_KNOWLEDGE_BELOW_MINIMUM")
    if not protocol_frozen:
        blockers.append("DAY1_FIVE_ACCEPTANCE_ITEMS_NOT_FROZEN")
    if mixed < slate_minimum:
        blockers.append("TRUSTWORTHY_MIXED_SLATES_BELOW_EXPLORATORY_THRESHOLD")
    return {"contract_status": "FROZEN" if protocol_frozen and len(reviewed) >= verified_minimum else "PENDING_FREEZE",
            "verified_measurable_knowledge": len(reviewed), "discriminable_slates": mixed,
            "formal_baseline_allowed": not blockers, "blockers": blockers}


def prepare(output, config_path):
    config_path = Path(config_path).resolve()
    config = read(config_path)
    require(config["version"] == VERSION, "unsupported Day 1 contract version")
    output = Path(output).resolve()
    require(output.is_relative_to(ROOT / "local"), "private outputs must remain under local/")
    require(not output.exists(), "preparation output exists; use a new version")
    releases = {}
    for field in ("source_release", "knowledge_release", "result_store"):
        path = inside(ROOT, config[field])
        releases[field] = verify(path)
        require(releases[field]["release_id"] == config[field + "_id"], "input release identity changed")
    source, knowledge_path, store = (inside(ROOT, config[f]) for f in ("source_release", "knowledge_release", "result_store"))
    knowledge = rows(knowledge_path / "knowledge_active.jsonl")
    cases = rows(source / "cases.jsonl")
    probes = read(source / "probes.json")
    require(probes == read(knowledge_path / "probe_catalog.json"), "probe catalogs differ")
    for probe in probes:
        validate_probe(probe)
    require(len({p["metric"] for p in probes}) == 16 and {p["window_days"] for p in probes} == {7, 14, 28} and
            len({p["operation"] for p in probes}) == 6, "probe registry dimensions changed")
    split = read(source / "splits.json")
    assigned_subjects, assigned_cases, case_split = set(), set(), {}
    all_case_ids = {c["case_id"] for c in cases}
    for part, expected in config["participant_split"].items():
        ids = split["partitions"][part]["subject_ids"]
        cids = split["partitions"][part]["case_ids"]
        require(len(ids) == len(set(ids)) == expected and not set(ids) & assigned_subjects, "participant leakage or quota mismatch")
        expected_cases = {c["case_id"] for c in cases if c["subject_id"] in ids}
        require(len(cids) == len(set(cids)) and set(cids) == expected_cases and not set(cids) & assigned_cases, "case/participant split mismatch")
        assigned_subjects.update(ids); assigned_cases.update(cids)
        case_split.update({cid: part for cid in cids})
    require(assigned_cases == all_case_ids, "unassigned windows")
    report = read(store / "report.json")
    require(report["release_id"] == releases["source_release"]["release_id"], "result store belongs to another data release")
    # Streaming validation: no values or verdicts are consulted by candidate_plan.
    counts = Counter()
    seen = set()
    case_ids = all_case_ids
    probe_ids = {p["probe_id"] for p in probes}
    with (store / "evidence.jsonl").open(encoding="utf-8") as stream:
        for line in stream:
            e = json.loads(line)
            pair = (e["case_id"], e["probe_id"])
            require(e["case_id"] in case_ids and e["probe_id"] in probe_ids and pair not in seen, "result key invalid or duplicated")
            require(e["status"] in ("COMPUTED", "INSUFFICIENT_INFORMATION") and
                    ((e["value"] is None) == (e["status"] == "INSUFFICIENT_INFORMATION")), "invalid result status/null")
            require(digest({k: v for k, v in e.items() if k not in ("result_sha256", "elapsed_ns")}) == e["result_sha256"], "result content hash mismatch")
            seen.add(pair); counts[e["status"]] += 1
    actual = {"participants": len(assigned_subjects), "windows": len(cases), "knowledge": len(knowledge), "probes": len(probes), "results": len(seen)}
    require(actual == config["expected_counts"] and len(case_ids) == len(cases) and
            len({k["knowledge_id"] for k in knowledge}) == len(knowledge), "asset counts or identities changed")
    require(dict(counts) == report["probe_statuses"], "result count disagrees with frozen report")
    require(config["ranker_version"] == RANKER_VERSION and not config["formal_baseline_execution"], "unsupported ranker or premature baseline authorization")
    candidates = candidate_plan(knowledge, config)
    slates = [{"query_id": "Q1-" + digest([VERSION, c["case_id"], topic])[:24],
               "case_id": c["case_id"], "subject_id": c["subject_id"], "split": case_split[c["case_id"]],
               "topic": topic, "goal": None, "candidate_ids": candidates[topic]}
              for c in cases for topic in config["topics"]]
    byid = {k["knowledge_id"]: k for k in knowledge}
    queue = []
    for topic, ids in candidates.items():
        for kid in ids[:config["review_queue_per_topic"]]:
            item = byid[kid]
            queue.append({"knowledge_id": kid, "topic": topic, "text": item["text"],
                          "source_url": item["source_url"], "source_sha256": item["source_sha256"],
                          "source_anchor": item["source_anchor"], "legacy_condition_hints": item["conditions"],
                          "semantic_status": "REVIEW_REQUIRED", "verified_predicates": [],
                          "required_review": ["source entailment", "role and AND/OR", "threshold, unit and exact time semantics", "probe observability"],
                          "not_a_verified_measurable_knowledge_item": True})
    output.mkdir(parents=True)
    write(output / "config.json", config)
    write(output / "candidate_plan.json", candidates)
    jsonl(output / "slates.jsonl", slates)
    jsonl(output / "source_review_queue.jsonl", queue)
    for name in ("SELECTION", "ANNOTATION", "KNOWLEDGE", "EVIDENCE", "QUERY", "OBSERVATION"):
        write(output / "schemas" / (name.lower() + ".json"), getattr(schemas, name))
    files = [config_path, ROOT / "docs/C1_DAY1_CONTRACT_V01.md", ROOT / config["qwen_budget_config"]]
    # Pin transitive deterministic computation/validation dependencies as well.
    files += sorted((ROOT / "src").rglob("*.py")) + [ROOT / "tests/test_day1.py"]
    hashes = {p.relative_to(ROOT).as_posix(): sha(p) for p in files}
    write(output / "implementation_hashes.json", hashes)
    result = {"version": VERSION, "status": "PREPARED_NOT_FROZEN", "asset_counts": actual,
              "probe_statuses": dict(counts), "slates": len(slates), "review_queue": len(queue),
              "readiness": readiness([], [], slates), "new_model_calls": 0, "new_labels": 0,
              "prompt_version": PROMPT_VERSION, "schema_version": SCHEMA_VERSION,
              "validation_scope": "FROZEN_BYTES_RESULT_HASHES_SPLIT_AND_PROTOCOL_PREPARATION_ONLY",
              "semantic_entailment_validated": False, "baseline_comparison_executed": False}
    write(output / "report.json", result)
    freeze(output, {"version": VERSION, "status": "PREPARATION_SNAPSHOT_ONLY", "human_gold": False,
                    "input_release_ids": {k: v["release_id"] for k, v in releases.items()}})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "verify"))
    parser.add_argument("--config", default="configs/c1_day1_v01.json")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    try:
        if args.action == "prepare":
            result = prepare(args.output, args.config)
        else:
            output = Path(args.output).resolve()
            verify(output)
            for path, expected in read(output / "implementation_hashes.json").items():
                require(sha(inside(ROOT, path)) == expected, "protocol implementation changed; prepare a new version")
            config = read(output / "config.json")
            for field in ("source_release", "knowledge_release", "result_store"):
                require(verify(inside(ROOT, config[field]))["release_id"] == config[field + "_id"], "input release changed")
            result = read(output / "report.json")
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (ValueError, OSError, KeyError) as exc:
        print("BLOCKED: " + str(exc))
        raise SystemExit(2) from None


if __name__ == "__main__":
    main()
