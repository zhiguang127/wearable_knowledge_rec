"""Day 5 executable source audit, real-unknown records, independent kits and diagnostics."""
import argparse
from copy import deepcopy
from datetime import datetime,timezone
import hashlib
import hmac
import html
import json
from pathlib import Path
import secrets

from ..common import ROOT,read,rows,write,sha,digest,require
from ..datasets.v2_sources import freeze,verify,jsonl,verify_sources
from ..day1.evidence import EvidenceProvider
from ..day2.core import find_probe
from ..day2.knowledge import build_units
from .spec import VERSION,DOCTOR,HABITS,FIELDS,MEASUREMENTS,source_matrix,select_pair
from .context import contextual_evidence,selected_source_cues,ContextEnvironment,validate_real_form
from .review import validate_human_form,stable_reviewer,reconcile,adjudicate

BASE=ROOT/'local/day5'
PREPARED=BASE/'prepared-v01'
DIAGNOSTICS=BASE/'mechanism-v01'
CONFIG=ROOT/'configs/c1_day5_single_pair_v01.json'


def package_code():
    return {p.relative_to(ROOT).as_posix():sha(p) for p in sorted((ROOT/'src/day5').glob('*.py'))}


def html_book(path,packets,article_context):
    """Static, offline reader; response templates stay separately unfilled."""
    def esc(x):return html.escape(str(x),quote=True)
    body=['<!doctype html><html lang="zh"><meta charset="utf-8"><title>独立评审资料</title>',
          '<style>body{font:17px/1.65 system-ui;max-width:1080px;margin:32px auto;padding:0 24px;color:#17212b}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f2f5f7;padding:16px}article{border-top:2px solid #789;padding:26px 0}small{color:#456}h2{margin-bottom:8px}</style>',
          '<h1>单配对独立评审</h1><p>仅评价所示来源、Goal 和个人记录。允许并列与未知；来源条件不自动决定先读顺序。真实与合成材料分开标明。请填写本目录 judgments.template.json 的副本；不要修改封存模板。</p>',
          '<details><summary>完整原来源文章上下文（固定缓存；编码异常保留）</summary><pre>'+esc(article_context)+'</pre></details>']
    for p in packets:
        body.append('<article><h2>'+esc(p['packet_id'])+'</h2><p>资料类型：'+esc(p['data_origin'])+'</p><p>Topic：'+esc(p['topic'])+'</p><p>Goal：'+esc(p['goal'])+'</p>')
        for side in ('left','right'):
            c=p[side];body.append('<h3>'+side.upper()+': '+esc(c['candidate_id'])+' — '+esc(c['title'])+'</h3><pre>'+esc(c['text'])+'</pre>')
            for s in c['source_spans']:body.append('<small>'+esc(s['span_id'])+'</small><pre>'+esc(s['text'])+'</pre>')
        body.append('<h3>完整允许的个人情境（与在线 arm 无关）</h3><pre>'+esc(json.dumps(p['evidence'],ensure_ascii=False,indent=2))+'</pre></article>')
    body.append('</html>');path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x',encoding='utf-8') as f:f.write('\n'.join(body))


def measurement_protocol():
    return {'version':VERSION,'new_namespace_not_288_probe_extension':True,'measurements':MEASUREMENTS,
      'allowed_answers':['YES','NO','UNKNOWN'],'unknown_answer_vs_not_collected':'ANSWERED/UNKNOWN differs from NOT_COLLECTED/null; neither means NO',
      'minimum_primary_provenance':['episode_id','participant_id','as_of','reported_at','reference_start','reference_end','source_record_sha256','actual respondent attestation'],
      'questionnaire_is_validated_clinical_scale':False,'new_clinical_cutoffs':None,
      'qualitative_terms':'often/late/concern retain respondent meaning; no numeric conversion or percentile thresholds',
      'source_record_sha256':'Hash of separate contemporaneous original questionnaire/interview record, not a circular hash of the import form itself',
      'temporal_rule':'reference_start <= reference_end <= reported_at <= as_of; present-day answers cannot backfill historical windows',
      'prospective_sampling':'First two eligible episodes of first three genuinely consenting/enrolled participants, enrollment/time order; do not select on symptoms or ratings',
      'retrospective_recall':'Retain only in a separately marked secondary collection; not accepted by the primary importer',
      'additional_source_variables':[{'variable':'night_sleep_difficulty','source':'D5-S6','current_probe':None},
        {'variable':'daytime_nap_duration_and_event_time','source':'D5-S6','source_target_minutes':20,'target_is_priority_threshold':False},
        {'variable':'alcohol_use','source':'D5-S7','current_probe':None},
        {'variable':'smoking','source':'D5-S8','current_probe':None},
        {'variable':'daylight_and_activity_timing_large_meal_near_bedtime','source':'D5-S5','current_probe':None}],
      'unobservable_from_current_probes':['sleep symptoms/subjective concern','caffeine intake and timing','medicines/diagnosis','exact sleep/wake clock events'],
      'existing_sleep_duration_mean':'Descriptive background only, cannot measure these contexts',
      'automatically_contact_or_submit_to_anyone':False}


def prepare():
    require(not PREPARED.exists(),'fresh Day 5 preparation')
    config=read(CONFIG);old=verify(ROOT/'local/day4/analysis-v01r1')
    _,units,_,_=__import__('src.day2.pilot',fromlist=['load_prepared']).load_prepared(ROOT/'local/day2/prepared-v01')
    rebuilt=build_units(read(ROOT/'configs/c1_day2_pilot_v01.json'))
    require(rebuilt==units,'complete source unit reconstruction differs')
    sourceclosure=verify_sources(ROOT/'data/raw/c1-benchmark-v2',read(ROOT/'data/releases/c1-benchmark-v2.1/sources.json'))
    selection=select_pair(units);matrix=source_matrix(units);selected=[u for u in units if u['knowledge_id'] in (DOCTOR,HABITS)]
    require(selected[0]['article_context']==selected[1]['article_context'],'pair article contexts differ')
    write(PREPARED/'config.json',config);write(PREPARED/'measurement_protocol.json',measurement_protocol())
    write(PREPARED/'pair_selection.json',selection);jsonl(PREPARED/'source_condition_matrix.jsonl',matrix)
    jsonl(PREPARED/'knowledge_units.jsonl',selected);write(PREPARED/'source_closure.json',sourceclosure)
    write(PREPARED/'online_source_corroboration.json',{'url':selected[0]['source']['source_url'],
      'accessed_UTC':datetime.now(timezone.utc).isoformat(),'official_page_last_updated_as_displayed':'2026-07-06',
      'sections_checked':['See a Doctor','Daytime Habits'],'status':'CORE_CLAUSES_CORROBORATED_VIA_OFFICIAL_PAGE_NOT_BYTE_IDENTITY',
      'evaluation_source_remains_frozen_SHA256':selected[0]['source']['source_sha256']})
    real=rows(ROOT/'local/day4/reference-prepared-v01/scenarios.jsonl')
    cases={c['case_id']:c for c in rows(ROOT/'local/day4/reference-prepared-v01/selected_cases.jsonl')}
    probes=read(ROOT/'data/releases/c1-benchmark-v2.1/probes.json');pid=find_probe(probes,'sleep_duration','mean',14)
    scenarios=[]
    for s in real:
        require(cases[s['case_id']]['context'].get('symptoms') is None,'new real symptoms require separate prelabel sampling review')
        case='R5-'+digest(s['scenario_id'])[:16];asof=s['end_date']+'T23:59:59+00:00'
        # UTC here is a conservative administrative cutoff; source timezone is unknown, not inferred.
        ev=contextual_evidence(case,{f:None for f in FIELDS},'REAL_NOT_COLLECTED',asof,
             {'source':'Frozen WearableQA case has no contextual self-report','case_hash':s['case_hash']})
        wearable=EvidenceProvider(cases[s['case_id']],probes).get(pid)
        scenarios.append({'case_id':case,'participant':s['participant'],'original_case_id':s['case_id'],
          'data_origin':'REAL_WEARABLEQA_CONTEXT_NOT_COLLECTED','as_of':asof,'timezone_verified':False,
          'context_evidence':ev,'wearable_evidence':[wearable],'primary_real_context_collected':False,
          'topic':config['topic'],'goal':config['goal'],'candidate_ids':config['candidate_ids']})
    combinations=[('NO','NO'),('YES','NO'),('NO','YES'),('YES','YES'),('UNKNOWN','YES'),('YES','UNKNOWN')]
    for i,(often,caffeine) in enumerate(combinations):
        case=f'S5-{i+1:02d}';values=dict(zip(FIELDS,('NO',often,'NO',caffeine)))
        scenarios.append({'case_id':case,'participant':None,'original_case_id':None,
          'data_origin':'SYNTHETIC_MECHANISM_ONLY','as_of':'2026-01-31T12:00:00+00:00','timezone_verified':False,
          'context_evidence':contextual_evidence(case,values,'SYNTHETIC_MECHANISM_ONLY','2026-01-31T12:00:00+00:00',
             {'source':'Fixed fictional factorial conditions, not a real person or inferred from a desired ranking'}),
          'wearable_evidence':[],'primary_real_context_collected':False,
          'topic':config['topic'],'goal':config['goal'],'candidate_ids':config['candidate_ids']})
    require(len(scenarios)==18,'fixed real plus synthetic scene inventory')
    jsonl(PREPARED/'scenarios.jsonl',scenarios)
    write(PREPARED/'synthetic_matched_contrasts.json',{'origin':'SYNTHETIC_MECHANISM_ONLY','expected_priority':None,
      'edges':[{'left':a,'right':b,'only_changed':'often_trouble_sleeping'} for a,b in (('S5-01','S5-02'),('S5-03','S5-04'),('S5-03','S5-05'))]+
              [{'left':a,'right':b,'only_changed':'late_day_caffeine'} for a,b in (('S5-01','S5-03'),('S5-02','S5-04'),('S5-02','S5-06'))]})
    blank={'protocol_version':VERSION,'data_origin':'REAL_SELF_REPORT','episode_id':None,'participant_id':None,
      'respondent_attestation':False,'collection_mode':'CONTEMPORANEOUS','as_of':None,'reported_at':None,'source_record_sha256':None,
      'answers':{m['measurement_id']:{'value':None,'reference_start':None,'reference_end':None,'qualifier':''} for m in MEASUREMENTS}}
    write(PREPARED/'collection/context.template.json',blank)
    write(PREPARED/'collection/registered_episodes.json',{'status':'NOT_ENROLLED_NOT_COLLECTED','episodes':[],'real_responses':0})
    rubric={'version':'day5-independent-relative-priority-v1','topic_goal_relevance':['DIRECT','BACKGROUND','OFF_TOPIC','UNKNOWN'],
      'source_alignment':['SUPPORTED_CUE','NO_SELECTED_CUE','UNKNOWN','NOT_A_HARD_GATE'],
      'relative_priority':['LEFT','RIGHT','TIE','UNKNOWN'],
      'hard_applicability':'NO_VERIFIED_UNIT_LEVEL_GATE',
      'rules':['Judge information relevance to the exact Goal, not treatment priority.',
        'A source cue can support consultation information without requiring it to outrank habit information.',
        'Both may be relevant; no selected cue is not proof the unit is inapplicable.',
        'UNKNOWN is missing decisive context, not a known tie; TIE is supported comparable relevance.',
        'Cite both candidates source spans and actual contextual evidence or its missing status.',
        'Never derive symptoms or behaviors from mean sleep duration; do not invent frequency or time cutoffs.']}
    write(PREPARED/'rubric.json',rubric)
    secret=secrets.token_bytes(32);write(PREPARED/'PRIVATE_blinding_key.json',{'key_hex':secret.hex()})
    def anon(*parts):return hmac.new(secret,'|'.join(parts).encode(),hashlib.sha256).hexdigest()[:18]
    byunit={u['knowledge_id']:u for u in selected};mapping={}
    for slot in ('RATER_A','RATER_B'):
        mapping[slot]={}
        for number in (1,2,3):
            session=f'SESSION_{number}';packets=[];blankrows=[];sessionmap={}
            for s in scenarios:
                case=s['case_id'];primary=list(config['candidate_ids'])
                if int(anon(slot,case,'primary')[:2],16)%2:primary.reverse()
                order=primary[::-1] if number==2 else primary
                packetid='HP5-'+anon(slot,session,case);candidates=[];sourcemap={}
                for side,kid in zip(('left','right'),order):
                    unit=byunit[kid];spans=[]
                    for sp in unit['source_spans']:
                        alias='SS5-'+anon(slot,session,case,kid,sp['span_id']);sourcemap[alias]=sp['span_id']
                        spans.append({**sp,'span_id':alias})
                    candidates.append({'candidate_id':'HK5-'+anon(slot,session,case,kid),'title':unit['title'],
                                       'text':unit['text'],'source_url':unit['source']['source_url'],'source_spans':spans})
                evidence=[];emap={}
                for ev in s['context_evidence']:
                    alias='HE5-'+anon(slot,session,case,ev['evidence_id']);emap[alias]=ev['evidence_id']
                    evidence.append({'evidence_id':alias,'measurement_id':ev['measurement_id'],'variable':ev['variable'],
                      'status':ev['status'],'value':ev['value'],'data_origin':ev['data_origin'],'result_hash':ev['result_hash'],
                      'reference_start':ev['reference_start'],'reference_end':ev['reference_end'],'reported_at':ev['reported_at'],
                      'qualifier':ev['qualifier']})
                for ev in s['wearable_evidence']:
                    alias='HE5-'+anon(slot,session,case,ev['evidence_id']);emap[alias]=ev['evidence_id']
                    evidence.append({'evidence_id':alias,'measurement_id':ev['probe_id'],'variable':'sleep_duration_mean_14',
                      'status':ev['status'],'value':ev['value'],'unit':ev['unit'],'data_origin':'REAL_WEARABLEQA',
                      'result_hash':ev['result_hash'],'scope':'Descriptive mean, not symptoms, sleep need or nightly compliance'})
                packet={'packet_id':packetid,'topic':config['topic'],'goal':config['goal'],'data_origin':s['data_origin'],
                        'left':candidates[0],'right':candidates[1],'evidence':evidence,'rubric':rubric}
                packets.append(packet)
                sessionmap[packetid]={'case_id':case,'data_origin':s['data_origin'],'left':order[0],'right':order[1],
                  'evidence_ids':emap,'source_alias_to_original':sourcemap,
                  'source_span_ids':{side:[sp['span_id'] for sp in c['source_spans']] for side,c in zip(('left','right'),candidates)}}
                blankrows.append({'packet_id':packetid,'annotation_status':'UNFILLED','preference':None,
                  'topic_goal_left':None,'topic_goal_right':None,'source_alignment_left':None,'source_alignment_right':None,
                  'hard_applicability':None,'reason':'','missing_context':'','source_span_ids_left':[],
                  'source_span_ids_right':[],'evidence_ids':[]})
            packets.sort(key=lambda p:anon(slot,session,p['packet_id'],'order'))
            blank_by={j['packet_id']:j for j in blankrows};blankrows=[blank_by[p['packet_id']] for p in packets]
            folder=PREPARED/'reviewers'/slot/session
            jsonl(folder/'packets.jsonl',packets)
            write(folder/'judgments.template.json',{'package_version':config['version'],'slot':slot,'session_id':session,
              'reviewer_id':None,'annotator_type':None,'human_attestation':False,'saw_model_outputs':None,
              'saw_ranker_or_expected_directions':None,'saw_other_reviewer_answers':None,'completed_at':None,'judgments':blankrows})
            html_book(folder/'review.html',packets,selected[0]['article_context'])
            mapping[slot][session]=sessionmap
        source_bundle=[]
        for unit in selected:
            spans=[{**sp,'span_id':'SFS5-'+anon(slot,'source',unit['knowledge_id'],sp['span_id'])} for sp in unit['source_spans']]
            source_bundle.append({'source_unit_id':'SU5-'+anon(slot,'source',unit['knowledge_id']),
              'title':unit['title'],'text':unit['text'],'source':unit['source'],'source_spans':spans,'article_context':unit['article_context']})
        jsonl(PREPARED/'reviewers'/slot/'source_units.jsonl',source_bundle)
        write(PREPARED/'reviewers'/slot/'source_review.template.json',{'reviewer_id':None,'annotator_type':None,
           'human_attestation':False,'source_status':'UNFILLED','source_does_not_entail_order':None,
           'source_package_hash':digest(source_bundle),'complete_source_units_checked':[],'source_span_ids':[],'reason':''})
        with (PREPARED/'reviewers'/slot/'README.md').open('x',encoding='utf-8') as f:
            f.write('Independent human source and pair review. Open each session review.html, then fill a copy of its JSON template.\n'
                    'Three sessions must be completed independently at least 48 hours apart. Do not open later sessions early.\n'
                    'Do not see model results, rankers, expected directions, private mappings or the other reviewer.\n'
                    'Origins REAL/SYNTHETIC are visible. Source checking is separate; source action cues do not establish an order.\n'
                    'Leave actual identity/attestations empty until a real independent person completes the review.\n')
    write(PREPARED/'PRIVATE_mapping.json',mapping)
    write(PREPARED/'adjudication.template.json',{'adjudicator_id':None,'human_attestation':False,
          'saw_ranker_or_expected_directions':None,'decisions':[]})
    write(PREPARED/'status.json',{'status':'PREPARED_NOT_COLLECTED_NOT_ANNOTATED','real_cases':12,'synthetic_cases':6,
          'real_context_responses':0,'actual_independent_reviewers':0,'human_judgments':0,'ranking_labels':0,
          'packets_per_rater':54,'total_blank_judgments':108,'new_model_requests':0})
    write(PREPARED/'protocol_ref.json',{'path':'docs/C1_DAY5_SINGLE_PAIR_PROTOCOL_V01.md','sha256':sha(ROOT/'docs/C1_DAY5_SINGLE_PAIR_PROTOCOL_V01.md')})
    write(PREPARED/'code_hashes.json',package_code())
    for name in package_code():
        dest=PREPARED/'implementation'/name;dest.parent.mkdir(parents=True,exist_ok=True)
        with dest.open('xb') as f:f.write((ROOT/name).read_bytes())
    return freeze(PREPARED,{'status':'SINGLE_PAIR_PROTOCOL_FIXED_BEFORE_ANY_NEW_LABELS_OR_CONTEXTS',
      'created_at':datetime.now(timezone.utc).isoformat(),'Day4_analysis_id':old['release_id']})


def load():
    frozen=verify(PREPARED);require(read(CONFIG)==read(PREPARED/'config.json'),'Day 5 config changed')
    require(package_code()==read(PREPARED/'code_hashes.json'),'Day 5 frozen code changed')
    ref=read(PREPARED/'protocol_ref.json');require(sha(ROOT/ref['path'])==ref['sha256'],'Day 5 protocol changed')
    return read(CONFIG),frozen


def diagnose():
    config,frozen=load();require(not DIAGNOSTICS.exists(),'fresh Day 5 diagnosis')
    scenes=rows(PREPARED/'scenarios.jsonl');records=[];actions=[]
    for sc in scenes:
        full=selected_source_cues(sc['context_evidence'])
        if sc['data_origin'].startswith('REAL'):
            records.append({'case_id':sc['case_id'],'participant':sc['participant'],'data_origin':sc['data_origin'],
                            'full_context_source_support':full,'real_new_context_collected':False,'ranking':None})
            continue
        query={k:sc[k] for k in ('topic','goal','candidate_ids')}
        initial=['SR5-listed-sleep-difficulty','SR5-sleep-concern']
        for arm,mid in (('C','SR5-often-trouble-sleeping'),('D','SR5-late-day-caffeine')):
            env=ContextEnvironment(sc['case_id'],sc['context_evidence'],query);before=env.reset(initial,1)
            state,cost,done=env.step(mid)
            require(cost==1 and done and len(state['observed_evidence'])==3,'uniform one question acquisition')
            actions.append({'case_id':sc['case_id'],'data_origin':'SYNTHETIC_MECHANISM_ONLY','arm':arm,
                            'initial_observation_hash':digest(before),'state':state,'cost':cost})
        records.append({'case_id':sc['case_id'],'participant':None,'data_origin':sc['data_origin'],
                        'full_context_source_support':full,'real_new_context_collected':False,'ranking':None})
    jsonl(DIAGNOSTICS/'source_support_diagnostics.jsonl',records);jsonl(DIAGNOSTICS/'synthetic_acquisition_steps.jsonl',actions)
    decision={'status':'INSUFFICIENT_EVIDENCE','operational_status':'SOURCE_AND_PROTOCOL_READY_REAL_CONTEXT_AND_REFERENCE_PENDING',
      'five_stages':{
        'source_condition_action':{'status':'SUPPORTED_BY_FROZEN_TEXT','independent_human_source_review':None,'source_entailed_relative_order':False,'true_selected_source_cues_in_real_cases':None},
        'measurement':{'status':'PROTOCOL_READY_NOT_COLLECTED','new_protocol':VERSION,'real_responses':0,'conceptual_collectability':True,'validated_clinical_scale':False},
        'reference_reliability':{'status':'PENDING_ACTUAL_INDEPENDENT_HUMANS','actual_reviewers':0,'stable_reference_cases':0,'agreement':None},
        'personal_discrimination':{'status':'UNDETERMINED','supported_real_contrasts':None},
        'acquisition_gain':{'status':'NOT_EVALUATED','Observed_delta_U':None,'Expected_V':None}},
      'real_cases_checked':12,'real_source_cue_unknown_cases':12,'synthetic_cases':6,'synthetic_source_state_propagation_only':True,
      'synthetic_judgment_labels':0,'new_Qwen_requests':0,'ranking_rule':None,'formal_baseline_C2_or_benchmark_freeze':False,
      'next_unique_priority_action':'Collect contemporaneous source-defined self-reports for a minimal real paired episode set, then have two actual independent humans complete the sealed sessions; no current-day backfill of historical cases.'}
    write(DIAGNOSTICS/'stage_decision.json',decision)
    write(DIAGNOSTICS/'mechanism_summary.json',{'real_cases':12,'real_context_collected':0,'real_C_D_actions':0,
      'synthetic_cases':6,'synthetic_step_count':len(actions),'synthetic_cost_per_arm':6,'unknown_answers_cost_one':True,
      'reference_reliable':None,'priority_signal':None,'NDCG_at_3':None,'NDCG_at_5':None,
      'pairwise_agreement':None,'Observed_delta_C':None,'Observed_delta_D':None,'C_minus_D':None,'Expected_V':None,
      'ranking_not_manufactured_from_source_cues':True,'ranker_or_labels_retuned':False,'prepared_id':frozen['release_id']})
    freeze(DIAGNOSTICS,{'status':decision['status'],'synthetic_results_are_source_logic_only':True})
    return decision


def main():
    p=argparse.ArgumentParser();sub=p.add_subparsers(dest='command',required=True)
    sub.add_parser('prepare');sub.add_parser('diagnose')
    a=sub.add_parser('ingest');a.add_argument('--slot',required=True);a.add_argument('--session',required=True);a.add_argument('--form',required=True);a.add_argument('--output',required=True)
    a=sub.add_parser('context-import');a.add_argument('--form',required=True);a.add_argument('--source-record',required=True);a.add_argument('--output',required=True)
    a=sub.add_parser('reconcile');a.add_argument('--left',nargs=3,required=True);a.add_argument('--right',nargs=3,required=True);a.add_argument('--left-source',required=True);a.add_argument('--right-source',required=True);a.add_argument('--output',required=True)
    a=sub.add_parser('adjudicate');a.add_argument('--reconciliation',required=True);a.add_argument('--form',required=True);a.add_argument('--output',required=True)
    args=p.parse_args()
    if args.command=='prepare':result=prepare()
    elif args.command=='diagnose':result=diagnose()
    elif args.command=='ingest':
        _,prepared=load();mapping=read(PREPARED/'PRIVATE_mapping.json')[args.slot][args.session]
        form=read(args.form);require(form.get('slot')==args.slot,'reviewer slot mismatch')
        result=validate_human_form(form,mapping,args.session);result['prepared_id']=prepared['release_id'];write(args.output,result)
    elif args.command=='context-import':
        load();form=read(args.form);validate_real_form(form,sha(args.source_record))
        require(form['episode_id'] not in {s['case_id'] for s in rows(PREPARED/'scenarios.jsonl')},
                'new collection needs a new episode; no automatic historical/synthetic backfill')
        values={m['variable']:form['answers'][m['measurement_id']]['value'] for m in MEASUREMENTS}
        result={'kind':'ATTESTED_REAL_SELF_REPORT_NOT_CLINICAL_GOLD','form_hash':digest(form),
                'source_record_sha256':sha(args.source_record),'participant_id':form['participant_id'],
                'evidence':contextual_evidence(form['episode_id'],values,'REAL_SELF_REPORT',form['as_of'],
                  {'source_record_sha256':sha(args.source_record),'form_hash':digest(form)},
                  {'reported_at':form['reported_at'],'answers':form['answers']})}
        write(args.output,result)
    elif args.command=='reconcile':
        load();left=stable_reviewer([read(f) for f in args.left],read(args.left_source),rows(PREPARED/'reviewers/RATER_A/source_units.jsonl'))
        right=stable_reviewer([read(f) for f in args.right],read(args.right_source),rows(PREPARED/'reviewers/RATER_B/source_units.jsonl'))
        result=reconcile(left,right);write(args.output,result)
    else:
        load();rec=read(args.reconciliation);scenes=rows(PREPARED/'scenarios.jsonl');units=rows(PREPARED/'knowledge_units.jsonl')
        allowed={s['case_id']:{'source_span_ids':[sp['span_id'] for u in units for sp in u['source_spans']],
                 'evidence_ids':[e['evidence_id'] for e in s['context_evidence']+s['wearable_evidence']]} for s in scenes}
        result=adjudicate(rec,read(args.form),allowed);write(args.output,result)
    print(json.dumps({k:v for k,v in result.items() if k not in ('files','judgments','evidence','cases')},ensure_ascii=False,indent=2))


if __name__=='__main__':main()
