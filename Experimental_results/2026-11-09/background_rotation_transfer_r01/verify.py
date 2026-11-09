"""保存結果と関係する回帰を確認する。カメラ・GPU・ROSは起動しない。"""
import argparse
import hashlib
import io
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT/"src"))
sys.path.insert(0, str(ROOT/"tests"))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.output_dir.exists():
        raise ValueError("new output directory required")
    folders = [ROOT/"Experimental_results/2026-11-09/wide_floor_geometry_r01"/sub
               for sub in ("results_r01", "corner_identity_r01", "same_frame_pose_r01")]
    folders.append(Path(__file__).parent/"results_r01")
    checked = 0
    for folder in folders:
        for name, expected in json.loads((folder/"input_provenance.json").read_text()).items():
            if sha(Path(name)) != expected:
                raise ValueError("provenance changed: " + name)
            checked += 1
        summary = json.loads((folder/"summary.json").read_text())
        assert summary["usable_for_ffb"] is False
        assert summary["selected_solution"] is None
        assert summary["camera_images_edited_or_exported"] is False
    patterns = ["test_background_rotation_transfer.py", "test_wide_floor_corner_identity.py",
                "test_wide_floor_reference_audit.py", "test_floor_reference_pose.py",
                "test_angular_fisheye_geometry.py", "test_diagnose_floor_board_pose.py",
                "test_derive_fixed_floor_live_bundle.py"]
    suite = unittest.TestSuite()
    for pattern in patterns:
        suite.addTests(unittest.defaultTestLoader.discover(str(ROOT/"tests"), pattern=pattern))
    log = io.StringIO()
    run = unittest.TextTestRunner(stream=log, verbosity=2).run(suite)
    from test_background_rotation_transfer import synthetic_translation_control
    from cone_distance_core import load_config
    control = synthetic_translation_control(load_config()[1])
    source = [Path(__file__), Path(__file__).with_name("analyze.py")]
    source += [ROOT/"tests"/pattern for pattern in patterns]
    result = dict(status="PASS_OFFLINE_ONLY" if run.wasSuccessful() else "FAIL",
        tests=run.testsRun, failures=len(run.failures), errors=len(run.errors),
        skipped=len(run.skipped), provenance_hash_checks=checked,
        source_sha256={str(p): sha(p) for p in source},
        camera_started=False, ros_started=False, physical_output=False,
        runtime_changed=False, physical_metric_verified=False)
    args.output_dir.mkdir(parents=True)
    (args.output_dir/"tests.log").write_text(log.getvalue())
    (args.output_dir/"verification.json").write_text(json.dumps(result, indent=2)+"\n")
    (args.output_dir/"synthetic_translation_control.json").write_text(json.dumps(control, indent=2)+"\n")
    print(json.dumps(result, indent=2))
    raise SystemExit(not run.wasSuccessful())


if __name__ == "__main__":
    main()
