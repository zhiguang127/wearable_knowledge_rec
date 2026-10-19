"""Exact-byte provenance and exclusive, contained artifact writes."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class Blocked(ValueError):
    """A required verification could not be established."""


def require(condition, message):
    if not condition:
        raise Blocked("BLOCKED: " + message)


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def rows(path):
    return [json.loads(s) for s in Path(path).read_text(encoding="utf-8-sig").splitlines() if s.strip()]


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def digest(value, *, ascii=False, sorted_keys=True):
    return hashlib.sha256(json.dumps(value, sort_keys=sorted_keys, ensure_ascii=ascii,
                                    separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def inside(root, relative):
    root = Path(root).resolve()
    path = (root / relative).resolve()
    require(path.is_relative_to(root) and path != root, "path escapes artifact root")
    return path


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as f:
        json.dump(value, f, ensure_ascii=False, indent=2, allow_nan=False)
        f.write("\n")
