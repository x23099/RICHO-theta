"""新規局所支持テストとSHAを照合。既存成功記録は再実行せず再利用する。"""
import argparse
import io
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT/"src"))
from cone_distance_core import digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.output_dir.exists():
        raise ValueError("new output directory required")
    folder = Path(__file__).parent
    expected = json.loads((folder/"results_r01/input_provenance.json").read_text())
    reused = []
    for name, count_key in (("wide_l_boundary_audit_r01", "new_tests_run"), ("background_rotation_transfer_r01", "tests")):
        path = folder.parent/name/"verification_r01/verification.json"
        record = json.loads(path.read_text())
        if record["status"] != "PASS_OFFLINE_ONLY":
            raise ValueError("successful prior test record required")
        expected.update(record["source_sha256"])
        reused.append(dict(record=str(path), record_sha256=digest(path), tests=record[count_key]))
    for name, sha in expected.items():
        if digest(name) != sha:
            raise ValueError("input/source changed; cannot reuse success: " + name)
    suite = unittest.defaultTestLoader.discover(str(ROOT/"tests"), pattern="test_wide_l_local_support.py")
    log = io.StringIO()
    run = unittest.TextTestRunner(stream=log, verbosity=2).run(suite)
    sources = [Path(__file__), folder/"analyze.py", ROOT/"tests/test_wide_l_local_support.py"]
    result = dict(status="PASS_OFFLINE_ONLY" if run.wasSuccessful() else "FAIL",
        new_tests_run=run.testsRun, failures=len(run.failures), errors=len(run.errors), skipped=len(run.skipped),
        prior_success_records_reused=reused, provenance_hash_checks=len(expected),
        source_sha256={str(p):digest(p) for p in sources},
        results_sha256={str(p):digest(p) for p in sorted((folder/"results_r01").iterdir())},
        camera_started=False, ros_started=False, runtime_changed=False, physical_metric_verified=False)
    args.output_dir.mkdir(parents=True)
    (args.output_dir/"tests.log").write_text(log.getvalue())
    (args.output_dir/"verification.json").write_text(json.dumps(result,indent=2)+"\n")
    print(json.dumps(result,indent=2))
    raise SystemExit(not run.wasSuccessful())


if __name__ == "__main__":
    main()
