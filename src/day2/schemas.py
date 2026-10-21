"""Separate source facts, arm-conditional judgments and offline references."""
import json

from ..annotation.schemas import obj, arr, enum, STR, STRINGS, BOOL

FACET = obj({"span_id":STR,"kind":enum("POPULATION","HARD_TRIGGER","RECOMMENDED_TARGET","BEHAVIOR_STATE","TIME","BACKGROUND"),
             "role":enum("NECESSARY","SUFFICIENT","ADVICE_TRIGGER","OTHER","UNSPECIFIED"),
             "connective":enum("AND","OR","NOT_APPLICABLE","UNSPECIFIED"),
             "relation":enum("NO_PERSONAL_PREDICATE","UNMEASURED_CONTEXT","NON_EQUIVALENT_PROBE","DESCRIPTIVE_CONTEXT_ONLY","REVIEW_REQUIRED"),
             "reason":STR})
SOURCE_REVIEW = obj({"knowledge_id":STR,"meaning_preserved":BOOL,"standalone_context_sufficient":BOOL,
                     "facets":arr(FACET),"hard_gate_assessable":BOOL,"rationale":STR})
GRADE = obj({"knowledge_id":STR,"grade":{"type":["integer","null"],"enum":[0,1,2,3,None]},
             "basis":enum("TOPIC_OR_GOAL_ONLY","PERSONAL_EVIDENCE_CONTEXT","UNDETERMINED"),
             "evidence_ids":STRINGS,"source_span_ids":STRINGS,
             "unmeasured_context":STRINGS,"rationale":STR})
JUDGMENT = obj({"task_id":STR,"judgments":arr(GRADE),"rationale":STR})


def source_schema(unit):
    schema=json.loads(json.dumps(SOURCE_REVIEW))
    schema["properties"]["knowledge_id"]["enum"]=[unit["knowledge_id"]]
    schema["properties"]["facets"]["items"]["properties"]["span_id"]["enum"]=[s["span_id"] for s in unit["source_spans"]]
    return schema


def judgment_schema(task_id, units, evidence):
    schema=json.loads(json.dumps(JUDGMENT))
    schema["properties"]["task_id"]["enum"]=[task_id]
    p=schema["properties"]["judgments"]["items"]["properties"]
    p["knowledge_id"]["enum"]=[u["knowledge_id"] for u in units]
    p["evidence_ids"]["items"]["enum"]=[e["evidence_id"] for e in evidence]
    p["source_span_ids"]["items"]["enum"]=[s["span_id"] for u in units for s in u["source_spans"]]
    return schema
