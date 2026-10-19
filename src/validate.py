"""Independent project validation with explicit BLOCKED stages and nonzero exit."""
import argparse
import json
from pathlib import Path
import subprocess
from .common import ROOT, Blocked, digest, inside, read, require, rows, sha, write
from .datasets.releases import verify_release, load_cases
from .datasets.source_validation import validate_source
from .datasets.splits import validate_split, make_split
from .knowledge.provenance import audit as knowledge_audit
from .annotation.provenance import audit as silver_audit
from .baselines.replay import replay


def migration_check(root, source_root=None):
    root = Path(root)
    manifest = read(root / "local/migration/manifest.json")
    for record in manifest["copies"]:
        target = inside(root, record["destination"])
        require(sha(target) == record["sha256"] and target.stat().st_size == record["bytes"], "migrated asset differs")
    for record in manifest["adaptations"]:
        require(sha(inside(root, record["destination"])) == record["destination_sha256"], "adapted source differs from migration")
    supplement = read(root / "local/migration/supplement-corpus-v1.json")
    for record in supplement["copies"]:
        require(sha(inside(root, record["destination"])) == record["sha256"], "supplement asset differs")
    result = {"status": "PASS", "exact_byte_copies": len(manifest["copies"]), "adapted_modules": len(manifest["adaptations"]),
              "supplemental_exact_byte_copies": len(supplement["copies"]), "old_source_live_checked": False}
    if source_root is not None:
        import importlib.util
        spec = importlib.util.spec_from_file_location("migration_tools", root / "tools/migrate.py")
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        old, excluded = module.inventory(Path(source_root))
        snapshot = read(root / "local/migration/source_before.json")
        require(old == snapshot["files"] and excluded == snapshot["excluded_directories"], "old source changed since migration")
        require(digest(old) == manifest["source_snapshot_id"], "old snapshot digest mismatch")
        state = {"head": module.git(source_root, "rev-parse", "HEAD"), "branch": module.git(source_root, "branch", "--show-current"),
                 "status": module.git(source_root, "status", "--porcelain=v1", "--untracked-files=normal")}
        require(state == snapshot["git"], "old Git state changed")
        for record in supplement["copies"]:
            require(sha(inside(source_root, record["source"])) == record["sha256"], "supplement source changed")
        legacy = read(Path(source_root) / "data/input_freeze.json")["file_sha256"]
        for name, expected in legacy.items():
            require(sha(inside(source_root, name)) == expected, "legacy frozen source changed")
        result.update(old_source_live_checked=True, old_files_rehashed=len(old), legacy_frozen_hashes_verified=len(legacy))
    return result


def privacy_check(root):
    root = Path(root)
    paths = ["local/identity/pseudonym.key", "local/identity/mapping-p1-v2.json", "data/raw/pmdata/source_manifest.json",
             "data/releases/p1-v2/cases.jsonl", "data/processed/splits/participant-v1.json",
             "data/releases/qwen-max-silver-v1/annotations.jsonl", "local/archive/experiment_b0/runs/main/example.json"]
    result = subprocess.run(["git", "check-ignore", "-z", "--stdin"], cwd=root,
                            input=("\0".join(paths) + "\0").encode(), capture_output=True)
    require(set(result.stdout.decode().strip("\0").split("\0")) == set(paths), "private paths are not all Git ignored")
    tracked = subprocess.run(["git", "ls-files", "--cached"], cwd=root, capture_output=True, text=True, check=True).stdout.splitlines()
    forbidden = [p for p in tracked if p.startswith(("local/", "data/raw/", "data/processed/", "data/releases/")) and not p.endswith(".gitkeep")]
    require(not forbidden, "private artifacts present in Git index")
    return {"status": "PASS", "private_path_rules_checked": len(paths), "private_paths_in_index": 0}


def upstream_check(root, source_root=None):
    pins = read(Path(root) / "configs/upstream_pins.json")
    require(len(pins) == 11 and all(p["verification"] == "VERIFIED_LOCAL_CHECKOUT" for p in pins.values()), "official pin inventory incomplete or BLOCKED")
    checked = 0
    if source_root is not None:
        import os
        for name, pin in pins.items():
            directory = {"medcpt": "MedCPT", "trialgpt": "TrialGPT", "pha": "consumer-health-research"}.get(name, name)
            experiment = "experiment_a" if name in {"medcpt", "trialgpt", "pha"} else "experiment_b0"
            checkout = Path(source_root) / "research/problem_reidentification" / experiment / "local/upstream" / directory
            env = {**os.environ, "GIT_OPTIONAL_LOCKS": "0"}
            head = subprocess.run(["git", "-C", str(checkout), "rev-parse", "HEAD"], capture_output=True, text=True, env=env, check=True).stdout.strip()
            status = subprocess.run(["git", "-C", str(checkout), "status", "--porcelain=v1", "--untracked-files=no"], capture_output=True, text=True, env=env, check=True).stdout.strip()
            require(head == pin["commit"] and not status, "official checkout changed: " + name)
            for path, expected in pin["license_hashes"].items():
                require(sha(inside(checkout, path)) == expected, "official license hash changed: " + name)
            checked += 1
    return {"status": "PASS", "official_repository_pins": len(pins), "live_local_checkouts_verified": checked,
            "new_native_runs": 0, "online_verification": False,
            "license_not_established_not_vendored": [k for k, p in pins.items() if not p["license_hashes"]]}


def validate(root=ROOT, source_root=None):
    root = Path(root)
    results = {}
    def stage(name, fn):
        try:
            results[name] = fn()
        except (ValueError, KeyError, OSError, TypeError, IndexError, subprocess.CalledProcessError) as exc:
            results[name] = {"status": "BLOCKED", "error_type": type(exc).__name__, "reason": str(exc)}
    for kind, name in [("p1", "p1-v2"), ("a1", "a1-v1"), ("silver", "qwen-max-silver-v1")]:
        stage("release_" + kind, lambda k=kind, n=name: {"status": "PASS", "release_id": verify_release(root / "data/releases" / n, k)["release_id"]})
    stage("migration", lambda: migration_check(root, source_root))
    stage("upstream_pins", lambda: upstream_check(root, source_root))
    try:
        cases = load_cases(root)
    except (ValueError, OSError) as exc:
        cases = None
        results["cases"] = {"status": "BLOCKED", "reason": str(exc)}
    if cases is not None:
        stage("raw_source_chain", lambda: validate_source(root, cases))
        def splits():
            split = read(root / "data/processed/splits/participant-v1.json")
            require(split == make_split(cases), "split differs from deterministic registered rule")
            return {"status": "PASS", "counts": validate_split(cases, split), "historically_unexposed_test": False}
        stage("participant_splits", splits)
        stage("knowledge", lambda: knowledge_audit(root))
        stage("silver", lambda: silver_audit(root, cases))
        stage("baseline_and_c0_replay", lambda: replay(root, cases))
    else:
        for name in ("raw_source_chain", "participant_splits", "knowledge", "silver", "baseline_and_c0_replay"):
            results[name] = {"status": "BLOCKED", "reason": "Frozen cases unavailable; dependent validation not executed"}
    stage("git_privacy", lambda: privacy_check(root))
    blocked = [name for name, r in results.items() if r["status"] == "BLOCKED"]
    return {"status": "BLOCKED" if blocked else "PASS_ENGINEERING_ONLY", "stages": results, "blocked_stages": blocked,
            "research_blockers": ["BLOCKED_INDEPENDENT_HUMAN_SOURCE_REVIEW", "BLOCKED_HUMAN_PRIORITY_GOLD",
                                  "BLOCKED_QWEN3_8_MAX_NEW_SILVER_NOT_RUN", "BLOCKED_PRISTINE_HELDOUT_COHORT",
                                  ],
            "new_model_calls": 0, "training_runs": 0, "new_methods_implemented": 0}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--output", type=Path, help="New output path; existing reports are never overwritten")
    args = parser.parse_args()
    result = validate(source_root=args.source_root)
    if args.output:
        destination = args.output.resolve()
        require(destination.is_relative_to((ROOT / "local/validation").resolve()), "validation reports must stay under new-project local/validation")
        write(destination, result)
    print(json.dumps(result, indent=2, ensure_ascii=False))
    raise SystemExit(1 if result["blocked_stages"] else 0)
