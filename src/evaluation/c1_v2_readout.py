"""Aggregate-only readout. Never export participant IDs, dates, labels or model payloads."""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
from statistics import median
from ..common import digest, read, require, rows, write
from ..datasets.v2_sources import verify, freeze, jsonl
from ..knowledge.c1_v2 import duplicates


def distribution(values):
    values=sorted(values)
    return {"n":len(values),"min":min(values) if values else None,"median":median(values) if values else None,
            "p10":values[int((len(values)-1)*.1)] if values else None,
            "p90":values[int((len(values)-1)*.9)] if values else None,"max":max(values) if values else None}


def summarize(release,evaluation,annotation=None,qa=None):
    release,evaluation=Path(release),Path(evaluation)
    rf,ef=verify(release),verify(evaluation)
    require(ef['source_release_id']==rf['release_id'],'readout release mismatch')
    cases=rows(release/'cases.jsonl');casebyid={c['case_id']:c for c in cases}
    coverage=rows(evaluation/'coverage_by_participant_window.jsonl')
    window_metric=defaultdict(list);subject_metric=defaultdict(lambda:[0,0])
    for row in coverage:
        window_metric[row['metric']].append(row['coverage'])
        a=subject_metric[(row['subject_id'],row['metric'])];a[0]+=row['valid'];a[1]+=row['calendar_days']
    participant_metric=defaultdict(list)
    for (subject,metric),(n,d) in subject_metric.items():participant_metric[metric].append(n/d)
    batch=rows(evaluation/'batch_times.jsonl');bylength=defaultdict(list);status_by_length=defaultdict(Counter)
    for row in batch:
        bylength[str(row['history_days'])].append(row['batch_seconds']*1000)
        status_by_length[str(row['history_days'])].update(row['statuses'])
    knowledge=rows(release/'knowledge_candidates.jsonl')
    reviewed=[];active=[];annotation_report=None
    if annotation:
        annotation=Path(annotation);af=verify(annotation)
        require(af['source_release_id']==rf['release_id'],'readout annotations mismatch')
        annotation_report=read(annotation/'report.json')
        active=rows(annotation/'knowledge_active.jsonl');reviewed=rows(annotation/'knowledge_reviewed.jsonl')
        accepted=sum(annotation_report['label_statuses'].get(k,0) for k in ['SILVER_ACCEPTED'])
        annotation_report['accepted_label_pair_coverage']=accepted/max(1,len(cases)*len(active))
        annotation_report['knowledge_stage_disagreement_rate']=annotation_report.get('knowledge_stage_disagreements',0)/max(1,annotation_report.get('knowledge_two_stage_completed',0))
        annotation_report['label_stage_disagreement_rate']=annotation_report.get('label_conflicts',0)/max(1,annotation_report['labels'])
    size=[]
    for pool_name,pool in [('source_candidates',knowledge),('silver_active',active)]:
        ordered=sorted(pool,key=lambda k:digest(['c1-v2-size-coverage-v1',k['knowledge_id']]))
        for n in (26,100,300,500):
            selected=ordered[:n];pairs=duplicates(selected)
            size.append({'pool':pool_name,'requested_size':n,'actual_size':len(selected),
                         'selection':'nested SHA256 order independent of labels','topics':dict(Counter(k['topic'] for k in selected)),
                         'topic_count':len({k['topic'] for k in selected}),'near_duplicate_pairs':len(pairs),
                         'near_duplicate_pair_denominator':len(selected)*(len(selected)-1)//2,
                         'near_duplicate_pair_rate':len(pairs)/max(1,len(selected)*(len(selected)-1)//2),
                         'trigram_jaccard_threshold':.6})
    report={'release_id':rf['release_id'],'summary':read(release/'summary.json'),
            'evaluation':read(evaluation/'report.json'),'annotation':annotation_report,
            'quality_audit':read(qa) if qa else None,
            'window_metric_coverage':{m:distribution(v) for m,v in sorted(window_metric.items())},
            'participant_metric_coverage':{m:distribution(v) for m,v in sorted(participant_metric.items())},
            'coverage_note':'Participant ratios weight available windows; overlapping horizon windows are descriptive repeated measurements, not independent days or participants.',
            'all_probes_batch_ms_by_history':{n:distribution(v) for n,v in sorted(bylength.items(),key=lambda x:int(x[0]))},
            'probe_status_by_history':{n:dict(c) for n,c in sorted(status_by_length.items(),key=lambda x:int(x[0]))},
            'knowledge_size_comparison':size,'exact_duplicate_exclusions':sum('exact_duplicate' in r['reason'] for r in rows(release/'knowledge_exclusions.jsonl')),
            'knowledge_exclusion_reasons':dict(Counter(r['reason'].split(':')[0] for r in rows(release/'knowledge_exclusions.jsonl'))),
            'conditions_per_knowledge':distribution([len(k['conditions']) for k in active]),
            'executable_probe_count_per_knowledge':distribution([len({p for c in k['conditions'] for p in c['probe_ids']}) for k in active]),
            'supported_condition_probe_count_per_knowledge':distribution([len({p for c in k['conditions'] if c['dataset_support']=='supported' for p in c['probe_ids']}) for k in active]),
            'multiple_evidence_candidates':[{'knowledge_id':k['knowledge_id'],'title':k['title'],'source_url':k['source_url'],
                 'conditions':[{'condition_id':c['condition_id'],'text':c['text'],'role':c['role'],'logic':c['logic'],
                                'use':c['use'],'dataset_support':c['dataset_support'],'probe_ids':c['probe_ids']} for c in k['conditions']],
                 'status':'CANDIDATE_ONLY_NOT_CONFIRMED_JOINT_NECESSITY'} for k in active
                 if len({p for c in k['conditions'] for p in c['probe_ids']})>1],
            'dataset_support_roles':dict(Counter(c['dataset_support'] for k in active for c in k['conditions'])),
            'condition_logic':dict(Counter(c['logic'] for k in active for c in k['conditions'])),
            'silver_condition_status_is_not_gold':True,
            'conclusions':{'full_computation':'CHEAP_IN_THIS_MEASURED_SETTING',
                           'joint_evidence_dependencies':'NO_CONFIRMED_JOINT_NECESSARY_DEPENDENCY_OR_DELAYED_DISCOVERY_GAIN',
                           'delayed_discovery_gain':None,'clinical_benefit':None,'recommendation_accuracy':None,
                           'caveat':'Source-grounded education and model-only conditions do not establish personal health benefit or independent Gold. No KUV/M1/RL/AFA implemented.'}}
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--release',default='data/releases/c1-benchmark-v2.1');p.add_argument('--evaluation',required=True)
    p.add_argument('--annotation');p.add_argument('--qa');p.add_argument('--output',required=True)
    p.add_argument('--public-dir',help='New directory for source/probe/knowledge metadata only; no personal records')
    a=p.parse_args();report=summarize(a.release,a.evaluation,a.annotation,a.qa)
    write(a.output,report);print(json.dumps({'output':a.output,'release_id':report['release_id'],'personal_rows_exported':0}))
    if a.public_dir:
        root=Path(a.public_dir);require(not root.exists(),'public export directory exists')
        release=Path(a.release);root.mkdir(parents=True)
        write(root/'aggregate_report.json',report)
        write(root/'sources.json',read(release/'sources.json'))
        write(root/'probes.json',read(release/'probes.json'))
        from ..datasets.probes import PROBE_SCHEMA
        from ..annotation import c1_v2_schemas
        for name,schema in [('probe',PROBE_SCHEMA),('knowledge_review',c1_v2_schemas.KNOWLEDGE),
                            ('knowledge_audit',c1_v2_schemas.AUDIT),('label',c1_v2_schemas.LABEL),('label_audit',c1_v2_schemas.LABEL_AUDIT)]:
            write(root/'schemas'/(name+'.json'),schema)
        if a.annotation:
            ann=Path(a.annotation)
            audits={r['knowledge_id']:r for r in rows(ann/'knowledge_reviews.jsonl')}
            canonical=read(ann/'canonical_duplicates.json')
            keys=('knowledge_id','title','topic','subtopic','source_url','source_sha256','accessed_at','review_status','condition_review_status','label_provenance')
            jsonl(root/'knowledge_index.jsonl',({**{k:item[k] for k in keys},
                  'source_anchor_id':item['source_anchor']['anchor_id'],'anchor_text_sha256':item['source_anchor']['text_sha256'],
                  'source_block_index':item['source_anchor']['block_index'],
                  'canonical_id':canonical.get(item['knowledge_id']),'active':canonical.get(item['knowledge_id'])==item['knowledge_id'],
                  'program_validation_errors':audits[item['knowledge_id']]['validation_errors'],
                  'condition_roles':[{'role':c['role'],'logic':c['logic'],'use':c['use'],
                                      'probe_ids':c['probe_ids'],'dataset_support':c['dataset_support']} for c in item['conditions']]}
                  for item in rows(ann/'knowledge_reviewed.jsonl')))
            write(root/'dependency_index.json',read(ann/'dependency_index.json'))
            write(root/'canonical_duplicates.json',canonical)
        if a.qa:write(root/'qa_report.json',read(a.qa))
        freeze(root,{'version':'c1-v2-public-metadata-v1','source_release_id':report['release_id'],
                     'personal_rows':0,'human_gold':False,'content':'Aggregate statistics, source identities and nonpersonal knowledge/probe metadata only'})


if __name__=='__main__':main()
