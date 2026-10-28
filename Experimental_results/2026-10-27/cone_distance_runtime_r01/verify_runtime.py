#!/usr/bin/env python3
"""Socket/GPU/camera-free regression and unchanged offline-evidence audit."""
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[3]
PATTERNS = ("test_scene_sampling_clock.py", "test_cone_distance_diagnostic.py",
            "test_theta_rtc_diagnostic.py", "test_cone_support_quality*.py",
            "test_cone_distance_worker_lifecycle.py", "test_cone_distance_live_cleanup.py")


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024*1024), b""):
            digest.update(block)
    return digest.hexdigest()


class RecordedResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.rows = []

    def addSuccess(self, test):
        super().addSuccess(test)
        self.rows.append(dict(test=test.id(), status="PASS", detail=""))

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self.rows.append(dict(test=test.id(), status="FAIL", detail=self._exc_info_to_string(err, test)))

    def addError(self, test, err):
        super().addError(test, err)
        self.rows.append(dict(test=test.id(), status="ERROR", detail=self._exc_info_to_string(err, test)))

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self.rows.append(dict(test=test.id(), status="SKIP", detail=reason))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=False)
    os.chdir(ROOT)
    suite = unittest.TestSuite()
    for pattern in PATTERNS:
        suite.addTests(unittest.defaultTestLoader.discover(str(ROOT/"tests"), pattern=pattern))
    with (args.output_dir/"tests.log").open("x") as stream:
        result = unittest.TextTestRunner(stream=stream, verbosity=2, resultclass=RecordedResult).run(suite)
    with (args.output_dir/"tests.csv").open("x", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=("test", "status", "detail"))
        writer.writeheader()
        writer.writerows(result.rows)

    # Reuse the exact numerical replay, not a new timing-dependent replay.
    # Check ALL recorded source hashes (native videos, saved boxes, algorithms,
    # config/calibration), plus outputs/illustrations in the latest report.
    evidence = ROOT/"Experimental_results/2026-10-26"
    manifests = [evidence/"cone_distance_replay_r05"/name/"summary.json" for name in
                 ("declared_central_scope", "static_center130", "static_no_central_cone")]
    manifests.append(evidence/"cone_distance_report_r03/summary.json")
    cache, checks = {}, []
    for manifest in manifests:
        summary = json.loads(manifest.read_text())
        paths = dict(summary["source_sha256"])
        paths.update({str(manifest.parent/name): expected
                      for name, expected in summary.get("output_sha256", {}).items()})
        for example in summary.get("examples", []):
            for kind in ("original", "visualization"):
                paths[str(manifest.parent/example[kind])] = example[kind+"_sha256"]
        for name, expected in paths.items():
            path = Path(name)
            if name not in cache:
                cache[name] = sha256(path) if path.is_file() else None
            checks.append(dict(manifest=str(manifest.relative_to(ROOT)), path=name,
                               expected=expected, actual=cache[name], matches=cache[name] == expected))
    (args.output_dir/"offline_evidence_checks.json").write_text(json.dumps(checks, indent=2)+"\n")
    mismatches = [row for row in checks if not row["matches"]]
    paths = {ROOT/"src"/name for name in ("cone_distance_worker.py", "run_cone_distance_live.py")}
    paths.add(Path(__file__).resolve())
    for pattern in PATTERNS:
        paths.update((ROOT/"tests").glob(pattern))
    successful = result.wasSuccessful() and not result.skipped and not mismatches
    summary = dict(work_date="2026-10-27", status="PASS_SOFTWARE_ONLY" if successful else "FAIL",
        git_base=subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        python=sys.version, tests=result.testsRun, failures=len(result.failures), errors=len(result.errors),
        skipped=len(result.skipped), offline_evidence_hash_checks=len(checks),
        unique_evidence_files=len(cache), offline_evidence_mismatches=mismatches,
        source_sha256={str(path.relative_to(ROOT)): sha256(path) for path in sorted(paths)},
        scene_thresholds_changed=False, new_distance_accuracy_measurement=False,
        physical_metric_verified=False, usable_for_ffb=False, physical_output=False,
        not_performed=["Camera / school-PC activation", "Network listeners / cross-PC WebRTC",
                       "CUDA inference / package installation", "ROS / robot / FFB", "Git commit / push"],
        test_scope="Controlled Futures and injected predictor; real scene executor lifecycle only in its dedicated test. HTTP/server/model/async-to-thread cleanup are stubbed in entrypoint tests.")
    (args.output_dir/"summary.json").write_text(json.dumps(summary, indent=2)+"\n")
    print(json.dumps({k: summary[k] for k in ("status", "tests", "failures", "errors", "skipped",
          "offline_evidence_hash_checks", "unique_evidence_files")}, indent=2))
    return 0 if successful else 1


if __name__ == "__main__":
    raise SystemExit(main())
