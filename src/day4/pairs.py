"""Fixed hypotheses and non-identifiability controls; no clinical thresholds."""
from ..common import digest, require

# Each tuple: id, topic, type, canonical left/right, exact synthetic goal,
# (left direction, left magnitude, right direction, right magnitude), control.
SPECS = [
 ('P4-01','physical_activity','STATE_ACTION','C1RC-c4a3e4104500140478e9','C1RC-a9b7b3a5d4a54069d286',
  'Choose educational guidance for reviewing my recorded activity progression: starting a routine or extending activity. Use only recorded activity as descriptive context; do not infer prior inactivity, fitness, intensity, modality or safety.',(-1,0,1,0),False),
 ('P4-02','physical_activity','GOAL_EVIDENCE','C1RC-6cabf80dc8b9d3f3b784','C1RC-108293cf465febe9f99c',
  'Choose what to read first while reviewing changes in my recorded steps: practical progress tracking or general benefits of activity. Do not infer a health outcome or an unmet target.',(0,1,0,0),False),
 ('P4-03','physical_activity','TREND_FOCUS','C1RC-a9b7b3a5d4a54069d286','C1RC-9833fe41669c020ce469',
  'Choose education for deciding what aspect of physical activity to review next: progression in recorded activity or muscle-strengthening guidance. Activity modality and aerobic intensity remain unknown.',(1,0,0,0),False),
 ('P4-04','physical_activity','UNMEASURED_CONTROL','C1RC-4b5da9e814d923d9b9d3','C1RC-ec35b96b0bb4684bb23a',
  'Choose which population-specific physical-activity guidance fits my personal situation better: older-adult guidance or disability guidance. Do not assume age or disability from wearable measurements.',(0,0,0,0),True),
 ('P4-05','sleep','TREND_FOCUS','C1RC-efd0553f87eb2737b4fb','C1RC-dfbe542e50306b3fca50',
  'Choose education for reviewing changes in my recorded sleep duration: duration and context, or nighttime routines. Do not assume age, symptoms, actual bedtimes, a nightly target or target failure.',(0,1,0,0),False),
 ('P4-06','sleep','TEMPORAL_SEMANTIC_CONTROL','C1RC-ed75f9d095c0cdea66a2','C1RC-dfbe542e50306b3fca50',
  'Choose education addressing whether my recent sleep timing is consistent: circadian schedule context or bedtime-routine guidance. Do not substitute variability of duration or an upstream summary with unknown lookback for observed recent sleep and wake clock times.',(0,0,0,0),True),
 ('P4-07','sleep','UNMEASURED_CONTROL','C1RC-450782cf53ce34f939b7','C1RC-15096c0d015ad39f4f61',
  'Choose whether consultation guidance or general daytime sleep-habit education is more specific to my current personal situation. Persistent sleep symptoms, sleepiness, medicines and daily routines are unknown unless actually observed.',(0,0,0,0),True),
 ('P4-08','sleep','GOAL_EVIDENCE','C1RC-4524edf1e4737f134543','C1RC-78178b3c637e548da474',
  'Choose education for putting my recorded sleep-duration pattern in context: general duration guidance or broad benefits of sleep. Do not infer my age, sleep need, nightly compliance or medical priority.',(0,1,0,0),False)
]


def build_pairs(units):
    byid={u['knowledge_id']:u for u in units};out=[]
    for pid,topic,kind,a,b,goal,links,control in SPECS:
        ua,ub=byid[a],byid[b]
        require(ua['topic']==ub['topic']==topic,'pair topic mismatch')
        same=ua['source']['article_id']==ub['source']['article_id'] and ua['source']['source']==ub['source']['source']
        shared_spans={s['span_id'] for s in ua['source_spans']}&{s['span_id'] for s in ub['source_spans']}
        length_ratio=max(len(ua['text']),len(ub['text']))/min(len(ua['text']),len(ub['text']))
        out.append({'pair_id':pid,'topic':topic,'goal':goal,'query_basis':'SYNTHETIC_BENCHMARK_GOAL',
          'type':kind,'candidate_ids':[a,b],'control':control,
          'links':{a:{'direction':links[0],'magnitude':links[1]},b:{'direction':links[2],'magnitude':links[3]}},
          'link_status':'PREREGISTERED_DESCRIPTIVE_RANK_HYPOTHESIS_NOT_VERIFIED_H',
          'source_relations':[{'knowledge_id':u['knowledge_id'],'source':u['source'],'anchor_id':u['anchor_id'],
                              'content_hash':u['content_hash'],'source_span_ids':[s['span_id'] for s in u['source_spans']]} for u in (ua,ub)],
          'source_overlap_or_granularity_risk':bool(shared_spans) or length_ratio>2,
          'shared_source_span_ids':sorted(shared_spans),
          'same_source_article':same,'text_length_ratio':length_ratio,
          'unmeasured_context':['age','symptoms','activity_intensity','activity_modality','sleep_clock_events'],
          'hypothesis_not_source_priority_rule':True,'pair_hash':digest([pid,a,b,goal,links])})
    return out
