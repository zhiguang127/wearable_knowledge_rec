"""Separate estimands and participant-clustered uncertainty."""
from copy import deepcopy
import math
import random
from statistics import mean
from .scorers import score,target,order,usable

def metrics(phi,reference,delta,tol=1e-8):
    nonzero=[i for i,v in enumerate(reference) if abs(v)>tol]
    sign=lambda v:1 if v>tol else -1 if v<-tol else 0
    strongest=max(map(abs,reference),default=0.)
    exact_top={i for i,v in enumerate(reference) if abs(abs(v)-strongest)<=tol}
    top=max(range(len(phi)),key=lambda i:abs(phi[i]))
    return {'mae':mean(abs(a-b) for a,b in zip(phi,reference)),
      'sign_agreement_nonzero':mean(sign(phi[i])==sign(reference[i]) for i in nonzero) if nonzero else None,
      'top_source_hit':float(top in exact_top) if strongest>tol else None,
      'efficiency_residual':abs(sum(phi)-delta),'max_abs_error':max(abs(a-b) for a,b in zip(phi,reference))}

def behavior(case,candidates,policy):
    original=score(case,candidates,policy);out=[]
    for kind in ('history_minus60','current_minus60','clock_alternating','reverse_current','unused_context'):
        c=deepcopy(case)
        for d in c['days']:
            if usable(d) and ((kind=='history_minus60' and d['phase']=='baseline') or (kind=='current_minus60' and d['phase']=='current')):
                d['metrics']['sleep_minutes']=max(0.,d['metrics']['sleep_minutes']-60)
            if kind=='clock_alternating' and d['phase']=='current' and usable(d) and d['metrics'].get('sleep_start_clock'):
                from .scorers import clock_minutes
                m=(clock_minutes(d['metrics']['sleep_start_clock'])+(120 if d['day']%2 else -120))%1440
                d['metrics']['sleep_start_clock']=f'{int(m//60):02}:{int(m%60):02}:{int((m%1)*60):02}'
        if kind=='reverse_current':
            old=[deepcopy(d) for d in c['days'] if d['phase']=='current'][::-1]
            for d,s in zip(c['days'][28:],old):
                for k in ('metrics','quality_flags','missing_metrics'): d[k]=deepcopy(s[k])
        if kind=='unused_context': c['context']['q1_unused_field']='DIAGNOSTIC_ONLY'
        changed=score(c,candidates,policy)
        out.append({'control':kind,'margin_delta':target(changed)-target(original),'pair_changed':target(changed,'pair')!=target(original,'pair'),
          'top1_changed':order(changed)[0]!=order(original)[0], 'top2_changed':set(order(changed)[:2])!=set(order(original)[:2]),
          'mechanism_only_not_physiological_intervention':True})
    return out

def clustered(records,field,seed=20261019,replicates=1000):
    by={}
    for r in records:
        v=r.get(field)
        if v is not None and math.isfinite(v):by.setdefault(r['subject_id'],[]).append(v)
    a=[mean(v) for v in by.values()]
    if not a:return {'mean':None,'ci95':None,'participants':0}
    rng=random.Random(seed);boot=sorted(mean(rng.choices(a,k=len(a))) for _ in range(replicates))
    return {'mean':mean(a),'ci95':[boot[int(.025*replicates)],boot[min(replicates-1,int(.975*replicates))]],'participants':len(a),
      'participant_mean_min':min(a),'participant_mean_max':max(a)}
