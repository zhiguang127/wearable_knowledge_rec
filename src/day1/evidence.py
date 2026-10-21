"""Backend-only canonical evidence, bound to the frozen case and probe computation."""
from copy import deepcopy
from datetime import date

from ..common import digest, require
from ..annotation.personal_evidence import EvidenceProvider as LegacyProvider
from ..annotation.validation import validate
from .schemas import EVIDENCE

VERSION = "day1-evidence-id-binding-v1"


class EvidenceProvider:
    """Never pass this object or its store to a policy; pass Observation JSON only.

    Supplied precomputed results are compared to deterministic recomputation on
    access. No historical responses, result rows, or failed citations are edited.
    """

    def __init__(self, case, probes, precomputed=None):
        self.__case = deepcopy(case)
        self.__provider = LegacyProvider(self.__case, deepcopy(probes))
        self.__precomputed = deepcopy(precomputed)
        if precomputed is not None:
            require(len(precomputed) == len({r["probe_id"] for r in precomputed}), "duplicate stored result")
            require({r["probe_id"] for r in precomputed} == set(self.__provider.probes), "incomplete stored result pool")
            self.__precomputed = {r["probe_id"]: r for r in precomputed}
        self.__cache = {}

    def probe_ids(self):
        return sorted(self.__provider.probes)

    def case_id(self):
        return self.__case["case_id"]

    def probe_definitions(self):
        return self.__provider.list_probes()

    def get(self, probe_id):
        actual = self.__provider.execute_probe(probe_id)
        if self.__precomputed is not None:
            supplied = self.__precomputed[probe_id]
            strip = lambda r: {k: v for k, v in r.items() if k != "elapsed_ns"}
            require(strip(supplied) == strip(actual), "precomputed value/unit/window/source/hash mismatch")
        if probe_id not in self.__cache:
            core = {"case_id": actual["case_id"], "probe_id": probe_id, "status": actual["status"],
                    "value": actual["value"], "unit": actual["unit"],
                    "start_time": actual["start_date"], "end_time": actual["end_date"],
                    "missing_reason": None if actual["status"] == "COMPUTED" else "INSUFFICIENT_VALID_DAYS_OR_COMPARISON_HISTORY",
                    "source_ref": {"case_sha256": self.__provider.case_sha256,
                                   "source_references": actual["source_references"],
                                   "comparison": actual["comparison"]},
                    "result_hash": actual["result_sha256"],
                    "computation_hash": digest({"version": VERSION, "probe": self.__provider.probes[probe_id],
                                                "case_hash": self.__provider.case_sha256,
                                                "result_hash": actual["result_sha256"]})}
            core["evidence_id"] = "E1-" + digest(core)
            require(not validate(core, EVIDENCE), "canonical evidence schema")
            require(date.fromisoformat(core["start_time"]) <= date.fromisoformat(core["end_time"]) <=
                    date.fromisoformat(self.__case["end_date"]), "evidence outside observation time")
            self.__cache[probe_id] = core
        return deepcopy(self.__cache[probe_id])

    def all(self):
        """Offline annotation/teacher/diagnostic capability only."""
        return [self.get(pid) for pid in self.probe_ids()]

    def bind(self, evidence_ids):
        require(len(evidence_ids) == len(set(evidence_ids)), "duplicate evidence selection")
        pool = {e["evidence_id"]: e for e in self.all()}
        require(set(evidence_ids) <= set(pool), "unknown or wrong-window evidence ID")
        return [deepcopy(pool[eid]) for eid in evidence_ids]

    def verify_bound(self, evidence):
        require(not validate(evidence, EVIDENCE), "invalid bound evidence schema")
        require(evidence == self.get(evidence["probe_id"]), "value/unit/time/source/hash binding mismatch")
