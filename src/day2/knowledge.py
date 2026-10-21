"""Deterministic source-complete units, never altered legacy knowledge rows."""
import xml.etree.ElementTree as ET

from ..common import ROOT, digest, read, require
from ..knowledge.c1_v2 import blocks

RAW = ROOT/"data/raw/c1-benchmark-v2"


def render(parts):
    lines, heading = [], None
    for part in parts:
        if part["heading"] and part["heading"] != heading:
            lines.append(part["heading"])
        lines.append(part["text"])
        heading = part["heading"]
    return "\n\n".join(lines)


def build_units(config):
    manifests = read(ROOT/config["source_release"]/"sources.json")
    sections = []
    for article in read(RAW/"myhealthfinder.json")["Result"]["Resources"]["Resource"]:
        if article["Title"] not in config["myhf_titles"]:
            continue
        article_context = "\n\n".join(render(blocks(s["Content"] or "")) for s in article["Sections"]["section"])
        for i, s in enumerate(article["Sections"]["section"]):
            sections.append({"source":"myhealthfinder", "article_id":article["Id"], "article_title":article["Title"],
                             "section_id":str(i), "section_title":s["Title"] or article["Title"],
                             "source_url":article["AccessibleVersion"], "markup":s["Content"] or "",
                             "article_context":article_context, "source_sha256":manifests["myhf"]["sha256"],
                             "source_last_update":article["LastUpdate"]})
    for topic in ET.parse(RAW/"medline.xml").getroot().findall("health-topic"):
        if topic.get("language")!="English" or topic.get("title") not in config["medline_titles"]:
            continue
        summary = topic.find("full-summary")
        require(summary is not None, "selected source summary missing")
        markup = (summary.text or "")+"".join(ET.tostring(c,encoding="unicode") for c in summary)
        sections.append({"source":"medlineplus", "article_id":topic.get("id"), "article_title":topic.get("title"),
                         "section_id":"full-summary", "section_title":"full-summary", "source_url":topic.get("url"),
                         "markup":markup,"article_context":render(blocks(markup)),
                         "source_sha256":manifests["medline"]["sha256"],"source_last_update":None})
    units = []
    for s in sections:
        parts = blocks(s["markup"])
        require(parts, "empty complete source unit; do not silently discard")
        text = render(parts)
        identity = {"url":s["source_url"], "section":s["section_id"], "text_hash":digest(text), "source_hash":s["source_sha256"]}
        kid = "C1RC-"+digest(identity)[:20]
        spans = [{"span_id":"SP2-"+digest([kid,i,part])[:20], "block_index":i, **part} for i,part in enumerate(parts)]
        # Fixed descriptive-link hypothesis, independent of model labels/case values.
        linked = ((s["source"]=="myhealthfinder" and s["article_title"]=="Get Enough Sleep" and s["section_id"]=="0") or
                  (s["source"]=="medlineplus" and s["article_title"]=="Healthy Sleep") or
                  (s["source"]=="myhealthfinder" and s["article_title"]=="Get Active" and s["section_id"]=="5") or
                  (s["source"]=="medlineplus" and s["article_title"]=="Exercise and Physical Fitness"))
        topic = "sleep" if s["article_title"] in ("Get Enough Sleep","Healthy Sleep") else "physical_activity"
        change_link=((s["source"]=="medlineplus" and s["article_title"]=="Healthy Sleep") or
                     (s["source"]=="myhealthfinder" and s["article_title"]=="Get Active" and s["section_id"]=="5"))
        units.append({"knowledge_id":kid, "topic":topic, "title":s["article_title"]+" / "+s["section_title"],
                      "text":text,"content_hash":digest(text),"source":{k:v for k,v in s.items() if k not in ("markup","article_context")},
                      "source_markup_hash":digest(s["markup"]), "anchor_id":"SRC2-"+digest(identity),
                      "source_spans":spans,"article_context":s["article_context"],
                      "completeness":"COMPLETE_SOURCE_SECTION_WITH_ARTICLE_CONTEXT",
                      "source_semantic_status":"REVIEW_REQUIRED", "hard_predicate_status":"NOT_ADMITTED",
                      "descriptive_context_link":int(linked), "change_context_link":int(change_link),
                      "link_scope":"RESEARCH_RELEVANCE_HYPOTHESIS_NOT_MEDICAL_GATE",
                      "human_gold":False})
    require(len({u["knowledge_id"] for u in units})==len(units), "duplicate new unit")
    return sorted(units,key=lambda u:u["knowledge_id"])


def validate_units(units, config):
    expected = build_units(config)
    require(units==expected, "source unit or context changed")
    require(all(u["content_hash"]==digest(u["text"]) and u["source_spans"] for u in units), "unit content identity")
    return {"units":len(units), "complete_source_sections":len(units), "source_reconstruction":"PASS_EXACT",
            "source_semantics":"MODEL_REVIEW_NOT_HUMAN_GOLD"}


def model_unit(unit):
    return {k:unit[k] for k in ("knowledge_id","topic","title","text","source_spans")}
