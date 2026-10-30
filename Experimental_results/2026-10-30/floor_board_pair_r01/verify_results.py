#!/usr/bin/env python3
"""Read-only numerical/input checks and focused tests; writes its own report."""
import csv
import json
from pathlib import Path
import subprocess
import sys

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "src"))
from cone_distance_core import digest, load_config
from floor_reference_pose import planar_floor_pose_candidates


def main():
    out = HERE / "consistency_r02"
    report = json.loads((out / "pair_summary.json").read_text())
    checks = {}
    checks["reported_input_hashes_unchanged"] = all(digest(Path(p)) == h
        for p, h in report["input_source_sha256"].items())
    checks["measured_paper_size_used"] = report["paper_size_mm"] == [296., 210.]
    image_checks = []
    for frame in (1259, 1655):
        name = f"decoded_15ae673c24484d119952ae391df611aa_f{frame:06d}.png"
        paths = [Path("/home/robo25/Downloads") / name,
                 ROOT / "recordings/2026-10-30_floor_board_intake_r01" / name,
                 HERE / "originals" / name]
        image_checks.append(dict(frame=frame, byte_hashes_identical=len({digest(p) for p in paths}) == 1,
                                 native_shape=all(cv2.imread(str(p)).shape == (720, 1280, 3) for p in paths)))
    checks["originals_preserved"] = all(c["byte_hashes_identical"] and c["native_shape"] for c in image_checks)
    rows = list(csv.DictReader((out / "pixel_sensitivity.csv").open(newline="")))
    checks["1024_unique_controls"] = len(rows) == 1024 and len({(r["frame"], r["amplitude_px"], r["corner_signs"]) for r in rows}) == 1024
    checks["all_perturbed_depth_and_projection_valid"] = all(r["all_positive_depth"] == "True" and r["all_projected"] == "True" for r in rows)
    checks["not_approved_or_integrated"] = all(report[k] is False for k in (
        "physical_metric_verified", "base_link_transform_verified", "distance_accuracy_evaluated", "live_integrated", "usable_for_ffb"))
    measured = json.loads((HERE / "white_paper_quad_measured_r01.json").read_text())
    _, camera, _, _ = load_config()
    points = next(r["quads"][0]["quad_xy"] for r in measured["rows"] if r["frame"] == 1259 and r["threshold"] == 170)
    world = np.array([[0, 0, 0], [.296, 0, 0], [.296, .210, 0], [0, .210, 0]])
    base = planar_floor_pose_candidates(points, world, camera)["candidates"]
    scaled = planar_floor_pose_candidates(points, world*2, camera)["candidates"]
    checks["two_planar_solutions_retained"] = len(base) == len(scaled) == 2
    checks["object_scale_doubles_height_not_normal_or_reprojection"] = all(
        np.isclose(b["camera_height_above_floor_m"]*2, s["camera_height_above_floor_m"], atol=1e-10)
        and np.allclose(b["up_optical"], s["up_optical"], atol=1e-10)
        and np.isclose(b["fit_native_rmse_px"], s["fit_native_rmse_px"], atol=1e-10)
        for b, s in zip(base, scaled))
    test_runs = []
    for pattern in ("test_floor_reference_pose.py", "test_diagnose_floor_board_pose.py"):
        cmd = [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", pattern]
        run = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=60)
        test_runs.append(dict(command=cmd, returncode=run.returncode, stdout=run.stdout, stderr=run.stderr))
    checks["focused_unit_tests_passed"] = all(r["returncode"] == 0 for r in test_runs)
    result = dict(status="PASS" if all(checks.values()) else "FAIL", checks=checks,
        meaning="Numerical consistency, input preservation and software tests only; NOT physical accuracy approval",
        image_checks=image_checks, test_runs=test_runs,
        source_sha256={str(Path(__file__).resolve()): digest(Path(__file__).resolve()),
                       str(HERE / "plot_sensitivity.py"): digest(HERE / "plot_sensitivity.py"),
                       str(out / "pixel_sensitivity.png"): digest(out / "pixel_sensitivity.png")})
    with (out / "verification.json").open("x") as f:
        json.dump(result, f, indent=2, allow_nan=False)
        f.write("\n")
    print(json.dumps(dict(status=result["status"], checks=checks), indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
