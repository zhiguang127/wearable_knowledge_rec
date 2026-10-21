"""Backend acquisition protocol and a fixed, parameter-free condition ranker.

The policy boundary is serialized Observation/action data. This backend object,
EvidenceProvider, case rows and reference labels are never policy inputs. This
module is a protocol implementation, not an adversarial Python sandbox.
"""
from copy import deepcopy
from time import perf_counter_ns

from ..common import digest, require
from ..annotation.validation import validate
from .contracts import condition_truth, public_query, validate_knowledge
from .schemas import KNOWLEDGE

RANKER_VERSION = "day1-equal-condition-match-v1"


class ConditionRanker:
    """Equal predeclared weights; unknown contributes zero, not a violation.

    Scores describe observed matches, not probabilities or reference verdicts.
    Tied scores share a rank; knowledge_id fixes serialization order only.
    """

    def rank(self, query, observed_evidence, candidate_knowledge):
        query = public_query(query)
        ids = [k["knowledge_id"] for k in candidate_knowledge]
        require(len(ids) == len(set(ids)) and set(ids) == set(query["candidate_ids"]), "ranker fixed candidate set mismatch")
        observed = {e["probe_id"]: e for e in observed_evidence}
        require(len(observed) == len(observed_evidence), "duplicate observed evidence")
        require(all(e["case_id"] == query["case_id"] for e in observed_evidence), "ranker wrong-window evidence")
        scored = []
        for item in candidate_knowledge:
            require(not validate(item, KNOWLEDGE), "ranker knowledge schema invalid")
            require(item["semantic_review"]["status"] == "VERIFIED" and
                    all(c["semantic_review"]["status"] == "VERIFIED" and
                        all(p["semantic_review"]["status"] == "VERIFIED" for p in c["predicates"]) for c in item["conditions"]),
                    "ranker accepts verified conditions only")
            values = [condition_truth(c, observed) for c in item["conditions"]]
            score = sum(0 if v is None else 1 if v else -1 for v in values) / max(1, len(values))
            scored.append((item["knowledge_id"], score))
        scored.sort(key=lambda x: (-x[1], x[0]))
        return [(kid, score, 1 + sum(s > score for _, s in scored)) for kid, score in scored]


class AcquisitionEnvironment:
    """One fixed query per backend; no label or teacher input accepted."""

    def __init__(self, query, candidate_knowledge, provider, *, source_items, initial_probe_ids=(), ranker=None):
        self.__query = deepcopy(public_query(query))
        require(query["case_id"] == provider.case_id(), "query/provider window mismatch")
        self.__candidates = deepcopy(candidate_knowledge)
        self.__provider = provider
        self.__ranker = ranker or ConditionRanker()
        self.__initial = tuple(initial_probe_ids)
        require(len(self.__initial) == len(set(self.__initial)) and set(self.__initial) <= set(provider.probe_ids()), "invalid initial evidence")
        # Source items come from the already hash-verified knowledge release.
        for k in self.__candidates:
            require(not validate(k, KNOWLEDGE), "unvalidated candidate metadata")
            require(k["knowledge_id"] in source_items and not validate_knowledge(
                k, provider.probe_definitions(), source_items[k["knowledge_id"]]), "invalid source-bound conditions")
            require(k["semantic_review"]["status"] == "VERIFIED", "unreviewed candidate cannot enter ranker")
            for c in k["conditions"]:
                require(c["semantic_review"]["status"] == "VERIFIED" and
                        all(p["semantic_review"]["status"] == "VERIFIED" for p in c["predicates"]), "unreviewed predicate or relation")
        self.__active = False

    def reset(self, query_id, budget):
        require(query_id == self.__query["query_id"], "unknown query")
        require(isinstance(budget, int) and not isinstance(budget, bool) and budget >= 0, "invalid probe budget")
        self.__budget = budget
        self.__remaining = budget
        self.__observed = {pid: self.__provider.get(pid) for pid in self.__initial}
        self.__active = True
        return self.__observation()

    def __observation(self):
        observed = [self.__observed[p] for p in sorted(self.__observed)]
        # Deliberate allowlist. Extra source dictionaries/legacy labels stay private.
        query = {k: deepcopy(self.__query[k]) for k in ("query_id", "case_id", "topic", "goal", "candidate_ids")}
        candidates = [{k: deepcopy(item[k]) for k in ("knowledge_id", "topic", "text", "criteria_kind", "conditions", "logic", "role")}
                      for item in self.__candidates]
        return {"query": query, "observed_evidence": deepcopy(observed), "candidates": candidates,
                "ranking": self.__ranker.rank(query, observed, self.__candidates),
                "remaining_budget": self.__remaining, "spent_probes": self.__budget - self.__remaining,
                "unobserved_state": "not_yet_acquired", "ranker_version": RANKER_VERSION}

    def available_actions(self, state):
        require(self.__active, "reset required")
        state = {k: v for k, v in state.items() if k != "last_acquisition_latency_ns"}
        require(state == self.__observation(), "stale or foreign state")
        if self.__remaining == 0:
            return []
        return sorted(set(self.__provider.probe_ids()) - set(self.__observed))

    def step(self, probe_id):
        require(self.__active, "reset required")
        require(self.__remaining > 0, "probe budget exhausted")
        require(probe_id in self.__provider.probe_ids() and probe_id not in self.__observed, "duplicate or illegal action")
        started = perf_counter_ns()
        evidence = self.__provider.get(probe_id)
        self.__observed[probe_id] = evidence
        self.__remaining -= 1
        observation = self.__observation()  # Always rerun the same ranker.
        observation["last_acquisition_latency_ns"] = perf_counter_ns() - started
        # Transient latency is not part of state identity for available_actions.
        return observation, 1, self.__remaining == 0 or len(self.__observed) == len(self.__provider.probe_ids())

    def identity(self):
        return digest({"query": self.__query, "knowledge": self.__candidates,
                       "initial_probe_ids": self.__initial, "ranker_version": RANKER_VERSION})
