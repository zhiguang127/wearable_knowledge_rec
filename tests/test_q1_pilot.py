"""Numerical laws, real-record interventions, behavior, and official adapters."""
from copy import deepcopy
from pathlib import Path
import unittest
from src.common import ROOT,read,rows,digest
from src.q1_pilot.scorers import features,score,target,summary,usable,clock_minutes,WEIGHTS
from src.q1_pilot.interventions import groups,donor,background,merge,eligibility,validate_donor
from src.q1_pilot.coalition_game import Game
from src.q1_pilot.exact_shapley import exact,efficiency
from src.q1_pilot.evaluation import behavior,metrics,clustered

class ShapleyLaws(unittest.TestCase):
    def test_additive_analytic(self):
        w=[1.,-2.,3.,0.]
        v=[7+sum(w[i] for i in range(4) if m>>i&1) for m in range(16)]
        self.assertEqual(exact(v,4),w)
    def test_dummy(self):
        self.assertAlmostEqual(exact([float(m&1) for m in range(8)],3)[2],0)
    def test_symmetry(self):
        p=exact([float(m.bit_count()>1) for m in range(8)],3)
        self.assertTrue(all(abs(v-1/3)<1e-12 for v in p))
    def test_efficiency_interactions(self):
        v=[float(m.bit_count()**3) for m in range(64)]
        self.assertLess(efficiency(exact(v,6),v),1e-10)
    def test_permutation_equivalence(self):
        w=[1.,-3.,4.];v=[sum(w[i] for i in range(3) if m>>i&1)+(2 if m&3==3 else 0) for m in range(8)]
        perm=[2,0,1]
        u=[v[sum(1<<perm[j] for j in range(3) if m>>j&1)] for m in range(8)]
        self.assertEqual(exact(u,3),[exact(v,3)[i] for i in perm])
    def test_repeatability(self):
        v=[m*m+.5 for m in range(256)]
        self.assertEqual(exact(v,8),exact(v,8))
    def test_incomplete_reference_rejected(self):
        with self.assertRaises(ValueError):exact([1,2],3)

class RealSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases=rows(ROOT/'data/releases/p1-v2/cases.jsonl')
        cls.case=next(c for c in cls.cases if eligibility(c)=='ELIGIBLE')
        cls.week=donor(cls.case);cls.bg=background(cls.case,cls.week)
        cls.k=read(ROOT/'experiments/q1_pilot/config.json')['panels']['p1']
    def test_groups_partition(self):
        for n in (6,8):self.assertEqual(sorted(sum(groups(n),[])),list(range(1,43)))
    def test_endpoints_identity_and_no_mutation(self):
        before=digest(self.case)
        self.assertEqual(merge(self.case,self.bg,groups(6),63),self.case)
        self.assertEqual(merge(self.case,self.bg,groups(6),0),self.bg)
        self.assertEqual(digest(self.case),before)
    def test_all_raw_children_replaced_and_target_coordinates_preserved(self):
        c=merge(self.case,self.bg,groups(6),0)
        for d,b,f in zip(c['days'],self.bg['days'],self.case['days']):
            self.assertEqual((d['day'],d['phase'],d['weekday']),(f['day'],f['phase'],f['weekday']))
            for key in ('metrics','quality_flags','missing_metrics'):self.assertEqual(d[key],b[key])
    def test_joint_recompute_matches_fresh_pipeline(self):
        g=Game(self.case,self.bg,self.k,'interaction')
        for mask in (0,1,15,31,63):self.assertEqual(g.scores(mask),score(merge(self.case,self.bg,groups(6),mask),self.k,'interaction'))
    def test_future_donor_rejected(self):
        with self.assertRaises(ValueError):validate_donor(self.case,deepcopy(self.case['days'][28:35]))
    def test_foreign_or_altered_donor_rejected(self):
        w=deepcopy(self.week);w[0]['metrics']['sleep_minutes']=999.
        with self.assertRaises(ValueError):validate_donor(self.case,w)
    def test_invalid_and_missing_donor_rejected(self):
        c=deepcopy(self.case)
        for d in c['days']:d['metrics']['sleep_minutes']=None
        with self.assertRaisesRegex(ValueError,'DONOR_UNAVAILABLE'):donor(c)
        with self.assertRaises(ValueError):background(self.case,self.week[:6])
    def test_quality_and_null_are_not_zero(self):
        d=deepcopy(self.case['days'][0]);d['metrics']['sleep_minutes']=None
        self.assertFalse(usable(d));d['metrics']['sleep_minutes']=400;d['metrics']['sleep_info_code']=1
        self.assertFalse(usable(d));d['metrics']['sleep_info_code']=None;self.assertFalse(usable(d))
    def test_zero_rhr_not_physiology(self):
        c=deepcopy(self.case)
        for d in c['days']:d['metrics']['resting_heart_rate_bpm']=0
        self.assertIsNone(summary(c)['current']['rhr']);self.assertEqual(features(c)['rhr'],0)
    def test_circular_clock(self):
        self.assertEqual(clock_minutes('23:59:00'),1439.)
        with self.assertRaises(ValueError):clock_minutes('25:00:00')
    def test_fixed_candidates_and_target(self):
        s=score(self.case,self.k,'additive');self.assertEqual(list(s),self.k)
        self.assertEqual(target(s),s['K006']-s['K017'])
        with self.assertRaises(ValueError):score(self.case,['UNKNOWN'],'additive')
    def test_item_only_all_coalitions_zero(self):
        g=Game(self.case,self.bg,self.k,'item_only');v=g.table()
        self.assertEqual(exact(v,6),[0.]*6)
    def test_real_reference_repeat_and_efficiency(self):
        a=Game(self.case,self.bg,self.k,'interaction').table();b=Game(self.case,self.bg,self.k,'interaction').table()
        self.assertEqual(a,b);self.assertLess(efficiency(exact(a,6),a),1e-10)
    def test_cache_counting(self):
        g=Game(self.case,self.bg,self.k,'additive');g.value(0);g.value(0)
        self.assertEqual((g.scorer_calls,g.requests),(1,2))
    def test_additive_mean_preserving_reverse_invariant(self):
        b={r['control']:r for r in behavior(self.case,self.k,'additive')}
        self.assertAlmostEqual(b['reverse_current']['margin_delta'],0,places=10)
        self.assertEqual(b['unused_context']['margin_delta'],0)
    def test_policy_weights_equal_frozen_configuration(self):
        config=read(ROOT/'experiments/q1_pilot/config.json')
        self.assertEqual(WEIGHTS,config['scorer_policy']['additive'])
    def test_no_raw_missing_values_filled(self):
        for d in self.bg['days']:
            src=self.week[(d['day']-1)%7]
            self.assertEqual(d['metrics'],src['metrics'])

class OfficialAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:import numpy,shap
        except ImportError:raise unittest.SkipTest('Official dependencies require local/q1-venv; core tests remain stdlib-only')
        from src.q1_pilot import baseline_adapters as official
        if not all((official.UPSTREAM/n).exists() for n in official.PINS):raise unittest.SkipTest('Fixed official checkouts unavailable')
        cls.case=next(c for c in rows(ROOT/'data/releases/p1-v2/cases.jsonl') if eligibility(c)=='ELIGIBLE')
        cls.bg=background(cls.case,donor(cls.case));cls.k=cls.case['candidate_ids'];cls.official=official
    def game(self,qoi='margin'):return Game(self.case,self.bg,self.k,'interaction',6,qoi)
    def test_rankingshap_full_budget_matches_same_game(self):
        v=self.game().table();p,r=self.official.rankingshap(self.game(),62)
        self.assertLess(metrics(p,exact(v,6),v[-1]-v[0])['max_abs_error'],1e-8)
        self.assertLessEqual(r['unique_coalitions'],64)
    def test_sharp_margin_matches_same_game(self):
        v=self.game().table();p,r=self.official.sharp(self.game())
        self.assertLess(metrics(p,exact(v,6),v[-1]-v[0])['max_abs_error'],1e-8)
        self.assertEqual(r['scorer_calls'],64)
    def test_sharp_outcome_separate_reference(self):
        v=self.game('pair').table();p,r=self.official.sharp(self.game('pair'))
        self.assertLess(metrics(p,exact(v,6),v[-1]-v[0])['max_abs_error'],1e-8)
    def test_official_item_only_dummy_control(self):
        for method in ('rankingshap','sharp'):
            g=Game(self.case,self.bg,self.k,'item_only')
            p,_=self.official.rankingshap(g,62) if method=='rankingshap' else self.official.sharp(g)
            self.assertTrue(all(abs(v)<1e-8 for v in p))
    def test_flow_separate_edge_cuts_conserve(self):
        f=self.official.flow(self.game(),8)
        self.assertLess(max(f['cut_residuals'].values()),1e-8)
        self.assertLess(f['max_node_conservation_residual'],1e-8)
    def test_flow_seed_replay_with_canonical_graph_order(self):
        a=self.official.flow(self.game(),8,0);b=self.official.flow(self.game(),8,0)
        def edges(x):return sorted((e['from'],e['to'],e['credit']) for e in x['edge_credits'])
        self.assertEqual(edges(a),edges(b))
    def test_native_flow_exact_boundary_consistency(self):
        import numpy as np
        f=self.official.load('Shapley-Flow')
        x=f.Node('x');z=f.Node('z');h=f.Node('h',lambda x:2*x,[x])
        y=f.Node('target',lambda h,z:h+z+h*z,[h,z],is_target_node=True)
        g=f.Graph([x,z,h,y],{'x':lambda:0.,'z':lambda:0.},{'x':lambda:1.,'z':lambda:1.})
        cuts=[]
        for graph in (g,f.boundary_graph(g,[])):
            graph.nodes.sort(key=lambda n:n.name)
            cf=f.CreditFlow(graph,nruns=-1,silent=True);cf.run(method='divide_and_conquer')
            seed={b.name:float(np.asarray(v).ravel()[0]) for a,d in cf.edge_credit.items() if a.name=='seed' for b,v in d.items()}
            self.assertEqual(seed,{'x':3.,'z':2.});cuts.append(seed)
        self.assertEqual(cuts[0],cuts[1])
    def test_official_placeholder_offset_reproduced(self):
        import numpy as np
        mod=self.official.load('RankingShap')
        # Native constructor's placeholder fnull is zero, while configured real
        # scalar target has baseline=2. This is an interface issue, not XAI novelty.
        state={}
        def pred(x):
            state['v']=2+float(np.asarray(x)[0,0]);return np.array([state['v'],0.])
        obj=mod.RankingShap('kernel',np.zeros((1,2)),pred,explanation_size=2,nsample_permutations=2,rank_similarity_coefficient=lambda a,b:state['v'])
        _,e=obj.get_query_explanation(np.ones((2,2)))
        self.assertAlmostEqual(sum(v for _,v in e.explanation),3.)
        self.assertAlmostEqual(obj.explainer.expected_value,0.)
        import shap
        from functools import partial
        obj.explainer=shap.KernelExplainer(partial(obj.new_model_predict,query_features=np.ones((2,2))),np.zeros((1,2)))
        _,fixed=obj.get_query_explanation(np.ones((2,2)))
        self.assertAlmostEqual(sum(v for _,v in fixed.explanation),1.)

class SummaryTests(unittest.TestCase):
    def test_metrics_zero_reference(self):
        m=metrics([0,0],[0,0],0);self.assertIsNone(m['sign_agreement_nonzero']);self.assertEqual(m['mae'],0)
    def test_cluster_unit(self):
        r=[{'subject_id':'fixture1','x':0.}]*8+[{'subject_id':'fixture2','x':2.}]
        self.assertEqual(clustered(r,'x')['mean'],1.)

if __name__=='__main__':unittest.main()
