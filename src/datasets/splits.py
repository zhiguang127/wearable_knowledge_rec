"""Deterministic partitions use only pseudonymous participant IDs, never labels."""
from collections import Counter
from ..common import digest, require


def make_split(cases, counts=(10, 3, 3), salt="wearable-knowledge-rec-split-v1"):
    ids = [c["case_id"] for c in cases]
    require(len(ids) == len(set(ids)), "duplicate case IDs")
    subjects = sorted({c["subject_id"] for c in cases}, key=lambda s: digest([salt, s]))
    require(sum(counts) == len(subjects) and all(x > 0 for x in counts), "invalid participant quotas")
    result = {"version": "participant-split-v1", "salt": salt,
              "rule": "SHA256(salt, subject_id); first 10 train, next 3 dev, last 3 test",
              "retrospective": True, "historically_unexposed_test": False, "partitions": {}}
    start = 0
    for name, count in zip(("train", "dev", "test"), counts):
        group = subjects[start:start + count]
        result["partitions"][name] = {"subject_ids": group,
            "case_ids": sorted(c["case_id"] for c in cases if c["subject_id"] in group)}
        start += count
    result["id"] = digest(result)
    validate_split(cases, result)
    return result


def validate_split(cases, split):
    require(split["id"] == digest({k: v for k, v in split.items() if k != "id"}), "split hash mismatch")
    by_id = {c["case_id"]: c for c in cases}
    require(len(by_id) == len(cases), "duplicate cases")
    require(set(split["partitions"]) == {"train", "dev", "test"}, "partition set differs")
    seen_subjects, seen_cases, counts = set(), set(), {}
    for name, p in split["partitions"].items():
        subjects, ids = p["subject_ids"], p["case_ids"]
        require(len(subjects) == len(set(subjects)) and len(ids) == len(set(ids)), "duplicate split membership")
        require(not seen_subjects.intersection(subjects) and not seen_cases.intersection(ids), "participant leakage")
        require(set(ids) <= set(by_id), "unknown split case")
        expected = {c["case_id"] for c in cases if c["subject_id"] in subjects}
        require(set(ids) == expected and set(subjects) == {by_id[c]["subject_id"] for c in ids},
                "all windows of a participant must stay together")
        seen_subjects.update(subjects); seen_cases.update(ids)
        counts[name] = {"participants": len(subjects), "windows": len(ids)}
    require(seen_cases == set(by_id), "split does not cover all cases")
    require(seen_subjects == {c["subject_id"] for c in cases}, "split does not cover all participants")
    return counts
