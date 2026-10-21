"""Versioned design, real evidence audit and blinded reference construction."""
import argparse
from collections import Counter,defaultdict
from concurrent.futures import ThreadPoolExecutor,as_completed
from datetime import datetime,timezone
from itertools import combinations
import json
from pathlib import Path
from statistics import mean

from ..common import ROOT,read,rows,write,sha,digest,require
from ..datasets.v2_sources import verify,freeze,jsonl,verify_sources
from ..day1.evidence import EvidenceProvider
from ..day1.structured import build_request,ANNOTATION_FUNCTION
from ..day2.pilot import load_prepared
from ..day2.core import display_evidence
from .pairs import build_pairs
from .reference import PROMPT,schema,ReferenceClient,errors,normalize

BASE=ROOT/'local/day4'
DESIGN=BASE/'design-v01'
PREPARED=BASE/'reference-prepared-v01'
REFERENCE=BASE/'reference-executed-v01'
CONFIG=ROOT/'configs/c1_day4_discriminative_v01.json'


def code_hashes():
    return {p.relative_to(ROOT).as_posix():sha(p) for p in sorted((ROOT/'src/day4').glob('*.py'))}


def prepare_design():
    require(not DESIGN.exists(),'fresh Day 4 design')
    config=read(CONFIG);oldcfg,units,queries,old=load_prepared(ROOT/config['day2_prepared'])
    verify(ROOT/config['day3_evaluated'])
    require(verify(ROOT/config['source_release'])['release_id']==config['source_release_id'],'source release drift')
    pairs=build_pairs(units);require(len(pairs)==8,'fixed pair inventory')
    write(DESIGN/'config.json',config);jsonl(DESIGN/'pairs.jsonl',pairs)
    write(DESIGN/'old_context.json',{'day2_protocol_id':old['release_id'],'day3_status':read(ROOT/config['day3_evaluated']/'stage_decision.json')['status'],
        'prior_exposure':'Researcher has seen Days 1–3, including negative control failure; new Qwen requests will not include any of those outputs'})
    write(DESIGN/'protocol_ref.json',{'path':'docs/C1_DAY4_DISCRIMINATIVE_PROTOCOL_V01.md','sha256':sha(ROOT/'docs/C1_DAY4_DISCRIMINATIVE_PROTOCOL_V01.md')})
    write(DESIGN/'implementation_hashes.json',code_hashes())
    for name in code_hashes():
        p=DESIGN/'implementation'/name;p.parent.mkdir(parents=True,exist_ok=True)
        with p.open('xb') as f:f.write((ROOT/name).read_bytes())
    model=read(ROOT/'configs/c1_day2_qwen_unrestricted_v01.json')
    model.pop('day2_protocol');model.update(version='day4-qwen-unrestricted-v01',day4_protocol=config['version'],
        scope_note='DAY1_RESEARCH is only a transport compatibility token; task is isolated Day 4 pairwise exploratory reference',
        authorization_ref='User explicitly authorized unlimited Qwen use and Day 4 execution; do not ask again or add fee/call ceilings',
        purpose='Fresh blinded full-record pairwise Silver only; no source rescreening, model self-Gold, old outputs or gain targets',
        price_checked='2026-10-20',price_verification='Official Qwen3.8-Max page and official model-pricing search refreshed for Day 4; original-rate estimate only, invoice null')
    write(DESIGN/'model_config.json',model)
    return freeze(DESIGN,{'version':config['version'],'created_at':datetime.now(timezone.utc).isoformat(),
                          'status':'DESIGN_FIXED_BEFORE_NEW_EVIDENCE_AUDIT_REFERENCE_AND_UTILITY','new_grades_seen':False})


def design():
    frozen=verify(DESIGN);require(read(CONFIG)==read(DESIGN/'config.json'),'Day 4 config drift')
    ref=read(DESIGN/'protocol_ref.json');require(sha(ROOT/ref['path'])==ref['sha256'],'protocol drift')
    require(code_hashes()==read(DESIGN/'implementation_hashes.json'),'Day 4 code drift; preserve old version and use an amendment')
    return read(CONFIG),rows(DESIGN/'pairs.jsonl'),frozen


def semantics(metric):
    if metric in ('steps','sleep_duration'):return 'DESCRIPTIVE_VALUE_VALID_NO_CLINICAL_OR_NIGHTLY_INFERENCE'
    if metric=='bed_time_std':return 'RECENT_TIMING_UNASSESSABLE_UPSTREAM_LOOKBACK_UNKNOWN'
    if metric=='sleep_efficiency':return 'RATIO_SCALE_UNVERIFIED'
    if metric in ('exercise_mets','hrv','vo2_max'):return 'UNSPECIFIED_AGGREGATION_OR_UNITS'
    if metric=='avg_stress_level':return 'DEVICE_SCORE_NOT_SUBJECTIVE_OR_CLINICAL_STRESS'
    if metric in ('exercise_count','exercise_hours'):return 'RECORDED_EXERCISE_TOTAL_NOT_INTENSITY_MODALITY_OR_STRENGTH'
    return 'DESCRIPTIVE_ONLY_NO_SUPPORTED_PAIRWISE_PRIORITY_RULE'


def audit_and_packets():
    config,pairs,registered=design();require(not PREPARED.exists(),'fresh reference preparation')
    _,units,queries,_=load_prepared(ROOT/config['day2_prepared']);source=ROOT/config['source_release']
    sourceclosure=verify_sources(ROOT/'data/raw/c1-benchmark-v2',read(source/'sources.json'))
    subjects=sorted({q['subject_id'] for q in queries});cases=rows(source/'cases.jsonl');probes=read(source/'probes.json')
    selected=[]
    for subject in subjects:
        long=sorted([c for c in cases if c['subject_id']==subject and c['history_days']==42],key=lambda c:c['end_date'])
        short=sorted([c for c in cases if c['subject_id']==subject and c['history_days']==14],key=lambda c:(c['end_date'],c['case_id']))
        require(len(long)==3 and short,'required fixed windows absent; no replacement')
        selected.extend(long+[short[0]])
    require(len(selected)==config['expected_real_cases'] and len(subjects)==config['expected_people'],'fixed sample count')
    split=read(source/'splits.json')['partitions'];sets=[set(split[p]['subject_ids']) for p in ('train','dev','test')]
    require(not(sets[0]&sets[1] or sets[0]&sets[2] or sets[1]&sets[2]) and set(subjects)<=sets[0],'participant split leak')
    originalcases={q['case_id'] for q in queries}
    identities={s:'P'+str(i+1) for i,s in enumerate(subjects)}
    pools={};scenario=[];allresults=[]
    for c in selected:
        sid='S4-'+digest(['day4-case-v1',c['case_id']])[:20]
        evidence=EvidenceProvider(c,probes).all();pools[c['case_id']]=evidence
        scenario.append({'scenario_id':sid,'case_id':c['case_id'],'case_hash':digest(c),'participant':identities[c['subject_id']],
                         'history_days':c['history_days'],'start_date':c['start_date'],'end_date':c['end_date'],
                         'original_Day2_window':c['case_id'] in originalcases,'data_origin':'REAL_WEARABLEQA',
                         'candidate_pair_ids':[p['pair_id'] for p in pairs]})
        for e in evidence:allresults.append({'scenario_id':sid,'participant':identities[c['subject_id']],
                                            'history_days':c['history_days'],'end_date':c['end_date'],**e})
    byprobe=defaultdict(list)
    for r in allresults:byprobe[r['probe_id']].append(r)
    audit=[]
    for p in probes:
        result=byprobe[p['probe_id']];good=[r for r in result if r['status']=='COMPUTED'];values=[r['value'] for r in good]
        oldids={s['scenario_id'] for s in scenario if s['original_Day2_window']}
        old=[r for r in good if r['scenario_id'] in oldids]
        count=len(set(values));status_var=len({r['status'] for r in result})>1
        audit.append({'probe':p,'semantic_admissibility':semantics(p['metric']),'valid_results':len(good),
                      'missing_results':len(result)-len(good),'missing_rate':1-len(good)/len(result),
                      'distinct_valid_values':count,'minimum':min(values) if values else None,'maximum':max(values) if values else None,
                      'numeric_discrimination':'OBSERVED_NUMERIC_VARIATION' if count>1 else 'STATUS_ONLY_VARIATION' if status_var else 'CONSTANT_OR_UNOBSERVED',
                      'Day2_three_windows':{'valid':len(old),'distinct_values':len({r['value'] for r in old}),
                          'minimum':min((r['value'] for r in old),default=None),'maximum':max((r['value'] for r in old),default=None)},
                      'within_person':{person:{'valid':sum(r['participant']==person for r in good),
                          'distinct':len({r['value'] for r in good if r['participant']==person}),
                          'chronological_values':[{'scenario_id':r['scenario_id'],'end_date':r['end_date'],'history_days':r['history_days'],'status':r['status'],'value':r['value']} for r in sorted(result,key=lambda r:r['end_date']) if r['participant']==person]}
                          for person in identities.values()},
                      'source_priority_threshold':None,'clinical_significance_of_range':None})
    jsonl(PREPARED/'scenarios.jsonl',scenario);jsonl(PREPARED/'selected_cases.jsonl',selected)
    jsonl(PREPARED/'canonical_results.jsonl',allresults);jsonl(PREPARED/'probe_audit.jsonl',audit)
    write(PREPARED/'backend_evidence.json',pools);write(PREPARED/'source_closure.json',sourceclosure)
    jsonl(PREPARED/'knowledge_units.jsonl',units);jsonl(PREPARED/'pairs.jsonl',pairs)
    write(PREPARED/'EVIDENCE_DISCRIMINABILITY_AUDIT.json',{'status':'REAL_NUMERIC_AUDIT_NOT_PRIORITY_LABELS',
          'cases':len(selected),'participants':len(subjects),'probes':len(probes),'results':len(allresults),
          'result_statuses':dict(Counter(r['status'] for r in allresults)),
          'numeric_variation_probes':sum(a['distinct_valid_values']>1 for a in audit),
          'status_only_variation_probes':sum(a['numeric_discrimination']=='STATUS_ONLY_VARIATION' for a in audit),
          'constant_or_unobserved_probes':sum(a['numeric_discrimination']=='CONSTANT_OR_UNOBSERVED' for a in audit),
          'metric_construct_status':{m:semantics(m) for m in sorted({p['metric'] for p in probes})},
          'only_existence_vs_numeric':'All registered probes return numeric aggregates or missing, not diagnostic booleans. The Day 2 B ranker used existence only; that is a consumer choice, not a limitation of the probe numeric values.',
          'clinical_meaningful_variation':None,'selection_using_values_or_labels':False,'synthetic_research_cases':0})
    rubric={'version':'day4-pair-relevance-v1','topic_relevance':['DIRECT','BACKGROUND','OFF_TOPIC'],
            'goal_relevance':['DIRECT','BACKGROUND','OFF_TOPIC'],'preference':['LEFT','RIGHT','TIE','UNKNOWN'],
            'grade':{'0':'Off query','1':'Background','2':'Direct','3':'Especially specific','null':'Unknown'},
            'evidence_relevance':'Specific legal observations may support relative specificity, but static Goal advantage is GOAL_ONLY',
            'hard_applicability':'NOT_ASSESSED','human_gold':False}
    tasks=[];mappings=[];byunit={u['knowledge_id']:u for u in units}
    for sc in scenario:
        c=next(c for c in selected if c['case_id']==sc['case_id'])
        display=display_evidence(pools[c['case_id']],probes,c['end_date'])
        for bundle in range(2):
            group=pairs[bundle*4:(bundle+1)*4]
            for view in ('primary','mirror'):
                taskid='J4-'+digest([sc['scenario_id'],bundle,view])[:20]
                unitids=sorted({kid for p in group for kid in p['candidate_ids']},key=lambda k:digest([taskid,k]))
                aliases={kid:'K4-'+digest([taskid,kid])[:14] for kid in unitids}
                shown=[];mapping=[]
                for pair in group:
                    a,b=pair['candidate_ids']
                    # Stable randomized primary orientation, then exact mirror.
                    if int(digest([sc['scenario_id'],pair['pair_id']])[:2],16)%2:a,b=b,a
                    if view=='mirror':a,b=b,a
                    alias='Q4-'+digest([taskid,pair['pair_id']])[:14]
                    shown.append({'pair_id':alias,'topic':pair['topic'],'goal':pair['goal'],
                                  'query_basis':'SYNTHETIC_BENCHMARK_GOAL','left':aliases[a],'right':aliases[b]})
                    mapping.append({'alias':alias,'pair_id':pair['pair_id'],'left':a,'right':b})
                knowledge=[{'candidate_id':aliases[k],'title':byunit[k]['title'],'text':byunit[k]['text'],
                            'source':byunit[k]['source'],'source_spans':byunit[k]['source_spans']} for k in unitids]
                payload={'task_id':taskid,'pairs':shown,'knowledge':knowledge,'evidence':display,'rubric':rubric,
                         'unknown_context':['age','symptoms','diagnoses','activity_modality','intensity_minutes','sleep_clock_events','preferences'],
                         'quality_scope':'Full allowed aggregate record; upstream bed_time_std lookback/efficiency scale/MET-HRV-VO2 units unresolved. Missing comparison history is retained.'}
                tasks.append({'task_id':taskid,'payload':payload,'schema':schema(payload)})
                mappings.append({'task_id':taskid,'scenario_id':sc['scenario_id'],'view':view,'bundle':bundle,'pairs':mapping})
    jsonl(PREPARED/'reference_tasks.jsonl',tasks);jsonl(PREPARED/'PRIVATE_reference_mapping.jsonl',mappings)
    write(PREPARED/'rubric.json',rubric);write(PREPARED/'prompt.json',{'system':PROMPT})
    sizes={t['task_id']:len(json.dumps(build_request([{'role':'system','content':PROMPT},{'role':'user','content':json.dumps(t['payload'],ensure_ascii=False)}],read(DESIGN/'model_config.json'),t['schema'],ANNOTATION_FUNCTION),ensure_ascii=False,separators=(',',':')).encode()) for t in tasks}
    require(max(sizes.values())<=read(DESIGN/'model_config.json')['max_input_bytes'],'packet too large; do not truncate full record')
    write(PREPARED/'packet_sizes.json',sizes)
    # Human materials contain no AI labels or scores, and make no reviewer attestations.
    jsonl(PREPARED/'human_review/packets.jsonl',[t['payload'] for t in tasks if next(m['view'] for m in mappings if m['task_id']==t['task_id'])=='primary'])
    write(PREPARED/'human_review/template.json',{'reviewer_id':None,'human_attestation':False,'independence_attestation':False,
          'status':'PREPARED_NOT_ANNOTATED','responses':[],'instructions':'Two genuine independent human reviews/adjudication required for human Gold. Do not fill using AI outputs.'})
    write(PREPARED/'design_ref.json',{'release_id':registered['release_id'],'code_hashes':code_hashes()})
    return freeze(PREPARED,{'status':'FRESH_BLINDED_REFERENCE_PACKETS_FIXED_BEFORE_CALLS','created_at':datetime.now(timezone.utc).isoformat(),
                           'real_cases':12,'pairs':8,'reference_tasks':len(tasks),'reference_grades_seen':False})


def execute_references(workers=4):
    config,pairs,registered=design();prepared=verify(PREPARED)
    require(not REFERENCE.exists(),'fresh reference execution')
    model=read(DESIGN/'model_config.json')
    client=ReferenceClient(BASE/'qwen-ledger-v01',model,api_key=read(ROOT/'local/c1-v2/connection.json')['api_key'])
    tasks=rows(PREPARED/'reference_tasks.jsonl');mappings={r['task_id']:r for r in rows(PREPARED/'PRIVATE_reference_mapping.jsonl')}
    def call_one(task):
        payload=task['payload'];mapping=mappings[task['task_id']]
        record={'task_id':task['task_id'],'scenario_id':mapping['scenario_id'],'view':mapping['view'],'status':'CALL_OR_SCHEMA_FAILURE',
                'reference_kind':'FRESH_QWEN_PAIRWISE_SILVER_DAY4','human_gold':False,'new_stateless_request':True}
        try:
            output,trace=client.call([{'role':'system','content':PROMPT},{'role':'user','content':json.dumps(payload,ensure_ascii=False)}],
                schema=task['schema'],function_name=ANNOTATION_FUNCTION,prompt_version=config['version']+'-blinded-pair-reference-v1')
            byalias={j['pair_id']:j for j in output['judgments']}
            require(len(byalias)==len(output['judgments']) and set(byalias)=={p['pair_id'] for p in payload['pairs']},'pair inventory mismatch')
            record.update(status='RESPONSE_RECEIVED',request_hash=trace['request_sha256'],response_hash=trace['response_sha256'],
                          model_id=trace['returned_model'],cache_key=trace['cache_key'],judgments=[])
            for alias,m in ((m['alias'],m) for m in mapping['pairs']):
                j=byalias[alias];p=next(p for p in payload['pairs'] if p['pair_id']==alias)
                e=errors(j,p,payload)
                record['judgments'].append({'pair_id':m['pair_id'],'status':'ACCEPTED' if not e else 'REVIEW_REQUIRED',
                        'validation_errors':e,'input_row':j,**normalize(j,m['left'],m['right'])})
        except Exception as exc:record['error_type']=type(exc).__name__
        write(REFERENCE/'records'/(task['task_id']+'.json'),record)
        return record
    results=[]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures=[pool.submit(call_one,t) for t in tasks]
        for future in as_completed(futures):
            result=future.result();results.append(result)
            print(json.dumps({'completed':len(results),'total':len(tasks),'status':result['status']}),flush=True)
    jsonl(REFERENCE/'reference_results.jsonl',sorted(results,key=lambda r:r['task_id']))
    cache=[read(p) for p in (BASE/'qwen-ledger-v01/cache').glob('*.json')]
    usage={key:sum((r.get('usage') or {}).get(key,0) for r in cache) for key in ('prompt_tokens','completion_tokens')}
    summary={'tasks':len(tasks),'task_statuses':dict(Counter(r['status'] for r in results)),
             'pair_views_received':sum(len(r.get('judgments',[])) for r in results),'token_usage':usage,
             'usage_original_price_estimate_cny':(usage['prompt_tokens']*12+usage['completion_tokens']*36)/1e6,'actual_invoice_cny':None,
             'attempts':len(list((BASE/'qwen-ledger-v01/attempts').glob('*.json'))),'raw_responses':len(cache),
             'independent_human_reviews':0,'same_model_mirror_is_independent':False,'request_blinded_to_ranker_and_old_outputs':True}
    write(REFERENCE/'summary.json',summary)
    write(REFERENCE/'preparation_ref.json',{'release_id':prepared['release_id'],'design_id':registered['release_id']})
    freeze(REFERENCE,{'status':'REAL_BLINDED_AI_REFERENCE_EXECUTED_PENDING_SEMANTICS','created_at':datetime.now(timezone.utc).isoformat()})
    return summary


def main():
    p=argparse.ArgumentParser();p.add_argument('stage',choices=['design','prepare','reference']);p.add_argument('--workers',type=int,default=4);a=p.parse_args()
    result={'design':prepare_design,'prepare':audit_and_packets,'reference':lambda:execute_references(a.workers)}[a.stage]()
    print(json.dumps({k:v for k,v in result.items() if k!='files'},ensure_ascii=False,indent=2))


if __name__=='__main__':main()
