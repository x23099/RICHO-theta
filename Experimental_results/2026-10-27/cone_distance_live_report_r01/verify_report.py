#!/usr/bin/env python3
"""Reuse runtime regression/audit, extending it with the offline report tests."""
import argparse
import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    output = args.output_dir.expanduser().resolve()
    base = ROOT/"Experimental_results/2026-10-27/cone_distance_runtime_r01/verify_runtime.py"
    spec = importlib.util.spec_from_file_location("distance_runtime_verification", base)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.PATTERNS += ("test_summarize_cone_distance_live.py",)
    # The base driver parses the same required --output-dir and performs no
    # hardware/network activation. Its old evidence is not edited or replaced.
    previous_argv = sys.argv
    try:
        sys.argv = [str(base), "--output-dir", str(output)]
        result = module.main()
    finally:
        sys.argv = previous_argv
    path = output/"summary.json"
    summary = json.loads(path.read_text())
    for source in (Path(__file__), ROOT/"src/summarize_cone_distance_live.py", ROOT/"start_cone_distance.sh"):
        summary["source_sha256"][str(source.relative_to(ROOT))] = module.sha256(source)
    summary["scope_extension"] = "Offline JSONL report parsing, consistency checks, plots and shell dispatch; no CUDA/socket activation."
    path.write_text(json.dumps(summary, indent=2)+"\n")
    return result


if __name__ == "__main__":
    raise SystemExit(main())
