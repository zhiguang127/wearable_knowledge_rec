"""Judged-slate metrics only; missing/unevaluable labels are never zero gain."""
from collections import defaultdict
import math
import random
from statistics import mean

from ..common import require


def slate_metrics(ranking, labels, candidate_ids, k):
    require(isinstance(k, int) and not isinstance(k, bool) and k > 0, "invalid K")
    ids = [x[0] for x in ranking]
    require(len(candidate_ids) == len(set(candidate_ids)) and len(ids) == len(candidate_ids) and set(ids) == set(candidate_ids), "ranking must cover fixed slate exactly once")
    require(len({x["knowledge_id"] for x in labels}) == len(labels), "duplicate slate labels")
    require({x["knowledge_id"] for x in labels} <= set(candidate_ids), "label outside fixed slate")
    accepted = {x["knowledge_id"]: x["verdict"] for x in labels if x["annotation_status"] == "ACCEPTED"}
    binary = {kid: int(v == "applicable") for kid, v in accepted.items() if v in ("applicable", "not_applicable")}
    groups = defaultdict(list)
    for kid, score, rank in ranking:
        require(isinstance(score, (int, float)) and not isinstance(score, bool) and math.isfinite(score), "invalid ranking score")
        if kid in binary:
            groups[score].append(kid)
    # Project onto binary-judged items. Expected DCG over permutations within ties.
    dcg, position = 0.0, 0
    for score in sorted(groups, reverse=True):
        group = groups[score]
        average_gain = mean(binary[kid] for kid in group)
        for _ in group:
            if position < k:
                dcg += average_gain / math.log2(position + 2)
            position += 1
    idcg = sum(1 / math.log2(i + 2) for i in range(min(k, sum(binary.values()))))
    scores = {kid: score for kid, score, _ in ranking}
    pairs = [(p, n) for p, v in binary.items() if v for n, w in binary.items() if not w]
    pairwise = mean(1 if scores[p] > scores[n] else .5 if scores[p] == scores[n] else 0 for p, n in pairs) if pairs else None
    return {"ndcg": dcg / idcg if idcg else None, "pairwise_accuracy": pairwise,
            "pair_count": len(pairs), "candidate_count": len(candidate_ids),
            "label_coverage": len(accepted) / len(candidate_ids) if candidate_ids else 0,
            "binary_label_coverage": len(binary) / len(candidate_ids) if candidate_ids else 0,
            "insufficient_information_count": sum(v == "insufficient_information" for v in accepted.values()),
            "not_assessable_count": sum(v == "not_assessable" for v in accepted.values()),
            "evaluation_scope": "JUDGED_SLATE_BINARY_PROJECTION"}


def participant_summary(records, metric, *, seed=20261020, bootstrap_samples=2000):
    """Average queries within a person, then macro-average/bootstrap people."""
    require(bootstrap_samples >= 1, "bootstrap_samples must be positive")
    grouped = defaultdict(list)
    for row in records:
        if row[metric] is not None:
            require(math.isfinite(row[metric]), "nonfinite metric")
            grouped[row["subject_id"]].append(row[metric])
    means = [mean(v) for _, v in sorted(grouped.items())]
    if not means:
        return {"mean": None, "ci95": None, "participants": 0}
    rng = random.Random(seed)
    draws = sorted(mean(rng.choices(means, k=len(means))) for _ in range(bootstrap_samples))
    return {"mean": mean(means), "ci95": [draws[int(.025 * (bootstrap_samples - 1))], draws[int(.975 * (bootstrap_samples - 1))]],
            "participants": len(means), "bootstrap_unit": "participant", "bootstrap_samples": bootstrap_samples, "seed": seed}


def measurement_metrics(observed_evidence):
    n = len(observed_evidence)
    valid = sum(e["status"] == "COMPUTED" for e in observed_evidence)
    return {"valid_measurement_rate": valid / n if n else None,
            "missing_evidence_rate": (n - valid) / n if n else None,
            "probe_count": n}
