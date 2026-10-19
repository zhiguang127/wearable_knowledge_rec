"""Independent raw-to-release check, separate from the migrated PMData importer."""
from collections import Counter
from datetime import date, datetime, timedelta
import hashlib
import hmac
from pathlib import Path
from ..common import inside, read, rows, sha, require

NUMERIC = {"resting_heart_rate_bpm": "resting_heart_rate.json",
           "fitbit_lightly_active_minutes": "lightly_active_minutes.json",
           "fitbit_moderately_active_minutes": "moderately_active_minutes.json",
           "fitbit_very_active_minutes": "very_active_minutes.json",
           "fitbit_sedentary_minutes": "sedentary_minutes.json"}
SLEEP = ("sleep_minutes", "time_in_bed_minutes", "sleep_start_clock", "sleep_end_clock",
         "sleep_start_day_offset", "sleep_log_type", "sleep_info_code")


def validate_source(root, cases):
    root = Path(root)
    release, raw = root / "data/releases/p1-v2", root / "data/raw/pmdata"
    manifest = read(raw / "source_manifest.json")
    audit = read(release / "import_audit.json")
    plan = read(release / "sampling_plan.json")
    download_plan = root / "configs/legacy_sampling_plan.json"
    require(manifest["source"] == "https://osf.io/vx4bk/" and manifest["real_records"] is True, "official real provenance absent")
    require("NonCommercial" in manifest["license_text"] and manifest["license_text"] == audit["license"], "license chain differs")
    require(sha(raw / "source_manifest.json") == audit["source_manifest_sha256"], "raw manifest changed")
    require(manifest["sampling_plan_sha256"] == sha(download_plan), "download-plan SHA mismatch")
    require(read(download_plan) == plan, "download and frozen sampling plans differ semantically")
    require(len(manifest["participants"]) == len(set(manifest["participants"])) == 16, "raw participant inventory differs")
    expected_paths = {p + "/fitbit/" + name for p in manifest["participants"] for name in plan["metrics"]}
    files = manifest["files"]
    require(len(files) == len(expected_paths) == 96 and {r["path"] for r in files} == expected_paths, "raw inventory incomplete")
    statuses = Counter()
    for record in files:
        path = inside(raw, record["path"])
        statuses[record["status"]] += 1
        if record["status"] == "downloaded":
            require(record["url"].startswith("https://osf.io/download/"), "unexpected raw source URL")
            require(sha(path) == record["sha256"] and path.stat().st_size == record["bytes"], "raw bytes/hash mismatch")
        else:
            require(record["status"] == "absent_at_source" and not path.exists(), "source absence was filled or status unknown")
    require(statuses == {"downloaded": 93, "absent_at_source": 3}, "raw counts differ")
    require(sorted(r["sha256"] for r in files if r["status"] == "downloaded") == audit["source_file_hashes"], "raw hashes differ from import audit")
    mapping_rows = read(root / "local/identity/mapping-p1-v2.json")
    mapping = {m["case_id"]: m for m in mapping_rows}
    require(len(mapping) == len(mapping_rows) == len(cases) == 48, "mapping is incomplete or duplicated")
    require(set(mapping) == {c["case_id"] for c in cases}, "mapping/release case mismatch")
    key = (root / "local/identity/pseudonym.key").read_bytes()
    require(len(key) >= 32, "HMAC key unavailable or too short")
    seen, missing, flags, blocks = set(), Counter(), Counter(), Counter()
    numeric_checked = sleep_dates = sleep_fields_checked = 0
    for case in cases:
        m = mapping[case["case_id"]]
        participant = m["participant"]
        opaque = lambda text: hmac.new(key, text.encode(), hashlib.sha256).hexdigest()[:16]
        require(participant in manifest["participants"] and m["included"] is True, "invalid mapped source participant")
        require(case["subject_id"] == "S" + opaque(participant) and case["case_id"] == "P1-" + opaque(participant + ":" + str(m["block"])), "pseudonymization mismatch")
        require(case["data_origin"] == "real_PMData" and case["block"] == m["block"], "non-real or wrong block")
        first = date.fromisoformat(m["start_date"])
        require(first == date.fromisoformat(plan["study_start"]) + timedelta(days=m["block"] * 42), "source window moved")
        require(case["baseline_days"] == 28 and case["current_days"] == 14 and len(case["days"]) == 42, "window shape differs")
        require(case["candidate_ids"] == plan["candidate_panel"], "fixed candidate panel changed")
        blocks[(case["subject_id"], case["block"])] += 1
        directory = raw / participant / "fitbit"
        source = {}
        for metric, name in NUMERIC.items():
            path = directory / name
            values = read(path) if path.exists() else []
            source[metric] = {v["dateTime"][:10]: v["value"].get("value") if isinstance(v["value"], dict) else v["value"] for v in values}
            require(len(source[metric]) == len(values), "duplicate source daily measurement")
        sleeps = {}
        for s in read(directory / "sleep.json"):
            if s.get("mainSleep", s.get("isMainSleep")) is True:
                start, end = datetime.fromisoformat(s["startTime"]), datetime.fromisoformat(s["endTime"])
                day = s.get("dateOfSleep", end.date().isoformat())
                projection = (s.get("minutesAsleep"), s.get("timeInBed"), start.strftime("%H:%M:%S"),
                              end.strftime("%H:%M:%S"), (start.date() - date.fromisoformat(day)).days,
                              s.get("type"), s.get("infoCode"))
                sleeps.setdefault(day, []).append((s.get("logId"), projection))
        observed = Counter()
        for index, row in enumerate(case["days"], 1):
            day = first + timedelta(days=index - 1)
            identity = (participant, day)
            require(identity not in seen, "overlapping participant windows")
            seen.add(identity)
            phase = "baseline" if index <= 28 else "current"
            require(row["day"] == index and row["phase"] == phase and row["weekday"] == day.isoweekday(), "time alignment mismatch")
            values = row["metrics"]
            require(set(values) == set(NUMERIC) | set(SLEEP), "metric inventory changed")
            for metric, entries in source.items():
                value = entries.get(day.isoformat())
                require(values[metric] == (None if value is None else float(value)), "numeric source mismatch")
                numeric_checked += 1
            logs = sleeps.get(day.isoformat(), [])
            distinct = set(logs)
            expected_flags = []
            if len(distinct) == 1:
                expected_sleep = next(iter(distinct))[1]
                if len(logs) > 1:
                    expected_flags.append("repeated_identical_selected_sleep_fields")
            else:
                expected_sleep = (None,) * len(SLEEP)
                if distinct:
                    expected_flags.append("ambiguous_main_sleep_all_sleep_fields_withheld")
            require(tuple(values[k] for k in SLEEP) == expected_sleep, "sleep source projection mismatch")
            if values["resting_heart_rate_bpm"] == 0:
                expected_flags.append("zero_rhr_source_value_not_valid_for_health_interpretation")
            if values["sleep_info_code"] not in (None, 0):
                expected_flags.append("nonzero_sleep_info_code_raw_device_quality_unknown")
            require(row["quality_flags"] == expected_flags, "source quality flags differ")
            expected_missing = [k for k, v in values.items() if v is None]
            require(row["missing_metrics"] == expected_missing, "missingness differs")
            missing.update(expected_missing); flags.update(expected_flags)
            observation_fields = set(values) - {"sleep_start_day_offset", "sleep_log_type", "sleep_info_code"}
            observed[phase] += any(values[k] is not None for k in observation_fields)
            sleep_dates += 1; sleep_fields_checked += len(SLEEP)
        require(dict(observed) == case["observed_days"] and min(observed.values()) >= 7, "inclusion rule changed")
    require(all(blocks[(s, b)] == 1 for s in {c["subject_id"] for c in cases} for b in range(3)), "participant block coverage differs")
    require(dict(missing) == audit["missing_counts"] and dict(flags) == audit["quality_flag_counts"], "import-audit quality counts disagree")
    return {"status": "PASS", "raw_downloaded": 93, "raw_absent_at_source": 3,
            "participants": len({c["subject_id"] for c in cases}), "windows": len(cases),
            "daily_rows": len(seen), "numeric_source_fields_checked": numeric_checked,
            "sleep_dates_checked": sleep_dates, "sleep_source_fields_checked": sleep_fields_checked,
            "quality_flag_counts": dict(flags), "hmac_identities_verified": len(cases),
            "sampling_plan_bytes_differ": sha(download_plan) != sha(release / "sampling_plan.json"),
            "sampling_plan_semantically_equal": True, "license": "CC-BY-NC-4.0"}
