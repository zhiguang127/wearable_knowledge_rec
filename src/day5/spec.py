"""Frozen source relations and an explicitly new self-report measurement scope."""
from ..common import require,digest

VERSION='c1-day5-source-context-v01'
DOCTOR='C1RC-450782cf53ce34f939b7'
HABITS='C1RC-15096c0d015ad39f4f61'
FIELDS=('listed_sleep_difficulty','often_trouble_sleeping','sleep_concern','late_day_caffeine')
STATES=('YES','NO','UNKNOWN')
MEASUREMENTS=[
 {'measurement_id':'SR5-listed-sleep-difficulty','variable':FIELDS[0],
  'question':'截至观察时刻，你是否出现完整来源列举的睡眠相关困扰？例如难以入睡或保持睡眠、白天难以保持清醒。请按来源完整列表作答；不确定请选择 UNKNOWN。',
  'construct':'Participant report of listed sleep difficulties, not a sleep disorder diagnosis',
  'source_unit':DOCTOR,'span_id':'SP2-b6e63d8f7fbca38f4224','role':'SOURCE_ACTION_CUE'},
 {'measurement_id':'SR5-often-trouble-sleeping','variable':FIELDS[1],
  'question':'截至观察时刻，按你自己的理解，你是否常常觉得睡觉有困难？请注明所指时间范围及你对“常常”的描述；本问卷不设每周次数或周数门槛。',
  'construct':'Source qualitative self-perception of often having trouble sleeping',
  'source_unit':DOCTOR,'span_id':'SP2-1ea34f86deeb1f8aaa75','role':'SOURCE_ACTION_CUE'},
 {'measurement_id':'SR5-sleep-concern','variable':FIELDS[2],
  'question':'截至观察时刻，你是否对自己的睡眠感到困扰或担忧？这是自述，不从研究 Goal 或睡眠均值推断。',
  'construct':'Self-reported sleep concern, source heading scope; not medical urgency',
  'source_unit':DOCTOR,'span_id':'SP2-b6e63d8f7fbca38f4224','role':'SOURCE_HEADING_CONTEXT'},
 {'measurement_id':'SR5-late-day-caffeine','variable':FIELDS[3],
  'question':'在你注明的参考时段内，是否在一天较晚的时候摄入含咖啡因饮品？按你对“较晚”的理解作答，可另记时间；不自动设几点以后的门槛。',
  'construct':'Reported caffeine timing behavior; possible habit-action opportunity, not proven cause',
  'source_unit':HABITS,'span_id':'SP2-71fb7ca524baad742301','role':'RECOMMENDATION_TARGET_CONTEXT_NOT_HARD_GATE'}
]


def source_matrix(units):
    byid={u['knowledge_id']:u for u in units};out=[]
    definitions=[
      ('D5-S1',DOCTOR,'SP2-b6e63d8f7fbca38f4224','text','listed sleep difficulties','consult a doctor or nurse','QUALITATIVE_CONDITIONAL_ACTION',None,None),
      ('D5-S2',DOCTOR,'SP2-1ea34f86deeb1f8aaa75','text','self-perceived often having trouble sleeping','talk with a doctor','QUALITATIVE_CONDITIONAL_ACTION',None,'often: source gives no frequency or duration cutoff'),
      ('D5-S3',DOCTOR,'SP2-b6e63d8f7fbca38f4224','heading','sleep concern','see a doctor','HEADING_SCOPE_NOT_EXCLUSIVE_GATE',None,None),
      ('D5-S4',DOCTOR,'SP2-4d629c6dd10277dfc1de','text','sleep diary preparation','keep diary and share with doctor','SUPPORTING_PREPARATION_NOT_APPLICABILITY',{'value':1,'unit':'week','role':'DIARY_SUGGESTION_NOT_TRIGGER'},None),
      ('D5-S5',HABITS,'SP2-71fb7ca524baad742301','text','late-day caffeine behavior','avoid late-day caffeine','RECOMMENDATION_TARGET_NOT_IF_AND_ONLY_IF',None,'late in day: no clock cutoff'),
      ('D5-S6',HABITS,'SP2-71fb7ca524baad742301','text','trouble sleeping at night','limit daytime naps','CONDITIONAL_ADVICE_WITH_TARGET',{'value':20,'unit':'minutes','role':'NAP_DURATION_TARGET_NOT_PRIORITY_THRESHOLD'},'nighttime trouble is qualitative'),
      ('D5-S7',HABITS,'SP2-71fb7ca524baad742301','text','drinking alcohol','limit beverages','QUALITATIVE_CONDITIONAL_ADVICE',None,None),
      ('D5-S8',HABITS,'SP2-71fb7ca524baad742301','text','smoking','make a plan to quit','QUALITATIVE_CONDITIONAL_ADVICE',None,None),
      ('D5-S9',HABITS,'SP2-174a8bd13f872117e8ac','text','general daytime habits','small routine changes may help sleep','GENERAL_EDUCATIONAL_CONTENT',None,None)]
    for cid,kid,sid,selector,antecedent,action,role,quantity,time in definitions:
        u=byid[kid];span=next(s for s in u['source_spans'] if s['span_id']==sid)
        out.append({'condition_id':cid,'knowledge_id':kid,'span_id':sid,'source_selector':selector,
             'source':u['source'],'anchor_id':u['anchor_id'],'unit_content_hash':u['content_hash'],
             'source_fragment_hash':digest(span[selector]),'antecedent':antecedent,'action':action,
             'relation_role':role,'source_quantity':quantity,'time_semantics':time,
             'existing_288_probe_equivalent':False,'source_relation_status':'SUPPORTED_BY_FROZEN_TEXT_MODEL_AUDIT',
             'independent_semantic_review_status':'REVIEW_REQUIRED','unit_level_necessary_or_sufficient_gate_verified':False,
             'entails_relative_priority':False,'no_trigger_does_not_mean_not_applicable':True})
    return out


def select_pair(units):
    matrix=source_matrix(units)
    byid={u['knowledge_id']:u for u in units}
    require(all(k in byid and byid[k]['completeness']=='COMPLETE_SOURCE_SECTION_WITH_ARTICLE_CONTEXT' for k in (DOCTOR,HABITS)),'incomplete preferred pair')
    require(all(r['source_fragment_hash'] for r in matrix),'missing source closure')
    # This is eligibility for independent priority review, not a priority verdict.
    return {'selected_pair':'P4-07','candidate_ids':[DOCTOR,HABITS],
            'selection_status':'CONDITIONAL_RELEVANCE_HYPOTHESIS_ADMITTED_FOR_BLIND_REVIEW_ONLY',
            'explicit_condition_action_relation':True,'source_entailed_relative_order':False,
            'ranking_use_admitted':False,'fallback_used':False,
            'reason':'Exact source has consultation cues and distinct habit content; relative order remains an independent judgment. No source priority rule is manufactured.'}
