"""Untrusted ZIP and AI labels; never an entry point into the human layer."""
from collections import Counter
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import zipfile

from ..common import ROOT, digest, read, rows, sha, write, require, inside
from ..datasets.v2_sources import freeze, verify, jsonl
from ..day2.pilot import load_prepared

CONFIG=ROOT/'configs/c1_day3_evaluation_v01.json'
PREPARED=ROOT/'local/day3/preregistered-v01'
IMPORTED=ROOT/'local/day3/imported-v01'
EXPECTED_MEMBERS={'qa_summary.json','README.md','judgments.ai_reference.jsonl',
                  'judgments.ai_reference.csv','judgments.rater_a.ai_reference.json'}


def strict_json(text):
    def pairs(items):
        out={}
        for k,v in items:
            require(k not in out,'duplicate JSON key: '+k)
            out[k]=v
        return out
    def bad(value):
        raise ValueError('nonfinite JSON: '+value)
    return json.loads(text,object_pairs_hook=pairs,parse_constant=bad)


def member_name(info):
    name=info.filename
    require(name and '\\' not in name and ':' not in name and not name.startswith('/'),'unsafe ZIP path')
    path=PurePosixPath(name)
    require(all(p not in ('','..','.') and not p.endswith((' ','.')) for p in name.split('/')),'unsafe ZIP component')
    reserved={'CON','PRN','AUX','NUL',*(f'COM{i}' for i in range(1,10)),*(f'LPT{i}' for i in range(1,10))}
    require(all(p.split('.')[0].upper() not in reserved for p in path.parts),'reserved Windows ZIP path')
    require(not (info.flag_bits&1),'encrypted ZIP')
    mode=info.external_attr>>16
    require(not stat.S_ISLNK(mode) and (stat.S_IFMT(mode) in (0,stat.S_IFREG,stat.S_IFDIR)),'ZIP special file')
    return path.as_posix()


def safe_extract(archive, dest, limits):
    require(not dest.exists(),'fresh extraction directory required')
    with zipfile.ZipFile(archive) as z:
        infos=z.infolist()
        require(len(infos)<=limits['max_entries'],'ZIP entry limit')
        names=[member_name(i) for i in infos]
        require(len({n.casefold() for n in names})==len(names),'ZIP name collision')
        require(sum(i.file_size for i in infos)<=limits['max_total_bytes'],'ZIP total size limit')
        for i in infos:
            require(i.file_size<=limits['max_file_bytes'],'ZIP file size limit')
            require(i.file_size/max(1,i.compress_size)<=limits['max_expansion_ratio'],'ZIP expansion ratio')
        result=[]
        for i,n in zip(infos,names):
            data=z.read(i)  # zipfile checks CRC; declared size is checked again.
            require(len(data)==i.file_size,'ZIP size mismatch')
            p=inside(dest,n);p.parent.mkdir(parents=True,exist_ok=True)
            with p.open('xb') as f:f.write(data)
            result.append({'path':n,'bytes':len(data),'crc':i.CRC,'sha256':sha(p)})
        return result


def verify_human_payload(directory, allowed):
    manifest=read(directory/'freeze.json')
    require(manifest['release_id']==digest({k:v for k,v in manifest.items() if k!='release_id'}),'human freeze identity')
    actual={p.relative_to(directory).as_posix() for p in directory.rglob('*') if p.is_file()}
    expected=set(manifest['files'])|{'freeze.json'}
    require(expected<=actual and actual-expected<=set(allowed),'unexpected human package inventory')
    for name,h in manifest['files'].items():require(sha(inside(directory,name))==h,'original human payload changed')
    return {'release_id':manifest['release_id'],'original_files_verified':len(manifest['files']),
            'additions':{name:sha(directory/name) for name in sorted(actual-expected)},
            'status':'ORIGINAL_PAYLOAD_INTACT_ADDITIVE_ANOMALY_RECORDED'}


def prepare():
    require(not PREPARED.exists(),'fresh Day 3 preparation required')
    config=read(CONFIG)
    _,_,_,old=load_prepared(ROOT/config['day2_prepared'])
    require(old['release_id']==config['day2_protocol_id'],'wrong Day 2 preparation')
    require(verify(ROOT/config['day2_run'])['release_id']==config['day2_run_id'],'wrong Day 2 run')
    human=verify_human_payload(ROOT/config['human_package'],config['allowed_unmanifested_human_package_additions'])
    source=ROOT/config['resolved_existing_archive']; require(sha(source)==config['archive_sha256'],'AI archive changed')
    dest=ROOT/config['requested_archive'];dest.parent.mkdir(parents=True,exist_ok=True)
    if not dest.exists():
        with dest.open('xb') as f:f.write(source.read_bytes())
    require(sha(dest)==sha(source),'input copy hash mismatch')
    write(PREPARED/'config.json',config)
    write(PREPARED/'protocol.json',{'path':'docs/C1_DAY3_EVALUATION_PROTOCOL_V01.md','sha256':sha(ROOT/'docs/C1_DAY3_EVALUATION_PROTOCOL_V01.md')})
    write(PREPARED/'human_boundary.json',human)
    files=sorted((ROOT/'src/day3').glob('*.py'))+sorted((ROOT/'tests').glob('test_day3*.py'))
    hashes={p.relative_to(ROOT).as_posix():sha(p) for p in files}
    write(PREPARED/'implementation_hashes.json',hashes)
    for name in hashes:
        p=PREPARED/'implementation'/name;p.parent.mkdir(parents=True,exist_ok=True)
        with p.open('xb') as f:f.write((ROOT/name).read_bytes())
    write(PREPARED/'input_provenance.json',{'archive_sha256':sha(dest),'archive_original_path':config['resolved_existing_archive'],
          'archive_requested_path':config['requested_archive'],'copied_without_overwrite':True})
    record=freeze(PREPARED,{'version':config['version'],'created_at':datetime.now(timezone.utc).isoformat(),
                  'status':'PROTOCOL_FIXED_BEFORE_AI_GRADE_IMPORT_AND_METRIC_EXECUTION','grades_imported':False})
    return {'protocol_id':record['release_id'],'status':record['status']}


def load_protocol():
    frozen=verify(PREPARED)
    for name,h in read(PREPARED/'implementation_hashes.json').items():
        require(sha(ROOT/name)==h,'Day 3 implementation drift; create a versioned amendment: '+name)
    require(digest(read(CONFIG))==digest(read(PREPARED/'config.json')),'Day 3 config changed')
    p=read(PREPARED/'protocol.json');require(sha(ROOT/p['path'])==p['sha256'],'Day 3 protocol changed')
    return read(CONFIG),frozen


def row_errors(j, flat, packet, mapping):
    errors=[]
    required={'packet_id','candidate_id','grade','annotation_status','reason_code','evidence_ids','source_span_ids'}
    if set(j)!=required:return ['SCHEMA_FIELDS']
    grade=j['grade']
    if grade is not None and (type(grade) is not int or not 0<=grade<=3):errors.append('INVALID_GRADE')
    if j['annotation_status'] not in ('ACCEPTED','REVIEW_REQUIRED','REJECTED'):errors.append('INVALID_ANNOTATION_STATUS')
    cid=j['candidate_id']
    if cid not in mapping['candidates']:return errors+['FOREIGN_CANDIDATE']
    for field in ('evidence_ids','source_span_ids'):
        if not isinstance(j[field],list) or not all(isinstance(x,str) for x in j[field]) or len(set(j[field]))!=len(j[field]):
            errors.append('INVALID_'+field.upper())
    if errors:return errors
    if not j['source_span_ids'] or not set(j['source_span_ids'])<=set(mapping['source_span_ids'][cid]):errors.append('WRONG_SOURCE_SPAN')
    if not set(j['evidence_ids'])<=set(mapping['evidence_ids']):errors.append('CROSS_TASK_EVIDENCE')
    if not isinstance(j['reason_code'],str) or not j['reason_code'].strip():errors.append('MISSING_REASON')
    if flat is None:return errors+['MISSING_FLAT_RECORD']
    for k in ('packet_id','candidate_id','grade','evidence_ids','source_span_ids'):
        if j[k]!=flat.get(k):errors.append('FORMAT_MISMATCH_'+k)
    if flat.get('reason')!=j['reason_code']:errors.append('REASON_FORMAT_MISMATCH')
    candidate=next(c for c in packet['candidates'] if c['candidate_id']==cid)
    if flat.get('candidate_title')!=candidate['title']:errors.append('TITLE_MISMATCH')
    if flat.get('topic')!=packet['query']['topic'] or flat.get('query_basis')!=packet['query']['query_basis']:errors.append('QUERY_MISMATCH')
    if flat.get('gold_eligible') is not False or flat.get('reviewer_type')!='AI':errors.append('MISREPRESENTED_PROVENANCE')
    evidence={e['evidence_id']:e for e in packet['evidence']}
    if any(evidence.get(eid,{}).get('status')!='COMPUTED' for eid in j['evidence_ids']):errors.append('INSUFFICIENT_RESULT_CITED_REQUIRES_SEMANTIC_REVIEW')
    return sorted(set(errors))


def import_labels():
    config,protocol=load_protocol();require(not IMPORTED.exists(),'fresh AI import required')
    archive=ROOT/config['requested_archive'];require(sha(archive)==config['archive_sha256'],'archive hash mismatch')
    inventory=safe_extract(archive,IMPORTED/'original',config['zip_security'])
    require({r['path'] for r in inventory}==EXPECTED_MEMBERS,'unexpected AI ZIP inventory')
    root=IMPORTED/'original'
    form=strict_json((root/'judgments.rater_a.ai_reference.json').read_text(encoding='utf-8-sig'))
    declared=strict_json((root/'qa_summary.json').read_text(encoding='utf-8-sig'))
    require(form['slot']=='RATER_A' and form['annotator_type']=='AI' and form['human_attestation'] is False,'AI reference provenance')
    require(form['saw_silver_or_ranker_outputs'] is True,'declared exposure changed')
    human=ROOT/config['human_package'];human_boundary=verify_human_payload(human,config['allowed_unmanifested_human_package_additions'])
    require(sha(human/'RATER_A/packets.jsonl')==declared['source_packets_sha256'],'AI source packet hash mismatch')
    require(sha(root/'judgments.rater_a.ai_reference.json')==declared['filled_template_sha256'],'AI form self hash mismatch')
    mapping=read(human/'PRIVATE_mapping.json')['RATER_A']
    packets={p['packet_id']:p for p in rows(human/'RATER_A/packets.jsonl')}
    taskdata={t['task_id']:t['payload'] for t in rows(ROOT/config['day2_run']/'tasks.jsonl')}
    assignments=rows(ROOT/config['day2_run']/'task_assignments.jsonl')
    _,units,queries,_=load_prepared(ROOT/config['day2_prepared'])
    byquery={q['query_id']:q for q in queries};byunit={u['knowledge_id']:u for u in units}
    require(len(packets)==config['expected_tasks'] and set(packets)==set(mapping),'packet inventory')
    flat=[strict_json(s) for s in (root/'judgments.ai_reference.jsonl').read_text(encoding='utf-8-sig').splitlines() if s.strip()]
    csvrows=list(csv.DictReader(io.StringIO((root/'judgments.ai_reference.csv').read_text(encoding='utf-8-sig'))))
    for r in csvrows:
        r['grade']=None if r['grade'] in ('','null','None') else int(r['grade'])
        # The delivered CSV uses semicolon-delimited ID cells, not JSON arrays.
        for k in ('evidence_ids','source_span_ids'):r[k]=r[k].split(';') if r[k] else []
        require(r['gold_eligible'].lower() in ('false','0'),'CSV gold provenance')
        r['gold_eligible']=False
    def index(records):
        keys=[(j['packet_id'],j['candidate_id']) for j in records]
        require(len(keys)==len(set(keys)),'duplicate candidate label')
        return dict(zip(keys,records))
    main=index(form['judgments']);flats=index(flat);csvs=index(csvrows)
    expected={(pid,c['candidate_id']) for pid,p in packets.items() for c in p['candidates']}
    require(len(main)==config['expected_candidate_judgments'] and set(main)==expected,'AI judgment inventory')
    require(set(main)==set(flats)==set(csvs),'format inventory mismatch')
    records=[];packet_checks=[]
    for pid,packet in packets.items():
        m=mapping[pid];task=taskdata[m['task_id']]
        require(packet['query']==task['query'] and packet['evidence']==task['evidence'],'task/query/evidence payload mismatch')
        require({m['candidates'][c['candidate_id']] for c in packet['candidates']}=={c['knowledge_id'] for c in task['candidates']},'candidate task mismatch')
        for c in packet['candidates']:
            u=byunit[m['candidates'][c['candidate_id']]]
            require(all(c[k]==u[k] for k in ('title','text','source_spans')),'original source content mismatch')
        affected=[a for a in assignments if a['task_id']==m['task_id']]
        require(affected,'unassigned task')
        for a in affected:
            q=byquery[a['query_id']]
            require({k:q[k] for k in ('topic','query_basis','goal')}==packet['query'],'mapped query mismatch')
        packet_checks.append({'packet_id':pid,'task_id':m['task_id'],'query_assignments':affected,'content_hash':digest(packet)})
        for c in packet['candidates']:
            key=(pid,c['candidate_id']);j=main[key];f=flats[key]
            errors=row_errors(j,f,packet,m)
            if f!=csvs[key]:errors.append('CSV_JSONL_CONTENT_MISMATCH')
            status='REJECTED' if errors else j['annotation_status']
            if j['grade'] is None and status=='ACCEPTED':status='REVIEW_REQUIRED';errors.append('NULL_UNDETERMINED')
            records.append({'layer':'AI_REFERENCE_V01','row_id':'AI3-'+digest(j),
                'row_hash':digest(j),'input_row':j,'task_id':m['task_id'],'assignments':affected,
                'knowledge_id':m['candidates'][c['candidate_id']],'grade':j['grade'],
                'annotation_status':status,'validation_errors':errors,'reason':f.get('reason'),
                'evidence_ids':j['evidence_ids'],'source_span_ids':j['source_span_ids'],
                'human_gold':False,'reviewer_id':form['reviewer_id'],
                'source_request_response_trace_available':False,
                'assessor_independence':'NOT_ESTABLISHED_PRIOR_SILVER_AGGREGATE_EXPOSURE',
                'personal_evidence_cited':bool(j['evidence_ids'])})
    counts=Counter(r['annotation_status'] for r in records)
    report={'layer':'AI_REFERENCE_V01','archive_sha256':sha(archive),'zip_inventory':inventory,
            'protocol_id':protocol['release_id'],'unique_tasks':len(packets),'candidate_judgments':len(records),
            'format_agreement':all('CSV_JSONL_CONTENT_MISMATCH' not in r['validation_errors'] for r in records),
            'status_counts':dict(counts),'reasons':dict(Counter(e for r in records for e in r['validation_errors'])),
            'single_AI_assessor':True,'independent_reviewers':0,'human_gold_count':0,
            'source_packet_hash_verified':True,'filled_form_hash_verified':True,
            'prior_silver_aggregate_exposure':True,'human_package_boundary':human_boundary,
            'self_reported_QA_is_not_independent_validation':True,
            'new_model_requests':0,'imported_at':datetime.now(timezone.utc).isoformat()}
    jsonl(IMPORTED/'labels.jsonl',records);jsonl(IMPORTED/'packet_integrity.jsonl',packet_checks)
    write(IMPORTED/'integrity_report.json',report)
    freeze(IMPORTED,{'layer':'AI_REFERENCE_V01','status':'STRUCTURAL_IMPORT_COMPLETE_SEMANTICS_SEPARATE'})
    return report
