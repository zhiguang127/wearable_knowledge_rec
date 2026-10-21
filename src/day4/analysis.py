"""Analyze fresh reference discrimination before permitting ranking utility."""
from collections import Counter,defaultdict
from itertools import combinations
from datetime import datetime,timezone
from statistics import mean

from ..common import ROOT,read,rows,write,digest,require,sha
from ..datasets.v2_sources import verify,freeze,jsonl
from ..day1.evidence import EvidenceProvider
from ..day2.core import DiagnosticRanker,ranking_relations
from ..day3.metrics import evaluate as metrics,changes,summarize,delta,METRICS
from .pilot import BASE,DESIGN,PREPARED,REFERENCE,design
from .core import Environment,arm_actions,VERSION

OUTPUT=BASE/'analysis-v01'
SEMANTIC=BASE/'semantic-review-v01.json'


def pair_comparisons(qrels):
    comparisons=[]
    for a,b in combinations(qrels,2):
        if a['pair_id']!=b['pair_id']:continue
        known=a['preference'] is not None and b['preference'] is not None
        changed=known and a['preference']!=b['preference']
        dependent=a['basis']=='DESCRIPTIVE_EVIDENCE' or b['basis']=='DESCRIPTIVE_EVIDENCE'
        supported=changed and dependent and a['measurement_signature']!=b['measurement_signature']
        comparisons.append({'pair_id':a['pair_id'],'scenario_ids':[a['scenario_id'],b['scenario_id']],
            'participants':[a['participant'],b['participant']],
            'comparison':'WITHIN_PERSON_TIME' if a['participant']==b['participant'] else 'ACROSS_PERSON_CALENDAR_CONFOUNDED',
            'both_known':known,'relation_changed':changed,
            'strict_reversal':known and a['preference']*b['preference']==-1,
            'tie_relation_change':changed and (a['preference']==0 or b['preference']==0),
            'source_audited_evidence_conditioned_change':supported,
            'same_cited_measurement_opposite':known and a['preference']*b['preference']==-1 and bool(a['evidence_ids']) and a['measurement_signature']==b['measurement_signature'],
            'non_evidence_basis_change':changed and not dependent})
    return comparisons


def signal_gate(comparisons):
    return sorted({c['pair_id'] for c in comparisons if c['source_audited_evidence_conditioned_change']})


def analyze():
    config,pairs,registered=design();verify(PREPARED);verify(REFERENCE);require(not OUTPUT.exists(),'fresh Day 4 analysis')
    require(SEMANTIC.exists(),'hash-bound source review required')
    reviewdoc=read(SEMANTIC);require(reviewdoc['human_gold'] is False and reviewdoc['reviewer_type']=='MODEL_SOURCE_AUDIT','review provenance')
    review={r['row_hash']:r for r in reviewdoc['rows']}
    raw=rows(REFERENCE/'reference_results.jsonl');allrows=[j for r in raw for j in r.get('judgments',[])]
    require(set(review)=={j['row_hash'] for j in allrows} and len(review)==len(reviewdoc['rows']),'semantic review exact inventory')
    scenarios=rows(PREPARED/'scenarios.jsonl');scmap={s['scenario_id']:s for s in scenarios};by_pair={p['pair_id']:p for p in pairs}
    tasks={t['task_id']:t['payload'] for t in rows(PREPARED/'reference_tasks.jsonl')}
    indexed={(r['scenario_id'],j['pair_id'],r['view']):(r,j) for r in raw for j in r.get('judgments',[])}
    require(len(indexed)==len(allrows),'duplicate pair/view')
    qrels=[];mismatches=[]
    for sc in scenarios:
        for pair in pairs:
            key=(sc['scenario_id'],pair['pair_id']);left=indexed.get((*key,'primary'));right=indexed.get((*key,'mirror'))
            issues=[]
            for label,item in (('primary',left),('mirror',right)):
                if item is None:issues.append(label+'_MISSING')
                elif item[1]['status']!='ACCEPTED' or review[item[1]['row_hash']]['status']!='ACCEPTED':issues.append(label+'_VALIDATION_OR_SEMANTIC_PENDING')
            pj=left[1] if left else None;mj=right[1] if right else None
            agreement=pj is not None and mj is not None and pj['preference']==mj['preference']
            exact=agreement and pj['grades']==mj['grades']
            if pj and mj and not agreement:issues.append('MIRRORED_PREFERENCE_DISAGREEMENT')
            if issues:mismatches.append({'scenario_id':sc['scenario_id'],'pair_id':pair['pair_id'],'issues':issues})
            allowed=not issues
            pref=pj['preference'] if allowed else None
            grades=pj['grades'] if allowed else {kid:None for kid in pair['candidate_ids']}
            evidence=pj['evidence_ids'] if allowed else []
            ev={e['evidence_id']:e for e in tasks[left[0]['task_id']]['evidence']} if left else {}
            signature=digest(sorted((ev[i]['metric'],ev[i]['operation'],ev[i]['window_days'],ev[i]['status'],ev[i]['value'],ev[i]['unit'],ev[i]['start_day'],ev[i]['end_day']) for i in evidence))
            qrels.append({'scenario_id':sc['scenario_id'],'pair_id':pair['pair_id'],'participant':sc['participant'],
                'topic':pair['topic'],'goal_hash':digest(pair['goal']),'history_days':sc['history_days'],
                'data_origin':'REAL_WEARABLEQA','reference_kind':'FRESH_QWEN_PAIRWISE_SILVER_DAY4','human_gold':False,
                'reference_status':'REVIEW_REQUIRED' if issues else 'UNKNOWN' if pref is None else 'ACCEPTED',
                'reference_issues':issues,'grades':grades,'preference':pref,'basis':pj['basis'] if allowed else None,
                'source_relation':pj['source_relation'] if allowed else None,'evidence_ids':evidence,
                'source_span_ids':pj['source_span_ids'] if allowed else {},
                'row_hash':pj['row_hash'] if pj else None,'mirror_row_hash':mj['row_hash'] if mj else None,
                'mirror_preference_agrees':agreement,'mirror_grades_exact':exact,
                'reason':pj['reason'] if pj else None,'limitations':pj['limitations'] if pj else None,
                'measurement_signature':signature,'source_overlap_or_granularity_risk':pair['source_overlap_or_granularity_risk']})
    comparisons=pair_comparisons(qrels);supported=signal_gate(comparisons);gate=bool(supported)
    # Reference analysis is completed before the first Ranker execution in this stage.
    discrimination={'real_scenarios':len(scenarios),'people':len({s['participant'] for s in scenarios}),'pairs':len(pairs),
        'paired_reference_slots':len(qrels),'material_returned_pair_views':len(allrows),
        'reference_status_counts':dict(Counter(r['reference_status'] for r in qrels)),
        'preference_counts':dict(Counter('UNKNOWN' if r['preference'] is None else 'TIE' if r['preference']==0 else 'STRICT' for r in qrels)),
        'basis_counts':dict(Counter(str(r['basis']) for r in qrels)),
        'mirrored_preference_disagreement_slots':sum('MIRRORED_PREFERENCE_DISAGREEMENT' in r['reference_issues'] for r in qrels),
        'mirrored_exact_grade_agreement_slots':sum(r['mirror_grades_exact'] for r in qrels),
        'source_audited_evidence_conditioned_pairs':supported,'reference_signal_gate_passed':gate,
        'comparison_totals':{kind:{field:sum(c[field] for c in comparisons if c['comparison']==kind)
             for field in ('both_known','relation_changed','strict_reversal','tie_relation_change','source_audited_evidence_conditioned_change','non_evidence_basis_change','same_cited_measurement_opposite')}
             for kind in ('WITHIN_PERSON_TIME','ACROSS_PERSON_CALENDAR_CONFOUNDED')},
        'per_pair':[{ 'pair_id':p['pair_id'],'control':p['control'],
             'reference_status_counts':dict(Counter(q['reference_status'] for q in qrels if q['pair_id']==p['pair_id'])),
             'preferences_by_person':{person:[q['preference'] for q in qrels if q['pair_id']==p['pair_id'] and q['participant']==person] for person in sorted({s['participant'] for s in scenarios})},
             'source_audited_changes':sum(c['source_audited_evidence_conditioned_change'] for c in comparisons if c['pair_id']==p['pair_id'])} for p in pairs],
        'identical_query_text_verified':len({q['goal_hash'] for q in qrels})==len(pairs),
        'synthetic_research_cases':0,'independent_human_gold':0,'model_family_independent':False}
    jsonl(OUTPUT/'shared_full_record_qrels.jsonl',qrels);jsonl(OUTPUT/'reference_context_comparisons.jsonl',comparisons)
    write(OUTPUT/'REFERENCE_DISCRIMINABILITY.json',discrimination)
    cases={c['case_id']:c for c in rows(PREPARED/'selected_cases.jsonl')};probes=read(ROOT/config['source_release']/'probes.json')
    units=rows(PREPARED/'knowledge_units.jsonl');pools=read(PREPARED/'backend_evidence.json')
    providers={cid:EvidenceProvider(c,probes) for cid,c in cases.items()}
    for cid,pool in pools.items():
        for e in pool:providers[cid].verify_bound(e)
    recordings=[];evaluations=[];action_records=[];legacy=[]
    for qrel in qrels:
        sc=scmap[qrel['scenario_id']];pair=by_pair[qrel['pair_id']]
        query={k:pair[k] for k in ('topic','goal','candidate_ids','links')}
        query.update(query_id='Q4-'+digest([sc['scenario_id'],pair['pair_id']])[:20],case_id=sc['case_id'],query_basis='SYNTHETIC_BENCHMARK_GOAL')
        candidate=[u for u in units if u['knowledge_id'] in pair['candidate_ids']]
        seeds,actions=arm_actions(pair,probes);states={}
        for arm in ('A','B','C','D','D0'):
            env=Environment(query,candidate,providers[sc['case_id']],probes);state=env.reset([] if arm=='A' else seeds,1);cost=0
            if arm in actions:
                before=state;state,cost,done=env.step(actions[arm]);require(cost==1 and done,'uniform acquisition path')
                require({e['probe_id'] for e in state['observed_evidence']}==set(seeds)|{actions[arm]},'hidden-result leakage')
                acquired=next(e for e in state['observed_evidence'] if e['probe_id']==actions[arm])
                action_records.append({'scenario_id':sc['scenario_id'],'pair_id':pair['pair_id'],'participant':sc['participant'],
                    'arm':arm,'initial_observation_hash':digest(before),'cost':cost,'acquired_probe_id':actions[arm],
                    'acquired_status':acquired['status'],'initial_evidence_ids':[e['evidence_id'] for e in before['observed_evidence']]})
            states[arm]=state
            recordings.append({'scenario_id':sc['scenario_id'],'pair_id':pair['pair_id'],'participant':sc['participant'],'arm':arm,'state':state,'cost':cost})
            legacy.append({'scenario_id':sc['scenario_id'],'pair_id':pair['pair_id'],'arm':arm,
                           'ranking':DiagnosticRanker().rank(query,state['observed_evidence'],candidate,probes),
                           'role':'HISTORICAL_DIAGNOSTIC_NOT_EMPIRICAL_SPECIFICITY_CONTROL'})
        for arm in ('C','D','D0'):
            record=next(r for r in action_records[::-1] if r['scenario_id']==sc['scenario_id'] and r['pair_id']==pair['pair_id'] and r['arm']==arm)
            require(record['initial_observation_hash']==next(r['initial_observation_hash'] for r in action_records[::-1] if r['scenario_id']==sc['scenario_id'] and r['pair_id']==pair['pair_id'] and r['arm']=='C'),'C/D seed mismatch')
        arms={arm:metrics(state['ranking'],qrel['grades']) if gate else {m:None for m in METRICS} for arm,state in states.items()}
        row={'scenario_id':sc['scenario_id'],'pair_id':pair['pair_id'],'participant':sc['participant'],'history_days':sc['history_days'],
             'reference_status':qrel['reference_status'],'reference_preference':qrel['preference'],'utility_gate_passed':gate,
             'arms':arms,'value':{m:{'delta_C':delta(arms['C'][m],arms['B'][m]),'delta_D':delta(arms['D'][m],arms['B'][m]),
                     'delta_delta':delta(arms['C'][m],arms['D'][m]),'delta_D0':delta(arms['D0'][m],arms['B'][m])} for m in METRICS},
             'changes':{key:changes(states[a]['ranking'],states[b]['ranking'],qrel['grades']) for key,a,b in (('A_B','A','B'),('B_C','B','C'),('B_D','B','D'),('B_D0','B','D0'),('C_D','C','D'))},
             'comparison_resolved':{a:s['mechanism_comparison_resolved'] for a,s in states.items()},
             'strict_preference_recovery':{a:None if not gate or qrel['preference'] in (None,0) else
                 int(next(iter(ranking_relations(states[a]['ranking']).values()))==qrel['preference']) for a in ('A','B','C','D','D0')},
             'source_overlap_or_granularity_risk':qrel['source_overlap_or_granularity_risk'],'mirror_grades_exact':qrel['mirror_grades_exact']}
        evaluations.append(row)
    def aggregate(data):
        return {'arms':{arm:{m:summarize(data,lambda r:r['arms'][arm][m]) for m in METRICS} for arm in ('A','B','C','D','D0')},
                'value':{m:{k:summarize(data,lambda r:r['value'][m][k]) for k in ('delta_C','delta_D','delta_delta','delta_D0')} for m in METRICS}}
    summary=aggregate(evaluations)
    sensitivity={'require_exact_mirror_grades':aggregate([r for r in evaluations if r['mirror_grades_exact']]),
                 'exclude_overlapping_spans_or_unequal_granularity':aggregate([r for r in evaluations if not r['source_overlap_or_granularity_risk']]),
                 'by_history':{str(h):aggregate([r for r in evaluations if r['history_days']==h]) for h in (14,42)}}
    effects=summary['value']['ndcg@5']['delta_delta'];gain=effects['participant_macro_mean']
    reviewed_by_person={person:{q['pair_id'] for q in qrels if q['participant']==person and q['reference_status']!='REVIEW_REQUIRED'} for person in sorted({s['participant'] for s in scenarios})}
    adequate=sum(len(v)==8 for v in reviewed_by_person.values())>=2
    sensitivity_gain=[v['value']['ndcg@5']['delta_delta']['participant_macro_mean'] for k,v in sensitivity.items() if k!='by_history']
    ready=gate and gain is not None and gain>1e-12 and all(v is not None and v>=-1e-12 for v in effects['leave_one_participant_out'].values()) and all(v is not None and v>1e-12 for v in sensitivity_gain)
    status='SIGNAL_SUPPORTED_EXPLORATORY' if ready else 'MEASUREMENT_OR_TASK_REDESIGN_REQUIRED' if adequate else 'INSUFFICIENT_EVIDENCE'
    mechanism={'reference_signal_gate_passed':gate,'ranking_utility_executed':gate,
               'utility_not_run_reason':None if gate else 'NO_SOURCE_AUDITED_EVIDENCE_DEPENDENT_REFERENCE_RELATION_CHANGE',
               'real_query_pairs':len(evaluations),'legal_acquisition_actions':len(action_records),
               'acquired_status_by_arm':{a:dict(Counter(r['acquired_status'] for r in action_records if r['arm']==a)) for a in ('C','D','D0')},
               'rank_change_summary':{k:{f:sum(r['changes'][k][f] for r in evaluations) for f in ('candidate_score_changes','changed_relations','tie_relation_changes','strict_order_reversals','ranking_changed')} for k in ('A_B','B_C','B_D','B_D0','C_D')},
               'model_comparison_resolved_counts':{a:sum(r['comparison_resolved'][a] for r in evaluations) for a in ('A','B','C','D','D0')},
               'expected_V':None,'synthetic_mechanism_research_utility':None,'synthetic_research_cases':0,
               'primary_control':'D_SAME_METRIC_7_DAY_ACTIVE_CONTROL_NOT_ASSUMED_IRRELEVANT',
               'D0_structure':'RHR_HAS_NO_SOURCE_COMPATIBLE_PAIR_FEATURES; SUPPRESSION_IS_NOT_EMPIRICAL_NEGATIVE_CONTROL_SUCCESS',
               'old_negative_control_preserved':read(ROOT/'local/day2/analysis-qualified-v01/report.json')['matched_changed_pair_counts_silver']}
    decision={'status':status,'source_audited_evidence_conditioned_pairs':supported,'reference_material_adequate_for_design_diagnosis':adequate,
              'ranking_utility_executed':gate,'real_C_minus_D_ndcg5':gain,'Expected_V':None,'human_gold':False,
              'formal_benchmark_frozen':False,'formal_baseline_started':False,'C2_started':False,
              'assessor_independence':'NEW_REQUESTS_BLINDED_SAME_MODEL_FAMILY_NOT_HUMAN_OR_FULL_EVALUATOR_INDEPENDENCE',
              'next_unique_priority_action':'Obtain source-grounded contextual measurements needed by the ambiguous paired judgments before enlarging the library or comparing acquisition algorithms.',
              'population_significance_claim':False}
    jsonl(OUTPUT/'ranker_observations.jsonl',recordings);jsonl(OUTPUT/'legacy_ranker_diagnostic.jsonl',legacy)
    jsonl(OUTPUT/'matched_evaluation.jsonl',evaluations);jsonl(OUTPUT/'acquisition_actions.jsonl',action_records)
    for name,value in (('evaluation_summary',summary),('sensitivity',sensitivity),('mechanism_results',mechanism),('stage_decision',decision)):
        write(OUTPUT/(name+'.json'),value)
    write(OUTPUT/'provenance.json',{'design_id':registered['release_id'],'reference_id':read(REFERENCE/'freeze.json')['release_id'],
          'semantic_review_sha256':sha(SEMANTIC),'ranker_version':VERSION,'created_at':datetime.now(timezone.utc).isoformat()})
    freeze(OUTPUT,{'status':status,'reference_signal_gate_passed':gate,'AI_exploratory_only':True})
    return {'decision':decision,'discrimination':discrimination,'mechanism':mechanism,'value':summary['value']['ndcg@5']}


if __name__=='__main__':
    import json
    print(json.dumps(analyze(),ensure_ascii=False,indent=2))
