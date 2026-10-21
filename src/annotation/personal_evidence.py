"""Independent deterministic evidence discovery; knowledge mappings never gate access."""
from copy import deepcopy
from datetime import date
from ..common import digest, require
from ..datasets.probes import execute, validate_probe

VERSION = "c1-v2.2-full-personal-evidence-v2"


class EvidenceProvider:
    def __init__(self, case, probes):
        self.case = case
        self.probes = {p["probe_id"]: p for p in probes}
        require(len(self.probes) == len(probes), "duplicate registry probe")
        for probe in probes:
            validate_probe(probe)
        require(all(d["date"] <= case["end_date"] for d in case["days"]), "future data in evidence provider")
        self.catalog_sha256 = digest(probes)
        self.case_sha256 = digest(case)
        self.results = {}

    def list_probes(self):
        return deepcopy(list(self.probes.values()))

    def execute_probe(self, probe_id):
        require(probe_id in self.probes, "probe not in the admissible registry")
        if probe_id not in self.results:
            self.results[probe_id] = execute(self.case, self.probes[probe_id])
        return deepcopy(self.results[probe_id])

    def compute_all(self):
        return [self.execute_probe(pid) for pid in self.probes]

    def identity(self):
        return {"version": VERSION, "case_sha256": self.case_sha256,
                "catalog_sha256": self.catalog_sha256, "probe_count": len(self.probes)}


def compact_catalog(probes):
    """Full registry, factored fields. This is serialization, never candidate pruning."""
    metrics = sorted({p["metric"] for p in probes})
    operations = sorted({p["operation"] for p in probes})
    comparisons = sorted({p["comparison"] for p in probes})
    fields = ["probe_id", "metric_index", "window_days", "offset_days", "operation_index", "comparison_index", "min_coverage"]
    units = [{op: next(p["unit"] for p in probes if p["metric"] == m and p["operation"] == op)
              for op in operations if any(p["metric"] == m and p["operation"] == op for p in probes)} for m in metrics]
    constants = {field: probes[0][field] for field in ("offset_days", "min_coverage")
                 if probes and all(p[field] == probes[0][field] for p in probes)}
    fields = [field for field in fields if field not in constants]
    complete_rows = [{"probe_id":p["probe_id"], "metric_index":metrics.index(p["metric"]),
                     "window_days":p["window_days"], "offset_days":p["offset_days"],
                     "operation_index":operations.index(p["operation"]), "comparison_index":comparisons.index(p["comparison"]),
                     "min_coverage":p["min_coverage"]} for p in probes]
    return {"schema": fields,
            "rows": [[p[field] for field in fields] for p in complete_rows], "constants":constants,
            "metrics": metrics, "operations": operations, "comparisons": comparisons, "units_by_metric_operation": units,
            "required_fields": "date, metrics.<metric>, quality_flags",
            "catalog_sha256": digest(probes), "count": len(probes)}


def compact_evidence(case, probes, evidence):
    """All results, including nulls, retaining exact numeric precision and identities."""
    byid = {e["probe_id"]: e for e in evidence}
    require(len(evidence) == len(probes) and set(byid) == {p["probe_id"] for p in probes}, "full evidence packet is incomplete or duplicated")
    fields = ["probe_index", "value", "n", "expected_days", "status_index", "result_sha256", "comparison_n"]
    statuses = ["COMPUTED", "INSUFFICIENT_INFORMATION"]
    rows = [[i, e["value"], e["n"], e["expected_days"], statuses.index(e["status"]), e["result_sha256"],
             e["comparison"]["n"] if e["comparison"] else None] for i,p in enumerate(probes) for e in [byid[p["probe_id"]]]]
    intervals = {}
    for p in probes:
        e = byid[p["probe_id"]]
        intervals[(p["window_days"],p["offset_days"])] = {"window_days":p["window_days"], "offset_days":p["offset_days"],
            "start_date":e["start_date"], "end_date":e["end_date"]}
    return {"version": VERSION, "case_end_date": case["end_date"],
            "case_start_date": min(d["date"] for d in case["days"]),
            "registry": compact_catalog(probes), "result_schema": fields, "results": rows, "statuses":statuses,
            "exact_time_intervals": list(intervals.values()),
            "comparison_rule": "previous_28_days ends the day before start; each phase needs >=70% coverage. Insufficient results remain null.",
            "context": case.get("context", {}),
            "limitations": ["Date clipping does not establish the upstream lookback of bed_time_std.",
                            "Device aggregates cannot establish unobserved symptoms, intensity, clock events or nutrition."]}


def balanced_pairs(cases, knowledge, partitions, max_pairs=120, salt="c1-v2.2-independent-plan-v1"):
    """Round robin across topics; never sort by probe mappings, values or labels."""
    require(max_pairs > 0 and max_pairs % 2 == 0, "paired plan needs a positive even pair count")
    train = set(partitions["partitions"]["train"]["subject_ids"])
    bysubject = {}
    for case in cases:
        if case["subject_id"] in train and case["block"] == 0 and case["history_days"] in (14, 42):
            bysubject.setdefault(case["subject_id"], {})[case["history_days"]] = case
    subjects = sorted([s for s, group in bysubject.items() if set(group) == {14, 42}], key=lambda s: digest([salt, s]))
    groups = {}
    for item in knowledge:
        groups.setdefault(item["topic"], []).append(item)
    require(bool(groups), "knowledge pool is empty")
    for topic in groups:
        groups[topic].sort(key=lambda k: digest([salt, k["knowledge_id"]]))
    topics = sorted(groups)
    require(max_pairs // 2 <= len(subjects), "plan would repeat participants")
    pairs = []
    for i, subject in enumerate(subjects[:max_pairs // 2]):
        topic = topics[i % len(topics)]
        item = groups[topic][(i // len(topics)) % len(groups[topic])]
        pairs.extend((bysubject[subject][h], item) for h in (14, 42))
    return pairs
