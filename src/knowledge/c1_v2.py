"""Source-grounded education candidates. Extraction is not an applicability judgment."""
from collections import Counter
from html.parser import HTMLParser
import html
import re
import xml.etree.ElementTree as ET
from ..common import digest, require

# Explicit scope, not selected using outcomes. Clinical diagnosis/treatment topics are not imported.
MEDLINE_TOPICS = {
    "Healthy Sleep":"sleep", "Benefits of Exercise":"physical_activity",
    "Exercise and Physical Fitness":"physical_activity", "How Much Exercise Do I Need?":"physical_activity",
    "Exercise for Older Adults":"healthy_aging", "Sports Fitness":"physical_activity",
    "Healthy Aging":"healthy_aging", "Healthy Living":"healthy_aging", "Stress":"stress",
    "Nutrition":"nutrition", "Nutrition for Older Adults":"nutrition", "Weight Control":"nutrition",
    "Dietary Fiber":"nutrition", "Dietary Fats":"nutrition", "Carbohydrates":"nutrition",
    "Proteins":"nutrition", "Drinking Water":"nutrition", "Food Labeling":"nutrition",
    "Healthy Recipes":"nutrition", "Vitamins":"nutrition", "Minerals":"nutrition"}
MYHF_TOPICS = {
    "Get Enough Sleep":"sleep", "Get Active":"physical_activity",
    "Help a Loved One Get More Active: Quick Tips":"physical_activity",
    "Stay Active as You Get Older: Quick Tips":"healthy_aging",
    "Stay Active with a Disability: Quick Tips":"physical_activity",
    "Manage Stress":"stress", "Eat Healthy":"nutrition", "Aim for a Healthy Weight":"nutrition",
    "Eat Less Sodium: Quick Tips":"nutrition", "Healthy Eating: Conversation Starters":"nutrition",
    "Lower-Sodium Foods: Shopping List":"nutrition", "Heart-Healthy Foods: Shopping List":"nutrition",
    "Keep Your Heart Healthy":"healthy_aging"}


class Blocks(HTMLParser):
    """Keep complete lists together: list fragments must not lose their qualifying lead-in."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.blocks=[];self.parts=[];self.depth=0;self.heading="";self.kind=None

    def handle_starttag(self, tag, attrs):
        if tag in {"p","ul","ol","h2","h3","h4","h5"}:
            if self.depth==0:
                self.parts=[];self.kind=tag
            self.depth+=1
        elif tag in {"li","br"}:
            self.parts.append("\n")

    def handle_data(self, data):
        if self.depth: self.parts.append(data)

    def handle_endtag(self, tag):
        if tag in {"p","ul","ol","h2","h3","h4","h5"} and self.depth:
            self.depth-=1
            if self.depth==0:
                value=" ".join("".join(self.parts).split())
                if self.kind.startswith("h"):
                    self.heading=value
                elif value:
                    self.blocks.append({"text":value,"heading":self.heading,"kind":self.kind})


def blocks(markup):
    parser=Blocks();parser.feed(markup);parser.close()
    return parser.blocks


def norm(text):
    return " ".join(re.findall(r"[a-z0-9]+",text.casefold()))


def shingles(text):
    words=norm(text).split()
    return {tuple(words[i:i+3]) for i in range(max(1,len(words)-2))}


def similarity(a,b):
    a,b=shingles(a),shingles(b)
    return len(a & b)/len(a | b) if a or b else 1.0


def extract(medline_path, myhf, manifests):
    candidates, excluded, sources = [], [], []
    root=ET.parse(medline_path).getroot()
    for topic in root.findall("health-topic"):
        title=topic.get("title")
        if topic.get("language")!="English" or title not in MEDLINE_TOPICS: continue
        summary=topic.find("full-summary")
        if summary is None: continue
        # MedlinePlus stores escaped HTML text; handle both actual children and escaped strings.
        markup=(summary.text or "") + "".join(ET.tostring(c,encoding="unicode") for c in summary)
        sources.append({"source":"medlineplus","topic_id":topic.get("id"),"title":title,"url":topic.get("url"),
                        "topic":MEDLINE_TOPICS[title],"section":"full-summary","markup":markup,
                        "source_sha256":manifests["medline"]["sha256"],"accessed_at":manifests["medline"]["accessed_at"],
                        "license":"Public domain NLM topic summary; linked third-party material excluded",
                        "attribution":"Source: MedlinePlus, National Library of Medicine", "last_update":None})
    if myhf:
        result=myhf["Result"]
        require(result.get("Error") in (False,None,"False","false",""), "MyHealthfinder API returned an error")
        articles=result["Resources"]["Resource"]
        require(len(articles)==int(result["Total"]), "MyHealthfinder result truncated")
        for article in articles:
            title=article["Title"]
            if title not in MYHF_TOPICS: continue
            for i,section in enumerate(article["Sections"]["section"]):
                sources.append({"source":"myhealthfinder","topic_id":article["Id"],"title":title,
                                "url":article["AccessibleVersion"],"topic":MYHF_TOPICS[title],
                                "section":str(i)+":"+(section["Title"] or "untitled_source_section"),"markup":section["Content"] or "",
                                "source_sha256":manifests["myhf"]["sha256"],"accessed_at":manifests["myhf"]["accessed_at"],
                                "license":"MyHealthfinder API Terms of Use; verbatim content, attribution and update retained",
                                "attribution":"MyHealthfinder, U.S. Department of Health and Human Services",
                                "logo_url":article["HealthfinderLogo"],"attribution_url":article["HealthfinderUrl"],
                                "last_update":article["LastUpdate"]})
    seen={}
    for source in sources:
        parts=blocks(source["markup"])
        context="\n\n".join((p["heading"]+"\n" if p["heading"] else "")+p["text"] for p in parts)
        for index,part in enumerate(parts):
            text=part["text"]
            identity=[source["source"],source["topic_id"],source["section"],index,digest(text)]
            kid="K2-"+digest(identity)[:20]
            reason=None
            if len(text.split())<12: reason="short_fragment_or_link_not_independent_knowledge"
            elif len(text)>5000: reason="overlong_block_requires_explicit_source_review"
            elif re.search(r"\b(medications?|medicines?|surgery|chemotherapy|prescri\w*|diagnos\w*|treatment|aspirin|sleeping pills)\b",text,re.I):
                reason="clinical_or_medication_content_quarantined"
            canonical=norm(text)
            if canonical in seen: reason="exact_duplicate_of:"+seen[canonical]
            if reason:
                excluded.append({"knowledge_id":kid,"source_url":source["url"],"anchor_index":index,"reason":reason})
                continue
            seen[canonical]=kid
            anchor_id=source["source"]+":"+source["topic_id"]+":"+source["section"]
            candidate={"knowledge_id":kid,"title":source["title"]+" / "+(part["heading"] or source["section"])+" / "+str(index),
                       "text":text,"topic":source["topic"],"subtopic":part["heading"] or source["section"],
                       "source_url":source["url"],"accessed_at":source["accessed_at"],"source_sha256":source["source_sha256"],
                       "source_anchor":{"anchor_id":anchor_id,"text":context,"text_sha256":digest(context),"block_index":index},
                       "attribution":source["attribution"],"license":source["license"],"source_last_update":source["last_update"],
                       "conditions":[],"review_status":"REVIEW_REQUIRED","condition_review_status":"REVIEW_REQUIRED",
                       "insufficient_information":["No source-validated personalized condition yet; keyword relevance is not applicability."],
                       "label_provenance":"UNREVIEWED_SOURCE_EXTRACTION","human_gold":False}
            if source["source"]=="myhealthfinder":
                candidate.update(logo_url=source["logo_url"],attribution_url=source["attribution_url"])
            candidates.append(candidate)
    order={"sleep":0,"physical_activity":1,"healthy_aging":2,"stress":3,"nutrition":4}
    candidates.sort(key=lambda k:(order[k["topic"]],k["source_url"],k["knowledge_id"]))
    return candidates, excluded


def duplicates(items, threshold=0.6):
    pairs=[]
    for i,a in enumerate(items):
        for b in items[:i]:
            score=similarity(a["text"],b["text"])
            if score>=threshold: pairs.append({"a":a["knowledge_id"],"b":b["knowledge_id"],"trigram_jaccard":score})
    return pairs


def nearest(item,items,limit=3):
    others=[k for k in items if k["knowledge_id"]!=item["knowledge_id"]]
    ranked=sorted(others,key=lambda k:(-similarity(item["text"],k["text"]),k["knowledge_id"]))
    return [{"knowledge_id":k["knowledge_id"],"text":k["text"]} for k in ranked[:limit]]
