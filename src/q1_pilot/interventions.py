"""Joint raw-block replacement, using only a subject's pre-current baseline."""
from copy import deepcopy
from .scorers import sleep_clock_usable, usable

def groups(n):
    if n==6: return [list(range(i,i+7)) for i in (1,8,15,22,29,36)]
    if n==8: return [list(range(a,b+1)) for a,b in ((1,7),(8,14),(15,21),(22,28),(29,32),(33,35),(36,39),(40,42))]
    raise ValueError('unsupported source granularity')

def eligibility(case):
    for phase,min_n in [('baseline',14),('current',7)]:
        if sum(sleep_clock_usable(d) for d in case['days'] if d['phase']==phase)<min_n:
            return 'INSUFFICIENT_'+phase.upper()+'_SLEEP_CLOCK'
    return 'ELIGIBLE'

def donor(case,strategy='latest',minimum=5):
    if strategy not in ('latest','earliest'): raise ValueError('unknown donor strategy')
    valid=[]
    for a in (1,8,15,22):
        week=[deepcopy(d) for d in case['days'] if a<=d['day']<a+7]
        if len(week)==7 and all(d['phase']=='baseline' and d['day']<=28 for d in week) and sum(sleep_clock_usable(d) for d in week)>=minimum:
            valid.append(week)
    if not valid: raise ValueError('DONOR_UNAVAILABLE')
    return valid[-1] if strategy=='latest' else valid[0]

def validate_donor(case,week):
    if len(week)!=7 or [d['day'] for d in week]!=list(range(week[0]['day'],week[0]['day']+7)):
        raise ValueError('invalid donor block')
    by={d['day']:d for d in case['days']}
    if any(d['day']>28 or d['phase']!='baseline' or by.get(d['day'])!=d for d in week):
        raise ValueError('future, foreign or altered donor')
    if sum(sleep_clock_usable(d) for d in week)<5: raise ValueError('unusable donor')

def background(case,week):
    validate_donor(case,week)
    b=deepcopy(case)
    for d in b['days']:
        source=week[(d['day']-1)%7]
        for k in ('metrics','quality_flags','missing_metrics'): d[k]=deepcopy(source[k])
    return b

def merge(case,bg,source_groups,mask):
    if len(case['days'])!=42 or len(bg['days'])!=42: raise ValueError('42 days required')
    flat=[d for g in source_groups for d in g]
    if sorted(flat)!=list(range(1,43)): raise ValueError('source groups must partition days')
    if mask<0 or mask>=2**len(source_groups): raise ValueError('invalid coalition')
    keep={d for i,g in enumerate(source_groups) if mask & (1<<i) for d in g}
    out=deepcopy(case)
    for d,b in zip(out['days'],bg['days']):
        if d['day']!=b['day'] or d['phase']!=b['phase']: raise ValueError('misaligned background')
        if d['day'] not in keep:
            for k in ('metrics','quality_flags','missing_metrics'): d[k]=deepcopy(b[k])
    return out

def splice_diagnostics(case,bg):
    jumps=[]
    for i in (7,14,21,28,35):
        a,b=case['days'][i-1],bg['days'][i]
        if usable(a) and usable(b): jumps.append(abs(a['metrics']['sleep_minutes']-b['metrics']['sleep_minutes']))
    def totals_bad(c):
        return sum(sum(d['metrics'].get(k) or 0 for k in ('fitbit_lightly_active_minutes','fitbit_moderately_active_minutes','fitbit_very_active_minutes','fitbit_sedentary_minutes'))>1440 for d in c['days'])
    return {'one_sided_seam_sleep_jump_max_minutes':max(jumps,default=None),
      'usable_sleep_coverage_delta':sum(usable(d) for d in bg['days'])-sum(usable(d) for d in case['days']),
      'foreground_activity_total_gt1440_days':totals_bad(case),'background_activity_total_gt1440_days':totals_bad(bg),
      'physiological_feasibility':'NOT_ESTABLISHED_REAL_BLOCK_TILING'}
