"""Observation-only minimal mechanism; one step path for all acquired probes."""
from copy import deepcopy
from statistics import mean
from ..common import require
from ..day2.core import find_probe, metric_for

VERSION='day4-signed-descriptive-mechanism-v01'


def normalized_change(current,delta):
    previous=current-delta
    require(current>=0 and previous>=-1e-10,'incompatible nonnegative mean/comparison')
    denominator=abs(current)+abs(previous)
    return delta/denominator if denominator else 0.


class MechanismRanker:
    def rank(self,query,observed_evidence,candidate_knowledge,probes):
        require(set(query['candidate_ids'])=={u['knowledge_id'] for u in candidate_knowledge},'ranker candidates')
        require(all(e['case_id']==query['case_id'] for e in observed_evidence),'wrong-case observation')
        require(len({e['probe_id'] for e in observed_evidence})==len(observed_evidence),'duplicate observation')
        definitions={p['probe_id']:p for p in probes}
        require(all(e['probe_id'] in definitions for e in observed_evidence),'unregistered evidence')
        metric=metric_for(query['topic']);values={}
        for e in observed_evidence:
            p=definitions[e['probe_id']]
            if p['metric']==metric and e['status']=='COMPUTED':values[p['operation'],p['window_days']]=e['value']
        zs=[normalized_change(values['mean',days],v) for (op,days),v in values.items()
            if op=='mean_difference' and ('mean',days) in values]
        scores=[]
        for kid in query['candidate_ids']:
            link=query['links'][kid]
            score=mean(link['direction']*z+link['magnitude']*abs(z) for z in zs) if zs else 0.
            scores.append((kid,score))
        scores.sort(key=lambda x:(-x[1],x[0]))
        return [(kid,s,1+sum(other>s for _,other in scores)) for kid,s in scores]


class Environment:
    def __init__(self,query,units,provider,probes):
        require(provider.case_id()==query['case_id'],'provider case mismatch')
        self.query=deepcopy(query);self.units=deepcopy(units);self.__provider=provider
        self.probes=deepcopy(probes);self.ranker=MechanismRanker()

    def reset(self,initial_ids,budget=1):
        require(type(budget) is int and budget>=0,'invalid budget')
        require(len(initial_ids)==len(set(initial_ids)) and set(initial_ids)<=set(self.__provider.probe_ids()),'invalid seed action')
        self.remaining=budget;self.observed={pid:self.__provider.get(pid) for pid in initial_ids}
        return self.observation()

    def observation(self):
        evidence=[self.observed[k] for k in sorted(self.observed)]
        definitions={p['probe_id']:p for p in self.probes}
        resolved=any(e['status']=='COMPUTED' and definitions[e['probe_id']]['metric']==metric_for(self.query['topic']) and
                     definitions[e['probe_id']]['operation']=='mean_difference' for e in evidence)
        return {'query':deepcopy(self.query),'observed_evidence':deepcopy(evidence),'remaining_budget':self.remaining,
                'ranking':self.ranker.rank(self.query,evidence,self.units,self.probes),
                'mechanism_comparison_resolved':resolved,'ranker_version':VERSION}

    def available_actions(self,state):
        require(state==self.observation(),'stale observation')
        return sorted(set(self.__provider.probe_ids())-set(self.observed)) if self.remaining else []

    def step(self,pid):
        require(self.remaining>0 and pid in self.__provider.probe_ids() and pid not in self.observed,'invalid/repeated/budget action')
        self.observed[pid]=self.__provider.get(pid);self.remaining-=1
        return self.observation(),1,self.remaining==0


def arm_actions(pair,probes):
    metric=metric_for(pair['topic'])
    seeds=[find_probe(probes,metric,'mean',7),find_probe(probes,metric,'mean',14),find_probe(probes,'rhr','mean',14)]
    return seeds,{'C':find_probe(probes,metric,'mean_difference',14),
                  'D':find_probe(probes,metric,'mean_difference',7),
                  'D0':find_probe(probes,'rhr','mean_difference',14)}
