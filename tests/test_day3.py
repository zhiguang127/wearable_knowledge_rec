"""Security, reference isolation and tie-aware utility regression tests."""
import math
from pathlib import Path
import stat
import tempfile
import unittest
import zipfile

from src.common import Blocked
from src.day3.importer import safe_extract, strict_json, row_errors
from src.day3.metrics import evaluate, tau_b, changes, value_record, summarize, cost_scenarios
from src.day3.evaluate import shared_reference, compare_grades, stage_decision


class Day3Tests(unittest.TestCase):
    limits={'max_entries':10,'max_total_bytes':10000,'max_file_bytes':10000,'max_expansion_ratio':100}

    def zip_rejected(self,name,mode=None,other=None,data=b'{}',limits=None):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'x.zip'
            with zipfile.ZipFile(p,'w',compression=zipfile.ZIP_DEFLATED) as z:
                i=zipfile.ZipInfo(name)
                if mode:i.create_system=3;i.external_attr=mode<<16
                z.writestr(i,data)
                if other:z.writestr(other,b'{}')
            with self.assertRaises((Blocked,ValueError)):safe_extract(p,Path(d)/'out',limits or self.limits)

    def test_traversal(self):self.zip_rejected('../escape')
    def test_absolute(self):self.zip_rejected('/escape')
    def test_backslash(self):self.zip_rejected('..\\escape')
    def test_ads(self):self.zip_rejected('a:secret')
    def test_windows_reserved(self):self.zip_rejected('con.txt')
    def test_case_collision(self):self.zip_rejected('A.json',other='a.json')
    def test_symlink(self):self.zip_rejected('link',stat.S_IFLNK|0o777)
    def test_size_limit(self):self.zip_rejected('a',data=b'x'*101,limits={**self.limits,'max_total_bytes':100})
    def test_json_duplicate(self):
        with self.assertRaises(Blocked):strict_json('{"grade":1,"grade":2}')
    def test_nonfinite(self):
        with self.assertRaises(ValueError):strict_json('{"grade":NaN}')
    def test_no_overwrite_extraction(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'x.zip'
            with zipfile.ZipFile(p,'w') as z:z.writestr('a',b'{}')
            out=Path(d)/'out';out.mkdir()
            with self.assertRaises(Blocked):safe_extract(p,out,self.limits)

    def test_kendall(self):
        self.assertEqual(tau_b([1,2,3],[1,2,3]),1)
        self.assertEqual(tau_b([1,2,3],[3,2,1]),-1)
        self.assertIsNone(tau_b([1,1],[1,2]))
        self.assertAlmostEqual(tau_b([12,2,1,12,2],[1,4,7,1,0]),-0.47140452079103173)
    def test_unknown_is_not_zero(self):
        r=[('a',2,1),('b',1,2),('c',0,3)]
        self.assertEqual(evaluate(r,{'a':3,'b':None,'c':0})['ndcg@3'],1)
        self.assertIsNone(evaluate(r,{'a':3,'b':None})['ndcg@5'])
    def test_tie_expected_gain(self):
        r=[('a',1,1),('b',1,1)]
        m=evaluate(r,{'a':3,'b':0})
        self.assertAlmostEqual(m['ndcg@3'],(1+1/math.log2(3))/2)
        self.assertEqual(m['pairwise_agreement'],.5)
        self.assertIsNone(m['kendall_tau_b'])
    def test_tied_reference_is_not_preference(self):
        m=evaluate([('a',1,1),('b',0,2)],{'a':2,'b':2})
        self.assertIsNone(m['pairwise_agreement']);self.assertIsNone(m['ndcg@5'])
    def test_no_arm_fallback(self):
        q={'query_id':'q','candidate_ids':['a','b']}
        labels=[{'task_id':'A','knowledge_id':'a','grade':3}]
        g,e=shared_reference(q,[{'query_id':'q','arm':'A','task_id':'A'}],labels,{})
        self.assertEqual(g,{'a':None,'b':None})
    def test_shared_F_mask_and_conservative(self):
        q={'query_id':'q','candidate_ids':['a','b']}
        labels=[{'task_id':'F','knowledge_id':'a','grade':3,'annotation_status':'ACCEPTED','row_hash':'h',
                 'row_id':'r','evidence_ids':['e'],'source_span_ids':['s'],'reason':'x','personal_evidence_cited':True}]
        assign=[{'query_id':'q','arm':'F','task_id':'F'}];review={'h':{'status':'ACCEPTED'}}
        self.assertEqual(shared_reference(q,assign,labels,review)[0],{'a':3,'b':None})
        self.assertEqual(shared_reference(q,assign,labels,review,True)[0],{'a':None,'b':None})
        self.assertEqual(shared_reference(q,assign,labels,{'h':{'status':'REVIEW_REQUIRED'}})[0],{'a':None,'b':None})
    def test_score_vs_tie_vs_strict_reversal(self):
        g={'a':3,'b':0}
        old=[('a',1,1),('b',1,1)];new=[('a',2,1),('b',1,2)]
        c=changes(old,new,g);self.assertEqual(c['tie_relation_changes'],1);self.assertEqual(c['strict_order_reversals'],0)
        reverse=[('b',2,1),('a',1,2)]
        self.assertEqual(changes(new,reverse,g)['strict_order_reversals'],1)
        self.assertEqual(changes(new,[('a',3,1),('b',2,2)],g)['changed_relations'],0)
    def test_participant_not_pair_aggregation(self):
        records=[{'participant':'p1','v':1}]*8+[{'participant':'p2','v':-1}]
        self.assertEqual(summarize(records,lambda r:r['v'])['participant_macro_mean'],0)
    def test_cost_and_null(self):
        records=[{'participant':'p','value':{'ndcg@5':{'delta_delta':.1}}}]
        out=cost_scenarios(records,[[2,1]],[.05])
        self.assertAlmostEqual(out[0]['net_C_minus_D']['participant_macro_mean'],.05)
        a={arm:{m:None for m in ('ndcg@3','ndcg@5','pairwise_agreement','kendall_tau_b')} for arm in 'ABCD'}
        self.assertIsNone(value_record(a)['ndcg@5']['delta_C'])
    def test_personalization_not_implied_by_ranker_changes(self):
        d=compare_grades({'a':3,'b':0},{'a':3,'b':0})
        self.assertEqual(d['strict_reversals'],0)
        self.assertEqual(stage_decision(12,3,0,{'p1':.1,'p2':.1},False),'REDESIGN_REQUIRED')
        self.assertEqual(stage_decision(7,3,0,{},False),'INSUFFICIENT_EVIDENCE')

    def test_foreign_evidence_and_source_and_bool_grade(self):
        j={'packet_id':'p','candidate_id':'a','grade':True,'annotation_status':'ACCEPTED',
           'reason_code':'x','evidence_ids':['foreign'],'source_span_ids':['wrong']}
        mapping={'candidates':{'a':'kid'},'evidence_ids':['e'],'source_span_ids':{'a':['s']}}
        packet={'candidates':[{'candidate_id':'a','title':'title'}],
                'query':{'topic':'sleep','query_basis':'TOPIC_ONLY'},'evidence':[{'evidence_id':'e','status':'COMPUTED'}]}
        self.assertIn('INVALID_GRADE',row_errors(j,None,packet,mapping))
        j['grade']=2
        flat={'packet_id':'p','candidate_id':'a','grade':2,'evidence_ids':['foreign'],'source_span_ids':['wrong'],
              'reason':'x','candidate_title':'title','topic':'sleep','query_basis':'TOPIC_ONLY','gold_eligible':False,'reviewer_type':'AI'}
        errors=row_errors(j,flat,packet,mapping)
        self.assertIn('CROSS_TASK_EVIDENCE',errors);self.assertIn('WRONG_SOURCE_SPAN',errors)
        flat['gold_eligible']=True
        self.assertIn('MISREPRESENTED_PROVENANCE',row_errors(j,flat,packet,mapping))


if __name__=='__main__':unittest.main()
