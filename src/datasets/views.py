"""Original quality-preserving longitudinal views, with new independent imports."""
from collections import Counter
from math import atan2, cos, pi, sin, sqrt
from statistics import mean, median, pstdev


def scalar_stats(points, total):
    vals = [v for _, v, _ in points]
    slope = None
    if len(points) >= 2:
        xs = [d for d, _, _ in points]
        xbar = mean(xs)
        denom = sum((x - xbar) ** 2 for x in xs)
        slope = sum((x - xbar) * (y - mean(vals)) for x, y in zip(xs, vals)) / denom if denom else None
    by_day = {d: v for d, v, _ in points}
    adjacent = [abs(v - by_day[d-1]) for d, v, _ in points if d-1 in by_day]
    return {"n": len(vals), "missing_or_unusable": total-len(vals),
            "mean": mean(vals) if vals else None, "median": median(vals) if vals else None,
            "sd": pstdev(vals) if vals else None, "min": min(vals) if vals else None,
            "max": max(vals) if vals else None, "slope_per_day": slope,
            "adjacent_mean_abs_change": mean(adjacent) if adjacent else None,
            "observations": [ref for _, _, ref in points]}

def representation(case, mode):
    """All views preserve missingness/quality; no source identity or sampling rationale."""
    base = {"context": case["context"], "quality_notes": case["quality_notes"],
            "baseline_day_range": [1, 28], "current_day_range": [29, 42]}
    if mode == "full":
        return {**base, "days": case["days"], "representation": "full_42_daily_rows_no_truncation"}
    if mode not in ("current", "statistics"):
        raise ValueError("Unknown information view")
    statistics = {}
    phases = ("current",) if mode == "current" else ("baseline", "current")
    for phase in phases:
        daily = [d for d in case["days"] if d["phase"] == phase]
        summary = {}
        for metric in daily[0]["metrics"]:
            raw = [(d["day"], d["metrics"][metric], f"d{d['day']}.{metric}") for d in daily]
            numeric = [(day, v, ref) for day, v, ref in raw if isinstance(v, (int, float)) and not isinstance(v, bool)
                       and not (metric == "resting_heart_rate_bpm" and v == 0)]
            if numeric or all(v is None or isinstance(v, (int, float)) for _, v, _ in raw):
                summary[metric] = scalar_stats(numeric, len(daily))
            elif metric.endswith("_clock"):
                valid = [(day, sum(int(n)*m for n, m in zip(v.split(":"), [60, 1, 1/60])), ref)
                         for day, v, ref in raw if v is not None]
                xs = [v/1440*2*pi for _, v, _ in valid]
                s, c = sum(sin(x) for x in xs), sum(cos(x) for x in xs)
                summary[metric] = {"n": len(xs), "missing": len(daily)-len(xs),
                    "circular_mean_minute": (atan2(s, c) % (2*pi))*1440/(2*pi) if xs else None,
                    "circular_resultant_length": sqrt(s*s+c*c)/len(xs) if xs else None,
                    "observations": [ref for _, _, ref in valid], "timezone_or_dst_known": False}
            else:
                summary[metric] = {"value_counts": dict(Counter(str(v) for _, v, _ in raw)),
                                   "interpretation": "source category, not independently verified quality"}
        statistics[phase] = {"day_range": [daily[0]["day"], daily[-1]["day"]], "metrics": summary,
                             "quality_flags": {f"d{d['day']}": d["quality_flags"] for d in daily if d["quality_flags"]}}
    return {**base, "statistics": statistics, "representation": mode,
            "sufficiency_limit": "Descriptive moments, slopes and clock concentration are not sufficient statistics for every possible temporal condition"}

def evidence_value(case, reference):
    if reference.startswith("context."):
        return case["context"].get(reference.removeprefix("context."))
    import re
    match = re.fullmatch(r"d(\d+)\.([a-z_]+)", reference)
    if not match:
        raise ValueError("Unknown evidence reference: " + reference)
    day, metric = int(match[1]), match[2]
    row = next((d for d in case["days"] if d["day"] == day), None)
    if row is None or metric not in row["metrics"]:
        raise ValueError("Unknown evidence reference: " + reference)
    return row["metrics"][metric]
