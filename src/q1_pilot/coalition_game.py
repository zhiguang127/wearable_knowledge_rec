"""One cold cache per run; actual complete scorer computations counted."""
from time import perf_counter
from .interventions import merge,groups
from .scorers import features,score_features,target

class Game:
    def __init__(self,case,bg,candidates,policy,n=6,qoi='margin'):
        self.case,self.bg,self.candidates,self.policy,self.n,self.qoi=case,bg,list(candidates),policy,n,qoi
        self.source_groups=groups(n);self.cache={};self.requests=0;self.scorer_calls=0;self.scorer_seconds=0.
    def scores(self,mask):
        self.requests+=1
        if mask not in self.cache:
            t=perf_counter();f=features(merge(self.case,self.bg,self.source_groups,mask))
            s=score_features(f,self.candidates,self.policy)
            self.cache[mask]=(f,s);self.scorer_calls+=1;self.scorer_seconds+=perf_counter()-t
        return self.cache[mask][1]
    def value(self,mask): return target(self.scores(mask),self.qoi)
    def table(self): return [self.value(m) for m in range(1<<self.n)]
    def vector(self,rows):
        import numpy as np
        return np.asarray([self.value(self.mask(row)) for row in rows])
    def mask(self,row):
        if len(row)!=self.n or any(float(x) not in (0.,1.) for x in row): raise ValueError('binary source selectors required')
        return sum((1<<i) for i,x in enumerate(row) if float(x)==1.)
    def counters(self):
        return {'scorer_calls':self.scorer_calls,'unique_coalitions':len(self.cache),'query_requests':self.requests,
          'cache_hits':self.requests-self.scorer_calls,'cache_hit_rate':(self.requests-self.scorer_calls)/self.requests if self.requests else 0.,
          'scorer_seconds':self.scorer_seconds,'background_samples':1}
