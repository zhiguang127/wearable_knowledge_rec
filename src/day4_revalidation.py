"""Explicit input-schema amendment; original Day 4 modules and traces stay sealed."""
from copy import deepcopy
from datetime import datetime,timezone
import json

from .common import ROOT,read,rows,write,sha,digest,require
from .datasets.v2_sources import verify,freeze,jsonl
from .day1.structured import decode_response,ANNOTATION_FUNCTION
from .day4.pilot import BASE,DESIGN,PREPARED,REFERENCE,design
from .day4.reference import errors,normalize

CONFIG=ROOT/'configs/c1_day4_reference_revalidation_v01r1.json'
AMENDMENT=BASE/'schema-amendment-v01r1'


def amended_schema(original):
    result=deepcopy(original)
    props=result['properties']['judgments']['items']['properties']
    for name in ('goal_left','goal_right'):
        props[name]['type']=['string','null'];props[name]['enum']+=['UNKNOWN',None]
    return result


def unknown_goal_errors(j):
    if any(j[k] in ('UNKNOWN',None) for k in ('goal_left','goal_right')):
        if j['preference']!='UNKNOWN' or j['grade_left'] is not None or j['grade_right'] is not None:
            return ['UNKNOWN_GOAL_REQUIRES_UNKNOWN_PERSONAL_COMPARISON']
    return []


def prepare_amendment():
    design();require(not AMENDMENT.exists(),'fresh schema amendment')
    write(AMENDMENT/'config.json',read(CONFIG))
    write(AMENDMENT/'code.json',{'path':'src/day4_revalidation.py','sha256':sha(__file__),
          'document_sha256':sha(ROOT/'docs/C1_DAY4_REFERENCE_SCHEMA_AMENDMENT_V01R1.md')})
    return freeze(AMENDMENT,{'status':'POST_RESPONSE_SCHEMA_FIX_BEFORE_REFERENCE_SIGNAL_OR_UTILITY_ANALYSIS',
                            'created_at':datetime.now(timezone.utc).isoformat(),'results_observed':'Some raw outputs and validation errors, no ranking evaluation'})


def revalidate():
    design();verify(PREPARED);verify(REFERENCE);amend=verify(AMENDMENT)
    require(sha(__file__)==read(AMENDMENT/'code.json')['sha256'] and read(CONFIG)==read(AMENDMENT/'config.json'),'amendment drift')
    cfg=read(CONFIG);output=ROOT/cfg['reference_output'];require(not output.exists(),'fresh r1 reference layer')
    tasks=rows(PREPARED/'reference_tasks.jsonl');mapping={r['task_id']:r for r in rows(PREPARED/'PRIVATE_reference_mapping.jsonl')}
    original={r['task_id']:r for r in rows(REFERENCE/'reference_results.jsonl')}
    caches={read(p)['request_sha256']:read(p) for p in (BASE/'qwen-ledger-v01/cache').glob('*.json')}
    from .day4.reference import PROMPT
    from .day1.structured import build_request
    model=read(DESIGN/'model_config.json');records=[]
    for task in tasks:
        payload=task['payload'];m=mapping[task['task_id']]
        request=build_request([{'role':'system','content':PROMPT},{'role':'user','content':json.dumps(payload,ensure_ascii=False)}],model,task['schema'],ANNOTATION_FUNCTION)
        trace=caches.get(digest(request));before=original[task['task_id']]
        record={'task_id':task['task_id'],'scenario_id':m['scenario_id'],'view':m['view'],'status':'CALL_OR_SCHEMA_FAILURE',
                'reference_kind':'FRESH_QWEN_PAIRWISE_SILVER_DAY4_SCHEMA_R1','human_gold':False,
                'original_v01_status':before['status'],'schema_amendment_id':amend['release_id'],'new_model_call':False}
        try:
            require(trace is not None,'original raw response absent')
            require(trace['response_sha256']==digest(trace['response']),'original response hash mismatch')
            decoded=decode_response(trace['response'],function_name=ANNOTATION_FUNCTION,schema=amended_schema(task['schema']))
            byalias={j['pair_id']:j for j in decoded['judgments']}
            require(len(byalias)==len(decoded['judgments']) and set(byalias)=={p['pair_id'] for p in payload['pairs']},'pair inventory')
            record.update(status='RESPONSE_RECEIVED',request_hash=trace['request_sha256'],response_hash=trace['response_sha256'],
                          cache_key=trace['cache_key'],model_id=trace['returned_model'],judgments=[])
            for match in m['pairs']:
                j=byalias[match['alias']];pair=next(p for p in payload['pairs'] if p['pair_id']==match['alias'])
                problems=errors(j,pair,payload)+unknown_goal_errors(j)
                record['judgments'].append({'pair_id':match['pair_id'],'status':'ACCEPTED' if not problems else 'REVIEW_REQUIRED',
                    'validation_errors':sorted(set(problems)),'input_row':j,**normalize(j,match['left'],match['right'])})
        except Exception as exc:record['error_type']=type(exc).__name__
        records.append(record)
    jsonl(output/'reference_results.jsonl',records)
    from collections import Counter
    write(output/'summary.json',{'original_run':REFERENCE.relative_to(ROOT).as_posix(),'original_summary':read(REFERENCE/'summary.json'),
        'task_statuses':dict(Counter(r['status'] for r in records)),'pair_views_received':sum(len(r.get('judgments',[])) for r in records),
        'original_failed_tasks_now_revalidated':sum(r['original_v01_status']!='RESPONSE_RECEIVED' and r['status']=='RESPONSE_RECEIVED' for r in records),
        'new_model_calls':0,'original_responses_edited':False,'grades_or_preferences_edited':False,'human_gold':False})
    freeze(output,{'status':'VERSIONED_UNKNOWN_PRESERVING_SCHEMA_REVALIDATION_NOT_NEW_ANNOTATION','amendment_id':amend['release_id']})
    return read(output/'summary.json')


def analyze():
    from .day4 import analysis
    cfg=read(CONFIG)
    analysis.REFERENCE=ROOT/cfg['reference_output']
    analysis.OUTPUT=ROOT/cfg['analysis_output']
    analysis.SEMANTIC=ROOT/cfg['semantic_review']
    return analysis.analyze()


if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('stage',choices=['prepare','revalidate','analyze']);args=p.parse_args()
    result={'prepare':prepare_amendment,'revalidate':revalidate,'analyze':analyze}[args.stage]()
    print(json.dumps({k:v for k,v in result.items() if k!='files'},ensure_ascii=False,indent=2))
