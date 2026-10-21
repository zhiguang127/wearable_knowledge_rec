"""Source/context, hidden-input, unknown, utility and real-human boundary regressions."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from src.common import ROOT, Blocked, read
from src.day2.knowledge import build_units,validate_units
from src.day2.core import (DiagnosticRanker,PilotEnvironment,graded_utility,reference_utility,expected_gain,
                           ranking_relations,validate_judgment,source_errors)
from src.day2.schemas import judgment_schema
from src.day2.human import validate_form,adjudicate
from src.day2.client import Day2Client
from src.day2.standard_schema import standard_schema,standard_errors
from src.day2.qualification import validate_findings


class Day2SourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config=read(ROOT/'configs/c1_day2_pilot_v01.json')
        cls.units=build_units(cls.config)

    def test_complete_units_keep_short_qualifiers_and_child_age_list(self):
        self.assertEqual(len(self.units),21)
        u=next(u for u in self.units if u['source']['article_title']=='Get Enough Sleep' and u['source']['section_id']=='0')
        self.assertIn('Kids need even more sleep than adults:',u['text'])
        self.assertIn('age 0 to 3 months',u['text'])
        self.assertIn('7 or more hours',u['text'])
        self.assertIn('Most adults',u['article_context'])

    def test_tampering_unit_or_population_context_is_detected(self):
        changed=deepcopy(self.units);changed[0]['text']+='invented rule'
        with self.assertRaises(Blocked):validate_units(changed,self.config)
        changed=deepcopy(self.units);changed[0]['article_context']=''
        with self.assertRaises(Blocked):validate_units(changed,self.config)

    def test_source_review_cannot_admit_a_new_hard_gate(self):
        u=self.units[0]
        review={'knowledge_id':u['knowledge_id'],'meaning_preserved':True,'standalone_context_sufficient':True,
                'facets':[],'hard_gate_assessable':True,'rationale':'unadjudicated proposal'}
        self.assertIn('new_hard_gate_claim_requires_separate_semantic_adjudication',source_errors(review,u))


class Day2JudgmentTests(unittest.TestCase):
    def setUp(self):
        self.units=[{'knowledge_id':'k1','source_spans':[{'span_id':'s1'}],'descriptive_context_link':1},
                    {'knowledge_id':'k2','source_spans':[{'span_id':'s2'}],'descriptive_context_link':0}]
        self.evidence=[{'evidence_id':'e1','metric':'steps','status':'COMPUTED'}]
        self.output={'task_id':'t','judgments':[
            {'knowledge_id':'k1','grade':2,'basis':'PERSONAL_EVIDENCE_CONTEXT','evidence_ids':['e1'],'source_span_ids':['s1'],'unmeasured_context':[],'rationale':'context'},
            {'knowledge_id':'k2','grade':None,'basis':'UNDETERMINED','evidence_ids':[],'source_span_ids':['s2'],'unmeasured_context':['age'],'rationale':'unknown'}], 'rationale':'fixture'}

    def errors(self):return validate_judgment(self.output,'t',self.units,self.evidence,'steps')

    def test_valid_unknown_is_preserved(self):self.assertEqual(self.errors(),[])

    def test_cross_window_or_hidden_evidence_id_is_rejected(self):
        self.output['judgments'][0]['evidence_ids']=['not-acquired']
        self.assertTrue(self.errors())

    def test_foreign_source_span_is_rejected(self):
        self.output['judgments'][0]['source_span_ids']=['s2']
        self.assertIn('wrong_unit_or_empty_source_span',self.errors())

    def test_missing_is_not_positive_support_and_unrelated_probe_is_not_topic_state(self):
        self.evidence[0]['status']='INSUFFICIENT_INFORMATION'
        self.assertIn('insufficient_result_used_as_positive_support',self.errors())
        self.evidence[0].update(status='COMPUTED',metric='rhr')
        self.assertIn('unrelated_measurement_used_as_personal_support',self.errors())

    def test_unknown_cannot_be_replaced_by_grade_zero(self):
        self.output['judgments'][1]['grade']=0
        self.assertIn('unknown_must_have_null_grade',self.errors())

    def test_no_evidence_schema_has_a_standards_valid_empty_array_domain(self):
        s=judgment_schema('t',self.units,[])
        converted=standard_schema(s)
        self.assertEqual(converted['properties']['judgments']['items']['properties']['evidence_ids']['maxItems'],0)
        self.assertIn('enum',s['properties']['judgments']['items']['properties']['evidence_ids']['items'])
        self.output['judgments'][0].update(basis='TOPIC_OR_GOAL_ONLY',evidence_ids=[])
        self.assertEqual(standard_errors(self.output,s),[])
        self.output['judgments'][0]['evidence_ids']=['foreign']
        self.assertTrue(standard_errors(self.output,s))


class Day2UtilityTests(unittest.TestCase):
    def test_score_change_without_order_change_is_not_rank_change(self):
        self.assertEqual(ranking_relations([('a',2,1),('b',1,2)]),ranking_relations([('a',20,1),('b',10,2)]))

    def test_nonconstant_reference_unknown_projection_and_ties(self):
        rank=[('unknown',10,1),('a',1,2),('b',1,2)]
        tied=graded_utility(rank,{'unknown':None,'a':3,'b':0})
        self.assertAlmostEqual(tied,(1+1/__import__('math').log2(3))/2)
        self.assertIsNone(graded_utility(rank,{'a':1,'b':1}))
        self.assertIsNone(graded_utility(rank,{'a':None,'b':1}))

    def test_positive_zero_negative_and_expected_gain_are_distinct(self):
        grades={'a':3,'b':0}
        before=graded_utility([('a',1,1),('b',1,1)],grades)
        good=graded_utility([('a',2,1),('b',1,2)],grades)
        bad=graded_utility([('b',2,1),('a',1,2)],grades)
        self.assertGreater(good-before,0);self.assertLess(bad-before,0)
        self.assertEqual(before-before,0)
        self.assertAlmostEqual(expected_gain(before,[(.5,good),(.5,bad)]),0)

    def test_silver_reference_cannot_enter_gold_utility(self):
        with self.assertRaises(Blocked):reference_utility([('a',1,1)],{'kind':'MODEL_SILVER','annotation_status':'ACCEPTED','grades':{'a':3}},required_kind='HUMAN_GOLD')


class FakeProvider:
    def case_id(self):return 'c'
    def probe_ids(self):return ['mean','delta','unrelated']
    def get(self,pid):
        return {'case_id':'c','probe_id':pid,'evidence_id':'e-'+pid,'status':'INSUFFICIENT_INFORMATION' if pid=='unrelated' else 'COMPUTED',
                'value':{'mean':6,'delta':6,'unrelated':None}[pid]}


class Day2EnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.query={'query_id':'q','case_id':'c','subject_id':'private','topic':'sleep','goal':None,'query_basis':'TOPIC_ONLY','candidate_ids':['a','b']}
        self.units=[{'knowledge_id':'a','title':'sleep','text':'sleep','descriptive_context_link':1,'change_context_link':0},
                    {'knowledge_id':'b','title':'sleep pattern','text':'sleep pattern','descriptive_context_link':1,'change_context_link':1}]
        self.probes=[{'probe_id':pid,'metric':'rhr' if pid=='unrelated' else 'sleep_duration','operation':'mean_difference' if pid=='delta' else 'mean','window_days':14} for pid in FakeProvider().probe_ids()]

    def test_one_new_probe_can_change_diagnostic_rank_without_hidden_inputs(self):
        env=PilotEnvironment(self.query,self.units,FakeProvider(),self.probes)
        b=env.reset(['mean'])
        c,cost,done=env.step('delta')
        self.assertNotEqual(ranking_relations(b['ranking']),ranking_relations(c['ranking']))
        self.assertEqual((cost,done),(1,True))
        self.assertNotIn('subject_id',c['query'])
        self.assertEqual(len(c['observed_evidence']),2)

    def test_insufficient_still_costs_one_and_illegal_or_duplicate_actions_fail(self):
        env=PilotEnvironment(self.query,self.units,FakeProvider(),self.probes);state=env.reset(['mean'])
        self.assertNotIn('mean',env.available_actions(state))
        with self.assertRaises(Blocked):env.step('mean')
        with self.assertRaises(Blocked):env.step('illegal')
        state,cost,done=env.step('unrelated')
        self.assertEqual(cost,1);self.assertEqual(env.available_actions(state),[])


class Day2HumanBoundaryTests(unittest.TestCase):
    def form(self):
        return {'annotator_type':'HUMAN','human_attestation':True,'reviewer_id':'actual-reviewer-fixture',
                'saw_silver_or_ranker_outputs':False,'judgments':[{'packet_id':'p','candidate_id':'k','grade':None,
                    'annotation_status':'ACCEPTED','reason_code':'UNKNOWN','evidence_ids':[],'source_span_ids':['s']}]}

    def test_blank_or_model_forms_cannot_be_imported_as_human(self):
        f=self.form();f['annotator_type']='MODEL'
        with self.assertRaises(Blocked):validate_form(f,[('p','k')],{'p':{'evidence_ids':[],'source_span_ids':{'k':['s']}}})
        f=self.form();f['human_attestation']=False
        with self.assertRaises(Blocked):validate_form(f,[('p','k')],{'p':{'evidence_ids':[],'source_span_ids':{'k':['s']}}})

    def test_unknown_human_grade_and_citation_inventory(self):
        f=self.form();self.assertTrue(validate_form(f,[('p','k')],{'p':{'evidence_ids':[],'source_span_ids':{'k':['s']}}}))
        f['judgments'][0]['source_span_ids']=['foreign']
        with self.assertRaises(Blocked):validate_form(f,[('p','k')],{'p':{'evidence_ids':[],'source_span_ids':{'k':['s']}}})

    def test_existing_rater_cannot_adjudicate_even_when_all_raters_disagree(self):
        from src.common import write
        with tempfile.TemporaryDirectory() as d:
            d=Path(d);write(d/'r.json',{'accepted':[],'reviewer_ids':['A','B'],'needs_adjudication':[]})
            write(d/'f.json',{'human_attestation':True,'adjudicator_id':'A','decisions':[]})
            with self.assertRaises(Blocked):adjudicate(d/'r.json',d/'f.json',d/'out.json')

    def test_day2_transport_keeps_unlimited_authorization(self):
        cfg=read(ROOT/'configs/c1_day2_qwen_unrestricted_v01.json')
        with tempfile.TemporaryDirectory() as d:
            client=Day2Client(d,cfg,api_key='fixture',transport=lambda r:None)
            self.assertIsNone(client.config['max_calls']);self.assertIsNone(client.config['authorized_cap_cny'])

    def test_semantic_sidecar_cannot_claim_an_edited_response_or_promote_gold(self):
        from src.common import digest
        row={'knowledge_id':'k','grade':2}
        record={'output':{'judgments':[row]},'response_hash':'original'}
        finding={'task_id':'t','knowledge_id':'k','original_response_hash':'original','judgment_hash':digest(row),'annotation_status':'REVIEW_REQUIRED'}
        review={'reviewer_kind':'model','human_gold':False,'findings':[finding]}
        self.assertEqual(validate_findings(review,{'t':record}),{'t'})
        finding['original_response_hash']='fabricated'
        with self.assertRaises(Blocked):validate_findings(review,{'t':record})

    def test_private_review_ui_preserves_data_without_script_injection(self):
        from src.day2.review_ui import write_ui
        import json
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'review.html';packets=[{'text':'</script><script>unsafe</script>'}]
            write_ui(path,packets,{'judgments':[]})
            content=path.read_text(encoding='utf-8')
            embedded=content.split('<script id="payload" type="application/json">')[1].split('</script>')[0]
            self.assertEqual(json.loads(embedded)['packets'],packets)
            self.assertNotIn('</script>',embedded)


if __name__=='__main__':unittest.main()
