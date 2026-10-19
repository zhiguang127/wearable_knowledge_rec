"""Supplement: deterministic Flow replay and independent, noncoalition raw probes."""
import argparse
import contextlib
from copy import deepcopy
import json
from pathlib import Path
import sys
from time import perf_counter
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from src.common import read,rows,digest,sha,write
from src.q1_pilot.coalition_game import Game
from src.q1_pilot.interventions import eligibility,donor,background,groups
from src.q1_pilot.scorers import usable,score,target
from src.q1_pilot import baseline_adapters as official

def main(name):
    if Path(name).name!=name or name in ('','.','..'):raise ValueError('invalid run name')
    out=ROOT/'local/experiments/q1_pilot'/name;out.mkdir(parents=True,exist_ok=False)
    config=read(ROOT/'experiments/q1_pilot/config.json');k=config['panels']['p1'];cid=digest(config)
    write(out/'manifest.json',{'config_id':cid,'supplement':'canonical graph ordering + raw +30 minute probes outside the binary coalition game',
      'source_sha256':{str(p.relative_to(ROOT)):sha(p) for p in [Path(__file__).resolve(),ROOT/'src/q1_pilot/baseline_adapters.py']},
      'probe_interpretation':'Descriptive response only; source replacement attribution is NOT a prediction of +30 minute changes; no cross-game error metric',
      'flow_runs':config['flow_runs'],'flow_seed':0,'paid_calls':0})
    t=perf_counter();records=[]
    with (out/'stdout.txt').open('x',encoding='utf-8') as f,contextlib.redirect_stdout(f),patch('socket.socket',side_effect=RuntimeError('Q1 network forbidden')):
        for case in rows(ROOT/'data/releases/p1-v2/cases.jsonl'):
            if eligibility(case)!='ELIGIBLE':continue
            try:bg=background(case,donor(case))
            except ValueError:continue
            for policy in ('additive','interaction'):
                base={'case_id':case['case_id'],'subject_id':case['subject_id'],'policy':policy,'config_id':cid}
                result=official.flow(Game(case,bg,k,policy),config['flow_runs'],0)
                # Repeat exact same graph in an independently constructed object.
                again=official.flow(Game(case,bg,k,policy),config['flow_runs'],0)
                edge=lambda r:sorted((e['from'],e['to'],e['credit']) for e in r['edge_credits'])
                repeated=edge(result)==edge(again)
                if not repeated:raise ValueError('canonical Flow seed replay failed')
                old=score(case,k,policy);probes=[]
                for i,days in enumerate(groups(6)):
                    c=deepcopy(case);changed=0
                    for d in c['days']:
                        if d['day'] in days and usable(d) and d['metrics']['sleep_minutes']<=1410:
                            d['metrics']['sleep_minutes']+=30
                            # Preserve sleep<=bed; this is an explicit software probe,
                            # not a source-donor or physiological intervention.
                            if d['metrics'].get('time_in_bed_minutes') is not None:
                                d['metrics']['time_in_bed_minutes']=max(d['metrics']['time_in_bed_minutes'],d['metrics']['sleep_minutes'])
                            changed+=1
                    s=score(c,k,policy)
                    probes.append({'source_group':i,'changed_days':changed,'margin_delta':target(s)-target(old),'pair_changed':target(s,'pair')!=target(old,'pair')})
                rec={**base,'status':'TASK_ADAPTED_AND_RUN','flow':result,'independent_repeat_resources':again['resources'],'seed_replay_identical':repeated,
                  'noncoalition_probes':probes,'probe_scorer_calls':7}
                records.append(rec)
                with (out/'records.jsonl').open('a',encoding='utf-8') as h:h.write(json.dumps(rec,ensure_ascii=False)+'\n')
    summary={'config_id':cid,'records':len(records),'windows':len({r['case_id'] for r in records}),'participants':len({r['subject_id'] for r in records}),
      'status':'TASK_ADAPTED_AND_RUN','seconds':perf_counter()-t,'canonical_seed_replay_identical':all(r['seed_replay_identical'] for r in records),
      'max_cut_residual':max(max(r['flow']['cut_residuals'].values()) for r in records),
      'max_node_conservation_residual':max(r['flow']['max_node_conservation_residual'] for r in records),
      'total_raw_scorer_calls':sum(r['flow']['resources']['scorer_calls']+r['independent_repeat_resources']['scorer_calls'] for r in records),
      'total_all_candidate_score_node_evaluations':sum(r['flow']['resources']['all_candidate_score_evaluations']+r['independent_repeat_resources']['all_candidate_score_evaluations'] for r in records),
      'noncoalition_probes':len(records)*6,'probe_scorer_calls':len(records)*7,
      'responsive_probes':sum(abs(p['margin_delta'])>1e-8 for r in records for p in r['noncoalition_probes']),
      'pair_changed_probes':sum(p['pair_changed'] for r in records for p in r['noncoalition_probes']),
      'no_attribution_error_for_different_game':True,'source_game_comparison':'NOT_PERFORMED_EDGE_GAME_DISTINCT','new_paid_calls':0}
    write(out/'summary.json',summary);print(json.dumps(summary,indent=2))

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--name',required=True);a=ap.parse_args();main(a.name)
