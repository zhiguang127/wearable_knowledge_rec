"""Original observation/statistic semantics; no clinical conclusions."""
from ..datasets.views import representation, evidence_value


def case_payload(case):
    """Preserve B0's compact table and three-decimal derived-statistic contract."""
    columns = ["day", "weekday", "phase", *case["days"][0]["metrics"]]
    flags = list(dict.fromkeys(flag for d in case["days"] for flag in d["quality_flags"]))
    metrics = columns[3:]
    stats = {}
    for phase, entry in representation(case, "statistics")["statistics"].items():
        stats[phase] = {"day_range": entry["day_range"], "metrics": {
            metric: {k: round(v, 3) if isinstance(v, float) else v for k, v in values.items()
                     if k not in ("observations", "value_counts", "interpretation")}
            for metric, values in entry["metrics"].items()}}
    return {"case_id": case["case_id"], "context": case["context"], "quality_notes": case["quality_notes"],
            "baseline_days": [1, 28], "current_days": [29, 42], "daily_columns": columns,
            "daily_rows": [[d["day"], d["weekday"], d["phase"], *[d["metrics"][m] for m in metrics]] for d in case["days"]],
            "quality_flag_dictionary": flags, "missing_metric_dictionary": metrics,
            "daily_quality_columns": ["day", "quality_flag_ids", "missing_metric_ids"],
            "daily_quality_rows": [[d["day"], [flags.index(f) for f in d["quality_flags"]],
                                    [metrics.index(m) for m in d["missing_metrics"]]]
                                   for d in case["days"] if d["quality_flags"] or d["missing_metrics"]],
            "stats": stats,
            "statistics_policy": "Derived floats rounded to 3 decimals; raw daily values unchanged. Population SD; OLS daily slope; RHR 0/null excluded; circular clocks, timezone unknown; original units"}


def resolve(case, ref):
    if not isinstance(ref, str):
        raise ValueError("Evidence reference must be text")
    if ref.startswith("stats."):
        parts = ref.split(".")
        if len(parts) != 4 or parts[1] not in ("baseline", "current"):
            raise ValueError("Unknown statistic reference")
        metrics = case_payload(case)["stats"][parts[1]]["metrics"]
        if parts[2] not in metrics or parts[3] not in metrics[parts[2]]:
            raise ValueError("Unknown statistic reference")
        return metrics[parts[2]][parts[3]], parts[1]
    value = evidence_value(case, ref)
    if ref.startswith("context.") and ref[8:] not in case["context"]:
        raise ValueError("Unknown context field")
    phase = "context" if ref.startswith("context.") else "baseline" if int(ref.split(".")[0][1:]) <= 28 else "current"
    return value, phase
