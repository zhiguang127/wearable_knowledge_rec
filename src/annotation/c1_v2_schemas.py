"""V2 schemas reuse the existing schema builder and validator; all judgments are Silver."""
from .schemas import obj, arr, enum, STR, BOOL, STRINGS

CITATION=obj({"anchor_id":STR,"source_sha256":STR,"quote":STR})
CONDITION=obj({"condition_id":STR,"text":STR,
               "role":enum("necessary","optional","alternative","restriction","uncertain"),
               "logic":enum("ALL","ANY","UNKNOWN"),"probe_ids":STRINGS,
               "dataset_support":enum("supported","partial","unsupported","uncertain"),
               "source_citations":arr(CITATION),"insufficient_information":STRINGS,
               "use":enum("applicability","sufficiency","priority","explanation")})
KNOWLEDGE=obj({"knowledge_id":STR,"source_supported":BOOL,"independently_recommendable":BOOL,
               "education_only":BOOL,"normalized_text":STR,"conditions":arr(CONDITION),
               "duplicate_ids":STRINGS,"conflict_ids":STRINGS,"source_citations":arr(CITATION),
               "unsupported_and":BOOL,"uncertainties":STRINGS,"rationale":STR})
AUDIT=obj({"knowledge_id":STR,"verdict":enum("SUPPORTED","REVIEW_REQUIRED","REJECTED"),
           "unsupported_and":BOOL,"issues":STRINGS,"source_citations":arr(CITATION),"rationale":STR})
EVIDENCE=obj({"probe_id":STR,"result_sha256":STR,"value":{"type":["number","null"]},"unit":STR,
              "start_date":STR,"end_date":STR})
LABEL=obj({"case_id":STR,"knowledge_id":STR,
           "applicability":enum("applicable","not_applicable","insufficient_information"),
           "topic_relevance":enum("relevant","not_relevant","uncertain"),
           "recommendation_priority":enum("undetermined","low","medium","high"),
           "priority_basis":STR,"evidence":arr(EVIDENCE),"source_citations":arr(CITATION),
           "missing_information":STRINGS,"uncertainties":STRINGS,"rationale":STR})
LABEL_AUDIT=obj({"case_id":STR,"knowledge_id":STR,"verdict":enum("SUPPORTED","REVIEW_REQUIRED","REJECTED"),
                 "applicability":enum("applicable","not_applicable","insufficient_information"),
                 "issues":STRINGS,"evidence":arr(EVIDENCE),"source_citations":arr(CITATION),"rationale":STR})
