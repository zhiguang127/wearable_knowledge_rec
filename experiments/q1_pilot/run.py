"""Offline runner. Exclusive versioned outputs, blocked network during experiments."""
import argparse
import contextlib
from collections import Counter,defaultdict
from copy import deepcopy
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import subprocess
import sys
from time import perf_counter
import traceback
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from src.common import digest,read,rows,sha,write
from src.datasets.releases import verify_release
from src.q1_pilot.scorers import features,score,score_features,target,order,FEATURES
from src.q1_pilot.interventions import eligibility,donor,background,splice_diagnostics
from src.q1_pilot.coalition_game import Game
from src.q1_pilot.exact_shapley import exact,efficiency
from src.q1_pilot.evaluation import behavior,metrics,clustered
from src.q1_pilot import baseline_adapters as official

def reference(case,bg,k,policy,n,qoi='margin'):
    g=Game(case,bg,k,policy,n,qoi);t=perf_counter();v=g.table()
    p=exact(v,n)
    return g,v,p,{**g.counters(),'seconds':perf_counter()-t,'efficiency_residual':efficiency(p,v)}

def native_kendall_table(g):
    import numpy as np
    from scipy.stats import kendalltau
    mod=official.load('RankingShap')
    original=mod.rank_list(np.array(list(g.scores((1<<g.n)-1).values())))
    return [float(kendalltau(original,mod.rank_list(np.array(list(g.scores(m).values()))))[0]) for m in range(1<<g.n)]

def derived_control(case,bg,k,policy):
    f,b=features(case),features(bg);n=len(FEATURES)
    v=[];inconsistent=0
    for m in range(1<<n):
        x={name:(f[name] if m>>i&1 else b[name]) for i,name in enumerate(FEATURES)}
        v.append(target(score_features(x,k,policy)))
        # Gap and current short share the same raw current mean. A hybrid may retain
        # foreground short but background gap: incoherent under fixed baseline.
        inconsistent+=int((m&1)!=0 and (m&2)==0 and abs(f['gap']-b['gap'])>1e-8)
    return {'game':'independent_derived_coordinates_NOT_source_game','phi':exact(v,n),'efficiency_residual':efficiency(exact(v,n),v),
      'coalitions':len(v),'fore_short_background_gap_hybrids':inconsistent,'no_cross_game_mae':True}

def public_summary(records,excluded,methods,natives,config_id,elapsed,phase):
    successful=[r for r in records if r['status']=='TASK_ADAPTED_AND_RUN']
    per=defaultdict(list)
    for r in successful:
        if 'metrics' in r:
            key=(r['method'],r['panel'],r['policy'],r['donor_strategy'],r['n_groups'],r.get('qoi','margin'),r.get('kernel_nsamples','full'))
            per[key].append({**r['metrics'],'subject_id':r['subject_id'],'seconds':r['resources']['seconds'],
              'scorer_calls':r['resources']['scorer_calls'],'unique_coalitions':r['resources']['unique_coalitions']})
    tables=[]
    for key,rs in sorted(per.items(),key=str):
        tables.append({'method':key[0],'panel':key[1],'policy':key[2],'donor_strategy':key[3],'n_groups':key[4],'qoi':key[5],'kernel_nsamples':key[6],
          'records':len(rs),**{f:clustered(rs,f) for f in ('mae','sign_agreement_nonzero','top_source_hit','efficiency_residual','seconds','scorer_calls','unique_coalitions')}})
    cases={r['case_id'] for r in records};subjects={r['subject_id'] for r in records}
    behavior_summary=[]
    for policy in ('additive','interaction','item_only'):
        for control in ('history_minus60','current_minus60','clock_alternating','reverse_current','unused_context'):
            rr=[{**b,'subject_id':r['subject_id']} for r in records if r['method']=='behavior' and r['policy']==policy for b in r['controls'] if b['control']==control]
            if rr:behavior_summary.append({'policy':policy,'control':control,'windows':len(rr),'margin_delta':clustered(rr,'margin_delta'),
              'responsive_windows':sum(abs(x['margin_delta'])>1e-8 for x in rr),'pair_changed':sum(x['pair_changed'] for x in rr),
              'top1_changed':sum(x['top1_changed'] for x in rr),'top2_changed':sum(x['top2_changed'] for x in rr)})
    flows=[r for r in successful if r['method']=='ShapleyFlow']
    statuses=Counter(r['status'] for r in records)
    return {'config_id':config_id,'phase':phase,'seconds':elapsed,'eligible_participants':len(subjects),'eligible_windows':len(cases),
      'screened_windows':48 if phase=='full' else None,'exclusions':dict(Counter(r['reason'] for r in excluded)),
      'donor_window_counts':dict(Counter(r['donor_strategy'] for r in records if r['method']=='donor_diagnostics')),
      'unique_donor_blocks':len({(r['subject_id'],r['case_id'],r['donor_start_day']) for r in records if r['method']=='donor_diagnostics'}),
      'candidate_pairs':1,'panels':{'p1':5,'a1_duration_and_timing':4},'record_status_counts':dict(statuses),
      'method_status_counts':{m:dict(Counter(r['status'] for r in records if r['method']==m)) for m in sorted({r['method'] for r in records})},
      'native_smokes':natives,'aggregate_metrics':tables,'behavior':behavior_summary,
      'flow':{'records':len(flows),'max_cut_residual':max((max(r['flow']['cut_residuals'].values()) for r in flows),default=None),
        'max_node_conservation_residual':max((r['flow']['max_node_conservation_residual'] for r in flows),default=None),
        'total_all_candidate_score_evaluations':sum(r['resources']['all_candidate_score_evaluations'] for r in flows),
        'total_raw_pipeline_scorer_calls':sum(r['resources']['scorer_calls'] for r in flows)},
      'total_resources':{'raw_pipeline_scorer_calls':sum(r.get('resources',{}).get('scorer_calls',0) for r in records),
        'query_requests':sum(r.get('resources',{}).get('query_requests',0) for r in records),
        'method_seconds':sum(r.get('resources',{}).get('seconds',0) for r in records)},
      'external_ranker':'BLOCKED_EXTERNAL_RANKER_VALIDATION','TimeSHAP':'BLOCKED_OPTIONAL_NOT_IMPLEMENTED_NOT_RUN',
      'decision':'INCONCLUSIVE','decision_scope':'Only two hand-written policies; no external real ranker. Numeric controls cannot establish general algorithm failure.',
      'gate1':'See exact-budget residuals and edge-cut checks; never infer failure from low-budget noise or cross-game differences',
      'gate2':'No new algorithm necessity established','new_paid_calls':0,'training_runs':0,'human_gold_used':False}

def execute(args):
    import numpy as np
    out=ROOT/'local/experiments/q1_pilot'/args.name
    out.mkdir(parents=True,exist_ok=False)
    config=read(ROOT/'experiments/q1_pilot/config.json');cid=digest(config)
    for kind,directory in [('p1','p1-v2'),('a1','a1-v1')]:
        release=verify_release(ROOT/'data/releases'/directory,kind)
        if release['release_id']!=config['data_release_ids'][kind]:raise ValueError('frozen data contract mismatch')
    source_files=[*sorted((ROOT/'src/q1_pilot').glob('*.py')),ROOT/'experiments/q1_pilot/run.py',ROOT/'experiments/q1_pilot/config.json',ROOT/'experiments/q1_pilot/protocol.md']
    implementation={str(p.relative_to(ROOT)):sha(p) for p in source_files}
    pins={}
    for name,expected in official.PINS.items():
        p=official.UPSTREAM/name
        actual=subprocess.check_output(['git','-C',str(p),'rev-parse','HEAD'],text=True).strip()
        status=subprocess.check_output(['git','-C',str(p),'status','--porcelain','--untracked-files=no'],text=True).strip()
        if actual!=expected or status:raise ValueError('official source pin mismatch or tracked source modified')
        pins[name]={'commit':actual,'tracked_source_unchanged':True}
    manifest={'config_id':cid,'config':config,'implementation_sha256':implementation,'upstreams':pins,'python':platform.python_version(),
      'dependencies':dict((d.metadata['Name'],d.version) for d in importlib.metadata.distributions()),'argv':sys.argv,'network':'socket forbidden during all experiment execution'}
    write(out/'manifest.json',manifest)
    records=[];excluded=[];t=perf_counter()
    def save(r):
        r['config_id']=cid;records.append(r)
        with (out/'records.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(r,ensure_ascii=False,allow_nan=False)+'\n')
    with (out/'stdout.txt').open('x',encoding='utf-8') as stdout,(out/'stderr.txt').open('x',encoding='utf-8') as stderr,contextlib.redirect_stdout(stdout),contextlib.redirect_stderr(stderr),patch('socket.socket',side_effect=RuntimeError('Q1 network forbidden')):
        natives=official.native_smokes();write(out/'native_smokes.json',natives)
        cases=rows(ROOT/'data/releases/p1-v2/cases.jsonl')
        selected=[]
        for case in cases:
            reason=eligibility(case)
            if reason!='ELIGIBLE':excluded.append({'case_id':case['case_id'],'reason':reason});continue
            try:w=donor(case)
            except ValueError:excluded.append({'case_id':case['case_id'],'reason':'DONOR_UNAVAILABLE'});continue
            selected.append(case)
        if args.smoke:selected=selected[:1]
        # Stage 1 is completed and checked for the entire selected set BEFORE
        # any attribution call. Failed policy controls must not become XAI failures.
        for case in selected:
            base={'case_id':case['case_id'],'subject_id':case['subject_id']}
            for policy in ('additive','interaction','item_only'):
                save({**base,'method':'behavior','policy':policy,'controls':behavior(case,config['panels']['p1'],policy),'status':'TASK_ADAPTED_AND_RUN'})
        checks={}
        for policy in ('additive','interaction','item_only'):
            controls=[b for r in records if r['method']=='behavior' and r['policy']==policy for b in r['controls']]
            checks[policy]={'history_responsive':sum(abs(b['margin_delta'])>1e-8 for b in controls if b['control']=='history_minus60'),
              'current_responsive':sum(abs(b['margin_delta'])>1e-8 for b in controls if b['control']=='current_minus60'),
              'unused_invariant':all(abs(b['margin_delta'])<1e-8 for b in controls if b['control']=='unused_context')}
            if policy=='item_only' and any(abs(b['margin_delta'])>1e-8 for b in controls):raise ValueError('item-only behavior control failed')
            if policy!='item_only' and not (checks[policy]['history_responsive'] and checks[policy]['current_responsive']):raise ValueError('policy nonresponsive; stop before explanation')
            if not checks[policy]['unused_invariant']:raise ValueError('unused input invariance failed')
            if policy=='additive' and any(abs(b['margin_delta'])>1e-8 for b in controls if b['control']=='reverse_current'):raise ValueError('moment policy temporal invariance failed')
        write(out/'behavior_gate.json',{'status':'PASS','checks':checks,'windows':len(selected)})
        for case in selected:
            base={'case_id':case['case_id'],'subject_id':case['subject_id']}
            print('CASE_START',case['case_id'],flush=True)
            for strategy in ('latest','earliest'):
                week=donor(case,strategy);bg=background(case,week)
                save({**base,'method':'donor_diagnostics','donor_strategy':strategy,'donor_start_day':week[0]['day'],
                    'diagnostics':splice_diagnostics(case,bg),'status':'TASK_ADAPTED_AND_RUN'})
                conditions=[('p1',6)]
                if strategy=='latest':conditions += [('p1',8),('a1_duration_and_timing',6)]
                for panel,n in conditions:
                    k=config['panels'][panel]
                    for policy in ('additive','interaction','item_only'):
                        if policy=='item_only' and (strategy!='latest' or n!=6 or panel!='p1'):continue
                        common={**base,'panel':panel,'n_groups':n,'policy':policy,'donor_strategy':strategy,'qoi':'margin'}
                        g,v,p,res=reference(case,bg,k,policy,n)
                        save({**common,'method':'exact_source','phi':p,'values':v,'all_scores':{str(m):s for m,(_,s) in g.cache.items()},'resources':res,
                          'metrics':metrics(p,p,v[-1]-v[0]),'status':'TASK_ADAPTED_AND_RUN'})
                        if policy=='item_only':
                            if any(abs(x)>1e-8 for x in p):raise ValueError('item-only dummy control failed')
                        if n==6 and panel=='p1' and strategy=='latest':
                            save({**common,'method':'derived_negative_control','derived':derived_control(case,bg,k,policy),'status':'TASK_ADAPTED_AND_RUN'})
                            # Descriptive deletion diagnostic. At full enumeration these
                            # coalitions are in the reference table, NOT independent holdout.
                            changes=[v[-1]-v[((1<<n)-1)^(1<<i)] for i in range(n)]
                            top=max(range(n),key=lambda i:abs(p[i]));rng=np.random.RandomState(0)
                            save({**common,'method':'heldout_delete','signed_changes':changes,'top_attribution_group':top,
                              'top_group_abs_change':abs(changes[top]),'random_group_abs_change_mean':sum(map(abs,changes))/n,
                              'sign_statement_matches':sum((p[i]*changes[i]>=0) for i in range(n))/n,'status':'TASK_ADAPTED_AND_RUN'})
                        if policy=='item_only':continue
                        for method in ('RankingSHAP','ShaRP'):
                            if natives[{'RankingSHAP':'RankingShap','ShaRP':'ShaRP'}[method]]['status']!='NATIVE_REPRODUCED':
                                save({**common,'method':method,'status':'BLOCKED','reason':'native smoke unavailable'});continue
                            budgets=config['ranking_kernel_nsamples_'+str(n)] if method=='RankingSHAP' and panel=='p1' and strategy=='latest' else [2**n-2]
                            for budget in budgets:
                                seeds=config['seeds'] if method=='RankingSHAP' and panel=='p1' and strategy=='latest' else [0]
                                for seed in seeds:
                                    try:
                                        gg=Game(case,bg,k,policy,n)
                                        pp,rr=official.rankingshap(gg,budget,seed) if method=='RankingSHAP' else official.sharp(gg)
                                        save({**common,'method':method,'kernel_nsamples':budget if method=='RankingSHAP' else 'full','seed':seed,
                                          'phi':pp,'resources':rr,'metrics':metrics(pp,p,v[-1]-v[0]),'status':'TASK_ADAPTED_AND_RUN'})
                                    except Exception as e:save({**common,'method':method,'kernel_nsamples':budget,'seed':seed,'status':'FAILED','error':repr(e),'traceback':traceback.format_exc()})
                        if panel=='p1' and n==6 and strategy=='latest':
                            # Native listwise target and actual outcome/rank/top-k wrappers get separate references.
                            for qoi in ('pair','negative_rank','top2','kendall'):
                                try:
                                    gg=Game(case,bg,k,policy,n,'margin' if qoi=='kendall' else qoi)
                                    vv=native_kendall_table(gg) if qoi=='kendall' else gg.table();ref=exact(vv,n)
                                    cold=Game(case,bg,k,policy,n,'margin' if qoi=='kendall' else qoi)
                                    pp,rr=official.rankingshap(cold,62,0,True) if qoi=='kendall' else official.sharp(cold)
                                    save({**common,'qoi':qoi,'method':'RankingSHAP_listwise' if qoi=='kendall' else 'ShaRP_outcome','phi':pp,'reference':ref,
                                      'resources':rr,'metrics':metrics(pp,ref,vv[-1]-vv[0]),'status':'TASK_ADAPTED_AND_RUN'})
                                except Exception as e:save({**common,'qoi':qoi,'method':'secondary_qoi','status':'FAILED','error':repr(e),'traceback':traceback.format_exc()})
                            try:
                                gg=Game(case,bg,k,policy,n);f=official.flow(gg,config['flow_runs'],0)
                                save({**common,'method':'ShapleyFlow','flow':f,'resources':f['resources'],'status':'TASK_ADAPTED_AND_RUN'})
                            except Exception as e:save({**common,'method':'ShapleyFlow','status':'FAILED','error':repr(e),'traceback':traceback.format_exc()})
            if args.smoke:break
        print('FINISHED',len(records),'records',flush=True)
    write(out/'excluded.json',excluded)
    result=public_summary(records,excluded,None,natives,cid,perf_counter()-t,'smoke' if args.smoke else 'full')
    write(out/'summary.json',result)
    # Privacy allowlist: summaries contain neither identities nor raw daily records.
    s=json.dumps(result,ensure_ascii=False)
    for c in cases:
        if c['case_id'] in s or c['subject_id'] in s:raise ValueError('private identity in public summary')
    print(json.dumps({'output':str(out),'config_id':cid,'records':len(records),'seconds':result['seconds'],'status_counts':result['record_status_counts']},indent=2))

if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--name',required=True);ap.add_argument('--smoke',action='store_true');a=ap.parse_args()
    if Path(a.name).name!=a.name or a.name in ('','.','..'):raise ValueError('invalid run name')
    execute(a)
