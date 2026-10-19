"""Run the real test suite and validation, preserving logs in a new private directory."""
import argparse
import json
from pathlib import Path
import platform
import subprocess
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.common import require, write


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--name", required=True, help="New version directory name under local/validation/")
    parser.add_argument("--source-root", type=Path)
    args = parser.parse_args()
    require(Path(args.name).name == args.name and args.name not in {"", ".", ".."}, "invalid check version name")
    target = ROOT / "local/validation" / args.name
    require(not target.exists(), "check version exists; use a new name")
    target.mkdir(parents=True)
    commands = [[sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
                [sys.executable, "-m", "src.validate", "--output", str(target / "validation.json")]]
    if args.source_root:
        commands[1] += ["--source-root", str(args.source_root)]
    results = []
    for name, command in zip(("tests", "validation"), commands):
        started = perf_counter()
        result = subprocess.run(command, cwd=ROOT, capture_output=True)
        for kind, content in (("stdout", result.stdout), ("stderr", result.stderr)):
            (target / (name + "." + kind + ".txt")).write_bytes(content)
        results.append({"name": name, "command": command, "exit_code": result.returncode,
                        "duration_seconds": perf_counter() - started})
    summary = {"status": "PASS" if all(r["exit_code"] == 0 for r in results) else "BLOCKED",
               "python": platform.python_version(), "results": results,
               "scope": "Engineering checks only; no model inference, annotation or training"}
    write(target / "checks.json", summary)
    print(json.dumps(summary, indent=2))
    return 0 if summary["status"] == "PASS" else 1


if __name__ == "__main__": raise SystemExit(main())
