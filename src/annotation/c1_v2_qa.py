"""Independent artifact QA: rerun support checks and reproduce every annotated statistic."""
import argparse
from collections import Counter
import json
from pathlib import Path
from ..common import ROOT, digest, read, require, rows, sha, write
from ..datasets.probes import execute, relation_index
from ..datasets.v2_sources import verify, verify_sources, freeze, jsonl
from .c1_v2_pipeline import check_review, check_label, candidate_probes


def audit(release,run,ledger,extra_ledgers=()):
    release,run,ledger=Path(release),Path(run),Path(ledger)
    rf,af=verify(release),verify(run)
    source_check=verify_sources(ROOT/'data/raw/c1-benchmark-v2',read(release/'sources.json'))
    require(af["source_release_id"]==rf["release_id"],"annotation release mismatch")
    items={k["knowledge_id"]:k for k in rows(release/"knowledge_candidates.jsonl")}
    cases={c["case_id"]:c for c in rows(release/"cases.jsonl")}
    probes=read(release/"probes.json");pmap={p["probe_id"]:p for p in probes}
    review_records=rows(run/"knowledge_reviews.jsonl");labels=rows(run/"silver_labels.jsonl")
    failures=[];stats=Counter()
    def request_chain(stage):
        if not stage or stage["status"]!="RETURNED":return
        directories=[ledger]+[Path(p) for p in extra_ledgers]
        matching=[d for d in directories if (d/"cache"/(stage["cache_key"]+".json")).exists() and
                  read(d/"cache"/(stage["cache_key"]+".json"))["response_sha256"]==stage["response_sha256"]]
        require(bool(matching),"QA response missing from supplied ledgers")
        cached=read(matching[0]/"cache"/(stage["cache_key"]+".json"))
        request=read(matching[0]/"requests"/(stage["cache_key"]+".json"))
        require(digest(cached["response"])==cached["response_sha256"]==stage["response_sha256"],"QA response hash mismatch")
        require(digest(request)==cached["request_sha256"]==stage["request_sha256"],"QA request hash mismatch")
        stats["request_response_chains"]+=1
    for record in review_records:
        item=items[record["knowledge_id"]]
        require(record["input_sha256"]==digest(item),"QA knowledge input mismatch")
        request_chain(record["stage1"]);request_chain(record["stage2"])
        if record["stage1"]["status"]=="RETURNED" and record["stage2"] and record["stage2"]["status"]=="RETURNED":
            errors,spans=check_review(record["stage1"]["output"],record["stage2"]["output"],item,candidate_probes(item,probes))
            # Extra catalog-neighbor validation may be appended by the runner; all deterministic base errors must persist.
            require(set(errors)<=set(record["validation_errors"]),"QA dropped knowledge validation error")
            if record["review_status"]=="SILVER_ACCEPTED":require(not errors,"accepted knowledge fails fresh QA")
            stats["source_quote_spans"]+=len(spans)
        stats["review:"+record["review_status"]]+=1
        failures.extend(record["validation_errors"])
    active={k["knowledge_id"]:k for k in rows(run/"knowledge_active.jsonl")}
    require(read(run/"dependency_index.json")==relation_index(list(active.values()),probes),"QA dependency index mismatch")
    for label in labels:
        item=active[label["knowledge_id"]];case=cases[label["case_id"]]
        require(label["input_sha256"]==digest([case,item]),"QA case/knowledge hash mismatch")
        require(label["human_gold"] is False and label["label_provenance"]=="QWEN_PLUS_SILVER","QA label provenance")
        for stage in (label["stage1"],label["stage2"]):request_chain(stage)
        for evidence in label["evidence"]:
            rerun=execute(case,pmap[evidence["probe_id"]])
            require({k:v for k,v in rerun.items() if k!="elapsed_ns"}=={k:v for k,v in evidence.items() if k!="elapsed_ns"},"QA deterministic personal evidence mismatch")
            stats["personal_statistics_recomputed"]+=1
        if label["stage1"]["status"]=="RETURNED" and label["stage2"] and label["stage2"]["status"]=="RETURNED":
            errors,spans=check_label(label["stage1"]["output"],label["stage2"]["output"],item,case,label["evidence"])
            require(errors==label["validation_errors"],"QA label error list changed")
            if label["status"]=="SILVER_ACCEPTED":require(not errors,"accepted label fails fresh QA")
            stats["source_quote_spans"]+=len(spans)
        failures.extend(label["validation_errors"])
    return {"status":"PASS_ARTIFACT_CONSISTENCY_ONLY","release_id":rf["release_id"],"annotation_release_id":af["release_id"],
            "counts":dict(stats),"preserved_validation_errors":dict(Counter(failures)),
            "source_integrity":source_check,
            "human_gold":False,"semantic_correctness_proven":False,"label_count":len(labels)}


def revalidate_labels(release,run,destination):
    """Offline validator correction; no model calls or source/condition edits."""
    release,run,destination=Path(release),Path(run),Path(destination)
    parent=verify(run);verify(release)
    require(not destination.exists(),"revalidation destination exists")
    items={k['knowledge_id']:k for k in rows(run/'knowledge_active.jsonl')}
    cases={c['case_id']:c for c in rows(release/'cases.jsonl')}
    labels=[]
    for old in rows(run/'silver_labels.jsonl'):
        record={**old,'prior_validation_errors':old['validation_errors'],'prior_status':old['status'],
                'validator_version':'c1-v2-evidence-missingness-3'}
        if old['stage1']['status']=='RETURNED' and old['stage2'] and old['stage2']['status']=='RETURNED':
            errors,spans=check_label(old['stage1']['output'],old['stage2']['output'],items[old['knowledge_id']],cases[old['case_id']],old['evidence'])
            record.update(validation_errors=errors,citation_spans=spans,status='REVIEW_REQUIRED',applicability='insufficient_information')
            if not errors and old['stage2']['output']['verdict']=='SUPPORTED':
                record.update(status='SILVER_ACCEPTED',applicability=old['stage1']['output']['applicability'])
        labels.append(record)
    destination.mkdir(parents=True)
    # Copy exact immutable bytes for unrelated outputs; only the derived labels/report receive new versions.
    for name in parent['files']:
        if name in {'silver_labels.jsonl','report.json'}:continue
        target=destination/name;target.parent.mkdir(parents=True,exist_ok=True)
        with target.open('xb') as stream:stream.write((run/name).read_bytes())
    jsonl(destination/'silver_labels.jsonl',labels)
    report=read(run/'report.json')
    report.update(label_validator_version='c1-v2-evidence-missingness-3',parent_annotation_release_id=parent['release_id'],
                  offline_revalidation_new_model_calls=0,
                  revalidation_reason='Permit exact null evidence only to document insufficient information; definite labels still require computed numeric evidence.',
                  label_statuses=dict(Counter(r['status'] for r in labels)),
                  applicability=dict(Counter(r['applicability'] for r in labels)),
                  accepted_label_applicability=dict(Counter(r['applicability'] for r in labels if r['status']=='SILVER_ACCEPTED')),
                  label_program_validation_errors=dict(Counter(e for r in labels for e in r['validation_errors'])),
                  label_review_required_rate=sum(r['status']=='REVIEW_REQUIRED' for r in labels)/max(1,len(labels)))
    write(destination/'report.json',report)
    freeze(destination,{'source_release_id':parent['source_release_id'],'parent_annotation_release_id':parent['release_id'],
                        'label_provenance':'QWEN_PLUS_SILVER','human_gold':False,'new_model_calls':0})


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--release",default="data/releases/c1-benchmark-v2.1");p.add_argument("--run",required=True)
    p.add_argument("--ledger",default="local/c1-v2/qwen-ledger-v1");p.add_argument("--output",required=True)
    p.add_argument("--extra-ledger",action="append",default=[])
    p.add_argument("--revalidate-to",help="Offline correction for exact missing-value evidence; preserve original frozen run")
    args=p.parse_args()
    if args.revalidate_to:
        revalidate_labels(args.release,args.run,args.revalidate_to)
        args.run=args.revalidate_to
    result=audit(args.release,args.run,args.ledger,args.extra_ledger);write(args.output,result)
    print(json.dumps(result,indent=2))


if __name__=="__main__":main()
