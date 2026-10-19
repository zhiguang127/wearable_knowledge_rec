"""Replay frozen B0 outputs, source packets and C0 cards without model calls."""
from collections import Counter
from pathlib import Path
from ..common import digest, inside, read, require, rows, sha
from ..evaluation.evidence import case_payload
from ..evaluation.review import make_cards, check_blinding
from .contracts import validate


def source_packet(root, knowledge):
    root = Path(root)
    directory = root / "data/processed/legacy_knowledge"
    manifest = read(directory / "source_manifest.json")
    sources = {x["source_url"].rstrip("/"): x for x in manifest.values()}
    frozen = read(directory / "input_freeze.json")["file_sha256"]
    result = []
    for k in knowledge:
        source = sources[k["source_url"].rstrip("/")]
        path = root / "data/raw/knowledge_sources" / Path(source["text_path"]).name
        require(sha(path) == frozen[source["text_path"]], "frozen baseline source bytes differ")
        paragraphs = [x.strip() for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
        indices = [i for i, text in enumerate(paragraphs) if any(a.lower() in text.lower() for a in k.get("support_anchors", []))]
        require(bool(indices), "baseline source anchors missing")
        result.append({**k, "source_paragraphs": [{"id": k["id"] + ".p" + str(i), "text": paragraphs[i]} for i in indices],
                       "source_packet_complete": False, "source_bytes_sha256": sha(path),
                       "historical_manifest_text_hash_matches": sha(path) == source["text_sha256"],
                       "draft_conditions_human_confirmed": False})
    return result


def payload(root, case, knowledge):
    return {"records": case_payload(case), "candidates": source_packet(root, [knowledge[k] for k in case["candidate_ids"]]),
            "task": "Prioritize optional general health education; no diagnosis or treatment. Partial order and unknown are allowed."}


def replay(root, cases):
    root = Path(root)
    base = root / "local/archive/experiment_b0"
    frozen = read(base / "records/configs/freeze.json")
    require(frozen["id"] == digest({k: v for k, v in frozen.items() if k != "id"}, sorted_keys=False), "B0 freeze identity differs")
    for name, expected in frozen["files"].items():
        if name.startswith("configs/"):
            path = inside(base / "records", name)
        else:
            path = inside(base / "implementation", name)
        require(sha(path) == expected, "B0 frozen code/config mismatch: " + name)
    require(sha(base / "records/results/upstream_pins.json") == frozen["upstream_pins_sha256"], "B0 upstream pins differ")
    knowledge = {k["knowledge_id"]: {**k, "id": k["knowledge_id"]} for k in rows(root / "data/releases/p1-v2/knowledge.jsonl")}
    by_id = {c["case_id"]: c for c in cases}
    packets = []
    for c in frozen["cases"]:
        data = payload(root, by_id[c["case_id"]], knowledge)
        require(digest(data, sorted_keys=False) == c["input_sha256"], "frozen baseline payload differs")
        packets.append({"case_id": c["case_id"], "candidate_ids": c["candidate_ids"], "packet": data})
    require(len(packets) == 16 and len({by_id[c["case_id"]]["subject_id"] for c in packets}) == 16, "B0 participant/window set differs")
    main = [read(p) for p in sorted((base / "runs/main").rglob("*.json"))]
    reverse = [read(p) for p in sorted((base / "runs/candidate_reverse").rglob("*.json"))]
    all_runs = [read(p) for p in sorted((base / "runs").rglob("*.json"))]
    require(len(main) == 160 and len(reverse) == 40 and len(all_runs) == 200, "B0 original denominator changed")
    expected_cases = {c["case_id"]: c for c in frozen["cases"]}
    seen = set()
    for record in main:
        identity = (record["case_id"], record["method"])
        require(identity not in seen, "duplicate B0 slot")
        seen.add(identity)
        require(record["input_sha256"] == expected_cases[record["case_id"]]["input_sha256"], "B0 run input differs")
        if record["status"] == "EXECUTED":
            require(not validate(record["output"], by_id[record["case_id"]]), "historical accepted output no longer validates")
        else:
            require(record["status"] in {"FAILED", "INVALID_OUTPUT"}, "unknown historical status")
    c0base = root / "local/archive/experiment_c0/c0a-v1"
    original_manifest = read(c0base / "manifest.json")
    for artifact in original_manifest["artifacts"]:
        path = inside(c0base, artifact["path"])
        require(sha(path) == artifact["sha256"] and path.stat().st_size == artifact["bytes"], "C0 artifact bytes/hash differ")
        if artifact["rows"] is not None:
            require(len(rows(path)) == artifact["rows"], "C0 artifact row count differs")
    private = read(c0base / "steward/reproducibility.json")
    case_cards, explanation_cards, crosswalk, missing = make_cards(packets, main, seed=private["private_seed"])
    for replayed, relative in [(case_cards, "review_packets/stage1/stage1_cases.jsonl"),
                               (explanation_cards, "review_packets/stage2/stage2_explanations.jsonl"),
                               (crosswalk, "steward/STUDY_STEWARD_ONLY_crosswalk.jsonl"),
                               (missing, "steward/all_failure_slots.jsonl")]:
        require(replayed == rows(c0base / relative), "C0 original content replay mismatch: " + relative)
    summary = read(root / "local/archive/experiment_c0/records/results/local_execution_summary.json")
    require(len(case_cards) == summary["case_cards"] == 16 and len(explanation_cards) == summary["explanation_cards"] == 140,
            "C0 review denominator changed")
    require(len(missing) == summary["missing_or_invalid_slots"] == 21, "C0 failures dropped")
    identities = [c["case_id"] for c in cases] + [c["subject_id"] for c in cases]
    check_blinding(case_cards, explanation_cards, identities)
    return {"status": "PASS_HISTORICAL_REPLAY_ONLY", "frozen_payloads_verified": len(packets),
            "main_records": len(main), "total_records": len(all_runs),
            "all_record_statuses": dict(Counter(r["status"] for r in all_runs)),
            "c0_case_cards": len(case_cards), "c0_explanation_cards": len(explanation_cards),
            "c0_failure_slots": len(missing), "human_annotations": 0, "new_model_calls": 0,
            "decision_accuracy": None, "explanation_fidelity": None}
