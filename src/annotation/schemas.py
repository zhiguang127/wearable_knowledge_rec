"""Declarative function-argument schemas; no executable tools or generated labels."""
def obj(properties):
    return {'type':'object','properties':properties,'required':list(properties),'additionalProperties':False}

def arr(item):return {'type':'array','items':item}
def enum(*values):return {'type':'string','enum':list(values)}
STR={'type':'string'}
BOOL={'type':'boolean'}
STRINGS=arr(STR)
REF={'type':'string','pattern':r'^(d([1-9]|[1-3][0-9]|4[0-2])\.[a-z_]+|context\.[a-z_]+|stats\.(baseline|current)\.[a-z_]+\.[a-z_]+)$',
     'description':'Exact original dN.field, context.field or provided stats.phase.metric.stat only. Never daily_rows, daily_columns, invented fields, prose or numeric row indexes.'}
VALUE={'anyOf':[{'type':'number'},{'type':'string'},{'type':'boolean'},{'type':'null'}]}
CONDITION=obj({'condition_id':STR,'status':enum('satisfied','violated','unknown','not_applicable_to_condition'),
               'role':enum('necessary_prerequisite','optional_background','claim_scope_restriction','disputed'),
               'rationale':STR,'observations':arr(REF)})
OBS=obj({'reference':REF,'value':VALUE,'purpose':enum('physiology','context','missingness'),
         'phase':enum('baseline','current','all','context')})
LABEL=obj({'case_id':STR,'knowledge_id':STR,'applicability':enum('applicable','not_applicable','insufficient_information'),
           'condition_judgments':arr(CONDITION),'supporting_observations':arr(OBS),'violated_conditions':STRINGS,
           'missing_information':STRINGS,'source_scope_disputed':BOOL,'rationale':STR,'annotation_model':enum('qwen-max'),
           'label_provenance':enum('QWEN_MAX_SILVER'),'review_required':BOOL})
LABELS=obj({'items':arr(LABEL)})
STATUS=enum('VALID_EVIDENCE','INVALID_REFERENCE','INVALID_VALUE','TEMPORAL_MISMATCH','UNSUPPORTED_INFERENCE','INSUFFICIENT_INFORMATION','UNRESOLVED')
FINDING=obj({'status':STATUS,'claim_excerpt':STR,'observation_references':STRINGS,'rationale':STR})
EVIDENCE_ITEM=obj({'audit_id':STR,'statuses':arr(STATUS),
  'legacy_failure_interpretation':enum('format_only','validator_false_positive','potential_evidence_error','mixed','no_legacy_failure','unresolved'),
  'findings':arr(FINDING),'source_scope_issue':BOOL,'applicability_error_established':{'type':'boolean','enum':[False]},
  'review_required':BOOL,'rationale':STR})
EVIDENCE=obj({'items':arr(EVIDENCE_ITEM)})
