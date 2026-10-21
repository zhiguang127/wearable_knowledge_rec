"""Private blind review packages and explicit human-only import/adjudication.

Attestations are auditable declarations, not a technical proof of a human identity.
No template is filled automatically and no model output is imported as Gold.
"""
import argparse
from collections import Counter
import hashlib
import hmac
import json
from pathlib import Path
import secrets

from ..common import ROOT, digest, read, require, rows, write
from ..datasets.v2_sources import freeze, jsonl, verify


def validate_form(form,expected_items,expected_packets):
    require(form.get("annotator_type")=="HUMAN" and form.get("human_attestation") is True and
            bool(form.get("reviewer_id","").strip()),"actual independent human attestation required")
    require(form.get("saw_silver_or_ranker_outputs") is False,"review is not blind")
    judgments=form.get("judgments",[])
    keys=[(j["packet_id"],j["candidate_id"]) for j in judgments]
    require(len(keys)==len(set(keys)),"duplicate human judgment")
    require(set(keys)==set(expected_items),"human judgment inventory differs")
    for j in judgments:
        require(j.get("annotation_status") in ("ACCEPTED","REVIEW_REQUIRED","REJECTED"),"unfilled human judgment")
        require(j.get("grade") is None or type(j["grade"]) is int and 0<=j["grade"]<=3,"invalid human grade")
        require(bool(j.get("reason_code","").strip()),"human rationale/reason required")
        require(set(j.get("evidence_ids",[]))<=set(expected_packets[j["packet_id"]]["evidence_ids"]),"foreign evidence in human judgment")
        source_ids=expected_packets[j["packet_id"]]["source_span_ids"][j["candidate_id"]]
        require(set(j.get("source_span_ids",[]))<=set(source_ids),"foreign source span in human judgment")
        require(j["annotation_status"]!="ACCEPTED" or j.get("source_span_ids"),"accepted human judgment needs source citation")
    return True


def build(prepared,run,output):
    prepared,run,output=Path(prepared),Path(run),Path(output).resolve()
    require(output.is_relative_to(ROOT/"local") and not output.exists(),"fresh private review package path required")
    verify(prepared);verify(run)
    units=rows(prepared/"knowledge_units.jsonl");tasks=rows(run/"tasks.jsonl")
    key=secrets.token_bytes(32)
    write(output/"private_blinding_key.json",{"key_hex":key.hex(),"private":True})
    def anon(value):return hmac.new(key,value.encode(),hashlib.sha256).hexdigest()[:16]
    mappings={};template_info={}
    for slot in ("RATER_A","RATER_B"):
        packets=[];blank=[];slot_map={}
        for task in tasks:
            payload=task["payload"];packet_id="P-"+anon(slot+task["task_id"])
            candidate_map={c["knowledge_id"]:"K-"+anon(slot+task["task_id"]+c["knowledge_id"]) for c in payload["candidates"]}
            candidates=[]
            for c in payload["candidates"]:
                candidate_id=candidate_map[c["knowledge_id"]]
                candidates.append({"candidate_id":candidate_id,"title":c["title"],"text":c["text"],"source_spans":c["source_spans"]})
                blank.append({"packet_id":packet_id,"candidate_id":candidate_id,"grade":None,"annotation_status":"UNFILLED",
                              "reason_code":"","evidence_ids":[],"source_span_ids":[]})
            candidates.sort(key=lambda c:c["candidate_id"])
            evidence=payload["evidence"]
            packet={"packet_id":packet_id,"query":payload["query"],"rubric":payload["rubric"],
                    "candidates":candidates,"evidence":evidence,"unknown_context":payload["unknown_context"],
                    "instruction":"Judge only this packet. Null and ties are allowed. No clinical priority claim. Source facts need separate review."}
            packets.append(packet)
            slot_map[packet_id]={"task_id":task["task_id"],"candidates":{v:k for k,v in candidate_map.items()},
                                 "evidence_ids":[e["evidence_id"] for e in evidence],
                                 "source_span_ids":{candidate_map[c["knowledge_id"]]:[s["span_id"] for s in c["source_spans"]] for c in payload["candidates"]}}
        packets.sort(key=lambda p:p["packet_id"])
        jsonl(output/slot/"packets.jsonl",packets)
        form={"package_version":"day2-human-review-v1","slot":slot,"reviewer_id":None,"annotator_type":None,
              "human_attestation":False,"saw_silver_or_ranker_outputs":None,"judgments":blank}
        write(output/slot/"judgments.template.json",form)
        from .review_ui import write_ui
        write_ui(output/slot/"review.html",packets,form)
        mappings[slot]=slot_map
        template_info[slot]={"packets":len(packets),"blank_judgments":len(blank)}
    write(output/"PRIVATE_mapping.json",mappings)
    # Separate source facts packet, never populated with a fabricated human decision.
    jsonl(output/"SOURCE_REVIEW"/"units.jsonl",units)
    write(output/"SOURCE_REVIEW"/"review.template.json",{"reviewer_id":None,"annotator_type":None,"human_attestation":False,
          "reviews":[{"knowledge_id":u["knowledge_id"],"source_semantic_status":"UNFILLED","hard_conditions":[],
                      "descriptive_links_review":"UNFILLED","rationale":""} for u in units]})
    write(output/"adjudication.template.json",{"adjudicator_id":None,"human_attestation":False,"decisions":[]})
    instructions="""Day 2 private independent review package

Distribute RATER_A and RATER_B folders to two different human reviewers. Do not distribute
PRIVATE_mapping.json, the blinding key, model labels, diagnostic rankings or analysis outputs.
Each folder contains query, full candidate source text/spans and only that packet's evidence.
Packet IDs/candidate order differ by reviewer; arm, subject/window IDs and Silver results are hidden.
Some contexts intentionally have no evidence. Judge the available information, retaining nulls/ties.
The complete original source facts packet is separate under SOURCE_REVIEW.
Do not infer nightly adherence, diagnosis, exercise intensity or a user goal from aggregates.
For each judgment enter grade (0-3 or null), annotation status, reason and actual cited IDs.
Fill human identity and truthful blindness/identity attestations; unfilled templates are not judgments.
Import with: python -m src.day2.human ingest --package <package> --form <filled.json> --output <new.json>
Combine with: python -m src.day2.human reconcile --left <importA.json> --right <importB.json> --output <new.json>
Disagreements remain NEEDS_ADJUDICATION, requiring a third distinct actual human identity.
Attestations are human declarations; this code cannot establish physical human independence itself.
"""
    path=output/"README.txt";path.write_text(instructions,encoding="utf-8")
    summary={"status":"PREPARED_NOT_ANNOTATED","reviewer_slots":template_info,"independent_human_judgments":0,
             "source_review_units":len(units),"gold_labels":0,"human_agreement":None}
    write(output/"summary.json",summary)
    freeze(output,{"version":"day2-human-review-v1","status":"PREPARED_NOT_ANNOTATED_PRIVATE"})
    print(json.dumps(summary),flush=True)


def ingest(package,form_path,output):
    package=Path(package);verify(package)
    form=read(form_path);mapping=read(package/"PRIVATE_mapping.json")
    require(form.get("slot") in mapping,"unknown rater slot")
    packets=mapping[form["slot"]]
    expected=[(pid,kid) for pid,p in packets.items() for kid in p["candidates"]]
    validate_form(form,expected,packets)
    decoded=[]
    for j in form["judgments"]:
        p=packets[j["packet_id"]]
        decoded.append({**j,"task_id":p["task_id"],"knowledge_id":p["candidates"][j["candidate_id"]]})
    write(output,{"kind":"ATTESTED_HUMAN_SINGLE_REVIEW_NOT_ADJUDICATED_GOLD","reviewer_id":form["reviewer_id"],"slot":form["slot"],
                  "form_hash":digest(form),"package_id":read(package/"freeze.json")["release_id"],"judgments":decoded})


def reconcile(left,right,output):
    a,b=read(left),read(right)
    require(a["kind"]==b["kind"]=="ATTESTED_HUMAN_SINGLE_REVIEW_NOT_ADJUDICATED_GOLD", "human imports required")
    require(a["reviewer_id"]!=b["reviewer_id"] and a["slot"]!=b["slot"] and a["package_id"]==b["package_id"],"independent raters and same package required")
    aa={(j["task_id"],j["knowledge_id"]):j for j in a["judgments"]}
    bb={(j["task_id"],j["knowledge_id"]):j for j in b["judgments"]}
    require(set(aa)==set(bb),"human comparison inventory differs")
    accepted=[];disagreements=[]
    for key,j in aa.items():
        other=bb[key]
        if j["annotation_status"]==other["annotation_status"]=="ACCEPTED" and j["grade"]==other["grade"]:
            accepted.append({"task_id":key[0],"knowledge_id":key[1],"grade":j["grade"],"kind":"HUMAN_DOUBLE_REVIEW_AGREEMENT",
                             "reviewer_ids":[a["reviewer_id"],b["reviewer_id"]]})
        else:disagreements.append({"task_id":key[0],"knowledge_id":key[1],"left":j,"right":other,"status":"NEEDS_ADJUDICATION"})
    write(output,{"kind":"HUMAN_RECONCILIATION","accepted":accepted,"needs_adjudication":disagreements,
                  "reviewer_ids":[a["reviewer_id"],b["reviewer_id"]],
                  "input_hashes":[digest(a),digest(b)],"automatic_majority_vote":False})


def adjudicate(reconciliation,form_path,output):
    rec,form=read(reconciliation),read(form_path)
    require(form.get("human_attestation") is True and bool(form.get("adjudicator_id")),"actual adjudicator required")
    existing=set(rec["reviewer_ids"])
    require(form["adjudicator_id"] not in existing,"third distinct human adjudicator required")
    pending={(j["task_id"],j["knowledge_id"]) for j in rec["needs_adjudication"]}
    decisions=form.get("decisions",[])
    keys=[(j["task_id"],j["knowledge_id"]) for j in decisions]
    require(len(keys)==len(set(keys)) and set(keys)==pending,"adjudication must cover exact disagreements")
    for j in decisions:
        require(j.get("grade") is None or type(j["grade"]) is int and 0<=j["grade"]<=3,"invalid adjudicated grade")
        require(bool(j.get("rationale","").strip()),"adjudication rationale required")
    write(output,{"kind":"HUMAN_ADJUDICATION","adjudicator_id":form["adjudicator_id"],"decisions":decisions,
                  "input_reconciliation_hash":digest(rec),"form_hash":digest(form)})


if __name__=="__main__":
    p=argparse.ArgumentParser();sub=p.add_subparsers(dest="command",required=True)
    a=sub.add_parser("build");a.add_argument("--prepared",required=True);a.add_argument("--run",required=True);a.add_argument("--output",required=True)
    a=sub.add_parser("ingest");a.add_argument("--package",required=True);a.add_argument("--form",required=True);a.add_argument("--output",required=True)
    a=sub.add_parser("reconcile");a.add_argument("--left",required=True);a.add_argument("--right",required=True);a.add_argument("--output",required=True)
    a=sub.add_parser("adjudicate");a.add_argument("--reconciliation",required=True);a.add_argument("--form",required=True);a.add_argument("--output",required=True)
    args=p.parse_args()
    if args.command=="build":build(args.prepared,args.run,args.output)
    elif args.command=="ingest":ingest(args.package,args.form,args.output)
    elif args.command=="reconcile":reconcile(args.left,args.right,args.output)
    else:adjudicate(args.reconciliation,args.form,args.output)
