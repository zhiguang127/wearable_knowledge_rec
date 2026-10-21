"""Synthetic software fixtures only; these do not establish real relevance qrels."""
from copy import deepcopy
from datetime import date,timedelta
import unittest

from src.common import ROOT,Blocked,rows
from src.datasets.probes import catalog
from src.day1.evidence import EvidenceProvider
from src.day4.core import MechanismRanker,Environment,arm_actions,normalized_change
from src.day4.pairs import build_pairs
from src.day4.reference import errors,normalize
from src.day4.analysis import signal_gate,pair_comparisons


def fixture(days=42):
    end=date(2026,1,31);probes=catalog()
    case={'case_id':'synthetic-software-only','end_date':end.isoformat(),'days':[
        {'date':(end-timedelta(days=days-1-i)).isoformat(),'metrics':{'steps':1000+10*i,'rhr':60+i/100,'sleep_duration':8},'quality_flags':[]} for i in range(days)]}
    query={'case_id':case['case_id'],'candidate_ids':['a','b'],'topic':'physical_activity','goal':'Fixed test goal',
           'links':{'a':{'direction':1,'magnitude':0},'b':{'direction':-1,'magnitude':0}}}
    units=[{'knowledge_id':'a'},{'knowledge_id':'b'}]
    return case,query,units,probes


class Day4Tests(unittest.TestCase):
    def test_normalization_physical(self):
        self.assertEqual(normalized_change(0,0),0)
        self.assertAlmostEqual(normalized_change(10,2),2/18)
        self.assertAlmostEqual(normalized_change(10,-2),-2/22)
        with self.assertRaises(Blocked):normalized_change(1,2)

    def test_matched_C_D_same_function_both_can_change_scores(self):
        c,q,u,p=fixture();provider=EvidenceProvider(c,p);seed,actions=arm_actions(q,p)
        states={}
        for arm in ('C','D'):
            env=Environment(q,u,provider,p);initial=env.reset(seed,1);state,cost,done=env.step(actions[arm])
            self.assertEqual(cost,1);self.assertTrue(done);self.assertTrue(state['mechanism_comparison_resolved'])
            self.assertGreater(state['ranking'][0][1],0);states[arm]=initial
        self.assertEqual(states['C'],states['D'])

    def test_insufficient_action_still_costs_and_is_not_negative(self):
        c,q,u,p=fixture(14);env=Environment(q,u,EvidenceProvider(c,p),p);seed,actions=arm_actions(q,p)
        env.reset(seed,1);state,cost,done=env.step(actions['C'])
        self.assertEqual(cost,1);self.assertTrue(done);self.assertFalse(state['mechanism_comparison_resolved'])
        self.assertTrue(all(r[1]==0 for r in state['ranking']))
        with self.assertRaises(Blocked):env.step(actions['C'])

    def test_illegal_stale_duplicate_and_zero_budget(self):
        c,q,u,p=fixture();env=Environment(q,u,EvidenceProvider(c,p),p);seed,actions=arm_actions(q,p)
        state=env.reset(seed,1)
        with self.assertRaises(Blocked):env.step(seed[0])
        with self.assertRaises(Blocked):env.step('nonexistent')
        env.step(actions['D'])
        with self.assertRaises(Blocked):env.available_actions(state)
        self.assertEqual(env.available_actions(env.observation()),[])

    def test_no_provider_or_hidden_results_in_observation(self):
        c,q,u,p=fixture();env=Environment(q,u,EvidenceProvider(c,p),p);seed,_=arm_actions(q,p)
        obs=env.reset(seed,1)
        self.assertEqual({e['probe_id'] for e in obs['observed_evidence']},set(seed))
        self.assertEqual(set(obs),{'query','observed_evidence','remaining_budget','ranking','mechanism_comparison_resolved','ranker_version'})

    def test_wrong_window_and_future_rejected(self):
        c,q,u,p=fixture();e=EvidenceProvider(c,p).get(arm_actions(q,p)[0][0]);e['case_id']='wrong'
        with self.assertRaises(Blocked):MechanismRanker().rank(q,[e],u,p)
        c['days'][-1]['date']='2030-01-01'
        with self.assertRaises(Blocked):EvidenceProvider(c,p)

    def test_control_units_do_not_gain_a_diagnosis(self):
        c,q,u,p=fixture();q['links']={k:{'direction':0,'magnitude':0} for k in ('a','b')}
        env=Environment(q,u,EvidenceProvider(c,p),p);seed,actions=arm_actions(q,p);env.reset(seed,1)
        state,_,_=env.step(actions['C']);self.assertTrue(all(x[1]==0 for x in state['ranking']))

    def test_mirror_normalization(self):
        j={'preference':'LEFT','grade_left':3,'grade_right':1,'basis':'GOAL_ONLY','source_relation':'NO_SUPPORTED_PERSONAL_BRIDGE',
           'evidence_ids':[],'source_span_ids_left':['s1'],'source_span_ids_right':['s2'],'reason':'why','limitations':'unknown'}
        normalized=normalize(j,'b','a');self.assertEqual(normalized['preference'],-1)
        self.assertEqual(normalized['grades'],{'a':1,'b':3})

    def test_gate_excludes_goal_only_and_unknown_changes(self):
        base={'pair_id':'p','scenario_id':'1','participant':'p1','preference':1,'basis':'GOAL_ONLY','measurement_signature':'x','evidence_ids':[]}
        other={**base,'scenario_id':'2','participant':'p2','preference':-1,'measurement_signature':'y'}
        self.assertFalse(signal_gate(pair_comparisons([base,other])))
        other['basis']='DESCRIPTIVE_EVIDENCE';other['evidence_ids']=['real-bound-in-pipeline']
        self.assertEqual(signal_gate(pair_comparisons([base,other])),['p'])
        other['preference']=None;self.assertFalse(signal_gate(pair_comparisons([base,other])))

    def test_same_evidence_opposition_not_signal(self):
        a={'pair_id':'p','scenario_id':'1','participant':'p','preference':1,'basis':'DESCRIPTIVE_EVIDENCE','measurement_signature':'same','evidence_ids':['e']}
        b={**a,'scenario_id':'2','preference':-1}
        comparisons=pair_comparisons([a,b]);self.assertTrue(comparisons[0]['same_cited_measurement_opposite'])
        self.assertFalse(signal_gate(comparisons))

    def test_pairs_complete_fixed_and_not_verified_rules(self):
        pairs=build_pairs(rows(ROOT/'local/day2/prepared-v01/knowledge_units.jsonl'))
        self.assertEqual(len(pairs),8);self.assertEqual(sum(p['control'] for p in pairs),3)
        self.assertTrue(all(p['hypothesis_not_source_priority_rule'] for p in pairs))
        self.assertTrue(all(len(p['source_relations'])==2 and p['goal'] for p in pairs))

    def test_reference_binding_and_unknown_not_false(self):
        pair={'left':'a','right':'b','topic':'sleep'}
        payload={'knowledge':[{'candidate_id':'a','source_spans':[{'span_id':'s1'}]},
                              {'candidate_id':'b','source_spans':[{'span_id':'s2'}]}],
                 'evidence':[{'evidence_id':'e','status':'INSUFFICIENT_INFORMATION','metric':'sleep_duration'}]}
        j={'preference':'UNKNOWN','grade_left':None,'grade_right':None,'basis':'INSUFFICIENT_EVIDENCE',
           'evidence_ids':['e'],'source_span_ids_left':['s1'],'source_span_ids_right':['s2'],
           'reason':'Missing context','limitations':'Unknown symptoms','source_relation':'NO_SUPPORTED_PERSONAL_BRIDGE'}
        self.assertEqual(errors(j,pair,payload),[])
        j.update(preference='LEFT',grade_left=3,grade_right=1,basis='DESCRIPTIVE_EVIDENCE',source_relation='INFERENTIAL_RELEVANCE')
        self.assertIn('INSUFFICIENT_RESULT_AS_POSITIVE_SUPPORT',errors(j,pair,payload))
        j['source_span_ids_left']=['s2'];self.assertIn('WRONG_LEFT_SOURCE_SPAN',errors(j,pair,payload))


if __name__=='__main__':unittest.main()
