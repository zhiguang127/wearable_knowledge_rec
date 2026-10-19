"""Reproducible V2 CLI. All participant/label artifacts remain in ignored directories."""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from statistics import median
from time import perf_counter
from .common import ROOT, Blocked, digest, read, require, rows, sha, write
from .datasets.v2_sources import snapshot, jsonl, freeze, verify, verify_sources
from .datasets.wearableqa import UNITS, import_histories, construct_windows, split, usable
from .datasets.probes import catalog, execute, relation_index
from .datasets.splits import validate_split
from .knowledge.c1_v2 import extract, duplicates

CONFIG=ROOT/"configs/c1_benchmark_v2.json"
RAW=ROOT/"data/raw/c1-benchmark-v2"
RELEASE=ROOT/"data/releases/c1-benchmark-v2.1"


def fetch(config):
    commit=config["wearableqa_commit"]
    prefix="https://raw.githubusercontent.com/facebookresearch/WearableQA/"+commit+"/"
    urls={"wearable":("WearableQA_raw.json","https://media.githubusercontent.com/media/facebookresearch/WearableQA/"+commit+"/WearableQA_raw.json",config["wearableqa_sha256"]),
          "readme":("WearableQA_README.md",prefix+"README.md",None),
          "license":("WearableQA_LICENSE.txt",prefix+"LICENSE",None),
          "renderer":("render_raw.py.txt",prefix+"render_raw.py",None),
          "hf":("hf_metadata.json","https://huggingface.co/api/datasets/facebook/WearableQA/revision/"+config["hf_revision_audited"],None),
          "medline":("medline.xml",config["medline_url"],config["medline_sha256"]),
          "medline_terms":("medline_terms.html","https://medlineplus.gov/about/using/usingcontent/",None),
          "myhf":("myhealthfinder.json","https://odphp.health.gov/myhealthfinder/api/v4/topicsearch.json?Lang=en",config.get("myhealthfinder_sha256")),
          "myhf_terms":("myhealthfinder_terms.html","https://odphp.health.gov/our-work/national-health-initiatives/health-literacy/consumer-health-content/free-web-content/apis-developers/terms-use",None),
          "myhf_docs":("myhealthfinder_docs.html","https://odphp.health.gov/our-work/national-health-initiatives/health-literacy/consumer-health-content/free-web-content/apis-developers/how-use-api",None),
          "qwen_price":("qwen_plus_price.html",config["qwen"]["price_source"],None)}
    def one(pair):
        key,(name,url,expected)=pair
        return key,snapshot(RAW,name,url,expected)
    with ThreadPoolExecutor(max_workers=4) as pool:
        manifests=dict(pool.map(one,urls.items()))
    print(json.dumps({k:{"status":v["status"],"bytes":v.get("bytes"),"sha256":v.get("sha256")} for k,v in manifests.items()},indent=2))
    return manifests


def build(config):
    require(not RELEASE.exists(), "V2 release exists; verify it or use a new version, never overwrite")
    manifests=fetch(config)
    for name in ("wearable","license","renderer","readme","medline","medline_terms"):
        require(manifests[name]["status"]=="FETCHED", "required source unavailable: "+name)
    require(manifests["wearable"]["bytes"]==config["wearableqa_bytes"], "WearableQA byte count mismatch")
    keypath=ROOT/"local/identity/c1-v2.key"
    if not keypath.exists():
        keypath.parent.mkdir(parents=True,exist_ok=True)
        with keypath.open("xb") as f: f.write(os.urandom(32))
    data=read(RAW/"WearableQA_raw.json")
    records,mapping,counts=import_histories(data,keypath.read_bytes())
    cases,exclusions=construct_windows(records,config)
    partitions=split(cases,config)
    split_counts=validate_split(cases,partitions)
    myhf=read(RAW/"myhealthfinder.json") if manifests["myhf"]["status"]=="FETCHED" else None
    knowledge,kexcluded=extract(RAW/"medline.xml",myhf,manifests)
    probes=catalog()
    RELEASE.mkdir(parents=True)
    jsonl(RELEASE/"observations.jsonl",({"subject_id":s,**r} for s,daily in records.items() for r in daily.values()))
    jsonl(RELEASE/"cases.jsonl",cases)
    jsonl(RELEASE/"window_exclusions.jsonl",exclusions)
    jsonl(RELEASE/"knowledge_candidates.jsonl",knowledge)
    jsonl(RELEASE/"knowledge_exclusions.jsonl",kexcluded)
    write(RELEASE/"splits.json",partitions)
    write(RELEASE/"probes.json",probes)
    write(RELEASE/"units.json",UNITS)
    write(RELEASE/"sources.json",manifests)
    write(RELEASE/"build_config.json",config)
    write(RELEASE/"duplicate_candidates.json",duplicates(knowledge))
    mapping_path=ROOT/"local/identity/c1-v2-mapping.jsonl"
    if mapping_path.exists():require(rows(mapping_path)==mapping,"source identity mapping changed")
    else:jsonl(mapping_path,mapping)
    summary={"version":config["version"],"participants":len(records),"source_questions":len(data["mcqs"]),
             "source_daily_rows":counts["daily_rows"],"windows":len(cases),"excluded_windows":len(exclusions),
             "windows_by_history_length":dict(Counter(c["history_days"] for c in cases)),"split":split_counts,
             "knowledge_candidates":len(knowledge),"knowledge_excluded":len(kexcluded),
             "knowledge_topics":dict(Counter(k["topic"] for k in knowledge)),"probe_definitions":len(probes),
             "units":UNITS,"source_counts":counts,"human_gold":False,
             "boundaries":["Candidates are not reviewed/approved knowledge.","No MCQ ground truth reused as applicability labels.",
                           "Source dates, IDs, daily rows, splits and labels are private Git-ignored artifacts.",
                           "Daily aggregates cannot reconstruct events, posture, moderate/vigorous minutes or sleep start clocks."]}
    write(RELEASE/"summary.json",summary)
    frozen=freeze(RELEASE,{"version":config["version"],"config_sha256":sha(CONFIG),"human_gold":False})
    print(json.dumps({**summary,"release_id":frozen["release_id"]},indent=2))


def evaluate(out):
    frozen=verify(RELEASE)
    cases=rows(RELEASE/"cases.jsonl");probes=read(RELEASE/"probes.json")
    knowledge=rows(RELEASE/"knowledge_candidates.jsonl")
    output=Path(out);require(not output.exists(), "evaluation directory already exists")
    output.mkdir(parents=True)
    coverage=[];status=Counter();byprobe=Counter();elapsed=[];bycase=[]
    started=perf_counter()
    def evidence_stream():
        for i,case in enumerate(cases):
            cstart=perf_counter(); cstatus=Counter()
            for probe in probes:
                result=execute(case,probe)
                status[result["status"]]+=1;cstatus[result["status"]]+=1
                byprobe[(probe["probe_id"],result["status"])]+=1
                elapsed.append(result["elapsed_ns"])
                yield result
            bycase.append({"case_id":case["case_id"],"subject_id":case["subject_id"],"history_days":case["history_days"],
                           "statuses":dict(cstatus),"batch_seconds":perf_counter()-cstart})
            for metric in UNITS:
                n=sum(usable(metric,d["metrics"][metric]) for d in case["days"])
                coverage.append({"case_id":case["case_id"],"subject_id":case["subject_id"],"metric":metric,
                                 "valid":n,"calendar_days":len(case["days"]),"coverage":n/len(case["days"])})
            if (i+1)%100==0: print("evaluated windows:",i+1,flush=True)
    jsonl(output/"evidence.jsonl",evidence_stream())
    total_seconds=perf_counter()-started
    jsonl(output/"coverage_by_participant_window.jsonl",coverage)
    jsonl(output/"batch_times.jsonl",bycase)
    # Costs include Python checks and no memoization; record I/O separately from sum of computation timers.
    sort=sorted(elapsed)
    size_reports=[]
    size_order=sorted(knowledge,key=lambda k:digest(["c1-v2-size-coverage-v1",k["knowledge_id"]]))
    for requested in (26,100,300,500):
        subset=size_order[:requested]
        pairs=duplicates(subset)
        size_reports.append({"requested_size":requested,"actual_candidate_size":len(subset),
                             "reviewed_size":0,"topic_counts":dict(Counter(k["topic"] for k in subset)),
                             "exact_duplicates_after_collapse":0,"near_duplicate_pairs":len(pairs),
                             "pair_denominator":len(subset)*(len(subset)-1)//2,
                             "selection":"nested SHA256 order, independent of model labels",
                             "near_duplicate_threshold":0.6,"near_duplicate_pair_rate":len(pairs)/max(1,len(subset)*(len(subset)-1)//2)})
    report={"release_id":frozen["release_id"],"windows":len(cases),"probe_definitions":len(probes),
            "probe_attempts":sum(status.values()),"probe_statuses":dict(status),
            "probes_computable_in_at_least_one_window":sum(any(byprobe[(p["probe_id"],"COMPUTED")] for _ in [0]) for p in probes),
            "elapsed_wall_seconds_including_serialization":total_seconds,"summed_compute_seconds":sum(elapsed)/1e9,
            "single_probe_median_ms":median(elapsed)/1e6,"single_probe_p95_ms":sort[int(len(sort)*.95)]/1e6,
            "all_probes_per_window_median_ms":median(x["batch_seconds"] for x in bycase)*1000,
            "knowledge_size_reports":size_reports,"annotation_status":"PENDING_SEPARATE_QWEN_RUN",
            "conclusion":"Descriptive compute costs do not establish delayed discovery value; joint necessary conditions require source review.",
            "hardware":{"python":__import__('sys').version,"platform":__import__('platform').platform(),
                        "cpu":__import__('platform').processor(),"logical_cpus":os.cpu_count()},
            "knowledge_condition_claims_confirmed":0,"decision_accuracy":None,"clinical_benefit":None}
    write(output/"report.json",report)
    freeze(output,{"version":"c1-v2-evaluation-v1","source_release_id":frozen["release_id"]})
    print(json.dumps(report,indent=2))


def main():
    global CONFIG, RAW, RELEASE
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action",choices=["fetch","build","verify","evaluate"])
    parser.add_argument("--output",default="local/c1-v2/evaluation-v1")
    parser.add_argument("--config",type=Path,default=CONFIG)
    parser.add_argument("--raw-dir",type=Path,default=RAW)
    parser.add_argument("--release",type=Path,default=RELEASE)
    args=parser.parse_args()
    CONFIG,RAW,RELEASE=args.config,args.raw_dir,args.release
    config=read(CONFIG)
    try:
        if args.action=="fetch":fetch(config)
        elif args.action=="build":build(config)
        elif args.action=="verify": print(json.dumps({"release":verify(RELEASE),"sources":verify_sources(RAW,read(RELEASE/"sources.json"))},indent=2))
        elif args.action=="evaluate":evaluate(args.output)
    except (ValueError,KeyError,TypeError,OSError) as exc:
        print("BLOCKED:",type(exc).__name__,str(exc));raise SystemExit(2)


if __name__=="__main__": main()
