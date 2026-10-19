"""V2 counterexamples and real source consistency; no model calls in tests."""
import copy
from datetime import date, timedelta
import json
import re
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from src.common import ROOT, Blocked, read, rows, digest, write
from src.datasets.wearableqa import import_histories, construct_windows, split, usable, UNITS
from src.datasets.probes import make_probe, execute, catalog, validate_probe, relation_index
from src.datasets.splits import validate_split
from src.datasets.v2_sources import freeze, verify, snapshot, verify_sources
from src.knowledge.c1_v2 import blocks, similarity
from src.annotation.c1_v2_client import V2Client
from src.annotation.c1_v2_pipeline import citations, check_label, check_review, capability_errors


def fixture_case(n=56):
    first=date(2020,1,1)
    return {"case_id":"fixture","subject_id":"fixture-subject","end_date":(first+timedelta(days=n-1)).isoformat(),
            "days":[{"date":(first+timedelta(days=i)).isoformat(),"metrics":{"steps":float(i)},"quality_flags":[]} for i in range(n)]}


class ProbeTests(unittest.TestCase):
    def test_true_calendar_slope_and_phase_boundaries(self):
        case=fixture_case();p=make_probe("steps",14,"mean_difference")
        r=execute(case,p)
        self.assertEqual(r["value"],21)
        self.assertEqual(r["comparison"]["end_date"],case["days"][41]["date"])
        self.assertEqual(execute(case,make_probe("steps",14,"slope"))["value"],1)

    def test_future_data_rejected_even_outside_probe(self):
        c=fixture_case();c["days"].append({"date":"2021-01-01","metrics":{"steps":9000}})
        with self.assertRaises(Blocked):execute(c,make_probe("steps",14,"mean"))

    def test_missing_never_zero_or_adjacent_across_gap(self):
        c=fixture_case()
        for i in (43,45):c["days"][i]["metrics"]["steps"]=None
        r=execute(c,make_probe("steps",14,"adjacent_change"))
        self.assertEqual(r["n"],12);self.assertEqual(r["value"],1);self.assertEqual(r["adjacent_pairs"],9)
        for i in range(42,56):c["days"][i]["metrics"]["steps"]=None
        r=execute(c,make_probe("steps",14,"mean"))
        self.assertIsNone(r["value"]);self.assertEqual(r["status"],"INSUFFICIENT_INFORMATION")

    def test_short_baseline_not_filled(self):
        self.assertEqual(execute(fixture_case(28),make_probe("steps",14,"mean_difference"))["status"],"INSUFFICIENT_INFORMATION")

    def test_identity_unit_and_invalid_range_block(self):
        for key,value in (("unit","hours"),("window_days",0),("offset_days",-1),("min_coverage",1.5)):
            p=make_probe("steps",14,"mean");p[key]=value
            with self.assertRaises(Blocked):validate_probe(p)

    def test_duplicate_date_block(self):
        c=fixture_case();c["days"].append(c["days"][0])
        with self.assertRaises(Blocked):execute(c,make_probe("steps",14,"mean"))

    def test_unique_probe_definitions(self):
        probes=catalog();self.assertEqual(len(probes),len({p["probe_id"] for p in probes}))

    def test_and_without_source_cannot_be_compiled(self):
        p=make_probe("steps",14,"mean")
        k={"knowledge_id":"fixture","condition_review_status":"REVIEW_REQUIRED","conditions":[{"condition_id":"c","role":"necessary","logic":"ALL","probe_ids":[p["probe_id"]],"source_citations":[]}]}
        with self.assertRaises(Blocked):relation_index([k],[p])
        k["conditions"][0].update(role="alternative",logic="ANY")
        self.assertEqual(relation_index([k],[p])["unique_probes"],1)


class ImportTests(unittest.TestCase):
    def test_source_values_preserved_and_duplicates_rejected(self):
        d={"n_unique_users":1,"n_mcqs":0,"mcqs":[],"user_histories":{"a":[{"date":"2020-01-01","rhr":0,"steps":None}]}}
        records,mapping,_=import_histories(d,b'a'*32);row=next(iter(next(iter(records.values())).values()))
        self.assertEqual(row["metrics"]["rhr"],0);self.assertIn("rhr:unusable_source_value",row["quality_flags"])
        self.assertNotIn("sleep_duration",row["source_present_fields"])
        self.assertIsNone(row["metrics"]["sleep_duration"])
        self.assertEqual(mapping[0]["source_participant_id"],"a")
        d["user_histories"]["a"]*=2
        with self.assertRaises(Blocked):import_histories(d,b'a'*32)

    def test_boolean_nan_impossible_and_ambiguous_zero_unusable(self):
        for metric,v in (("steps",True),("steps",float('nan')),("sleep_duration",25),("exercise_hours",0),("sleep_efficiency",90)):
            self.assertFalse(usable(metric,v))
        self.assertTrue(usable("steps",0))

    def test_window_reproducible_without_future_data(self):
        history={date(2020,1,1)+timedelta(days=i):{"metrics":{m:float(i) for m in UNITS},"quality_flags":[],"missing_metrics":[]} for i in range(100)}
        config={"baseline_days":28,"current_days":14,"history_lengths":[42,90],"windows_per_participant_per_length":2}
        a,excluded=construct_windows({"s":history},config)
        self.assertEqual(len(a),3);self.assertEqual(len(excluded),1)
        self.assertEqual(a,construct_windows({"s":dict(reversed(list(history.items())))},config)[0])
        for c in a:self.assertTrue(all(d["date"]<=c["end_date"] for d in c["days"]))

    def test_14_day_cold_start_has_no_prior_baseline(self):
        history={date(2020,1,1)+timedelta(days=i):{"metrics":{m:float(i) for m in UNITS},"quality_flags":[],"missing_metrics":[]} for i in range(100)}
        config={"baseline_days":28,"current_days":14,"history_lengths":[14],"windows_per_participant_per_length":3}
        cases,excluded=construct_windows({"s":history},config)
        self.assertFalse(excluded);self.assertEqual(len(cases),3)
        for c in cases:
            self.assertTrue(c["cold_start"]);self.assertEqual(len(c["days"]),14)
            self.assertEqual({d["phase"] for d in c["days"]},{"current"})
            r=execute(c,make_probe("steps",14,"mean_difference"))
            self.assertIsNone(r["value"]);self.assertEqual(r["comparison"]["n"],0)

    def test_blocks_keep_lists_and_scope(self):
        result=blocks('<h4>For adults</h4><p>Try these changes.</p><ul><li>A</li><li>B</li></ul>')
        self.assertEqual(len(result),2);self.assertEqual(result[1]["text"],"A B")
        self.assertEqual(result[1]["heading"],"For adults")
        self.assertEqual(similarity("Get enough SLEEP.","get enough sleep"),1)


class TransportTests(unittest.TestCase):
    def config(self):
        return {**read(ROOT/"configs/c1_v2_qwen_budget.json"),"authorized_cap_cny":1,"max_calls":1}

    def body(self):
        return {"model":"qwen-plus","usage":{"prompt_tokens":10,"completion_tokens":4},"choices":[{"finish_reason":"stop","message":{"content":"{\"fixture\":true}"}}]}

    def test_exact_replay_and_cap(self):
        with tempfile.TemporaryDirectory() as d:
            calls=[]
            client=V2Client(d,self.config(),transport=lambda req:(calls.append(req) or self.body()))
            x,meta=client.call([],prompt_version="fixture")
            self.assertTrue(x["fixture"]);self.assertFalse(meta["cache_hit"])
            self.assertTrue(client.call([],prompt_version="fixture")[1]["cache_hit"])
            self.assertEqual(len(calls),1)
            with self.assertRaises(Blocked):client.call([],prompt_version="other")

    def test_failed_request_keeps_reservation_and_no_retry(self):
        with tempfile.TemporaryDirectory() as d:
            def broken(req):raise TimeoutError()
            c=V2Client(d,self.config(),transport=broken)
            for i in range(2):
                with self.assertRaises(Blocked):c.call([],prompt_version="fixture")
            self.assertEqual(c.report()["attempts"],1);self.assertGreater(c.report()["reserved_cny"],0)

    def test_tampered_response_not_replayed(self):
        with tempfile.TemporaryDirectory() as d:
            c=V2Client(d,self.config(),transport=lambda req:self.body());c.call([],prompt_version="fixture")
            p=next((Path(d)/"cache").glob('*.json'));j=read(p);j["response"]["model"]="fake";p.write_text(json.dumps(j))
            with self.assertRaises(Blocked):c.call([],prompt_version="fixture")

    def test_no_budget_no_network(self):
        with tempfile.TemporaryDirectory() as d,patch('socket.socket',side_effect=AssertionError('network')):
            cfg=self.config();cfg['authorized_cap_cny']=0
            with self.assertRaises(Blocked):V2Client(d,cfg)


class SourceAndCitationTests(unittest.TestCase):
    def test_correlated_aggregates_cannot_stand_for_unobserved_inputs(self):
        base={'probe_ids':['fixture-probe'],'use':'applicability','role':'necessary','logic':'UNKNOWN'}
        for text in ('At least 150 minutes of moderate-intensity activity','Does strengthening exercises weekly',
                     'Consistent bedtime and wake time','Stress keeps getting worse'):
            self.assertTrue(capability_errors({**base,'text':text}))
        self.assertFalse(capability_errors({**base,'text':'Daily step count is available'}))
        self.assertFalse(capability_errors({**base,'text':'Consistent bedtime','probe_ids':[]}))

    def test_multiple_summaries_not_promoted_to_necessary_AND(self):
        c={'probe_ids':['mean','sd'],'use':'applicability','role':'necessary','logic':'ALL','text':'Low activity'}
        self.assertIn('necessary_ALL_probe_group_has_no_grounded_per_probe_predicates',capability_errors(c))
        c['role']='optional'
        self.assertFalse(capability_errors(c))

    def label_fixture(self):
        c=fixture_case();ev=execute(c,make_probe('steps',14,'mean'))
        anchor='Source supports sleep.'
        item={'knowledge_id':'k','source_sha256':'hash','source_anchor':{'anchor_id':'a','text':anchor,'text_sha256':digest(anchor)}}
        cite={'anchor_id':'a','source_sha256':'hash','quote':'supports sleep'}
        ref={k:ev[k] for k in ('probe_id','result_sha256','value','unit','start_date','end_date')}
        first={'case_id':c['case_id'],'knowledge_id':'k','applicability':'applicable','topic_relevance':'relevant',
               'recommendation_priority':'undetermined','priority_basis':'unknown','evidence':[ref],
               'source_citations':[cite],'missing_information':[],'uncertainties':[],'rationale':'fixture only'}
        second={'case_id':c['case_id'],'knowledge_id':'k','verdict':'SUPPORTED','applicability':'applicable',
                'issues':[],'evidence':[copy.deepcopy(ref)],'source_citations':[cite],'rationale':'fixture only'}
        return first,second,item,c,[ev]

    def test_model_cannot_invent_numeric_unit_hash_or_future_range(self):
        for field,value in (('value',999999),('unit','minutes'),('result_sha256','invented'),('end_date','2030-01-01')):
            first,second,item,case,ev=self.label_fixture()
            first['evidence'][0][field]=value
            self.assertIn('numeric_hash_unit_or_time_mismatch',check_label(first,second,item,case,ev)[0])

    def test_disagreement_not_overwritten_or_promoted(self):
        first,second,item,case,ev=self.label_fixture();second['applicability']='not_applicable'
        self.assertIn('stage_applicability_disagreement',check_label(first,second,item,case,ev)[0])
        self.assertEqual(first['applicability'],'applicable')

    def test_missing_evidence_cannot_be_a_definite_personal_label(self):
        first,second,item,case,ev=self.label_fixture();first['evidence']=[]
        self.assertIn('definite_label_without_personal_evidence',check_label(first,second,item,case,ev)[0])

    def test_exact_missing_evidence_supports_only_insufficient_information(self):
        first,second,item,case,ev=self.label_fixture()
        ev[0].update(value=None,status='INSUFFICIENT_INFORMATION')
        for out in (first,second):
            out['applicability']='insufficient_information';out['evidence'][0]['value']=None
        self.assertFalse(check_label(first,second,item,case,ev)[0])
        first['applicability']='applicable'
        self.assertIn('noncomputed_or_unknown_evidence',check_label(first,second,item,case,ev)[0])

    def test_citation_text_hash_and_span(self):
        item={"source_sha256":"hash","source_anchor":{"anchor_id":"a","text":"Source supports sleep.","text_sha256":digest("Source supports sleep.")}}
        cite={"anchor_id":"a","source_sha256":"hash","quote":"supports sleep"}
        errors,spans=citations([cite],item);self.assertFalse(errors);self.assertEqual(spans[0]['start'],7)
        cite['quote']='invented';self.assertTrue(citations([cite],item)[0])
        cite.update(quote='sleep',source_sha256='bad');self.assertTrue(citations([cite],item)[0])

    def test_source_cache_hash_required(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'s').write_text('fixture');write(p/'s.source.json',{'url':'https://example.invalid','status':'FETCHED','sha256':'bad'})
            with patch('socket.socket',side_effect=AssertionError('network')):
                with self.assertRaises(Blocked):snapshot(p,'s','https://example.invalid')

    def test_original_source_integrity_checked_without_network(self):
        from src.common import sha
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'source').write_bytes(b'fixture')
            record={'url':'https://example.invalid','status':'FETCHED','sha256':sha(p/'source'),'bytes':7}
            write(p/'source.source.json',record)
            self.assertEqual(verify_sources(p,{'s':record})['source_files_rehashed'],1)
            (p/'source').write_bytes(b'changed')
            with self.assertRaises(Blocked):verify_sources(p,{'s':record})

    def test_freeze_exclusive_and_tamper(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);write(p/'a.json',{});freeze(p,{'version':'fixture'});verify(p)
            (p/'a.json').write_text('{"changed":true}')
            with self.assertRaises(Blocked):verify(p)


class RealV2Consistency(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.release=ROOT/'data/releases/c1-benchmark-v2.0'
        if not cls.release.exists():raise unittest.SkipTest('Real V2 assets absent; run documented build, never fabricate them')
        verify(cls.release)

    def test_real_raw_projection_and_inventory(self):
        raw=read(ROOT/'data/raw/c1-benchmark-v2/WearableQA_raw.json')
        records,mapping,counts=import_histories(raw,(ROOT/'local/identity/c1-v2.key').read_bytes())
        self.assertEqual((len(records),counts['daily_rows']),(200,119795))
        imported=rows(self.release/'observations.jsonl')
        bysource={m['subject_id']:m['source_participant_id'] for m in mapping}
        rawbydate={s:{r['date']:r for r in v} for s,v in raw['user_histories'].items()}
        for row in imported:self.assertEqual(row['source_record'],rawbydate[bysource[row['subject_id']]][row['date']])

    def test_real_split_no_leakage_and_window_replay(self):
        cases=rows(self.release/'cases.jsonl');partition=read(self.release/'splits.json')
        self.assertEqual(sum(p['participants'] for p in validate_split(cases,partition).values()),200)
        for case in cases:
            self.assertEqual(len(case['days']),case['history_days'])
            self.assertEqual(case['days'][-1]['date'],case['end_date'])
            self.assertEqual(case['days'][0]['date'],case['start_date'])

    def test_all_coldstart_release_windows_replay_from_original_values(self):
        release=ROOT/'data/releases/c1-benchmark-v2.1'
        if not release.exists():self.skipTest('Cold-start release absent')
        verify(release)
        raw=read(ROOT/'data/raw/c1-benchmark-v2/WearableQA_raw.json')
        records,_,_=import_histories(raw,(ROOT/'local/identity/c1-v2.key').read_bytes())
        cases,excluded=construct_windows(records,read(release/'build_config.json'))
        self.assertEqual(cases,rows(release/'cases.jsonl'))
        self.assertEqual(excluded,rows(release/'window_exclusions.jsonl'))
        frozen=read(release/'splits.json')
        self.assertEqual(split(cases,read(release/'build_config.json')),frozen)


class PublicMetadataPrivacy(unittest.TestCase):
    def test_public_export_contains_no_personal_identity_or_credentials(self):
        directory=ROOT/'docs/c1_v2_artifacts'
        if not directory.exists():self.skipTest('Public aggregate export absent')
        verify(directory)
        text='\n'.join(p.read_text(encoding='utf-8') for p in directory.rglob('*') if p.is_file())
        self.assertFalse(re.search(r'sk-[A-Za-z0-9]{20,}',text))
        release=ROOT/'data/releases/c1-benchmark-v2.1'
        if release.exists():
            cases=rows(release/'cases.jsonl')
            private_ids={c['case_id'] for c in cases}|{c['subject_id'] for c in cases}
            self.assertFalse(any(identifier in text for identifier in private_ids))


if __name__=='__main__':unittest.main()
