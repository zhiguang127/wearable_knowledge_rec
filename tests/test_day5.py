"""Synthetic software fixtures; no actual human reference or real context is generated."""
from copy import deepcopy
import unittest

from src.common import ROOT,Blocked,digest,rows
from src.day5.context import (contextual_evidence,selected_source_cues,ContextEnvironment,validate_real_form,require_utility_ready)
from src.day5.spec import VERSION,FIELDS,MEASUREMENTS,source_matrix,select_pair
from src.day5.review import validate_human_form,stable_reviewer,reconcile,adjudicate


def evidence(often='YES',caffeine='NO',origin='SYNTHETIC_MECHANISM_ONLY'):
    values=dict(zip(FIELDS,('NO',often,'NO',caffeine)))
    if origin=='REAL_NOT_COLLECTED':values={f:None for f in FIELDS}
    return contextual_evidence('SOFTWARE_FIXTURE_ONLY',values,origin,'2026-01-31T12:00:00+00:00',{'fixture':True})


def sessions(reviewer='TEST_ONLY_A',slot='RATER_A',prefs=(1,1,1)):
    return [{'reviewer_id':reviewer,'slot':slot,'prepared_id':'TEST_ONLY_PACKAGE','session_id':f'SESSION_{i+1}',
             'completed_at':f'2026-01-{1+i*3:02d}T12:00:00+00:00',
             'judgments':[{'case_id':'TEST_CASE','canonical_preference':p,'annotation_status':'ACCEPTED','data_origin':'SYNTHETIC_SOFTWARE_FIXTURE'}]}
            for i,p in enumerate(prefs)]


def source(review_id):
    units=[{'source_unit_id':'u1','source_spans':[{'span_id':'s1'}]}, {'source_unit_id':'u2','source_spans':[{'span_id':'s2'}]}]
    form={'reviewer_id':review_id,'annotator_type':'HUMAN','human_attestation':True,'source_package_hash':digest(units),
          'source_status':'SUPPORTED_WITH_LIMITS','source_does_not_entail_order':True,
          'complete_source_units_checked':['u1','u2'],'source_span_ids':['s1','s2'],'reason':'Software source-binding fixture only'}
    return form,units


class Day5Tests(unittest.TestCase):
    def test_source_conditional_advice_does_not_entail_order(self):
        units=rows(ROOT/'local/day2/prepared-v01/knowledge_units.jsonl');selection=select_pair(units)
        self.assertTrue(selection['explicit_condition_action_relation']);self.assertFalse(selection['source_entailed_relative_order'])
        matrix=source_matrix(units);self.assertEqual(len(matrix),9)
        self.assertTrue(all(not r['entails_relative_priority'] for r in matrix))
        self.assertEqual(next(r['source_quantity']['value'] for r in matrix if r['condition_id']=='D5-S6'),20)

    def test_unknown_is_not_no(self):
        result=selected_source_cues(evidence(origin='REAL_NOT_COLLECTED'))
        self.assertEqual(result['consultation_source_cue'],'UNKNOWN');self.assertIsNone(result['relative_priority'])

    def test_explicit_no_is_not_not_applicable(self):
        result=selected_source_cues(evidence('NO','NO'))
        self.assertEqual(result['consultation_source_cue'],'NO_SELECTED_CUE_REPORTED')
        self.assertEqual(result['unit_applicability'],'NO_VERIFIED_UNIT_LEVEL_GATE')

    def test_selected_positive_supports_source_action_only(self):
        result=selected_source_cues(evidence('YES','YES'))
        self.assertEqual(result['consultation_source_cue'],'SUPPORTED_SELECTED_CUE')
        self.assertEqual(result['late_caffeine_behavior_context'],'REPORTED_PRESENT')
        self.assertIsNone(result['relative_priority'])

    def test_both_actions_same_initial_and_question_cost(self):
        query={'goal':'Fixed neutral test Goal'};initial=['SR5-listed-sleep-difficulty','SR5-sleep-concern'];before=[]
        for action in ('SR5-often-trouble-sleeping','SR5-late-day-caffeine'):
            env=ContextEnvironment('SOFTWARE_FIXTURE_ONLY',evidence('UNKNOWN','UNKNOWN'),query)
            before.append(env.reset(initial,1));state,cost,done=env.step(action)
            self.assertEqual(cost,1);self.assertTrue(done);self.assertIsNone(state['ranking'])
            self.assertEqual(len(state['observed_evidence']),3)
        self.assertEqual(before[0],before[1])

    def test_hidden_context_not_acquired_and_illegal_actions(self):
        env=ContextEnvironment('SOFTWARE_FIXTURE_ONLY',evidence(),{'goal':'test'})
        old=env.reset([],1);self.assertEqual(old['observed_evidence'],[])
        with self.assertRaises(Blocked):env.step('P2-old-registry-id')
        env.step('SR5-often-trouble-sleeping')
        with self.assertRaises(Blocked):env.step('SR5-often-trouble-sleeping')
        with self.assertRaises(Blocked):env.available_actions(old)

    def test_uncollected_real_answer_is_not_a_simulated_action(self):
        env=ContextEnvironment('SOFTWARE_FIXTURE_ONLY',evidence(origin='REAL_NOT_COLLECTED'),{})
        env.reset([],1)
        with self.assertRaises(Blocked):env.step('SR5-often-trouble-sleeping')

    def test_context_hash_tampering_rejected(self):
        ev=evidence();ev[0]['value']='YES'
        with self.assertRaises(Blocked):ContextEnvironment('SOFTWARE_FIXTURE_ONLY',ev,{})

    def test_sleep_mean_does_not_measure_symptoms(self):
        self.assertEqual(selected_source_cues([{'protocol_version':'OLD_PROBE','value':4.5}])['consultation_source_cue'],'UNKNOWN')

    def test_real_context_time_and_attestation_guards(self):
        form={'protocol_version':VERSION,'data_origin':'REAL_SELF_REPORT','episode_id':'TEST_EPISODE','participant_id':'TEST_PERSON',
          'respondent_attestation':True,'source_record_sha256':'test-source-hash','collection_mode':'CONTEMPORANEOUS',
          'as_of':'2026-01-02T12:00:00+00:00','reported_at':'2026-01-02T11:00:00+00:00',
          'answers':{m['measurement_id']:{'value':'UNKNOWN','reference_start':'2026-01-01T00:00:00+00:00',
              'reference_end':'2026-01-02T10:00:00+00:00','qualifier':'Software unknown fixture only'} for m in MEASUREMENTS}}
        self.assertTrue(validate_real_form(form,'test-source-hash'))
        form['reported_at']='2026-01-03T12:00:00+00:00'
        with self.assertRaises(Blocked):validate_real_form(form,'test-source-hash')
        form['respondent_attestation']=False
        with self.assertRaises(Blocked):validate_real_form(form,'test-source-hash')

    def test_AI_and_empty_forms_rejected_as_human(self):
        for form in ({},{'annotator_type':'AI','human_attestation':True,'reviewer_id':'Qwen'}):
            with self.assertRaises(Blocked):validate_human_form(form,{},'SESSION_1')

    def test_exact_mirror_repeat_stability_no_majority(self):
        form,units=source('TEST_ONLY_A')
        good=stable_reviewer(sessions(),form,units);self.assertTrue(good['cases'][0]['stable'])
        bad=stable_reviewer(sessions(prefs=(1,1,-1)),form,units);self.assertFalse(bad['cases'][0]['stable'])
        self.assertIsNone(bad['cases'][0]['preference'])

    def test_repeat_washout_is_required(self):
        s=sessions();s[1]['completed_at']=s[0]['completed_at'];form,u=source('TEST_ONLY_A')
        with self.assertRaises(Blocked):stable_reviewer(s,form,u)

    def test_two_distinct_reviewers_and_real_disagreement(self):
        fa,u=source('TEST_ONLY_A');a=stable_reviewer(sessions(),fa,u)
        with self.assertRaises(Blocked):reconcile(a,a)
        fb,u=source('TEST_ONLY_B');b=stable_reviewer(sessions('TEST_ONLY_B','RATER_B',(-1,-1,-1)),fb,u)
        rec=reconcile(a,b);self.assertEqual(rec['cases'][0]['status'],'NEEDS_THIRD_HUMAN_ADJUDICATION')
        with self.assertRaises(Blocked):adjudicate(rec,{'human_attestation':False}, {})

    def test_unstable_cannot_be_fixed_by_adjudication(self):
        fa,u=source('TEST_ONLY_A');a=stable_reviewer(sessions(prefs=(1,-1,1)),fa,u)
        fb,u=source('TEST_ONLY_B');b=stable_reviewer(sessions('TEST_ONLY_B','RATER_B'),fb,u)
        self.assertEqual(reconcile(a,b)['cases'][0]['status'],'INTRA_RATER_UNSTABLE_NOT_REPAIRED_BY_ADJUDICATION')

    def test_no_utility_without_reliable_reference_or_real_data(self):
        for count,reference,ranker in ((0,True,'x'),(4,False,'x'),(4,True,None)):
            with self.assertRaises(Blocked):require_utility_ready(count,reference,ranker)


if __name__=='__main__':unittest.main()
