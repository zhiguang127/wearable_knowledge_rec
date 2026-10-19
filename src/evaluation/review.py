"""C0-A pure blind-card logic. All returned content must remain in ignored local/."""
import hashlib
import json
import random
import re


METHODS = (
    "B1_direct", "B2_re2_style", "B3_self_refine", "B4_critic",
    "BM_critic", "S4_relative",
)

SEED = 20261018

def token(seed, *parts):
    data = "|".join(map(str, (seed, *parts)))
    return hashlib.sha256(data.encode()).hexdigest()[:18]

def top_pairs(output):
    """Only strict top-tier vs immediately next-tier pairs; ties NOT forced."""
    ranking = output["ranking"]
    if not ranking or any(not isinstance(group, list) or not group for group in ranking):
        raise ValueError("Invalid ranking")
    if len({item for group in ranking for item in group}) != sum(map(len, ranking)):
        raise ValueError("Duplicate candidate")
    if len(ranking) < 2:
        return []
    return [(hi, lo) for hi in sorted(ranking[0]) for lo in sorted(ranking[1])]

def make_cards(cases, runs, seed=SEED, methods=METHODS):
    """Pure builder; all resulting cards/private crosswalk MUST remain local."""
    case_ids = [c["case_id"] for c in cases]
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("Duplicate case IDs")
    by_run = {}
    for r in runs:
        key = (r["case_id"], r["method"])
        if key in by_run:
            raise ValueError("Duplicate model record")
        by_run[key] = r
    case_cards, explanation_cards, crosswalk, missing = [], [], [], []
    for c in sorted(cases, key=lambda x: x["case_id"]):
        ident = c["case_id"]
        case_card_id = "C-" + token(seed, "case", ident)
        # Blind the source candidate presentation order, without altering evidence.
        private_packet = json.loads(json.dumps(c["packet"], ensure_ascii=False))
        private_packet["records"].pop("case_id", None)
        private_packet["records"].pop("subject_id", None)
        random.Random(token(seed, "candidate_order", ident)).shuffle(private_packet["candidates"])
        case_cards.append({
            "card_id": case_card_id,
            "goal_policy": "UNSPECIFIED_IN_B0",
            "review_task": "Check source scope and whether priority is identifiable; DO NOT infer a unique top-1",
            "data_and_sources": private_packet,
        })
        crosswalk.append({"card_id": case_card_id, "case_id": ident, "method": None})
        for method in methods:
            r = by_run.get((ident, method))
            if not r or r.get("status") != "EXECUTED":
                missing.append({"case_id": ident, "method": method,
                                "status": "MISSING_RECORD" if not r else r.get("status", "UNKNOWN"),
                                "error_type": r.get("error_type") if r else None,
                                "error": r.get("error") if r else None,
                                "validation_errors": r.get("validation_errors", []) if r else []})
                continue
            output = r["output"]
            ranking = output["ranking"]
            if sorted(k for group in ranking for k in group) != sorted(c["candidate_ids"]):
                raise ValueError("Accepted ranking does not partition frozen candidates")
            items = {x["id"]: x for x in output["items"]}
            if set(items) != set(c["candidate_ids"]) or len(output["items"]) != len(items):
                raise ValueError("Accepted output has incorrect item set")
            pairs = top_pairs(output)
            if not pairs:
                # Keep ties in the denominator rather than silently discarding them.
                pairs = [(None, None)]
            for index, (hi, lo) in enumerate(pairs):
                card_id = "E-" + token(seed, "explanation", ident, method, index)
                reasons = [x["reason"] for x in output.get("pairwise_reasons", [])
                           if x.get("higher") == hi and x.get("lower") == lo]
                card = {
                    "card_id": card_id,
                    "case_card_id": case_card_id,
                    "goal_policy": "UNSPECIFIED_IN_B0",
                    "higher": hi, "lower": lo,
                    "ranking": ranking,
                    "higher_item": items.get(hi) if hi else None,
                    "lower_item": items.get(lo) if lo else None,
                    "explicit_pairwise_reasons": reasons,
                    "pairwise_reason_absent": bool(hi and not reasons),
                    "task": "Audit local support and whether the stated relative claim follows. Do not judge hidden model internals.",
                }
                explanation_cards.append(card)
                crosswalk.append({"card_id": card_id, "case_id": ident,
                                  "method": method, "higher": hi, "lower": lo})
    rng = random.Random(seed)
    rng.shuffle(case_cards)
    rng.shuffle(explanation_cards)
    return case_cards, explanation_cards, crosswalk, missing

def check_blinding(case_cards, explanation_cards, private_ids):
    """Refuse to alter explanations to hide self-identification; block instead.

    Text/style may still suggest a method. Masking is not empirically established
    blinding, and is not a behavioral-faithfulness measurement.
    """
    text = json.dumps([case_cards, explanation_cards], ensure_ascii=False)
    if any(ident in text for ident in private_ids):
        raise ValueError("Private source identity remains in review cards")
    pattern = r"(?i)\b(?:B[1-5]_[a-z_]+|BM_[a-z_]+|S3[ab]_[a-z_]+|S4(?:_relative)?|CRITIC|RE2|Self[-_ ]Refine|RARR)\b"
    if re.search(pattern, text):
        raise ValueError("Method identifier remains in review cards; steward review required")
    for card in case_cards:
        if any(k in card for k in ("method", "output", "ranking")):
            raise ValueError("Stage 1 contains model metadata")
    return {"method_identifier_matches": 0, "private_identity_matches": 0,
            "stage1_model_metadata_matches": 0}
