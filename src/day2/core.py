"""Observed-only diagnostic ranker, acquisition and explicitly graded utility."""
from collections import defaultdict
from copy import deepcopy
from datetime import date
import math
import re
from statistics import mean

from ..common import require
from ..annotation.validation import validate
from .schemas import judgment_schema, source_schema

RANKER_VERSION="day2-lexical-descriptive-context-v1"
STOPWORDS=set("a an the and or to of in on for with my i me it is are as at be do not from that this you your can how what want recent recorded understand choose relevant general education particular assume".split())


def tokens(text):
    return set(re.findall(r"[a-z]+",text.lower()))-STOPWORDS


def metric_for(topic):
    return {"sleep":"sleep_duration","physical_activity":"steps"}[topic]


def find_probe(probes, metric, operation, days=14):
    found=[p["probe_id"] for p in probes if p["metric"]==metric and p["operation"]==operation and p["window_days"]==days and p["offset_days"]==0]
    require(len(found)==1,"ambiguous legal probe")
    return found[0]


def display_evidence(evidence, probes, end_date):
    """Bind display deterministically; no dates, raw daily rows or subject IDs sent."""
    definitions={p["probe_id"]:p for p in probes}
    end=date.fromisoformat(end_date)
    return [{"evidence_id":e["evidence_id"],"probe_id":e["probe_id"],
             **{k:definitions[e["probe_id"]][k] for k in ("metric","operation","window_days","comparison")},
             "status":e["status"],"value":e["value"],"unit":e["unit"],
             "start_day":(date.fromisoformat(e["start_time"])-end).days,"end_day":(date.fromisoformat(e["end_time"])-end).days,
             "missing_reason":e["missing_reason"],"result_hash":e["result_hash"]} for e in evidence]


class DiagnosticRanker:
    """No provider, reference labels or hidden-result parameter accepted."""
    def rank(self, query, observed_evidence, units, probes):
        require(set(query["candidate_ids"])=={u["knowledge_id"] for u in units},"ranker candidate mismatch")
        require(all(e["case_id"]==query["case_id"] for e in observed_evidence),"wrong-window observed evidence")
        require(len({e["probe_id"] for e in observed_evidence})==len(observed_evidence),"repeated evidence")
        legal={p["probe_id"]:p for p in probes}
        require(all(e["probe_id"] in legal for e in observed_evidence),"unregistered evidence")
        metric=metric_for(query["topic"])
        values={legal[e["probe_id"]]["operation"]:e["value"] for e in observed_evidence
                if legal[e["probe_id"]]["metric"]==metric and legal[e["probe_id"]]["window_days"]==14 and e["status"]=="COMPUTED"}
        valid_mean="mean" in values
        delta=values.get("mean_difference")
        magnitude=0.
        if valid_mean and delta is not None:
            current=values["mean"];previous=current-delta
            denominator=abs(current)+abs(previous)
            magnitude=abs(delta)/denominator if denominator else 0.
        q=tokens(query["topic"].replace("_"," ")+" "+(query["goal"] or ""))
        scored=[]
        for u in units:
            words=tokens(u["title"]+" "+u["text"])
            base=len(q&words)/len(q|words) if q|words else 0.
            score=base+.1*u["descriptive_context_link"]*int(valid_mean)+u["change_context_link"]*magnitude
            scored.append((u["knowledge_id"],score))
        scored.sort(key=lambda v:(-v[1],v[0]))
        return [(kid,score,1+sum(v>score for _,v in scored)) for kid,score in scored]


class PilotEnvironment:
    """Serialized observations; a backend object is not an adversarial sandbox."""
    def __init__(self,query,units,provider,probes):
        self.query=deepcopy(query);self.units=deepcopy(units);self._provider=provider;self.probes=deepcopy(probes)
        require(provider.case_id()==query["case_id"],"provider mismatch")
        self.ranker=DiagnosticRanker()

    def reset(self,initial_ids,budget=1):
        require(isinstance(budget,int) and not isinstance(budget,bool) and budget>=0,"invalid budget")
        require(len(initial_ids)==len(set(initial_ids)) and set(initial_ids)<=set(self._provider.probe_ids()),"bad initial actions")
        self.remaining=budget;self.observed={pid:self._provider.get(pid) for pid in initial_ids}
        return self.observation()

    def observation(self):
        evidence=[self.observed[pid] for pid in sorted(self.observed)]
        public={k:deepcopy(self.query[k]) for k in ("query_id","case_id","topic","query_basis","goal","candidate_ids")}
        return {"query":public,"observed_evidence":deepcopy(evidence),"remaining_budget":self.remaining,
                "ranking":self.ranker.rank(self.query,evidence,self.units,self.probes),"ranker_version":RANKER_VERSION}

    def available_actions(self,state):
        require(state==self.observation(),"stale/foreign state")
        return sorted(set(self._provider.probe_ids())-set(self.observed)) if self.remaining else []

    def step(self,pid):
        require(self.remaining>0 and pid in self._provider.probe_ids() and pid not in self.observed,"illegal or duplicate action/budget")
        self.observed[pid]=self._provider.get(pid);self.remaining-=1
        return self.observation(),1,self.remaining==0


def validate_judgment(output,task_id,units,evidence,linked_metric):
    errors=validate(output,judgment_schema(task_id,units,evidence))
    if errors:return errors
    byid={u["knowledge_id"]:u for u in units};byev={e["evidence_id"]:e for e in evidence}
    ids=[j["knowledge_id"] for j in output["judgments"]]
    if len(ids)!=len(set(ids)) or set(ids)!=set(byid):errors.append("judgment_inventory_mismatch")
    for j in output["judgments"]:
        unit=byid[j["knowledge_id"]]
        if len(j["evidence_ids"])!=len(set(j["evidence_ids"])):errors.append("duplicate_reference")
        if not set(j["source_span_ids"])<={s["span_id"] for s in unit["source_spans"]} or not j["source_span_ids"]:
            errors.append("wrong_unit_or_empty_source_span")
        if j["basis"]=="UNDETERMINED" and j["grade"] is not None:errors.append("unknown_must_have_null_grade")
        if j["grade"] is None and j["basis"]!="UNDETERMINED":errors.append("null_grade_requires_unknown_basis")
        if j["basis"]=="TOPIC_OR_GOAL_ONLY" and j["evidence_ids"]:errors.append("topic_only_claim_has_personal_citations")
        if j["basis"]=="PERSONAL_EVIDENCE_CONTEXT":
            if not j["evidence_ids"]:errors.append("personal_claim_without_evidence")
            if not unit["descriptive_context_link"]:errors.append("personal_claim_outside_preregistered_descriptive_link")
            if any(byev[eid]["status"]!="COMPUTED" for eid in j["evidence_ids"]):errors.append("insufficient_result_used_as_positive_support")
            # Other measured constructs cannot be silently turned into a topic-specific state.
            if not any(e["metric"]==linked_metric for eid in j["evidence_ids"] if (e:=byev[eid])):
                errors.append("unrelated_measurement_used_as_personal_support")
    return sorted(set(errors))


def source_errors(output,unit):
    errors=validate(output,source_schema(unit))
    if errors:return errors
    if not output["meaning_preserved"] or not output["standalone_context_sufficient"]:errors.append("source_completeness_disputed")
    if output["hard_gate_assessable"]:errors.append("new_hard_gate_claim_requires_separate_semantic_adjudication")
    return errors


def graded_utility(ranking,grades,k=5):
    """Fixed reference projection and expected DCG within ties; unknown != zero."""
    require(len({kid for kid,_,_ in ranking})==len(ranking),"duplicate ranking")
    require(set(grades)<={kid for kid,_,_ in ranking},"foreign reference")
    require(all(g is None or type(g) is int and 0<=g<=3 for g in grades.values()),"invalid grade")
    known={kid:g for kid,g in grades.items() if g is not None}
    if len(known)<2 or len(set(known.values()))<2:return None
    groups=defaultdict(list)
    for kid,score,_ in ranking:
        if kid in known:groups[score].append(2**known[kid]-1)
    dcg=0.;pos=0
    for score in sorted(groups,reverse=True):
        for _ in groups[score]:
            if pos<k:dcg+=mean(groups[score])/math.log2(pos+2)
            pos+=1
    ideal=sorted((2**g-1 for g in known.values()),reverse=True)
    idcg=sum(v/math.log2(i+2) for i,v in enumerate(ideal[:k]))
    return dcg/idcg if idcg else None


def reference_utility(ranking,reference,*,required_kind):
    require(reference["kind"]==required_kind,"Silver/Gold provenance mismatch")
    if reference["annotation_status"]!="ACCEPTED":return None
    return graded_utility(ranking,reference["grades"])


def pairs_from_grades(grades):
    result={}
    keys=sorted(grades)
    for i,a in enumerate(keys):
        for b in keys[i+1:]:
            ga,gb=grades[a],grades[b]
            result[a+"|"+b]=None if ga is None or gb is None else (ga>gb)-(ga<gb)
    return result


def expected_gain(before,outcomes):
    """A computation only: probabilities must be externally justified, never invented."""
    require(outcomes and abs(sum(p for p,u in outcomes)-1)<1e-10,"probabilities must sum to one")
    require(all(math.isfinite(p) and p>=0 and math.isfinite(u) for p,u in outcomes),"invalid outcome distribution")
    require(math.isfinite(before),"invalid initial utility")
    return sum(p*u for p,u in outcomes)-before


def ranking_relations(ranking):
    """An order/tie change is distinct from a mere score change."""
    scores={kid:score for kid,score,_ in ranking}
    keys=sorted(scores)
    return {(a,b):(scores[a]>scores[b])-(scores[a]<scores[b]) for i,a in enumerate(keys) for b in keys[i+1:]}
