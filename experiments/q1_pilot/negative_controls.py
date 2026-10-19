"""All-eligible-window official item-only dummy attribution control."""
import argparse
import contextlib
import json
from pathlib import Path
import sys
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT))
from src.common import read,rows,digest,sha,write
from src.q1_pilot.interventions import eligibility,donor,background
from src.q1_pilot.coalition_game import Game
from src.q1_pilot import baseline_adapters as official

def main(name):
    if Path(name).name!=name or name in ('','.','..'):raise ValueError('invalid run name')
    out=ROOT/'local/experiments/q1_pilot'/name;out.mkdir(parents=True,exist_ok=False)
    cfg=read(ROOT/'experiments/q1_pilot/config.json');cid=digest(cfg);k=cfg['panels']['p1']
    write(out/'manifest.json',{'config_id':cid,'source_sha256':sha(Path(__file__)),'adapter_sha256':sha(ROOT/'src/q1_pilot/baseline_adapters.py'),
      'purpose':'Complete predeclared item-only negative control using official methods on all eligible windows','paid_calls':0})
    a=[]
    with (out/'stdout.txt').open('x',encoding='utf-8') as f,(out/'stderr.txt').open('x',encoding='utf-8') as e,contextlib.redirect_stdout(f),contextlib.redirect_stderr(e),patch('socket.socket',side_effect=RuntimeError('Q1 network forbidden')):
        for c in rows(ROOT/'data/releases/p1-v2/cases.jsonl'):
            if eligibility(c)!='ELIGIBLE':continue
            try:bg=background(c,donor(c))
            except ValueError:continue
            for method in ('RankingSHAP','ShaRP','ShapleyFlow'):
                g=Game(c,bg,k,'item_only')
                if method=='ShapleyFlow':
                    result=official.flow(g,cfg['flow_runs']);error=max(abs(e['credit']) for e in result['edge_credits'])
                    res=result['resources']
                else:
                    p,res=official.rankingshap(g,62) if method=='RankingSHAP' else official.sharp(g)
                    error=max(map(abs,p));result={'phi':p}
                r={'case_id':c['case_id'],'subject_id':c['subject_id'],'method':method,'policy':'item_only','config_id':cid,
                   'status':'TASK_ADAPTED_AND_RUN','max_abs_attribution':error,'resources':res,'result':result}
                if error>1e-8:raise ValueError('official item-only dummy control failed')
                a.append(r)
                with (out/'records.jsonl').open('a',encoding='utf-8') as h:h.write(json.dumps(r)+'\n')
    s={'config_id':cid,'status':'PASS','windows':len({r['case_id'] for r in a}),'participants':len({r['subject_id'] for r in a}),
      'records':len(a),'methods':{m:{'records':sum(r['method']==m for r in a),'max_abs_attribution':max(r['max_abs_attribution'] for r in a if r['method']==m)} for m in ('RankingSHAP','ShaRP','ShapleyFlow')},
      'raw_pipeline_scorer_calls':sum(r['resources']['scorer_calls'] for r in a),'query_requests':sum(r['resources']['query_requests'] for r in a),
      'all_candidate_score_node_evaluations':sum(r['resources'].get('all_candidate_score_evaluations',0) for r in a),'new_paid_calls':0}
    write(out/'summary.json',s);print(json.dumps(s,indent=2))

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--name',required=True);args=ap.parse_args();main(args.name)
