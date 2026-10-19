"""Deterministic daily probes; canonical IDs deduplicate actual computations."""
from datetime import date, timedelta
import math
from statistics import mean, median, pstdev
from time import perf_counter_ns
from .wearableqa import UNITS, usable
from ..common import digest, require
from ..annotation.validation import validate

PROBE_SCHEMA = {"type":"object", "required":["probe_id","metric","window_days","offset_days","operation","comparison","required_fields","unit","min_coverage"],
                "properties":{"probe_id":{"type":"string"},"metric":{"type":"string","enum":list(UNITS)},
                              "window_days":{"type":"integer"},"offset_days":{"type":"integer"},
                              "operation":{"type":"string","enum":["mean","median","sd","slope","adjacent_change","mean_difference"]},
                              "comparison":{"type":"string","enum":["none","previous_28_days"]},
                              "required_fields":{"type":"array","items":{"type":"string"}},
                              "unit":{"type":"string"},"min_coverage":{"type":"number"}},"additionalProperties":False}


def make_probe(metric, days, operation, offset=0, min_coverage=0.7):
    unit = UNITS[metric] + ("/calendar_day" if operation == "slope" else "")
    spec = {"metric":metric,"window_days":days,"offset_days":offset,"operation":operation,
            "comparison":"previous_28_days" if operation=="mean_difference" else "none",
            "required_fields":["date", "metrics."+metric, "quality_flags"],"unit":unit,"min_coverage":min_coverage}
    return {"probe_id":"P2-"+digest(spec)[:20], **spec}


def catalog():
    # Fixed before observing labels; additional horizons are sensitivity checks, not independent evidence claims.
    return [make_probe(m,d,op) for m in UNITS for d in (7,14,28)
            for op in ("mean","median","sd","slope","adjacent_change","mean_difference")]


def validate_probe(probe):
    require(not validate(probe,PROBE_SCHEMA), "Probe JSON Schema invalid")
    require(1 <= probe["window_days"] <= 3660 and probe["offset_days"] >= 0, "invalid probe time range")
    require(0 < probe["min_coverage"] <= 1, "invalid minimum coverage")
    expected = make_probe(probe["metric"],probe["window_days"],probe["operation"],probe["offset_days"],probe["min_coverage"])
    require(probe == expected, "Probe identity/units/comparison do not match operation")


def execute(case, probe):
    validate_probe(probe)
    started = perf_counter_ns()
    end = date.fromisoformat(case["end_date"]) - timedelta(days=probe["offset_days"])
    start = end - timedelta(days=probe["window_days"]-1)
    metric = probe["metric"]
    dates = [r["date"] for r in case["days"]]
    require(len(dates)==len(set(dates)), "duplicate input dates")
    require(all(date.fromisoformat(d) <= date.fromisoformat(case["end_date"]) for d in dates), "future input row")
    bydate = {date.fromisoformat(r["date"]): r for r in case["days"]}

    def points(first,last):
        vals, refs, rejected = [], [], []
        for i in range((last-first).days+1):
            day = first+timedelta(days=i)
            row = bydate.get(day)
            value = row["metrics"].get(metric) if row else None
            ref = day.isoformat()+"."+metric
            if usable(metric,value):
                vals.append((i,float(value)));refs.append(ref)
            elif value is not None:
                rejected.append(ref)
        return vals,refs,rejected

    vals, refs, rejected = points(start,end)
    n, total = len(vals), probe["window_days"]
    result = {"case_id":case["case_id"],"probe_id":probe["probe_id"],"metric":metric,
              "start_date":start.isoformat(),"end_date":end.isoformat(),"unit":probe["unit"],
              "n":n,"expected_days":total,"coverage":n/total,"missing_or_unusable":total-n,
              "source_references":refs,"unusable_references":rejected,"value":None,"status":"INSUFFICIENT_INFORMATION",
              "quality_policy":"No imputation. Preserve raw values; exclude invalid/ambiguous device zeros. Minimum 70% per phase.",
              "comparison":None}
    good = start >= min(bydate) and n/total >= probe["min_coverage"]
    ys = [v for _,v in vals]
    if good:
        op = probe["operation"]
        if op == "mean": result["value"] = mean(ys)
        elif op == "median": result["value"] = median(ys)
        elif op == "sd": result["value"] = pstdev(ys) if n>=2 else None
        elif op == "slope" and n>=2:
            xs=[i for i,_ in vals];xb,yb=mean(xs),mean(ys)
            result["value"] = sum((x-xb)*(y-yb) for x,y in vals)/sum((x-xb)**2 for x in xs)
        elif op == "adjacent_change":
            vmap=dict(vals);changes=[abs(y-vmap[i-1]) for i,y in vals if i-1 in vmap]
            result["value"] = mean(changes) if changes else None
            result["adjacent_pairs"] = len(changes)
        elif op == "mean_difference":
            b_end=start-timedelta(days=1);b_start=b_end-timedelta(days=27)
            bv,brefs,brejected=points(b_start,b_end)
            result["comparison"]={"start_date":b_start.isoformat(),"end_date":b_end.isoformat(),"n":len(bv),
                                  "expected_days":28,"coverage":len(bv)/28,"source_references":brefs,"unusable_references":brejected}
            if b_start>=min(bydate) and len(bv)/28>=probe["min_coverage"]:
                result["value"]=mean(ys)-mean(y for _,y in bv)
        if result["value"] is not None:
            result["status"] = "COMPUTED"
    result["result_sha256"] = digest(result)
    result["elapsed_ns"] = perf_counter_ns()-started
    return result


def relation_index(knowledge, probes):
    pids={p["probe_id"] for p in probes}
    edges=[]
    for item in knowledge:
        for condition in item.get("conditions",[]):
            ids=condition["probe_ids"]
            require(set(ids)<=pids, "unknown condition probe")
            require(condition["role"] in {"necessary","optional","alternative","restriction","uncertain"}, "invalid condition role")
            require(condition["logic"] in {"ALL","ANY","UNKNOWN"}, "invalid condition connective")
            if condition["role"] in {"necessary","restriction"} or condition["logic"]=="ALL":
                require(bool(condition["source_citations"]), "source support required for necessity/AND")
            for pid in ids:
                edges.append({"knowledge_id":item["knowledge_id"],"condition_id":condition["condition_id"],
                              "probe_id":pid,"role":condition["role"],"logic":condition["logic"],
                              "use":condition.get("use","uncertain"),"dataset_support":condition.get("dataset_support","uncertain"),
                              "review_status":item["condition_review_status"]})
    return {"edges":edges,"unique_probes":len({e["probe_id"] for e in edges}),
            "knowledge_to_probes":{k["knowledge_id"]:sorted({e["probe_id"] for e in edges if e["knowledge_id"]==k["knowledge_id"]}) for k in knowledge},
            "probe_to_knowledge":{pid:sorted({e["knowledge_id"] for e in edges if e["probe_id"]==pid}) for pid in sorted(pids)}}
