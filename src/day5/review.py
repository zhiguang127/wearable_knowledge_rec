"""True-human-only import, mirror/repeat checks and explicit third-human adjudication."""
from collections import defaultdict
from datetime import timedelta
from ..common import require,digest
from .context import timestamp

PREFERENCES=('LEFT','RIGHT','TIE','UNKNOWN')


def validate_human_form(form,mapping,session_id):
    require(form.get('annotator_type')=='HUMAN' and form.get('human_attestation') is True and bool(form.get('reviewer_id')),
            'actual human identity/attestation required; no AI substitution')
    require(form.get('saw_model_outputs') is False and form.get('saw_ranker_or_expected_directions') is False and
            form.get('saw_other_reviewer_answers') is False,'independent blind review required')
    require(form.get('session_id')==session_id,'wrong session')
    timestamp(form['completed_at'])
    judgments=form['judgments'];keys=[j['packet_id'] for j in judgments]
    require(len(keys)==len(set(keys)) and set(keys)==set(mapping),'exact review packet inventory')
    decoded=[]
    for j in judgments:
        m=mapping[j['packet_id']]
        require(j.get('annotation_status') in ('ACCEPTED','REVIEW_REQUIRED','REJECTED') and j.get('preference') in PREFERENCES,'unfilled human judgment')
        require(j.get('topic_goal_left') in ('DIRECT','BACKGROUND','OFF_TOPIC','UNKNOWN') and
                j.get('topic_goal_right') in ('DIRECT','BACKGROUND','OFF_TOPIC','UNKNOWN'),'topic/goal axis')
        require(j.get('source_alignment_left') in ('SUPPORTED_CUE','NO_SELECTED_CUE','UNKNOWN','NOT_A_HARD_GATE') and
                j.get('source_alignment_right') in ('SUPPORTED_CUE','NO_SELECTED_CUE','UNKNOWN','NOT_A_HARD_GATE'),'source alignment axis')
        require(j.get('hard_applicability')=='NO_VERIFIED_UNIT_LEVEL_GATE','source cue is not unit applicability')
        require(bool(j.get('reason','').strip()),'relative priority reason required')
        if j['preference']=='UNKNOWN':require(bool(j.get('missing_context','').strip()),'unknown needs missing context')
        for side in ('left','right'):
            refs=j.get('source_span_ids_'+side,[])
            require(refs and len(refs)==len(set(refs)) and set(refs)<=set(m['source_span_ids'][side]),'wrong/empty candidate source binding')
        refs=j.get('evidence_ids',[])
        require(len(refs)==len(set(refs)) and set(refs)<=set(m['evidence_ids']),'foreign/repeated contextual evidence')
        require(bool(refs),'personal comparison/unknown needs explicit evidence or missing-state citation')
        pref={'LEFT':1,'RIGHT':-1,'TIE':0,'UNKNOWN':None}[j['preference']]
        if m['left']!=min(m['left'],m['right']) and pref is not None:pref=-pref
        decoded.append({'case_id':m['case_id'],'canonical_preference':pref,'input_hash':digest(j),'annotation_status':j['annotation_status'],
                        'data_origin':m['data_origin'],'source_human_checked':False,'input_row':j})
    return {'kind':'ATTESTED_HUMAN_SESSION_NOT_GOLD','reviewer_id':form['reviewer_id'],'session_id':session_id,
            'slot':form['slot'],'completed_at':form['completed_at'],'judgments':decoded,'form_hash':digest(form)}


def stable_reviewer(sessions,source_review,source_units,gap_hours=48):
    require(len(sessions)==3 and len({s['reviewer_id'] for s in sessions})==1,'same actual reviewer, three sessions')
    require(len({s['prepared_id'] for s in sessions})==1 and len({s['slot'] for s in sessions})==1,'same package and reviewer slot')
    require(source_review.get('human_attestation') is True and source_review.get('reviewer_id')==sessions[0]['reviewer_id'],
            'same actual human source review required')
    require(source_review.get('annotator_type')=='HUMAN' and source_review.get('source_package_hash')==digest(source_units),
            'human source package hash required')
    require(set(source_review.get('complete_source_units_checked',[]))=={u['source_unit_id'] for u in source_units},'both complete source units must be checked')
    refs=set(source_review.get('source_span_ids',[]))
    require(refs and refs<={s['span_id'] for u in source_units for s in u['source_spans']} and
            all(refs&{s['span_id'] for s in u['source_spans']} for u in source_units) and bool(source_review.get('reason','').strip()),
            'source review needs legal spans for both units and scope rationale')
    require(source_review.get('source_status')=='SUPPORTED_WITH_LIMITS' and source_review.get('source_does_not_entail_order') is True,
            'independent source scope verification required')
    ordered=sorted(sessions,key=lambda s:s['session_id'])
    require({s['session_id'] for s in sessions}=={'SESSION_1','SESSION_2','SESSION_3'},'session inventory')
    for a,b in zip(ordered,ordered[1:]):
        require(timestamp(b['completed_at'])-timestamp(a['completed_at'])>=timedelta(hours=gap_hours),'repeat/mirror washout interval not met')
    grouped=defaultdict(list)
    for session in sessions:
        require(len({j['case_id'] for j in session['judgments']})==len(session['judgments']),'duplicate case within session')
        for j in session['judgments']:grouped[j['case_id']].append(j)
    result=[]
    for case,items in sorted(grouped.items()):
        require(len(items)==3,'missing repeated judgment')
        prefs=[j['canonical_preference'] for j in items]
        stable=len(set(prefs))==1 and all(j.get('annotation_status')=='ACCEPTED' for j in items)
        result.append({'case_id':case,'data_origin':items[0]['data_origin'],'stable':stable,
                       'preference':prefs[0] if stable else None,'original_preferences':prefs,
                       'status':'STABLE_HUMAN_SINGLE_REVIEW' if stable else 'INTRA_RATER_UNSTABLE',
                       'reviewer_id':sessions[0]['reviewer_id']})
    return {'reviewer_id':sessions[0]['reviewer_id'],'slot':sessions[0]['slot'],'prepared_id':sessions[0]['prepared_id'],
            'source_review_hash':digest(source_review),'cases':result}


def reconcile(left,right):
    require(left['reviewer_id']!=right['reviewer_id'],'two different actual people required')
    require(left['prepared_id']==right['prepared_id'] and left['slot']!=right['slot'],'same prepared package and different reviewer slots')
    aa={r['case_id']:r for r in left['cases']};bb={r['case_id']:r for r in right['cases']}
    require(set(aa)==set(bb),'paired reviewer inventories')
    result=[]
    for case,a in aa.items():
        b=bb[case]
        if not a['stable'] or not b['stable']:status='INTRA_RATER_UNSTABLE_NOT_REPAIRED_BY_ADJUDICATION'
        elif a['preference']!=b['preference']:status='NEEDS_THIRD_HUMAN_ADJUDICATION'
        else:status='TWO_HUMAN_STABLE_AGREEMENT'
        result.append({'case_id':case,'data_origin':a['data_origin'],'status':status,
                       'preference':a['preference'] if status=='TWO_HUMAN_STABLE_AGREEMENT' else None,
                       'reviewer_ids':[left['reviewer_id'],right['reviewer_id']],
                       'original_preferences':[a['preference'],b['preference']]})
    return {'kind':'DAY5_HUMAN_RECONCILIATION_NOT_CLINICAL_GOLD','cases':result,
            'reviewer_ids':[left['reviewer_id'],right['reviewer_id']],'automatic_majority':False}


def adjudicate(reconciliation,form,allowed_references):
    require(form.get('human_attestation') is True and bool(form.get('adjudicator_id')) and
            form['adjudicator_id'] not in reconciliation['reviewer_ids'],'third distinct actual human required')
    require(form.get('saw_ranker_or_expected_directions') is False,'adjudicator must not see ranker/expected direction')
    pending={r['case_id'] for r in reconciliation['cases'] if r['status']=='NEEDS_THIRD_HUMAN_ADJUDICATION'}
    decisions=form.get('decisions',[]);require({r['case_id'] for r in decisions}==pending and len(decisions)==len(pending),'exact stable-disagreement adjudication inventory')
    for row in decisions:
        require(row['preference'] in ('DOCTOR','HABITS','TIE','UNKNOWN') and bool(row.get('reason','').strip()) and
                row.get('source_span_ids') and row.get('evidence_ids'),'adjudication reason and source/evidence required')
        allowed=allowed_references[row['case_id']]
        require(set(row['source_span_ids'])<=set(allowed['source_span_ids']) and
                set(row['evidence_ids'])<=set(allowed['evidence_ids']),'foreign adjudication source/evidence')
    return {'kind':'ACTUAL_HUMAN_ADJUDICATION_NOT_CLINICAL_GOLD','adjudicator_id':form['adjudicator_id'],
            'decisions':decisions,'input_reconciliation_hash':digest(reconciliation),'form_hash':digest(form),
            'intra_rater_instability_remains_excluded':True}
