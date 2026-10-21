"""Actual sealed Day 5 kits/logic; no fabricated human outcomes."""
from collections import Counter,defaultdict
from html.parser import HTMLParser
from pathlib import Path
import unittest
import zipfile

from src.common import ROOT,read,rows,sha,digest,Blocked
from src.datasets.v2_sources import verify
from src.day5.pilot import PREPARED,BASE,load
from src.day5.review import validate_human_form


@unittest.skipUnless((BASE/'mechanism-v01/freeze.json').exists(),'Day 5 artifacts absent')
class Day5Artifacts(unittest.TestCase):
    def test_sealed_inputs_outputs_and_immutable_history(self):
        load();verify(BASE/'mechanism-v01');verify(BASE/'distribution-v01')
        for name,h in read(BASE/'boundary-before-v01.json').items():self.assertEqual(sha(ROOT/name),h,name)

    def test_all_real_missing_all_synthetic_disclosed(self):
        scenes=rows(PREPARED/'scenarios.jsonl');self.assertEqual(len(scenes),18)
        real=[s for s in scenes if s['data_origin'].startswith('REAL')];self.assertEqual(len(real),12)
        self.assertTrue(all(e['status']=='NOT_COLLECTED' and e['value'] is None for s in real for e in s['context_evidence']))
        self.assertTrue(all(not s['primary_real_context_collected'] for s in scenes))
        self.assertEqual(sum(s['data_origin']=='SYNTHETIC_MECHANISM_ONLY' for s in scenes),6)

    def test_factorial_edges_change_only_declared_context(self):
        scenes={s['case_id']:s for s in rows(PREPARED/'scenarios.jsonl')}
        for edge in read(PREPARED/'synthetic_matched_contrasts.json')['edges']:
            left={e['variable']:e['value'] for e in scenes[edge['left']]['context_evidence']}
            right={e['variable']:e['value'] for e in scenes[edge['right']]['context_evidence']}
            self.assertEqual([k for k in left if left[k]!=right[k]],[edge['only_changed']])
            self.assertEqual(scenes[edge['left']]['goal'],scenes[edge['right']]['goal'])

    def test_packet_orientations_repeat_mirror_and_same_evidence(self):
        mapping=read(PREPARED/'PRIVATE_mapping.json')
        for slot,sessions in mapping.items():
            bycase=defaultdict(dict)
            for session,packets in sessions.items():
                self.assertEqual(len(packets),18)
                for packet_id,m in packets.items():bycase[m['case_id']][session]=m
            for case,items in bycase.items():
                a,b,c=[items[f'SESSION_{n}'] for n in (1,2,3)]
                self.assertEqual((a['left'],a['right']),(b['right'],b['left']))
                self.assertEqual((a['left'],a['right']),(c['left'],c['right']))
                self.assertEqual(set(a['evidence_ids'].values()),set(b['evidence_ids'].values()))
                self.assertEqual(set(a['evidence_ids'].values()),set(c['evidence_ids'].values()))

    def test_empty_human_forms_are_not_judgments(self):
        mapping=read(PREPARED/'PRIVATE_mapping.json')
        for slot in ('RATER_A','RATER_B'):
            for session in ('SESSION_1','SESSION_2','SESSION_3'):
                form=read(PREPARED/'reviewers'/slot/session/'judgments.template.json')
                self.assertIsNone(form['reviewer_id']);self.assertFalse(form['human_attestation'])
                self.assertTrue(all(j['preference'] is None and j['annotation_status']=='UNFILLED' for j in form['judgments']))
                with self.assertRaises(Blocked):validate_human_form(form,mapping[slot][session],session)

    def test_blind_zip_inventory_no_private_maps_scores_or_expected_labels(self):
        paths=list((BASE/'distribution-v01').glob('*.zip'));self.assertEqual(len(paths),6)
        for p in paths:
            with zipfile.ZipFile(p) as z:
                names=z.namelist();self.assertTrue(all('PRIVATE' not in n and 'expected' not in n.lower() for n in names))
                self.assertEqual(sum(n.endswith('packets.jsonl') for n in names),1)
                self.assertFalse(any('stage_decision' in n or 'source_condition_matrix' in n or 'ranker' in n for n in names))

    def test_offline_reader_safe_and_contains_all_packets(self):
        class Parser(HTMLParser):
            def __init__(self):super().__init__();self.articles=0;self.external=[]
            def handle_starttag(self,tag,attrs):
                if tag=='article':self.articles+=1
                if tag in ('script','iframe','img') or any(k=='src' for k,v in attrs):self.external.append(tag)
        for p in (PREPARED/'reviewers').glob('*/SESSION_*/review.html'):
            parser=Parser();parser.feed(p.read_text(encoding='utf-8'))
            self.assertEqual(parser.articles,18);self.assertEqual(parser.external,[])

    def test_mechanism_is_logic_not_priority_or_utility(self):
        result=read(BASE/'mechanism-v01/stage_decision.json');self.assertEqual(result['status'],'INSUFFICIENT_EVIDENCE')
        self.assertIsNone(result['five_stages']['acquisition_gain']['Observed_delta_U'])
        self.assertEqual(result['five_stages']['reference_reliability']['actual_reviewers'],0)
        actions=rows(BASE/'mechanism-v01/synthetic_acquisition_steps.jsonl');self.assertEqual(len(actions),12)
        grouped=defaultdict(list)
        for a in actions:
            self.assertEqual(a['data_origin'],'SYNTHETIC_MECHANISM_ONLY');self.assertEqual(a['cost'],1)
            self.assertIsNone(a['state']['ranking']);grouped[a['case_id']].append(a)
        self.assertTrue(all(len({x['initial_observation_hash'] for x in group})==1 for group in grouped.values()))


if __name__=='__main__':unittest.main()
