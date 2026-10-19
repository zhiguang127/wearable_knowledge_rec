"""Versioned source snapshots, using the existing exclusive-write/hash helpers."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import urllib.error
import urllib.request
from ..common import inside, read, require, sha, write


def snapshot(root, name, url, expected=None):
    root = Path(root)
    path, manifest = inside(root,name), inside(root,name + ".source.json")
    if manifest.exists():
        record = read(manifest)
        require(record["url"] == url, "source URL changed; use a new snapshot name")
        if record["status"] != "FETCHED":
            return record
        require(path.exists() and sha(path) == record["sha256"], "source cache corrupt")
        require(expected is None or sha(path) == expected, "pinned source hash mismatch")
        return record
    require(not path.exists(), "unmanifested source exists")
    root.mkdir(parents=True, exist_ok=True)
    record = {"url": url, "accessed_at": datetime.now(timezone.utc).isoformat()}
    request = urllib.request.Request(url, headers={"User-Agent": "wearable-knowledge-rec-c1-v2/0.2 (research)"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            body = response.read()
            record.update(final_url=response.geturl(), http_status=response.status,
                          etag=response.headers.get("ETag"), last_modified=response.headers.get("Last-Modified"))
        actual = hashlib.sha256(body).hexdigest()
        require(expected is None or actual == expected, "download differs from pinned SHA256")
        require(not body.startswith(b"version https://git-lfs"), "received LFS pointer, not data")
        with path.open("xb") as f:
            f.write(body)
        record.update(status="FETCHED", sha256=actual, bytes=len(body))
    except (urllib.error.URLError, TimeoutError) as exc:
        record.update(status="BLOCKED_SOURCE_UNAVAILABLE", error=type(exc).__name__,
                      http_status=getattr(exc, "code", None))
    write(manifest, record)
    return record


def jsonl(path, records):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        for record in records:
            stream.write(json.dumps(record, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n")


def freeze(directory, metadata):
    directory = Path(directory)
    from ..common import digest
    files = {p.relative_to(directory).as_posix(): sha(p) for p in sorted(directory.rglob("*")) if p.is_file()}
    result = {**metadata, "files": files}
    result["release_id"] = digest(result)
    write(directory / "freeze.json", result)
    return result


def verify(directory):
    directory = Path(directory)
    from ..common import digest, inside
    manifest = read(directory / "freeze.json")
    require(manifest["release_id"] == digest({k:v for k,v in manifest.items() if k != "release_id"}), "V2 freeze identity")
    require({p.relative_to(directory).as_posix() for p in directory.rglob("*") if p.is_file()} == set(manifest["files"]) | {"freeze.json"}, "V2 inventory changed")
    for name, expected in manifest["files"].items():
        require(sha(inside(directory, name)) == expected, "V2 frozen bytes changed")
    return manifest


def verify_sources(directory, records):
    """Close the release -> source-manifest -> original-byte chain without network."""
    directory=Path(directory)
    manifests={read(p)["url"]:(p,read(p)) for p in directory.glob("*.source.json")}
    verified=0
    for record in records.values():
        require(record["url"] in manifests,"original source manifest absent")
        path,current=manifests[record["url"]]
        require(current==record,"source manifest changed since release")
        if record["status"]=="FETCHED":
            original=inside(directory,path.name.removesuffix(".source.json"))
            require(original.stat().st_size==record["bytes"] and sha(original)==record["sha256"],"original source bytes/hash mismatch")
            verified+=1
    return {"source_files_rehashed":verified,"status":"PASS_EXACT_SOURCE_BYTES"}
