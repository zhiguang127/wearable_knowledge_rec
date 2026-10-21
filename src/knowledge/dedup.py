"""Lossless identity deduplication. Model similarity edges are suggestions only."""
import copy
from ..common import digest, require


def identity_key(item):
    """Do not merge across source scope, advice text, topic or condition variants."""
    anchor = item.get("source_anchor", {})
    return digest({"text": " ".join(item["text"].split()),
                   "topic": item.get("topic"), "subtopic": item.get("subtopic"),
                   "source_url": item.get("source_url"),
                   "source_sha256": item.get("source_sha256"),
                   "anchor_id": anchor.get("anchor_id"),
                   "conditions": item.get("conditions", [])})


def exact_deduplicate(items):
    """Return every variant unless its complete source/condition identity matches."""
    groups = {}
    for item in items:
        groups.setdefault(identity_key(item), []).append(item)
    active, canonical = [], {}
    for members in groups.values():
        members = sorted(members, key=lambda k: k["knowledge_id"])
        representative = copy.deepcopy(members[0])
        representative["dedup_policy"] = "EXACT_TEXT_SOURCE_SCOPE_AND_CONDITIONS_V2_2"
        representative["member_variants"] = [
            {"knowledge_id": m["knowledge_id"], "source_url": m.get("source_url"),
             "source_sha256": m.get("source_sha256"), "conditions": copy.deepcopy(m.get("conditions", []))}
            for m in members]
        active.append(representative)
        canonical.update({m["knowledge_id"]: representative["knowledge_id"] for m in members})
    require(len(canonical) == len(items), "duplicate knowledge identity in dedup input")
    return sorted(active, key=lambda k: k["knowledge_id"]), canonical


def model_suggestions(reviews):
    """No transitive closure, representatives or deletions based on Qwen judgments."""
    return [{"a": r["knowledge_id"], "b": other,
             "status": "UNVERIFIED_MODEL_SIMILARITY_SUGGESTION", "used_to_merge": False}
            for r in reviews for other in ((r.get("stage1") or {}).get("output") or {}).get("duplicate_ids", [])]
