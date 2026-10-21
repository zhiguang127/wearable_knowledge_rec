"""Actual Day 4 traces, paired control fairness and unknown-preserving amendment."""
from collections import defaultdict
from pathlib import Path
import json
import unittest

from src.common import ROOT,read,rows,digest,sha
from src.datasets.v2_sources import verify
from src.day1.structured import build_request,ANNOTATION_FUNCTION
from src.day4.pilot import design
from src.day4.reference import PROMPT
from src.day4_revalidation import amended_schema,unknown_goal_errors

BASE=ROOT/'local/day4'


class GoalUnknownAmendment(unittest.TestCase):
    def test_extension_does_not_change_original_schema(self):
        original={'properties':{'judgments':{'items':{'properties':{n:{'type':'string','enum':['DIRECT','BACKGROUND','OFF_TOPIC']} for n in ('goal_left','goal_right')}}}}}
        before=digest(original);new=amended_schema(original)
        self.assertEqual(digest(original),before)
        self.assertIn(None,new['properties']['judgments']['items']['properties']['goal_left']['enum'])

    def test_unknown_goal_does_not_make_a_known_negative(self):
        j={'goal_left':'UNKNOWN','goal_right':None,'preference':'UNKNOWN','grade_left':None,'grade_right':None}
        self.assertEqual(unknown_goal_errors(j),[])
        j.update(preference='RIGHT',grade_left=0,grade_right=3)
        self.assertTrue(unknown_goal_errors(j))


@unittest.skipUnless((BASE/'analysis-v01r1/freeze.json').exists(),'Day 4 actual run absent')
class Day4ActualArtifacts(unittest.TestCase):
    def test_all_sealed_layers_and_original_code(self):
        design()
        for name in ('design-v01','reference-prepared-v01','reference-executed-v01','schema-amendment-v01r1','reference-revalidated-v01r1','analysis-v01r1'):
            verify(BASE/name)

    def test_raw_traces_exact_and_no_extra_revalidation_calls(self):
        ledger=BASE/'qwen-ledger-v01';requests=list((ledger/'requests').glob('*.json'));cache=list((ledger/'cache').glob('*.json'))
        self.assertEqual(len(requests),48);self.assertEqual(len(cache),48)
        for p in cache:
            trace=read(p)
            self.assertEqual(trace['response_sha256'],digest(trace['response']))
            self.assertEqual(trace['request_sha256'],digest(read(ledger/'requests'/p.name)))
            self.assertFalse(trace['human_gold'])
        r1=read(BASE/'reference-revalidated-v01r1/summary.json')
        self.assertEqual(r1['new_model_calls'],0);self.assertFalse(r1['grades_or_preferences_edited'])
        self.assertEqual(r1['original_failed_tasks_now_revalidated'],7)

    def test_actual_sent_payloads_are_prepared_blinded_inputs(self):
        hashes={read(p)['request_sha256'] for p in (BASE/'qwen-ledger-v01/cache').glob('*.json')}
        model=read(BASE/'design-v01/model_config.json')
        for t in rows(BASE/'reference-prepared-v01/reference_tasks.jsonl'):
            payload=t['payload'];self.assertEqual(len(payload['evidence']),288)
            self.assertNotIn('links',payload);self.assertNotIn('ranking',payload);self.assertNotIn('labels',payload)
            for p in payload['pairs']:
                self.assertEqual(set(p),{'pair_id','topic','goal','query_basis','left','right'})
            req=build_request([{'role':'system','content':PROMPT},{'role':'user','content':json.dumps(payload,ensure_ascii=False)}],model,t['schema'],ANNOTATION_FUNCTION)
            self.assertIn(digest(req),hashes)

    def test_reference_raw_judgments_not_repaired(self):
        records=rows(BASE/'reference-revalidated-v01r1/reference_results.jsonl')
        self.assertEqual(sum(len(r['judgments']) for r in records),192)
        for r in records:
            for j in r['judgments']:
                self.assertEqual(j['row_hash'],digest(j['input_row']))
                original=j['input_row']
                if original['preference']=='UNKNOWN':self.assertIsNone(j['preference'])
                self.assertEqual(sorted(j['grades'].values(),key=lambda v:-1 if v is None else v),
                                 sorted([original['grade_left'],original['grade_right']],key=lambda v:-1 if v is None else v))

    def test_real_cases_not_selected_by_values_or_human_gold(self):
        sc=rows(BASE/'reference-prepared-v01/scenarios.jsonl');self.assertEqual(len(sc),12)
        self.assertEqual(len({s['participant'] for s in sc}),3)
        self.assertEqual(sum(s['history_days']==42 for s in sc),9)
        self.assertTrue(all(s['data_origin']=='REAL_WEARABLEQA' for s in sc))
        audit=read(BASE/'reference-prepared-v01/EVIDENCE_DISCRIMINABILITY_AUDIT.json')
        self.assertEqual(audit['results'],3456);self.assertFalse(audit['selection_using_values_or_labels'])
        self.assertEqual(audit['synthetic_research_cases'],0)

    def test_all_C_D_D0_share_seeds_and_cost_missing_actions(self):
        grouped=defaultdict(list)
        actions=rows(BASE/'analysis-v01r1/acquisition_actions.jsonl');self.assertEqual(len(actions),288)
        for a in actions:
            grouped[a['scenario_id'],a['pair_id']].append(a)
            self.assertEqual(a['cost'],1)
        for group in grouped.values():
            self.assertEqual({r['arm'] for r in group},{'C','D','D0'})
            self.assertEqual(len({r['initial_observation_hash'] for r in group}),1)
        self.assertTrue(any(r['acquired_status']=='INSUFFICIENT_INFORMATION' for r in actions))
        mechanism=read(BASE/'analysis-v01r1/mechanism_results.json')
        self.assertGreater(mechanism['rank_change_summary']['B_D']['ranking_changed'],0)

    def test_unsupported_reference_does_not_become_zero_utility(self):
        decision=read(BASE/'analysis-v01r1/stage_decision.json')
        self.assertFalse(decision['ranking_utility_executed']);self.assertIsNone(decision['real_C_minus_D_ndcg5'])
        for r in rows(BASE/'analysis-v01r1/matched_evaluation.jsonl'):
            for m,d in r['value'].items():self.assertTrue(all(v is None for v in d.values()))
        for q in rows(BASE/'analysis-v01r1/shared_full_record_qrels.jsonl'):
            self.assertFalse(q['human_gold'])
            if q['reference_status']=='REVIEW_REQUIRED':self.assertTrue(all(v is None for v in q['grades'].values()))

    def test_human_materials_are_unfilled(self):
        p=BASE/'reference-prepared-v01/human_review'
        template=read(p/'template.json');self.assertFalse(template['human_attestation']);self.assertIsNone(template['reviewer_id'])
        self.assertEqual(template['responses'],[]);self.assertEqual(len(rows(p/'packets.jsonl')),24)

    def test_historical_boundary_preserved(self):
        for name,h in read(BASE/'boundary-before-v01.json').items():
            if name!='README.md':self.assertEqual(sha(ROOT/name),h,name)


if __name__=='__main__':unittest.main()
