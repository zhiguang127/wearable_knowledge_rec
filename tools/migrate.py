"""One-way exact-byte migration. The source is never imported or written.

Run once from the NEW project: python tools/migrate.py --source-root PATH
"""
import argparse
import ast
from collections import Counter
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.common import digest, inside, read, require, sha, write
from src.datasets.splits import make_split
from src.common import rows

RESEARCH = "research/problem_reidentification/"
SKIP = {".git", "__pycache__", "env", "envs", "checkenv", "upstream", "hf", "hf-general", "embeddings"}
SCOPES = [RESEARCH + x for x in ("p1", "experiment_a", "experiment_b0", "experiment_c0")] + ["data", "src", "docs"]


def git(source, *args):
    env = {**os.environ, "GIT_OPTIONAL_LOCKS": "0"}
    result = subprocess.run(["git", "-C", str(source), *args], capture_output=True, text=True,
                            encoding="utf-8", env=env)
    require(result.returncode == 0, "Git inspection failed: " + " ".join(args))
    return result.stdout.strip()


def inventory(source):
    result, excluded = {}, Counter()
    for scope in SCOPES:
        base = source / scope
        require(base.is_dir(), "required audit scope missing: " + scope)
        for current, directories, names in os.walk(base):
            for directory in list(directories):
                if directory in SKIP:
                    excluded[str((Path(current) / directory).relative_to(source)).replace("\\", "/")] += 1
                    directories.remove(directory)
            for name in names:
                p = Path(current) / name
                require(not p.is_symlink(), "symlink requires separate audit")
                rel = p.relative_to(source).as_posix()
                result[rel] = {"sha256": sha(p), "bytes": p.stat().st_size}
    return result, sorted(excluded)


def supplemental_provenance(source):
    """Close the corpus editorial-document chain outside the initial seven scopes."""
    source = Path(source).resolve()
    require(source != ROOT and not ROOT.is_relative_to(source) and not source.is_relative_to(ROOT), "independent source required")
    manifest_path = ROOT / "local/migration/supplement-corpus-v1.json"
    specs = [("data/" + n, "data/processed/legacy_knowledge/" + n) for n in
             ("corpus_verification.json", "independent_corpus_review.json", "corpus_review_input.json", "corpus_near_duplicate_candidates.json")]
    specs.append(("reports/CORPUS_AUDIT.md", "local/archive/legacy_corpus/CORPUS_AUDIT.md"))
    if manifest_path.exists():
        manifest = read(manifest_path)
        for record in manifest["copies"]:
            require(sha(inside(source, record["source"])) == sha(inside(ROOT, record["destination"])) == record["sha256"],
                    "supplement provenance differs")
        return {"status": "VERIFIED_EXISTING_SUPPLEMENT", "copies": len(manifest["copies"])}
    copies = []
    for old, new in specs:
        src, dst = inside(source, old), inside(ROOT, new)
        require(src.is_file() and not dst.exists(), "supplement source missing or destination exists")
        expected, size = sha(src), src.stat().st_size
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
        require(sha(src) == sha(dst) == expected and dst.stat().st_size == size, "supplement bytes differ")
        copies.append({"source": old, "destination": new, "sha256": expected, "bytes": size})
    manifest = {"version": "supplement-corpus-v1", "copies": copies,
                "reason": "Follow the knowledge provenance reference to reports/CORPUS_AUDIT.md and existing machine editorial records",
                "source_unchanged": True, "additional_source_files_outside_initial_scopes": 1}
    public = ROOT / "docs/MIGRATION_SUPPLEMENT.json"
    if public.exists():
        require(read(public) == manifest, "supplement public metadata differs")
    else:
        write(public, manifest)
    write(manifest_path, manifest)
    return {"status": "MIGRATED_SUPPLEMENT", "copies": len(copies)}


def migrate(source):
    source = Path(source).resolve()
    require(source != ROOT and not ROOT.is_relative_to(source) and not source.is_relative_to(ROOT),
            "old and new projects must be independent siblings")
    require(not (ROOT / "local/migration/manifest.json").exists(), "migration exists; validate it instead of overwriting")
    before, exclusions = inventory(source)
    state = {"head": git(source, "rev-parse", "HEAD"), "branch": git(source, "branch", "--show-current"),
             "status": git(source, "status", "--porcelain=v1", "--untracked-files=normal")}
    write(ROOT / "local/migration/source_before.json", {"files": before, "excluded_directories": exclusions, "git": state})
    copies = []

    def public_metadata(relative, value):
        path = ROOT / relative
        if path.exists():
            require(read(path) == value, "public provenance differs from restored source: " + relative)
        else:
            write(path, value)

    def copy(old, new):
        src, dst = inside(source, old), inside(ROOT, new)
        require(src.is_file() and old in before, "required migration input missing: " + old)
        if dst.exists():
            require((new.startswith("src/") or new == "configs/legacy_sampling_plan.json") and sha(dst) == before[old]["sha256"],
                    "destination exists; preserve existing bytes: " + new)
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)
        require(sha(src) == sha(dst) == before[old]["sha256"], "copy changed bytes")
        copies.append({"source": old, "destination": new, **before[old]})

    def tree(old, new):
        matches = sorted(p for p in before if p.startswith(old.rstrip("/") + "/"))
        require(matches, "required source tree missing: " + old)
        for p in matches:
            copy(p, new.rstrip("/") + p[len(old):])

    tree(RESEARCH + "p1/data/releases/p1-v2", "data/releases/p1-v2")
    tree(RESEARCH + "p1/local/pmdata", "data/raw/pmdata")
    copy(RESEARCH + "p1/local/pseudonym.key", "local/identity/pseudonym.key")
    copy(RESEARCH + "p1/local/mapping-p1-v2.json", "local/identity/mapping-p1-v2.json")
    copy(RESEARCH + "p1/sampling_plan.json", "configs/legacy_sampling_plan.json")
    tree(RESEARCH + "experiment_a/data/releases/a1-v1", "data/releases/a1-v1")
    tree(RESEARCH + "experiment_a/local/silver_annotations/v1", "local/archive/experiment_a/silver_annotations/v1")
    tree(RESEARCH + "experiment_a/local/silver_annotations/v1/release-v1", "data/releases/qwen-max-silver-v1")
    for name in ("knowledge_items.jsonl", "corpus_seed.json", "source_manifest.json", "input_freeze.json"):
        copy("data/" + name, "data/processed/legacy_knowledge/" + name)
    tree("data/source_snapshots", "data/raw/knowledge_sources")
    for experiment in ("p1", "experiment_a", "experiment_b0", "experiment_c0"):
        base = RESEARCH + experiment
        for p in sorted(before):
            if not p.startswith(base + "/") or "/local/" in p:
                continue
            rel = p[len(base) + 1:]
            if p.endswith(".md") or rel.startswith(("results/", "configs/")) or (experiment == "experiment_a" and rel.startswith("data/") and "/releases/" not in rel):
                copy(p, "local/archive/" + experiment + "/records/" + rel)
        # Historical implementations are evidence only, not importable runtime dependencies.
        for p in sorted(before):
            if p.startswith(base + "/") and "/local/" not in p and p.endswith(".py") and "/tests/" not in p:
                copy(p, "local/archive/" + experiment + "/implementation/" + p[len(base) + 1:])
    for experiment in ("experiment_a", "experiment_b0"):
        prefix = RESEARCH + experiment + "/local/"
        for p in sorted(before):
            if not p.startswith(prefix):
                continue
            rel = p[len(prefix):]
            if rel.startswith("silver_annotations/"):
                continue
            # Includes every run revision, request, cache, uncertain attempt and original failure log.
            if rel.startswith(("runs/", "runs_v", "cache/", "requests/", "protocol_history/", "native-replays/", "native-model-smoke/", "official-smoke/")) or "/" not in rel and (rel.endswith(".log") or rel in {"budget.json", "execution_manifest.json"}):
                copy(p, "local/archive/" + experiment + "/" + rel)
    tree(RESEARCH + "experiment_c0/local/c0a-v1", "local/archive/experiment_c0/c0a-v1")

    # Retain the original seven frozen P1 code files for code-hash verification.
    frozen = read(ROOT / "data/releases/p1-v2/freeze.json")
    for name, expected in frozen["code_sha256"].items():
        require(sha(ROOT / "local/archive/p1/implementation" / name) == expected, "P1 frozen importer code mismatch")

    # Extract pure definitions only; never execute/import old modules or copy legacy orchestrators.
    adaptations = []
    def extract(old, new, names, prelude):
        text = (source / old).read_text(encoding="utf-8-sig")
        nodes = [n for n in ast.parse(text).body if isinstance(n, (ast.FunctionDef, ast.ClassDef, ast.Assign))
                 and ((getattr(n, "name", None) in names) or isinstance(n, ast.Assign)
                      and any(isinstance(t, ast.Name) and t.id in names for t in n.targets))]
        found = {n.name for n in nodes if hasattr(n, "name")} | {t.id for n in nodes if isinstance(n, ast.Assign) for t in n.targets if isinstance(t, ast.Name)}
        require(found == set(names), "requested pure source definitions missing")
        target = inside(ROOT, new)
        target.parent.mkdir(parents=True, exist_ok=True)
        rendered = prelude + "\n\n" + "\n\n".join(ast.get_source_segment(text, n) for n in nodes) + "\n"
        rendered = rendered.replace("from ..experiment_a.silver.pipeline import resolve", "from ..evaluation.evidence import resolve")
        if target.exists():
            require(target.read_bytes() == rendered.encode("utf-8"), "existing adapted module differs from source extraction")
        else:
            with target.open("x", encoding="utf-8", newline="\n") as f:
                f.write(rendered)
        adaptations.append({"source": old, "source_sha256": sha(source / old), "destination": new,
                            "destination_sha256": sha(target), "definitions": sorted(names),
                            "change": "Exact pure definitions, independent imports and storage; no live driver"})

    extract(RESEARCH + "p1/dataset.py", "src/datasets/pmdata.py",
            ["opaque", "number", "daily_metric", "sleep_metric", "import_participant", "METRICS", "OBSERVATION_METRICS", "construct_cases"],
            '\"\"\"Pure PMData parsing and HMAC identities adapted from frozen P1; no download/write command.\"\"\"\nfrom datetime import date, datetime, timedelta\nimport hashlib\nimport hmac\nimport math\nfrom ..common import read as read_json, digest\n')
    extract(RESEARCH + "experiment_a/src/data.py", "src/datasets/views.py", ["scalar_stats", "representation", "evidence_value"],
            '\"\"\"Original quality-preserving longitudinal views, with new independent imports.\"\"\"\nfrom collections import Counter\nfrom math import atan2, cos, pi, sin, sqrt\nfrom statistics import mean, median, pstdev\n')
    extract(RESEARCH + "experiment_c0/pilot.py", "src/evaluation/review.py", ["top_pairs", "make_cards", "check_blinding", "token", "METHODS", "SEED"],
            '\"\"\"C0-A pure blind-card logic. All returned content must remain in ignored local/.\"\"\"\nimport hashlib\nimport json\nimport random\nimport re\n')
    extract(RESEARCH + "experiment_b0/core.py", "src/baselines/contracts.py", ["validate", "evidence_audit"],
            '\"\"\"Historical B0 output contract and mechanical evidence audit; not a clinical validator.\"\"\"')
    for old, new in [("experiment_a/silver/schemas.py", "src/annotation/schemas.py"),
                     ("experiment_b0/schemas.py", "src/baselines/schemas.py"),
                     ("experiment_b0/prompts.py", "src/baselines/legacy_prompts.py")]:
        copy(RESEARCH + old, new)

    a = read(source / (RESEARCH + "experiment_a/results/baseline_inventory.json"))["official_sources"]
    b = read(source / (RESEARCH + "experiment_b0/results/upstream_pins.json"))
    pins = {}
    for name, spec in {**a, **b}.items():
        repo = source / (RESEARCH + "experiment_a/local/upstream/" + spec["directory"] if name in a else RESEARCH + "experiment_b0/local/upstream/" + name)
        try:
            head = git(repo, "rev-parse", "HEAD")
            tracked_clean = not git(repo, "status", "--porcelain=v1", "--untracked-files=no")
            require(head == spec["commit"] and tracked_clean, "upstream pin or tracked code changed")
            status, detail = "VERIFIED_LOCAL_CHECKOUT", None
        except (ValueError, OSError) as exc:
            status, detail = "BLOCKED", str(exc)
        license_names = [spec["license"]] if name in a else spec["license_files"]
        license_hashes = {n: sha(inside(repo, n)) for n in license_names if inside(repo, n).is_file()}
        pins[name] = {"url": spec["url"], "commit": spec["commit"], "verification": status,
                      "detail": detail, "license_hashes": license_hashes,
                      "redistribution": "NOT_VENDORED", "reproduction": "HISTORICAL_RECORDS_ONLY_NO_NEW_RUN"}
    public_metadata("configs/upstream_pins.json", pins)
    cases = rows(ROOT / "data/releases/p1-v2/cases.jsonl")
    write(ROOT / "data/processed/splits/participant-v1.json", make_split(cases))

    by_source = {x["source"] for x in copies}
    adapted_source = {x["source"] for x in adaptations}
    decisions = []
    for path, info in sorted(before.items()):
        if path in adapted_source:
            decision, reason = "REFACTOR_MIGRATE", "Pure reusable definitions extracted; full historical implementation only in ignored archive"
        elif path in by_source:
            decision, reason = "DIRECT_MIGRATE", "Exact bytes preserve releases, provenance or complete historical successes and failures"
            if "local/archive/" in next((x["destination"] for x in copies if x["source"] == path), ""):
                decision, reason = "RECORD_ONLY", "Historical evidence retained privately; no legacy runtime import"
        elif path.startswith("src/") or path in {"data/wearable_cases.jsonl", "data/relevance_labels_provisional.csv", "data/relevance_labels_provisional.metadata.json"}:
            decision, reason = "DISCARD_FROM_NEW_PROJECT", "Legacy synthetic pilot/generation or coupled orchestration; source remains untouched"
        else:
            decision, reason = "RECORD_ONLY_NOT_COPIED", "Not necessary for the scoped independent project; hash inventory retains audit pointer"
        decisions.append({"path": path, **info, "decision": decision, "reason": reason})
    write(ROOT / "local/migration/asset_audit.json", decisions)
    public = [x for x in decisions if "/local/" not in x["path"]]
    public_metadata("docs/MIGRATION_ASSETS.json", {"scope": "All non-local files in seven requested scopes", "assets": public,
          "private_inventory": "local/migration/asset_audit.json", "excluded_dependency_directories": exclusions})
    after, after_exclusions = inventory(source)
    require(after == before and after_exclusions == exclusions, "old project changed during migration")
    require(state == {"head": git(source, "rev-parse", "HEAD"), "branch": git(source, "branch", "--show-current"),
                       "status": git(source, "status", "--porcelain=v1", "--untracked-files=normal")}, "old Git state changed")
    write(ROOT / "local/migration/manifest.json", {"version": "migration-v1", "source_root": str(source),
          "source_git": state, "copies": copies, "adaptations": adaptations, "source_snapshot_id": digest(before),
          "source_files_checked": len(before), "source_unchanged": True})
    supplemental_provenance(source)
    return {"status": "MIGRATED_PENDING_VALIDATION", "source_files_checked": len(before),
            "byte_identical_copies": len(copies), "adapted_modules": len(adaptations),
            "asset_decisions": dict(Counter(x["decision"] for x in decisions)), "paid_calls": 0}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--supplement-only", action="store_true", help="Preserve the original migration and add the corpus provenance supplement")
    args = parser.parse_args()
    print(json.dumps(supplemental_provenance(args.source_root) if args.supplement_only else migrate(args.source_root), indent=2))
