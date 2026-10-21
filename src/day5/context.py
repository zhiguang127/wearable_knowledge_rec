"""New contextual evidence only; never infer symptoms from a wearable aggregate."""
from copy import deepcopy
from datetime import datetime
from ..common import digest,require
from .spec import VERSION,FIELDS,MEASUREMENTS,STATES

BYID={m['measurement_id']:m for m in MEASUREMENTS}


def timestamp(text):
    t=datetime.fromisoformat(text.replace('Z','+00:00'))
    require(t.tzinfo is not None,'timezone-aware timestamp required')
    return t


def validate_real_form(form,source_bytes_hash):
    require(form.get('protocol_version')==VERSION and form.get('data_origin')=='REAL_SELF_REPORT','real context protocol/origin')
    require(form.get('respondent_attestation') is True and bool(form.get('participant_id')),'actual respondent attestation required')
    require(form.get('episode_id') and form.get('source_record_sha256')==source_bytes_hash,'episode/source record hash')
    require(form.get('collection_mode')=='CONTEMPORANEOUS','retrospective recall not primary')
    cutoff=timestamp(form['as_of']);reported=timestamp(form['reported_at'])
    require(reported<=cutoff,'future report cannot backfill historical window')
    answers=form['answers'];require(set(answers)==set(BYID),'exact four contextual measurements required')
    for mid,answer in answers.items():
        require(answer['value'] in STATES,'context must preserve YES/NO/UNKNOWN')
        start,end=timestamp(answer['reference_start']),timestamp(answer['reference_end'])
        require(start<=end<=reported<=cutoff,'reference period/report after cutoff')
        require(isinstance(answer.get('qualifier'),str) and bool(answer['qualifier'].strip()),'source qualitative scope/unknown reason required')
    return True


def contextual_evidence(episode,values,origin,as_of,source_ref,metadata=None):
    require(set(values)==set(FIELDS),'context field inventory')
    require(origin in ('REAL_NOT_COLLECTED','REAL_SELF_REPORT','SYNTHETIC_MECHANISM_ONLY'),'context origin')
    require(origin!='REAL_SELF_REPORT' or metadata is not None,'real context timing and qualitative metadata required')
    result=[]
    for m in MEASUREMENTS:
        value=values[m['variable']]
        require(value is None if origin=='REAL_NOT_COLLECTED' else value in STATES,'missing/answered states differ')
        detail=metadata['answers'][m['measurement_id']] if metadata else {}
        core={'protocol_version':VERSION,'episode_id':episode,'measurement_id':m['measurement_id'],
              'variable':m['variable'],'status':'NOT_COLLECTED' if origin=='REAL_NOT_COLLECTED' else 'ANSWERED',
              'value':value,'as_of':as_of,'data_origin':origin,'source_ref':deepcopy(source_ref),
              'reported_at':metadata['reported_at'] if metadata else None,
              'reference_start':detail.get('reference_start'),'reference_end':detail.get('reference_end'),
              'qualifier':detail.get('qualifier','Fictional qualitative state, no clinical cutoff' if origin=='SYNTHETIC_MECHANISM_ONLY' else None),
              'missing_reason':'NO_CONTEMPORANEOUS_SELF_REPORT' if origin=='REAL_NOT_COLLECTED' else None}
        core['result_hash']=digest(core);core['evidence_id']='E5-'+digest(core)
        result.append(core)
    return result


def selected_source_cues(observed):
    values={e['variable']:e['value'] if e['status']=='ANSWERED' else 'UNKNOWN' for e in observed if e.get('protocol_version')==VERSION}
    cues=[values.get(k,'UNKNOWN') for k in FIELDS[:3]]
    consult='SUPPORTED_SELECTED_CUE' if 'YES' in cues else 'UNKNOWN' if 'UNKNOWN' in cues else 'NO_SELECTED_CUE_REPORTED'
    caffeine=values.get('late_day_caffeine','UNKNOWN')
    return {'consultation_source_cue':consult,
            'late_caffeine_behavior_context':'REPORTED_PRESENT' if caffeine=='YES' else 'REPORTED_ABSENT' if caffeine=='NO' else 'UNKNOWN',
            'unit_applicability':'NO_VERIFIED_UNIT_LEVEL_GATE','relative_priority':None,
            'note':'No selected cue is not a contraindication or a negative applicability label; source cues do not entail order.'}


class ContextEnvironment:
    """One identical step path for symptom and behavior answers; no ranking fabricated."""
    def __init__(self,episode,evidence,query):
        require(all(e['episode_id']==episode for e in evidence),'wrong contextual episode')
        self.episode=episode;self.__pool={e['measurement_id']:deepcopy(e) for e in evidence};self.query=deepcopy(query)
        require(len(self.__pool)==len(evidence) and set(self.__pool)==set(BYID),'context measurement pool')
        for e in evidence:
            core={k:v for k,v in e.items() if k not in ('result_hash','evidence_id')}
            require(e['result_hash']==digest(core) and e['evidence_id']=='E5-'+digest({**core,'result_hash':e['result_hash']}),'context hash binding')

    def reset(self,initial_ids,budget=1):
        require(type(budget) is int and budget>=0,'context budget')
        require(len(set(initial_ids))==len(initial_ids) and set(initial_ids)<=set(self.__pool),'invalid/duplicate seeds')
        self.remaining=budget;self.observed={mid:deepcopy(self.__pool[mid]) for mid in initial_ids}
        return self.observation()

    def observation(self):
        evidence=[self.observed[k] for k in sorted(self.observed)]
        return {'query':deepcopy(self.query),'observed_evidence':deepcopy(evidence),'remaining_budget':self.remaining,
                'source_cue_diagnostic':selected_source_cues(evidence),'ranking':None,
                'ranking_state':'NOT_ADMITTED_WITHOUT_INDEPENDENT_REFERENCE_AND_PREREGISTERED_RANKER'}

    def available_actions(self,state):
        require(state==self.observation(),'stale context observation')
        return sorted(set(self.__pool)-set(self.observed)) if self.remaining else []

    def step(self,measurement_id):
        require(self.remaining>0 and measurement_id in self.__pool and measurement_id not in self.observed,'illegal/repeated/context budget')
        evidence=deepcopy(self.__pool[measurement_id])
        # Uncollected real answers are not an actually performable action result.
        require(evidence['status']=='ANSWERED','no actual response acquired; collection remains pending')
        self.observed[measurement_id]=evidence;self.remaining-=1
        return self.observation(),1,self.remaining==0


def require_utility_ready(real_context_count,reliable_reference,ranker_protocol):
    require(real_context_count>=4 and reliable_reference is True and bool(ranker_protocol),
            'real collected context, stable independent reference and preregistered ranker required')
    return True
