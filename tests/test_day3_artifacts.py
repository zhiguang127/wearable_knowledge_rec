"""Integration checks over the actual Day 3 artifacts (no model requests)."""
from itertools import groupby
import math
from pathlib import Path
import unittest

from src.common import ROOT, read, rows, sha
from src.datasets.v2_sources import verify
from src.day3.importer import verify_human_payload


@unittest.skipUnless((ROOT/'local/day3/evaluated-v01/freeze.json').exists(), 'Day 3 run not present')
class ActualDay3Artifacts(unittest.TestCase):
    root=ROOT/'local/day3/evaluated-v01'

    def test_sealed_artifacts(self):
        for name in ('preregistered-v01','imported-v01','evaluated-v01'):
            verify(ROOT/'local/day3'/name)
        r=verify_human_payload(ROOT/'local/day2/human-review-v01',['human-review-v01.zip'])
        self.assertEqual(r['original_files_verified'],13)

    def test_all_existing_code_preserved(self):
        boundary=read(ROOT/'local/day3/boundary-before-v01.json')
        for name,h in boundary.items():
            if name!='README.md':self.assertEqual(sha(ROOT/name),h,name)

    def test_independent_DCG_arithmetic_on_actual_rankings(self):
        qrels={q['query_id']:{r['knowledge_id']:r['grade'] for r in q['entries']} for q in rows(self.root/'shared_F_qrels.jsonl')}
        result={r['query_id']:r for r in rows(self.root/'matched_evaluation.jsonl')}
        for ranking in rows(self.root/'ranking_replay.jsonl'):
            grades=qrels[ranking['query_id']]
            for k in (3,5):
                ideal=sorted((2**g-1 for g in grades.values() if g is not None),reverse=True)
                idcg=sum(g/math.log2(i+2) for i,g in enumerate(ideal[:k]))
                dcg=0;position=0
                known=[r for r in ranking['ranking'] if grades[r[0]] is not None]
                for _,items in groupby(known,key=lambda r:r[1]):
                    block=list(items);expected_gain=sum(2**grades[r[0]]-1 for r in block)/len(block)
                    for i in range(position,min(position+len(block),k)):dcg+=expected_gain/math.log2(i+2)
                    position+=len(block)
                self.assertAlmostEqual(dcg/idcg,result[ranking['query_id']]['arms'][ranking['arm']][f'ndcg@{k}'])

    def test_zero_deltas_explained_by_equal_grade_pairs(self):
        attribution=rows(self.root/'pair_attribution.jsonl')
        self.assertEqual(len(attribution),5)
        self.assertEqual(len({p['participant'] for p in attribution}),3)
        self.assertTrue(all(p['reference_preference']==0 for p in attribution))
        records=rows(self.root/'matched_evaluation.jsonl')
        self.assertEqual(len(records),12)
        for r in records:
            for m,v in r['value'].items():self.assertEqual(v,{'delta_C':0.0,'delta_D':0.0,'delta_delta':0.0})

    def test_reference_layer_and_assessor_boundary(self):
        labels=rows(ROOT/'local/day3/imported-v01/labels.jsonl')
        self.assertEqual(len(labels),546)
        self.assertTrue(all(r['layer']=='AI_REFERENCE_V01' and not r['human_gold'] for r in labels))
        self.assertEqual({r['reviewer_id'] for r in labels},{'GPT-6_AI_REFERENCE'})
        for q in rows(self.root/'shared_F_qrels.jsonl'):
            self.assertTrue(all(r['source_task'].endswith('-F') for r in q['entries']))
            self.assertFalse(q['human_gold'])
        self.assertTrue(read(self.root/'stage_decision.json')['unresolved_assessor_isolation'])

    def test_historical_negative_control_not_erased(self):
        old=read(ROOT/'local/day2/analysis-qualified-v01/report.json')['matched_changed_pair_counts_silver']
        new=read(self.root/'signal_diagnostics.json')['day2_negative_control']
        self.assertEqual(new['B_C_silver_changed_relations'],old['B_C'])
        self.assertEqual(new['B_D_silver_changed_relations'],old['B_D'])
        self.assertFalse(new['resolved_by_this_AI_template_consistency'])


if __name__=='__main__':unittest.main()
