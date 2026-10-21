"""Replay the fixed Day 2 diagnostic ranker against shared F-only AI qrels."""
from collections import Counter, defaultdict
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path
from statistics import mean

from ..common import ROOT, digest, read, rows, sha, write, require
from ..datasets.v2_sources import verify, verify_sources, freeze, jsonl
from ..day1.evidence import EvidenceProvider
from ..day2.core import PilotEnvironment, find_probe, metric_for, pairs_from_grades, DiagnosticRanker
from ..day2.pilot import load_prepared, pool_for
from .importer import load_protocol, IMPORTED, verify_human_payload
from .metrics import METRICS, evaluate, value_record, summarize, changes, cost_scenarios

OUTPUT=ROOT/'local/day3/evaluated-v01'
REVIEW=ROOT/'local/day3/semantic-review-v01.json'


def shared_reference(query, assignments, labels, review, conservative=False):
    """No fallback, and no access to the evaluated arm's own labels."""
    task=next((a['task_id'] for a in assignments if a['query_id']==query['query_id'] and a['arm']=='F'),None)
    subset=[r for r in labels if r['task_id']==task] if task else []
    bykid={r['knowledge_id']:r for r in subset}
    require(len(bykid)==len(subset),'duplicate F qrel')
    grades={}
    entries=[]
    for kid in query['candidate_ids']:
        r=bykid.get(kid);why=[]
        if r is None:why.append('MISSING_F_LABEL')
        else:
            if r['annotation_status']!='ACCEPTED':why.append('STRUCTURAL_OR_ANNOTATION_PENDING')
            if review.get(r['row_hash'],{}).get('status')!='ACCEPTED':why.append('SEMANTIC_PENDING_OR_REJECTED')
            if conservative and r['personal_evidence_cited']:why.append('CONSERVATIVE_DROP_ALL_PERSONAL_CITATIONS')
        grades[kid]=r['grade'] if r is not None and not why else None
        entries.append({'knowledge_id':kid,'grade':grades[kid],
                        'row_id':r['row_id'] if r else None,'row_hash':r['row_hash'] if r else None,
                        'source_task':task,'excluded_reasons':why,
                        'evidence_ids':r['evidence_ids'] if r else [],
                        'source_span_ids':r['source_span_ids'] if r else [],
                        'reason':r['reason'] if r else None})
    return grades,entries


def profile(grades):
    pairs=pairs_from_grades(grades)
    known=[v for v in pairs.values() if v is not None]
    return {'grade_counts':dict(Counter(str(g) for g in grades.values())),
            'judged_candidates':sum(g is not None for g in grades.values()),
            'candidate_count':len(grades),'known_pairs':len(known),
            'strict_pairs':sum(v!=0 for v in known),'tied_pairs':sum(v==0 for v in known),
            'tie_fraction':sum(v==0 for v in known)/len(known) if known else None}


def compare_grades(left,right):
    require(set(left)==set(right),'label comparison candidates differ')
    a,b=pairs_from_grades(left),pairs_from_grades(right)
    common=[k for k in a if a[k] is not None and b[k] is not None]
    return {'grade_changes':sum(left[k]!=right[k] for k in left if left[k] is not None and right[k] is not None),
            'known_pairs':len(common),'relation_changes':sum(a[k]!=b[k] for k in common),
            'strict_reversals':sum(a[k]*b[k]==-1 for k in common),
            'tie_changes':sum(a[k]!=b[k] and (a[k]==0 or b[k]==0) for k in common)}


def aggregate_comparisons(comparisons):
    keys=('grade_changes','known_pairs','relation_changes','strict_reversals','tie_changes')
    return {k:sum(r[k] for r in comparisons) for k in keys}


def metrics_summary(records):
    return {'arms':{arm:{m:summarize(records,lambda r:r['arms'][arm][m]) for m in METRICS} for arm in 'ABCD'},
            'value':{m:{key:summarize(records,lambda r:r['value'][m][key]) for key in ('delta_C','delta_D','delta_delta')} for m in METRICS}}


def stage_decision(reference_contexts, reference_people, reference_changes, effects, isolation_ok=False):
    if reference_contexts<8 or reference_people<2:
        return 'INSUFFICIENT_EVIDENCE'
    if isolation_ok and reference_changes>=2 and sum(v>1e-12 for v in effects.values())>=2:
        return 'READY_FOR_BASELINE_PILOT'
    return 'REDESIGN_REQUIRED'


def execute():
    config,protocol=load_protocol();verify(IMPORTED);require(not OUTPUT.exists(),'fresh evaluation output required')
    require(REVIEW.exists(),'row-hash-bound semantic review required before evaluation')
    reviewdoc=read(REVIEW);require(reviewdoc['reviewer_type']=='MODEL_SOURCE_AUDIT' and reviewdoc['human_gold'] is False,'review provenance')
    labels=rows(IMPORTED/'labels.jsonl');review={r['row_hash']:r for r in reviewdoc['rows']}
    require(set(review)=={r['row_hash'] for r in labels} and len(reviewdoc['rows'])==len(labels),'semantic review exact inventory')
    oldcfg,units,queries,old=load_prepared(ROOT/config['day2_prepared'])
    require(verify(ROOT/config['day2_run'])['release_id']==config['day2_run_id'],'Day 2 run changed')
    human=verify_human_payload(ROOT/config['human_package'],config['allowed_unmanifested_human_package_additions'])
    source=ROOT/oldcfg['source_release'];verify(source)
    sourceclosure=verify_sources(ROOT/'data/raw/c1-benchmark-v2',read(source/'sources.json'))
    probes=read(source/'probes.json');chosen={q['case_id'] for q in queries}
    cases={c['case_id']:c for c in rows(source/'cases.jsonl') if c['case_id'] in chosen}
    expected=read(ROOT/config['day2_prepared']/'selection_manifest.json')['case_hashes']
    require(all(digest(c)==expected[cid] for cid,c in cases.items()),'selected case changed')
    split=read(source/'splits.json')['partitions']
    sets=[set(split[p]['subject_ids']) for p in ('train','dev','test')]
    require(not(sets[0]&sets[1] or sets[0]&sets[2] or sets[1]&sets[2]),'participant split leak')
    require({q['subject_id'] for q in queries}<=sets[0],'nontrain participant in pilot')
    run=ROOT/config['day2_run'];assignments=rows(run/'task_assignments.jsonl')
    original={(o['query_id'],o['arm']):o for o in rows(run/'observations.jsonl')}
    taskdata={t['task_id']:t['payload'] for t in rows(run/'tasks.jsonl')}
    backend=read(run/'backend_evidence.json')
    providers={cid:EvidenceProvider(c,probes) for cid,c in cases.items()}
    verified=0
    for cid,evidence in backend.items():
        require({e['probe_id'] for e in evidence}==set(providers[cid].probe_ids()),'full pool mismatch')
        for e in evidence:providers[cid].verify_bound(e);verified+=1
    # An evaluator backend may see F. The ranker is called below with only the arm's observed subset.
    identities={p:'P'+str(i+1) for i,p in enumerate(sorted({q['subject_id'] for q in queries}))}
    allrecords=[];conservative=[];qrels=[];replay=[];online=[]
    for q in queries:
        pid=identities[q['subject_id']];candidate=[u for u in units if u['knowledge_id'] in q['candidate_ids']]
        canonical={};grades,entries=shared_reference(q,assignments,labels,review)
        strictgrades,_=shared_reference(q,assignments,labels,review,True)
        qrels.append({'query_id':q['query_id'],'participant':pid,'topic':q['topic'],'query_basis':q['query_basis'],
                      'layer':'AI_REFERENCE_V01','reference_arm':'F','no_other_arm_fallback':True,
                      'assessor_independence':'NOT_ESTABLISHED_PRIOR_SILVER_AGGREGATE_EXPOSURE',
                      'human_gold':False,'entries':entries,'profile':profile(grades)})
        for arm in 'ABCD':
            provider=providers[q['case_id']]
            initial=[] if arm=='A' else [find_probe(probes,metric_for(q['topic']),'mean')]
            env=PilotEnvironment(q,candidate,provider,probes);state=env.reset(initial,1);cost=0
            if arm in 'CD':
                action=find_probe(probes,metric_for(q['topic']),'mean_difference') if arm=='C' else find_probe(probes,'rhr','mean')
                state,cost,done=env.step(action);require(done and cost==1,'step cost mismatch')
            before=original[q['query_id'],arm]
            require(digest(state)==digest(before['state']) and cost==before['cost'],'frozen ranking replay differs')
            evidence,display=pool_for(q,cases[q['case_id']],provider,probes,arm)
            tid=next(a['task_id'] for a in assignments if a['query_id']==q['query_id'] and a['arm']==arm)
            require(display==taskdata[tid]['evidence'],'task evidence display changed')
            require({e['evidence_id'] for e in evidence}=={e['evidence_id'] for e in state['observed_evidence']},'ranker observation mismatch')
            canonical[arm]=state['ranking']
            replay.append({'query_id':q['query_id'],'participant':pid,'arm':arm,'ranking':state['ranking'],
                           'observation_hash':digest(state),'replayed_exactly':True,'cost':cost})
            if arm in 'CD':online.append({'query_id':q['query_id'],'arm':arm,'status':state['observed_evidence'][-1]['status'],
                                         'all_observed_statuses':[e['status'] for e in state['observed_evidence']],
                                         'cost':cost,'historical_step_latency_ns':before['step_latency_ns']})
        for mask,target in ((grades,allrecords),(strictgrades,conservative)):
            arms={arm:evaluate(canonical[arm],mask) for arm in 'ABCD'}
            row={'query_id':q['query_id'],'participant':pid,'topic':q['topic'],'query_basis':q['query_basis'],
                 'reference_profile':profile(mask),'arms':arms,'value':value_record(arms),
                 'changes':{pair:changes(canonical[pair[0]],canonical[pair[2]],mask) for pair in config['comparisons']}}
            target.append(row)
    summary=metrics_summary(allrecords);sensitivity=metrics_summary(conservative)
    bytopic={t:metrics_summary([r for r in allrecords if r['topic']==t]) for t in sorted({q['topic'] for q in queries})}
    # AI arm judgments are diagnostics only, never fed into arm utility.
    taskgrades=defaultdict(dict)
    for r in labels:
        taskgrades[r['task_id']][r['knowledge_id']]=r['grade'] if r['annotation_status']=='ACCEPTED' and review[r['row_hash']]['status']=='ACCEPTED' else None
    def get(q,arm):
        tid=next(a['task_id'] for a in assignments if a['query_id']==q['query_id'] and a['arm']==arm)
        return taskgrades[tid]
    armcomparisons={pair:aggregate_comparisons([compare_grades(get(q,pair[0]),get(q,pair[2])) for q in queries])
                    for pair in config['comparisons']+['A_F','B_F','C_F','D_F']}
    crossperson=[]
    for template in sorted({q['template_id'] for q in queries}):
        matching=[q for q in queries if q['template_id']==template]
        for a,b in combinations(matching,2):
            crossperson.append({'template_id':template,'participants':[identities[a['subject_id']],identities[b['subject_id']]],
                                **compare_grades(get(a,'F'),get(b,'F'))})
    goal=[]
    for p in sorted(identities):
        for t in sorted({q['topic'] for q in queries}):
            a=next(q for q in queries if q['subject_id']==p and q['topic']==t and q['query_basis']=='TOPIC_ONLY')
            b=next(q for q in queries if q['subject_id']==p and q['topic']==t and q['query_basis']!='TOPIC_ONLY')
            goal.append({'participant':identities[p],'topic':t,**compare_grades(get(a,'F'),get(b,'F'))})
    # Attribute changed strict pairs; retaining all changed pairs prevents cherry-picking.
    attribution=[]
    for row in allrecords:
        q=next(q for q in queries if q['query_id']==row['query_id']);ag=get(q,'A')
        for d in row['changes']['B_C']['pair_details']:
            a,b=d['candidate_pair'];ga,gb=ag.get(a),ag.get(b)
            attribution.append({'query_id':row['query_id'],'participant':row['participant'],**d,
                                'A_reference_preference':None if ga is None or gb is None else (ga>gb)-(ga<gb),
                                'F_preference_already_present_in_A':None if ga is None or gb is None else ((ga>gb)-(ga<gb))==d['reference_preference']})
    valid_contexts=sum(r['arms']['B']['ndcg@5'] is not None for r in allrecords)
    valid_people={r['participant'] for r in allrecords if r['arms']['B']['ndcg@5'] is not None}
    effects=summary['value']['ndcg@5']['delta_delta']['participant_effects']
    personal_changed_people={r['participant'] for r in allrecords if compare_grades(get(next(q for q in queries if q['query_id']==r['query_id']),'A'),
                                                                                            get(next(q for q in queries if q['query_id']==r['query_id']),'F'))['strict_reversals']}
    decision=stage_decision(valid_contexts,len(valid_people),len(personal_changed_people),effects,False)
    finalstatuses=Counter('REJECTED' if r['annotation_status']=='REJECTED' or review[r['row_hash']]['status']=='REJECTED' else
                          'REVIEW_REQUIRED' if r['annotation_status']!='ACCEPTED' or review[r['row_hash']]['status']!='ACCEPTED' else 'ACCEPTED' for r in labels)
    quality={'input_judgments':len(labels),'final_status_counts':dict(finalstatuses),
             'grades_unique_tasks':dict(Counter(str(r['grade']) for r in labels)),
             'by_task':[{'task_id':tid,**profile(g)} for tid,g in sorted(taskgrades.items())],
             'arm_label_comparisons':armcomparisons,'cross_person_F_comparisons':crossperson,
             'cross_person_F_totals':aggregate_comparisons(crossperson),
             'goal_comparisons':goal,'goal_totals':aggregate_comparisons(goal),
             'F_candidate_slots':sum(len(q['entries']) for q in qrels),
             'F_accepted_candidate_slots':sum(q['profile']['judged_candidates'] for q in qrels),
             'evaluable_contexts':valid_contexts,'total_contexts':len(queries),'evaluable_participants':len(valid_people),
             'F_personal_evidence_rows':sum(r['personal_evidence_cited'] for r in labels if r['task_id'].endswith('-F')),
             'strict_pairs_F':sum(q['profile']['strict_pairs'] for q in qrels),
             'known_pairs_F':sum(q['profile']['known_pairs'] for q in qrels),
             'independent_human_labels':0,'independent_blinded_reference':False,
             'AI_seen_silver_aggregate':True,'no_human_or_Grade_validity_upgrade':True}
    counts={pair:{k:sum(r['changes'][pair][k] for r in allrecords) for k in ('candidate_score_changes','total_pairs','changed_relations','tie_relation_changes','strict_order_reversals','ranking_changed')} for pair in config['comparisons']}
    signal={'Topic':{'reference_profiles_with_strict_pairs':sum(q['profile']['strict_pairs']>0 for q in qrels),
                     'support':'Within-topic educational relevance varies. No off-topic candidate control or real user preference validation.',
                     'strongest_conclusion':'SOURCE_AND_QUERY_CONDITIONED_AI_EDUCATIONAL_RELEVANCE_ONLY'},
            'Goal':{'comparisons':aggregate_comparisons(goal),'synthetic_goal_only':True,
                    'strongest_conclusion':'EXPLICIT_SYNTHETIC_QUERY_EFFECT_NOT_OBSERVED_USER_PREFERENCE'},
            'PersonalEvidence':{'arm_label_comparisons':armcomparisons,'cross_person_F':aggregate_comparisons(crossperson),
                                'ranker_changes':counts,'strongest_conclusion':'REFERENCE_SUPPORTED_PERSONALIZATION_NOT_ESTABLISHED'},
            'Acquisition':{'delta':summary['value'],'expected_value':None,
                           'all_changed_B_C_pairs':len(attribution),
                           'changed_pairs_with_A_F_same_preference':sum(d['F_preference_already_present_in_A'] is True for d in attribution),
                           'strongest_conclusion':'POST_ACQUISITION_DIAGNOSTIC_RANK_ALIGNMENT_IS_NOT_EVIDENCE_DEPENDENT_REFERENCE_GAIN'},
            'day2_negative_control':{'B_C_silver_changed_relations':26,'B_D_silver_changed_relations':57,'pair_slots_each':612,
                                    'retained_counterevidence':True,'resolved_by_this_AI_template_consistency':False}}
    decisiondoc={'status':decision,'reference_layer':'AI_REFERENCE_V01','evaluable_contexts':valid_contexts,
                 'participant_count':len(valid_people),'strict_personal_reference_difference_people':len(personal_changed_people),
                 'C_D_positive_people':sum(v>1e-12 for v in effects.values()),'unresolved_assessor_isolation':True,
                 'benchmark_frozen':False,'formal_baselines_started':False,'C2_started':False,'new_model_calls':0,
                 'next_unique_priority_action':'Redesign a small source-grounded set of evidence-discriminating query/candidate pairs and obtain blinded independent matched judgments before comparing acquisition policies.',
                 'same_observed_pilot_data_exploratory_only':True,'population_significance_claim':False}
    boundary={'Day2_protocol_id':old['release_id'],'Day2_run_id':config['day2_run_id'],
              'Day3_protocol_id':protocol['release_id'],'source_closure':sourceclosure,'human_package':human,
              'canonical_results_recomputed_and_exact_bound':verified,'ranker_observations_replayed_exactly':len(replay),
              'train_people_only':True,'labels_passed_to_ranker':False,'F_results_passed_to_ranker':False,
              'programmatic_isolation':'PASS_OBSERVED_SUBSET_ONLY',
              'assessor_independence':'NOT_ESTABLISHED_PRIOR_SILVER_AGGREGATE_EXPOSURE',
              'new_model_requests':0,'ranker_weights_changed':False,
              'measurement_status_slots':dict(Counter(s for o in online for s in o['all_observed_statuses'])),
              'incremental_probe_actions':len(online),'cost_units':'PROBE_COUNT',
              'historical_acquisition_latency_ns':{'total':sum(o['historical_step_latency_ns'] for o in online),
                 'mean':mean(o['historical_step_latency_ns'] for o in online)},
              'latency_is_local_precomputed_lookup_not_healthcare_cost':True,
              'completed_at':datetime.now(timezone.utc).isoformat()}
    jsonl(OUTPUT/'shared_F_qrels.jsonl',qrels);jsonl(OUTPUT/'ranking_replay.jsonl',replay)
    jsonl(OUTPUT/'matched_evaluation.jsonl',allrecords);jsonl(OUTPUT/'conservative_evaluation.jsonl',conservative)
    jsonl(OUTPUT/'pair_attribution.jsonl',attribution)
    for name,data in {'label_quality':quality,'evaluation_summary':summary,'change_summary':counts,
                      'value_analysis':{'realized_value':summary['value'],'preacquisition_expected_value':None,
                                        'actual_incremental_costs':{'C':1,'D':1},'cost_sensitivity':cost_scenarios(allrecords,config['cost_sensitivity']['hypothetical_cost_pairs'],config['cost_sensitivity']['utility_penalties'])},
                      'sensitivity':{'exclude_disputed_semantics_primary':summary,'drop_all_personal_citations':sensitivity,'by_topic':bytopic},
                      'signal_diagnostics':signal,'stage_decision':decisiondoc,'boundary_audit':boundary}.items():write(OUTPUT/(name+'.json'),data)
    write(OUTPUT/'semantic_review_ref.json',{'path':REVIEW.relative_to(ROOT).as_posix(),'sha256':sha(REVIEW)})
    freeze(OUTPUT,{'status':decision,'reference_layer':'AI_REFERENCE_V01','exploratory_only':True})
    return {'decision':decisiondoc,'quality':quality,'value':summary['value']['ndcg@5'],'change_summary':counts}
