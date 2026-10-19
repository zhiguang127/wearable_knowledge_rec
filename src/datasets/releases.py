"""Validate legacy release algorithms without rewriting manifests or versions."""
from pathlib import Path
from ..common import digest, inside, read, require, sha, rows


def verify_release(directory, kind):
    directory = Path(directory)
    manifest = read(directory / "freeze.json")
    if kind == "p1":
        identity = digest(manifest["files"], ascii=True)
    elif kind in {"a1", "silver"}:
        identity = digest({k: v for k, v in manifest.items() if k != "release_id"})
    else:
        raise ValueError("Unknown manifest algorithm")
    require(identity == manifest["release_id"], "release manifest identity mismatch")
    require({p.name for p in directory.iterdir()} == set(manifest["files"]) | {"freeze.json"},
            "release inventory differs from freeze")
    for name, expected in manifest["files"].items():
        require(sha(inside(directory, name)) == expected, "frozen artifact hash mismatch: " + name)
    return manifest


def load_cases(root):
    release = Path(root) / "data/releases/p1-v2"
    verify_release(release, "p1")
    return rows(release / "cases.jsonl")
