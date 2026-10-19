"""Lossless daily source import. No MCQ answers, biomarkers or cohort percentiles as labels."""
from collections import Counter
from datetime import date, timedelta
import math
from .pmdata import opaque
from .splits import make_split
from ..common import digest, require

# Units follow official render_raw.py FIELD_LABELS; unspecified scales stay unspecified.
UNITS = {"steps":"count/day", "rhr":"bpm", "hrv":"source_unit_unspecified",
         "sleep_duration":"hours", "sleep_efficiency":"source_ratio_scale_unverified",
         "deep_percentage":"percent", "rem_percentage":"percent", "bed_time_std":"minutes",
         "exercise_hours":"hours/day", "exercise_count":"count/day", "exercise_avg_hr":"bpm",
         "exercise_mets":"source_MET_aggregation_unspecified", "active_burn":"source_calories",
         "calories_bmr":"source_calories", "vo2_max":"source_unit_unspecified",
         "avg_stress_level":"source_device_score"}


def usable(metric, value):
    if value is None:
        return False
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or value < 0:
        return False
    if metric in {"rhr", "hrv", "vo2_max", "exercise_avg_hr", "exercise_mets", "exercise_hours", "avg_stress_level"} and value == 0:
        return False
    if metric in {"sleep_duration", "exercise_hours"} and value > 24:
        return False
    if metric in {"deep_percentage", "rem_percentage"} and value > 100:
        return False
    if metric == "sleep_efficiency" and value > 1:
        return False
    return True


def import_histories(data, key):
    require(len(key) >= 32, "private identity key too short")
    require(isinstance(data,dict) and {"user_histories","n_unique_users","mcqs","n_mcqs"}<=set(data), "WearableQA root fields missing")
    require(len(data["user_histories"]) == data["n_unique_users"], "declared user count mismatch")
    require(len(data["mcqs"]) == data["n_mcqs"], "declared question count mismatch")
    records, mapping, counts = {}, [], Counter()
    for source_id, history in sorted(data["user_histories"].items()):
        require(isinstance(history,list),"participant history is not an array")
        subject_id = "W" + opaque(key, source_id)
        require(subject_id not in records, "identity collision")
        mapping.append({"subject_id":subject_id, "source_participant_id":source_id})
        daily = {}
        for raw in history:
            require(isinstance(raw,dict) and isinstance(raw.get("date"),str),"daily source row/date malformed")
            day = date.fromisoformat(raw["date"])
            require(day not in daily, "duplicate participant/date; no silent overwrite")
            require(not set(raw) - {"date", "_source", "_period"} - set(UNITS), "unknown source metric")
            metrics = {name: raw.get(name) for name in UNITS}
            flags = [name + ":unusable_source_value" for name,v in metrics.items() if v is not None and not usable(name,v)]
            daily[day] = {"date":day.isoformat(), "metrics":metrics,
                          "source_present_fields":sorted(raw), "source_record":dict(raw),
                          "missing_metrics":[m for m,v in metrics.items() if v is None],
                          "quality_flags":flags + ["daily_aggregate_no_intraday_events", "device_quality_and_timezone_not_provided"]}
            counts.update(["daily_rows"])
            counts.update("valid:"+m for m,v in metrics.items() if usable(m,v))
        records[subject_id] = dict(sorted(daily.items()))
    return records, mapping, dict(counts)


def construct_windows(records, config):
    cases, exclusions = [], []
    baseline, current = config["baseline_days"], config["current_days"]
    for subject, daily in sorted(records.items()):
        require(bool(daily), "empty participant history")
        last = max(daily)
        for length in config["history_lengths"]:
            require(length >= current, "history shorter than current period")
            for block in range(config["windows_per_participant_per_length"]):
                end = last - timedelta(days=block * length)
                start = end - timedelta(days=length-1)
                case_id = "WQ2-" + digest([subject, start.isoformat(), end.isoformat()])[:20]
                if start < min(daily):
                    exclusions.append({"case_id":case_id,"subject_id":subject,"history_days":length,"block":block,
                                       "reason":"insufficient_calendar_history"})
                    continue
                rows = []
                for i in range(length):
                    day = start + timedelta(days=i)
                    source = daily.get(day)
                    rows.append({"day":i+1, "date":day.isoformat(), "weekday":day.isoweekday(),
                                 "phase":"current" if i >= length-current else "baseline" if i >= length-current-baseline else "history",
                                 "metrics":dict(source["metrics"]) if source else {m:None for m in UNITS},
                                 "quality_flags":list(source["quality_flags"]) if source else ["absent_calendar_day"],
                                 "missing_metrics":list(source["missing_metrics"]) if source else list(UNITS)})
                cases.append({"case_id":case_id,"subject_id":subject,"data_origin":"real_WearableQA_daily",
                              "history_days":length,"cold_start":length==current,"block":block,"start_date":start.isoformat(),"end_date":end.isoformat(),
                              "baseline_days":baseline,"current_days":current,"days":rows,
                              "context":{"timezone":None,"symptoms":None,"age":None,"goals":None,"wear_time":None},
                              "quality_notes":["Daily aggregates only; bed_time_std is already computed with unspecified lookback.",
                                               "No demographics, biomarkers, MCQs or full-cohort percentiles used.",
                                               "History lengths overlap; windows are not independent participants.",
                                               "Cold start retains only 14 days; prior-baseline comparisons remain insufficient."]})
    return cases, exclusions


def split(cases, config):
    result = make_split(cases, counts=tuple(config["split_counts"]), salt=config["split_salt"])
    result.update(version="c1-v2-participant-split-v1", rule="SHA256(salt, subject_id); quotas from config",
                  retrospective=False, historically_unexposed_test=False,
                  exposure_note="New C1 import, public benchmark previously exposed to unknown model training; not a pristine clinical cohort")
    result["id"] = digest({k:v for k,v in result.items() if k != "id"})
    return result
