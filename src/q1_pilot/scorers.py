"""Transparent experimental policies; never trained labels or medical priorities."""
import math
from statistics import mean, pstdev

FEATURES = ('short','gap','clock','adjacent','trend','activity','rhr','missing','bed_gap')
WEIGHTS = {'K006': {'short':1.,'gap':.5}, 'K017':{'clock':1.},
 'K005':{'short':.6,'gap':.2},'K019':{'clock':.7},'K041':{'activity':.15},
 'K083':{'rhr':.3},'K094':{'missing':.4,'bed_gap':.15}}

def finite(v):
    return isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v)

def usable(day):
    m=day['metrics']; v=m.get('sleep_minutes')
    return finite(v) and 0 <= v <= 1440 and m.get('sleep_info_code') == 0

def clock_minutes(v):
    if not isinstance(v,str): return None
    a=v.split(':')
    if len(a)!=3: raise ValueError('invalid clock')
    h,m,s=map(float,a)
    if not (0<=h<24 and 0<=m<60 and 0<=s<60): raise ValueError('invalid clock')
    return h*60+m+s/60

def sleep_clock_usable(day):
    return usable(day) and clock_minutes(day['metrics'].get('sleep_start_clock')) is not None

def summary(case):
    out={}
    for phase in ('baseline','current'):
        days=[d for d in case['days'] if d['phase']==phase]
        points=[(d['day'],d['metrics']['sleep_minutes']) for d in days if usable(d)]
        vals=[v for _,v in points]
        clocks=[clock_minutes(d['metrics'].get('sleep_start_clock')) for d in days if usable(d)]
        clocks=[v for v in clocks if v is not None]
        r=math.hypot(sum(math.sin(v*math.tau/1440) for v in clocks),sum(math.cos(v*math.tau/1440) for v in clocks))/len(clocks) if clocks else None
        sd=min(6.,math.sqrt(-2*math.log(max(min(r,1.),1e-15)))*24/math.tau) if r is not None else None
        by=dict(points); adjacent=[abs(v-by[x-1]) for x,v in points if x-1 in by]
        xbar=mean(x for x,_ in points) if points else 0
        den=sum((x-xbar)**2 for x,_ in points)
        slope=sum((x-xbar)*(v-mean(vals)) for x,v in points)/den if den else None
        rhr=[d['metrics'].get('resting_heart_rate_bpm') for d in days]
        rhr=[v for v in rhr if finite(v) and v>0]
        act=[]; gaps=[]
        for d in days:
            m=d['metrics']; a=[m.get('fitbit_'+k+'_active_minutes') for k in ('lightly','moderately','very')]
            if all(finite(v) and v>=0 for v in a): act.append(sum(a))
            if usable(d) and finite(m.get('time_in_bed_minutes')) and m['time_in_bed_minutes']>=m['sleep_minutes']:
                gaps.append(m['time_in_bed_minutes']-m['sleep_minutes'])
        out[phase]={'n':len(vals),'clock_n':len(clocks),'mean':mean(vals) if vals else None,
          'sd':pstdev(vals) if vals else None,'clock_sd':sd,'adjacent':mean(adjacent) if adjacent else None,
          'slope':slope,'activity':mean(act) if act else None,'rhr':mean(rhr) if rhr else None,
          'bed_gap':mean(gaps) if gaps else None,'total':len(days)}
    return out

def features(case):
    h=summary(case); b,c=h['baseline'],h['current']
    def val(v, f): return f(v) if v is not None else 0.
    return {'short':val(c['mean'],lambda x:(420-x)/60),
      'gap':(b['mean']-c['mean'])/60 if b['mean'] is not None and c['mean'] is not None else 0.,
      'clock':val(c['clock_sd'],float),'adjacent':val(c['adjacent'],lambda x:x/60),
      'trend':val(c['slope'],lambda x:-x/15),'activity':val(c['activity'],lambda x:(60-x)/60),
      'rhr':abs(c['rhr']-b['rhr'])/10 if c['rhr'] is not None and b['rhr'] is not None else 0.,
      'missing':1-c['n']/c['total'],'bed_gap':val(c['bed_gap'],lambda x:x/60)}

def score_features(f, candidates, policy):
    if policy=='item_only': return {k:-float(i) for i,k in enumerate(candidates)}
    if policy not in ('additive','interaction'): raise ValueError('unknown policy')
    if any(k not in WEIGHTS for k in candidates): raise ValueError('unmapped candidate')
    s={k:sum(f[n]*w for n,w in WEIGHTS[k].items()) for k in candidates}
    if policy=='interaction':
        if 'K006' in s: s['K006']+=.3*f['short']*f['gap']+.25*f['trend']
        if 'K017' in s: s['K017']+=.3*f['clock']*f['adjacent']+.25*f['adjacent']
    return s

def score(case,candidates,policy): return score_features(features(case),candidates,policy)

def target(scores, kind='margin',pair=('K006','K017')):
    a,b=pair
    if kind=='margin': return scores[a]-scores[b]
    if kind=='pair': return 1. if scores[a]>scores[b]+1e-12 else 0. if scores[a]<scores[b]-1e-12 else .5
    rank=1+sum(v>scores[a]+1e-12 for v in scores.values())
    if kind=='negative_rank': return -float(rank)
    if kind=='top2': return float(rank<=2)
    raise ValueError('unknown target')

def order(scores): return sorted(scores,key=lambda k:(-scores[k],k))
