"""L字の新規試験と入力・生成結果を照合。変更のない既存79件は再利用。"""
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
    prior_path = folder.parent/"background_rotation_transfer_r01/verification_r01/verification.json"
    prior = json.loads(prior_path.read_text())
    if prior["status"] != "PASS_OFFLINE_ONLY" or prior["tests"] != 79:
        raise ValueError("successful prior regression record required")
    expected = dict(prior["source_sha256"])
    result_paths = []
    for sub in ("results_r01", "expanded_roi_r01", "reliability_r01"):
        expected.update(json.loads((folder/sub/"input_provenance.json").read_text()))
        result_paths += sorted((folder/sub).iterdir())
    for name, sha in expected.items():
        if digest(name) != sha:
            raise ValueError("fixed input/source changed; cannot reuse prior success: " + name)
    suite = unittest.defaultTestLoader.discover(str(ROOT/"tests"), pattern="test_wide_l_boundary_audit.py")
    log = io.StringIO()
    run = unittest.TextTestRunner(stream=log, verbosity=2).run(suite)
    sources = [Path(__file__), folder/"analyze.py", folder/"audit_expanded_roi.py", folder/"audit_reliability.py",
               ROOT/"tests/test_wide_l_boundary_audit.py"]
    result = dict(status="PASS_OFFLINE_ONLY" if run.wasSuccessful() else "FAIL",
        new_tests_run=run.testsRun, failures=len(run.failures), errors=len(run.errors), skipped=len(run.skipped),
        prior_tests_reused=79, prior_verification=str(prior_path), prior_verification_sha256=digest(prior_path),
        provenance_hash_checks=len(expected), source_sha256={str(p): digest(p) for p in sources},
        results_sha256={str(p): digest(p) for p in result_paths},
        camera_started=False, ros_started=False, runtime_changed=False, physical_metric_verified=False)
    args.output_dir.mkdir(parents=True)
    (args.output_dir/"tests.log").write_text(log.getvalue())
    (args.output_dir/"verification.json").write_text(json.dumps(result, indent=2)+"\n")
    print(json.dumps(result, indent=2))
    raise SystemExit(not run.wasSuccessful())


if __name__ == "__main__":
    main()
