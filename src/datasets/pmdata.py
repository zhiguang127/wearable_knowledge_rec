"""Pure PMData parsing and HMAC identities adapted from frozen P1; no download/write command."""
from datetime import date, datetime, timedelta
import hashlib
import hmac
import math
from ..common import read as read_json, digest


def opaque(key, text):
    return hmac.new(key, text.encode(), hashlib.sha256).hexdigest()[:16]

def number(value, maximum=None):
    if isinstance(value, bool):
        raise ValueError("Boolean is not a measurement")
    value = float(value)
    if not math.isfinite(value) or value < 0 or (maximum is not None and value > maximum):
        raise ValueError("Invalid measurement value")
    return value

def daily_metric(path, resting=False):
    result = {}
    if not path.exists():
        return result
    for row in read_json(path):
        day = date.fromisoformat(row["dateTime"][:10])
        if day in result:
            raise ValueError("Duplicate daily observation: " + path.name)
        value = row["value"]
        if resting:
            value = value["value"] if isinstance(value, dict) else value
        result[day] = None if value is None else number(value, 300 if resting else 1440)
    return result

def sleep_metric(path):
    """Only explicit main sleep; never turn timeInBed or nap sums into sleep."""
    grouped = {}
    if not path.exists():
        return {}
    for row in read_json(path):
        if row.get("mainSleep", row.get("isMainSleep")) is not True:
            continue
        start, end = datetime.fromisoformat(row["startTime"]), datetime.fromisoformat(row["endTime"])
        day = date.fromisoformat(row.get("dateOfSleep", end.date().isoformat()))
        asleep = row.get("minutesAsleep")
        projection = {"sleep_minutes": None if asleep is None else number(asleep, 1440),
                       "time_in_bed_minutes": None if row.get("timeInBed") is None else number(row["timeInBed"], 1440),
                       "sleep_start_clock": start.strftime("%H:%M:%S"),
                       "sleep_end_clock": end.strftime("%H:%M:%S"),
                       "sleep_start_day_offset": (start.date() - day).days,
                       "sleep_log_type": row.get("type"), "sleep_info_code": row.get("infoCode")}
        if projection["sleep_log_type"] not in {None, "classic", "stages"}:
            raise ValueError("Unknown source sleep log type")
        if projection["sleep_info_code"] is not None:
            projection["sleep_info_code"] = number(projection["sleep_info_code"], 100)
        grouped.setdefault(day, []).append((row.get("logId"), projection))
    result = {}
    for day, observations in grouped.items():
        distinct = {digest([log_id, projection]): projection for log_id, projection in observations}
        if len(distinct) == 1:
            result[day] = dict(next(iter(distinct.values())))
            result[day]["sleep_quality_flags"] = ["repeated_identical_selected_sleep_fields"] if len(observations) > 1 else []
        else:
            result[day] = {"sleep_quality_flags": ["ambiguous_main_sleep_all_sleep_fields_withheld"]}
    return result

def import_participant(path):
    metrics = {
        "resting_heart_rate_bpm": daily_metric(path / "resting_heart_rate.json", resting=True),
        "fitbit_lightly_active_minutes": daily_metric(path / "lightly_active_minutes.json"),
        "fitbit_moderately_active_minutes": daily_metric(path / "moderately_active_minutes.json"),
        "fitbit_very_active_minutes": daily_metric(path / "very_active_minutes.json"),
        "fitbit_sedentary_minutes": daily_metric(path / "sedentary_minutes.json"),
    }
    sleep = sleep_metric(path / "sleep.json")
    days = set(sleep).union(*(set(v) for v in metrics.values()))
    result = {}
    for day in sorted(days):
        result[day] = {name: values.get(day) for name, values in metrics.items()}
        result[day].update(sleep.get(day, {}))
    return result

METRICS = ["sleep_minutes", "time_in_bed_minutes", "sleep_start_clock", "sleep_end_clock",
           "sleep_start_day_offset", "sleep_log_type", "sleep_info_code", "resting_heart_rate_bpm", "fitbit_lightly_active_minutes",
           "fitbit_moderately_active_minutes", "fitbit_very_active_minutes", "fitbit_sedentary_minutes"]

OBSERVATION_METRICS = [x for x in METRICS if x not in {"sleep_start_day_offset", "sleep_log_type", "sleep_info_code"}]

def construct_cases(records, plan, key):
    cases, exclusions, mapping = [], [], []
    start = date.fromisoformat(plan["study_start"])
    length = plan["baseline_days"] + plan["current_days"]
    for participant, daily in sorted(records.items()):
        subject_id = "S" + opaque(key, participant)
        for block in range(plan["blocks_per_participant"]):
            first = start + timedelta(days=block * length)
            case_id = "P1-" + opaque(key, participant + ":" + str(block))
            rows = []
            for index in range(length):
                day = first + timedelta(days=index)
                values = {metric: daily.get(day, {}).get(metric) for metric in METRICS}
                flags = list(daily.get(day, {}).get("sleep_quality_flags", []))
                if values["resting_heart_rate_bpm"] == 0:
                    flags.append("zero_rhr_source_value_not_valid_for_health_interpretation")
                if values["sleep_info_code"] not in (None, 0):
                    flags.append("nonzero_sleep_info_code_raw_device_quality_unknown")
                rows.append({"day": index + 1, "weekday": day.isoweekday(),
                             "phase": "baseline" if index < plan["baseline_days"] else "current",
                             "metrics": values,
                             "quality_flags": flags,
                             "missing_metrics": [k for k, v in values.items() if v is None]})
            observed = {phase: sum(any(r["metrics"][m] is not None for m in OBSERVATION_METRICS)
                                   for r in rows if r["phase"] == phase)
                        for phase in ("baseline", "current")}
            included = min(observed.values()) >= plan["minimum_observed_days_per_phase"]
            mapping.append({"case_id": case_id, "participant": participant,
                            "start_date": first.isoformat(), "block": block, "included": included})
            if not included:
                exclusions.append({"case_id": case_id, "subject_id": subject_id,
                                   "reason": "insufficient_observed_days", "observed_days": observed})
                continue
            cases.append({"case_id": case_id, "subject_id": subject_id, "data_origin": "real_PMData",
                          "block": block, "baseline_days": plan["baseline_days"],
                          "current_days": plan["current_days"], "observed_days": observed,
                          "context": {"device": "Fitbit Versa 2 (dataset documentation)",
                                      "population": "Adult cohort, age range 25-60 in PMData publication section 3 (DOI: 10.1145/3339825.3394926); individual age not imported",
                                      "age": None, "symptoms": None, "diagnoses": None,
                                      "goals": None, "preferences": None, "medications": None,
                                      "work_schedule": None, "timezone": None,
                                      "wear_time": None, "device_change_history": None},
                          "quality_notes": ["Missing is unknown, not zero or absence.",
                                            "Device active-minute classes are not independently verified intensity.",
                                            "Sedentary minutes do not establish posture or continuous sitting.",
                                            "Local sleep clocks have unknown timezone/DST; no offset invented.",
                                            "Only explicit main sleep is imported; naps are excluded.",
                                            "A source RHR of zero is preserved but flagged as unusable for physiological interpretation; it does not mean a zero heartbeat.",
                                            "sleep_log_type and sleep_info_code are preserved source fields; classic logs do not establish availability of Light/Deep/REM stages.",
                                            "Repeated logs with identical logId and imported fields are collapsed; conflicting main sleep records are withheld and flagged.",
                                            "Participant metadata and self-reports have not been imported."],
                          "days": rows, "candidate_ids": plan["candidate_panel"]})
    return cases, exclusions, mapping
