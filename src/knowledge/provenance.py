"""Check exact source bytes and historical disagreement without validating medicine."""
import hashlib
from pathlib import Path
from ..common import digest, read, rows, sha, require


def audit(root):
    root = Path(root)
    corpus_dir = root / "data/processed/legacy_knowledge"
    corpus = rows(corpus_dir / "knowledge_items.jsonl")
    require(len(corpus) == 96 and len({k["id"] for k in corpus}) == 96, "legacy source corpus cardinality")
    by_id = {k["id"]: k for k in corpus}
    seeds = read(corpus_dir / "corpus_seed.json")
    seeds = seeds["items"] if isinstance(seeds, dict) else seeds
    manifest = read(corpus_dir / "source_manifest.json")
    frozen = read(corpus_dir / "input_freeze.json")["file_sha256"]
    snapshots = root / "data/raw/knowledge_sources"
    count, historical_mismatches = 0, []
    for path in snapshots.iterdir():
        rel = "data/source_snapshots/" + path.name
        require(rel in frozen and sha(path) == frozen[rel], "frozen knowledge snapshot mismatch")
        count += 1
    for key, source in manifest.items():
        if source.get("status") == "fetched":
            for kind in ("html", "text"):
                name = source.get(kind + "_path")
                if name:
                    path = snapshots / Path(name).name
                    require(path.is_file(), "historically fetched snapshot missing")
                    if sha(path) != source.get(kind + "_sha256"):
                        lf_sha = hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
                        require(lf_sha == source.get(kind + "_sha256"), "BLOCKED_UNEXPLAINED_HISTORICAL_SOURCE_HASH: " + key)
                        historical_mismatches.append({"source_key": key, "kind": kind,
                            "status": "VERIFIED_CRLF_LF_REPRESENTATION_DIFFERENCE",
                            "frozen_bytes_preserved": True, "historical_lf_hash_verified": True})
    a1 = root / "data/releases/a1-v1"
    groups = read(a1 / "groups.json")["groups"]
    selected = sorted({k for g in groups for k in g["ids"]})
    knowledge = rows(a1 / "knowledge.jsonl")
    require(len(groups) == 6 and len(selected) == 26 and sum(len(g["ids"]) for g in groups) == 27,
            "A1 six-panel selection changed")
    require(sorted(k["id"] for k in knowledge) == selected, "A1 knowledge panel differs")
    require(all(k == by_id[k["id"]] for k in knowledge), "A1 corpus item was changed")
    for k in knowledge:
        seed = seeds[int(k["id"][1:]) - 1]
        source = manifest[seed["source_key"]]
        require(source["source_url"] == k["source_url"] and source["status"] == "fetched", "selected A1 source unavailable or URL differs")
        text = (snapshots / (seed["source_key"] + ".txt")).read_text(encoding="utf-8")
        anchors = [seed["support_anchor"]] + seed.get("additional_support_anchors", [])
        require(all(a.casefold() in text.casefold() for a in anchors), "A1 support anchor missing")
    source_audit = read(a1 / "source_audit.json")
    require(source_audit["corpus_sha256"] == sha(corpus_dir / "knowledge_items.jsonl"), "A1 source corpus hash mismatch")
    for item in source_audit["items"]:
        require(item["condition_sha256"] == digest(by_id[item["id"]]["applicability"]) and item["human_confirmed"] is False,
                "source-audit conditions changed")
    assignments = rows(a1 / "cases.jsonl")
    p1 = rows(root / "data/releases/p1-v2/cases.jsonl")
    require({x["case_id"] for x in assignments} == {x["case_id"] for x in p1} and len(assignments) == 48,
            "A1 case set differs from frozen P1")
    require(all(x["candidate_ids"] == selected for x in assignments), "A1 candidates changed")
    p1_knowledge = rows(root / "data/releases/p1-v2/knowledge.jsonl")
    for k in p1_knowledge:
        kid = k["knowledge_id"]
        seed = seeds[int(kid[1:]) - 1]
        path = snapshots / (seed["source_key"] + ".txt")
        require(sha(path) == k["source_snapshot_sha256"], "P1 source snapshot hash mismatch")
        require(k["content"] == by_id[kid]["content"] and k["applicability"] == by_id[kid]["applicability"],
                "P1 knowledge content differs")
        text = path.read_text(encoding="utf-8")
        require(all(a.casefold() in text.casefold() for a in k["support_anchors"]), "P1 support anchor missing")
    return {"status": "FROZEN_BYTES_VERIFIED_HUMAN_SOURCE_REVIEW_BLOCKED", "legacy_corpus": 96,
            "p1_candidates": len(p1_knowledge), "a1_knowledge": len(knowledge), "a1_groups": len(groups),
            "a1_unique_case_knowledge_pairs": len(assignments) * len(knowledge),
            "frozen_snapshots_verified": count, "historical_manifest_disagreements": historical_mismatches,
            "a1_source_anchor_sets_verified": len(knowledge),
            "legacy_editorial_document": "VERIFIED_ARCHIVED_MACHINE_EDITORIAL_RECORD_NOT_HUMAN_REVIEW",
            "unavailable_legacy_sources": [{"source_key": key, "status": "BLOCKED_SOURCE_UNAVAILABLE_NOT_IN_ACTIVE_PANELS"}
                                           for key, value in manifest.items() if value["status"] != "fetched"],
            "human_confirmed_sources": 0, "medical_gold": False}
