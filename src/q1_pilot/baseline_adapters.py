"""Call fixed official algorithms. No substitute SHAP approximation is hidden here."""
import importlib
import json
import random
import sys
from functools import partial
from pathlib import Path
from time import perf_counter

UPSTREAM=Path(__file__).resolve().parents[2]/'local/q1-upstream'
PINS={'RankingShap':'36e45975f34ee167261af56c69521d55c998b282',
      'ShaRP':'6543226b7c4952aab61a15a977964344cabbf929',
      'Shapley-Flow':'0d9063f81759d4317de6c33d7782e5ec4a4cde85'}

def load(name):
    p=str(UPSTREAM/name)
    if p not in sys.path: sys.path.insert(0,p)
    return importlib.import_module({'RankingShap':'approaches.ranking_shap','ShaRP':'sharp','Shapley-Flow':'flow'}[name])

def rankingshap(game,nsamples,seed=0,listwise=False):
    import numpy as np
    import shap
    from scipy.stats import kendalltau
    mod=load('RankingShap');np.random.seed(seed)
    state={}
    def predict(rows):
        # Official common-column masking touches ALL candidates. Selectors must agree.
        rows=np.asarray(rows,dtype=float)
        if not np.all(rows==rows[0]): raise ValueError('shared-person selectors diverged across candidates')
        s=game.scores(game.mask(rows[0]));state['scores']=s
        return np.array([s[k] for k in game.candidates])
    def coefficient(og,new):
        if listwise: return float(kendalltau(og,new)[0])
        from .scorers import target
        return target(state['scores'],'margin')
    query=np.ones((len(game.candidates),game.n))
    t=perf_counter()
    obj=mod.RankingShap('kernel',np.zeros((1,game.n)),predict,explanation_size=game.n,
          nsample_permutations=nsamples,rank_similarity_coefficient=coefficient)
    # Official constructor uses a zero placeholder model. Rebind its query-specific
    # KernelExplainer before initialization so fnull/expected_value is the REAL baseline.
    # No official source or sampling algorithm modified. This is an interface repair.
    model=partial(obj.new_model_predict,query_features=query)
    obj.explainer=shap.KernelExplainer(model,np.zeros((1,game.n)))
    init=game.counters().copy()
    _,exp=obj.get_query_explanation(query)
    phi=np.zeros(game.n)
    for idx,v in exp.explanation: phi[idx-1]=v
    return phi.tolist(),{**game.counters(),'initialization':init,'seconds':perf_counter()-t,
      'kernel_nsamples':nsamples,'seed':seed,'official_core':'RankingShap.get_query_explanation',
      'adaptation':'shared raw-source binary selectors; query-specific baseline initialization; '+('native Kendall listwise QoI' if listwise else 'scalar margin callback')}

def sharp(game):
    import numpy as np
    mod=load('ShaRP');t=perf_counter()
    # diff on a source-selector vector, not native item-row rank. Entire K reranked.
    obj=mod.ShaRP(qoi='diff',target_function=game.vector,measure='shapley',sample_size=1,
                  replace=False,random_state=0,cache=False,n_jobs=1)
    obj.fit(np.zeros((1,game.n)))
    init=game.counters().copy()
    phi=obj.individual(np.ones(game.n))
    return [float(v) for v in phi],{**game.counters(),'initialization':init,'seconds':perf_counter()-t,
      'official_core':'ShaRP.individual -> official _shapley',
      'adaptation':'diff QoI over raw-source selectors; full-candidate '+game.qoi+' wrapper'}

def flow(game,nruns=64,seed=0):
    import numpy as np
    from .scorers import FEATURES,score_features,target
    mod=load('Shapley-Flow');np.random.seed(seed);t=perf_counter()
    roots=[mod.Node('G'+str(i)) for i in range(game.n)]
    current=[i for i,g in enumerate(game.source_groups) if min(g)>28]
    node_calls={'feature_evaluations':0,'all_candidate_score_evaluations':0,'margin_evaluations':0}
    def feature_f(name,indices):
        def f(*args):
            node_calls['feature_evaluations']+=1
            mask=sum(1<<i for i,a in zip(indices,args) if float(np.asarray(a).ravel()[0])==1.)
            game.scores(mask)
            return np.array([game.cache[mask][0][name]])
        return f
    hs=[]
    for name in FEATURES:
        idx=list(range(game.n)) if name in ('gap','rhr') else current
        hs.append(mod.Node('h_'+name,feature_f(name,idx),[roots[i] for i in idx]))
    def all_scores(*args):
        node_calls['all_candidate_score_evaluations']+=1
        f={k:float(np.asarray(a).ravel()[0]) for k,a in zip(FEATURES,args)}
        s=score_features(f,game.candidates,game.policy)
        return np.array([[s[k] for k in game.candidates]])
    scores=mod.Node('F_all_candidates',all_scores,hs)
    ia,ib=[game.candidates.index(k) for k in ('K006','K017')]
    def margin(a):
        node_calls['margin_evaluations']+=1
        return a[:,ia]-a[:,ib]
    output=mod.Node('margin',margin,[scores],is_target_node=True)
    graph=mod.Graph(roots+hs+[scores,output],{r.name:(lambda:0.) for r in roots},{r.name:(lambda:1.) for r in roots})
    # Official Graph converts nodes to a set. Stabilize adapter input order before
    # seeded Monte Carlo; do not alter the author's credit propagation algorithm.
    graph.nodes.sort(key=lambda node:node.name)
    cf=mod.CreditFlow(graph,nruns=nruns,silent=True)
    init=game.counters().copy();cf.run()
    edges=[{'from':a.name,'to':b.name,'credit':float(np.asarray(v).ravel()[0])} for a,d in cf.edge_credit.items() for b,v in d.items()]
    delta=game.value((1<<game.n)-1)-game.value(0)
    cuts={
      'source_cut':sum(e['credit'] for e in edges if e['from'].startswith('G')),
      'feature_cut':sum(e['credit'] for e in edges if e['to']=='F_all_candidates'),
      'output_cut':sum(e['credit'] for e in edges if e['to']=='margin')}
    residuals={k:abs(v-delta) for k,v in cuts.items()}
    conservation={h.name:abs(sum(e['credit'] for e in edges if e['to']==h.name)-sum(e['credit'] for e in edges if e['from']==h.name)) for h in hs}
    return {'edge_credits':edges,'cuts':cuts,'cut_residuals':residuals,'max_node_conservation_residual':max(conservation.values()),
      'delta':delta,'game':'official_distributed_edge_game_NOT_node_source_game',
      'resources':{**game.counters(),**node_calls,'initialization':init,'seconds':perf_counter()-t,'nruns':nruns,'seed':seed},
      'status':'TASK_ADAPTED_AND_RUN'}

def native_smokes():
    import numpy as np
    from scipy.stats import kendalltau
    results={}
    for name in PINS:
        t=perf_counter()
        try:
            mod=load(name);np.random.seed(0);random.seed(0)
            if name=='RankingShap':
                nb=json.loads((UPSTREAM/name/'synthetic_talent_search_case_study.ipynb').read_text(encoding='utf-8'))
                env={}
                for idx in (0,1,4,6,7,10,12,15,16,19): exec(compile(''.join(nb['cells'][idx]['source']),str(UPSTREAM/name/'synthetic_talent_search_case_study.ipynb')+':cell'+str(idx),'exec'),env)
                obj=mod.RankingShap('kernel',env['background_samples'],env['ranking_model'],explanation_size=5,nsample_permutations=30)
                _,e=obj.get_query_explanation(np.array(env['queries']['qualified']))
                out={'attributions':[(int(i),float(v)) for i,v in e.explanation], 'sample':'author talent-search qualified query, 100 author-generated background samples',
                  'baseline_initialization':'unmodified author zero placeholder; task adapter explicitly reinitializes real baseline'}
            elif name=='ShaRP':
                rng=np.random.RandomState(42)
                X=np.concatenate([rng.normal(size=(50,1)),rng.binomial(1,.5,size=(50,1))],axis=1)
                fn=lambda X:.5*X[:,0]+.5*X[:,1]
                obj=mod.ShaRP(qoi='rank',target_function=fn,measure='shapley',sample_size=None,replace=False,random_state=42,cache=False)
                obj.fit(X);p=obj.individual(9,X);pair=obj.pairwise(X[2],X[3])
                out={'individual':list(map(float,p)),'pairwise':list(map(float,pair)),'sample':'author examples/plot_basic_usage.py numerical workflow, plotting omitted; cache=False avoids Windows Manager subprocess'}
            else:
                graph=mod.sample_build_graph();cf=mod.CreditFlow(graph,nruns=64,silent=True);cf.run()
                es=[(a.name,b.name,float(np.asarray(v).ravel()[0])) for a,d in cf.edge_credit.items() for b,v in d.items()]
                out={'edges':es,'sample':'author sample_build_graph x1->x2 and y=x1+x2; author CreditFlow',
                  'output_cut':sum(v for a,b,v in es if b=='target')}
                if abs(out['output_cut']-2)>1e-8: raise ValueError('native flow conservation failed')
            results[name]={'status':'NATIVE_REPRODUCED','commit':PINS[name],'seconds':perf_counter()-t,**out}
        except Exception as e:
            import traceback
            results[name]={'status':'BLOCKED','commit':PINS[name],'error':repr(e),'traceback':traceback.format_exc(),'seconds':perf_counter()-t}
    return results
