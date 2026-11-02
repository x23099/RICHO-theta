#!/usr/bin/env python3
"""Headless tests and SYNTHETIC GUI previews only. Never opens a real window."""
import argparse
from collections import Counter
import copy
import csv
import importlib.util
import json
from pathlib import Path
import sys
import time
import unittest

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT/"src"))
from cone_distance_core import digest, render_distance
from cone_fixed_floor_display import append_comparison_panel, comparison_view_model, panel_lines
from summarize_cone_distance_live import load_frames


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=False)
    old360 = HERE.parent/"fixed_floor_derivation_r01/verification_r03/verification.json"
    previous = json.loads(old360.read_text())
    patterns = [*previous["patterns"], "test_fixed_floor_lifecycle_replay.py", "test_cone_fixed_floor_display.py"]
    spec = importlib.util.spec_from_file_location("display_test_helpers",
        ROOT/"Experimental_results/2026-10-27/cone_distance_runtime_r01/verify_runtime.py")
    helpers = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helpers)
    suite = unittest.TestSuite()
    for pattern in patterns:
        suite.addTests(unittest.defaultTestLoader.discover(str(ROOT/"tests"), pattern=pattern))
    with (args.output_dir/"tests.log").open("x") as stream:
        result = unittest.TextTestRunner(stream=stream, verbosity=2, resultclass=helpers.RecordedResult).run(suite)
    with (args.output_dir/"tests.csv").open("x", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=("test", "status", "detail"), lineterminator="\n")
        writer.writeheader()
        writer.writerows(result.rows)

    data = HERE.parent/"fixed_floor_lifecycle_replay_r01/results_r04"
    rows, _, _ = load_frames(data/"synthetic_lifecycle/distance_frames.jsonl")
    real, _, _ = load_frames(data/"real_wrong_session/distance_frames.jsonl")
    panel_views = [comparison_view_model(r, model_state=r["fixed_floor_load"], mode="synthetic") for r in rows]
    real_views = [comparison_view_model(r, model_state=r["fixed_floor_load"], mode="recorded") for r in real]
    (args.output_dir/"synthetic_panel_views.json").write_text(json.dumps(panel_views, indent=2)+"\n")
    (args.output_dir/"real_panel_summary.json").write_text(json.dumps(dict(processed_rows=len(real),
        numeric_rows=sum(v["range_span_m"] is not None for v in real_views),
        reason_counts=dict(Counter(v["reason"] for v in real_views)),
        real_camera_images_rendered_or_saved=False), indent=2)+"\n")
    image = np.zeros((720,1280,3),np.uint8)
    cv2.fillPoly(image,[np.array([[320,310],[295,400],[345,400]],np.int32)],(0,0,255))
    original = image.copy()
    if not cv2.imwrite(str(args.output_dir/"SYNTHETIC_native_cone.png"),image):
        raise ValueError("synthetic PNG save failed")
    examples=[]
    for number in (15,60,111):
        row = rows[number-1]
        before=copy.deepcopy(row)
        base=render_distance(image,row,replay=True)
        canvas=append_comparison_panel(base,row,model_state=row["fixed_floor_load"],mode="synthetic",
            expected_session=row["session"],expected_frame=row["frame"],expected_source_time=row["source_time_sec"])
        if not np.array_equal(canvas[:720],base) or row != before or not np.array_equal(image,original):
            raise ValueError("renderer modified original data")
        filename=f"SYNTHETIC_preview_f{number:06d}.png"
        if not cv2.imwrite(str(args.output_dir/filename),canvas):
            raise ValueError("synthetic preview save failed")
        examples.append(dict(file=filename,frame=number,ui=panel_views[number-1],
                             labels=panel_lines(panel_views[number-1]),sha256=digest(args.output_dir/filename)))
    (args.output_dir/"preview_manifest.json").write_text(json.dumps(dict(synthetic_only=True,
        real_camera_success_claimed=False,examples=examples),indent=2)+"\n")
    # Rendering cost on this CPU only, NOT real GPU/network/display latency.
    costs=[]
    positive=rows[14]
    for index in range(65):
        started=time.perf_counter()
        base=render_distance(image,positive)
        middle=time.perf_counter()
        append_comparison_panel(base,positive,model_state=positive["fixed_floor_load"],mode="synthetic")
        finished=time.perf_counter()
        if index>=5:
            costs.append(dict(iteration=index-4,baseline_render_ms=1000*(middle-started),panel_extra_ms=1000*(finished-middle)))
    with (args.output_dir/"synthetic_cpu_render_cost.csv").open("x",newline="") as stream:
        writer=csv.DictWriter(stream,fieldnames=list(costs[0]),lineterminator="\n")
        writer.writeheader()
        writer.writerows(costs)
    timing=dict(samples=len(costs),panel_extra_median_ms=float(np.median([r["panel_extra_ms"] for r in costs])),
                panel_extra_p95_ms=float(np.percentile([r["panel_extra_ms"] for r in costs],95)),
                local_cpu_synthetic_only=True,school_gpu_or_display_latency_measured=False)

    old309_path=HERE.parent/"fixed_floor_live_load_r01/verification_r04/verification.json"
    old309=json.loads(old309_path.read_text())
    mismatches=[]
    live_snapshot=HERE/"source_snapshot/run_cone_distance_live.py"
    old_test_snapshot=HERE.parent/"fixed_floor_derivation_r01/source_snapshot/test_cone_fixed_floor_live_load.py"
    for filename, hashed in old309["source_sha256"].items():
        path=Path(filename)
        if not path.is_absolute():
            path=ROOT/path
        if path == ROOT/"src/run_cone_distance_live.py":
            path=live_snapshot
        elif path == ROOT/"tests/test_cone_fixed_floor_live_load.py":
            path=old_test_snapshot
        if digest(path) != hashed:
            mismatches.append(filename)
    for filename,hashed in previous["source_sha256"].items():
        if digest(ROOT/filename) != hashed:
            mismatches.append(filename)
    old_derivation=HERE.parent/"fixed_floor_derivation_r01/results_r02/derivation_report.json"
    for filename,hashed in json.loads(old_derivation.read_text())["source_sha256"].items():
        if digest(filename) != hashed:
            mismatches.append(filename)
    checks=dict(tests_pass=result.wasSuccessful() and not result.skipped,
        prior_sources_preserved_except_explicit_gui_change=not mismatches,
        synthetic_numeric_rows_preserved=sum(v["range_span_m"] is not None for v in panel_views)==88,
        real_wrong_session_numeric_rows_zero=all(v["range_span_m"] is None for v in real_views),
        synthetic_input_not_mutated=np.array_equal(image,original),
        synthetic_only_examples=all(e["ui"]["mode"]=="synthetic" for e in examples),
        stale_preview_withheld=examples[1]["ui"]["range_span_m"] is None,
        reload_preview_withheld=examples[2]["ui"]["range_span_m"] is None)
    files=[Path(__file__).resolve(),ROOT/"src/cone_fixed_floor_display.py",ROOT/"src/run_cone_distance_live.py",
        ROOT/"tests/test_cone_fixed_floor_display.py",live_snapshot,old360,old309_path,
        data/"synthetic_lifecycle/distance_frames.jsonl",data/"real_wrong_session/distance_frames.jsonl"]
    report=dict(status="PASS_GUI_COMPARISON_NOT_REAL_CAMERA_APPROVAL" if all(checks.values()) else "FAIL",
        checks=checks,tests=result.testsRun,failures=len(result.failures),errors=len(result.errors),skipped=len(result.skipped),
        patterns=patterns,prior_hash_mismatches=mismatches,synthetic_cpu_render_cost=timing,
        source_sha256={str(p.resolve().relative_to(ROOT)):digest(p) for p in files},
        changed_runtime_scope=["src/run_cone_distance_live.py (GUI composition only)","src/cone_fixed_floor_display.py (new renderer)"],
        physical_metric_verified=False,real_model_positive_continuous_output_verified=False,
        usable_for_ffb=False,camera_gpu_ros_started=False,git_commit_or_push_performed=False)
    (args.output_dir/"verification.json").write_text(json.dumps(report,indent=2)+"\n")
    print(json.dumps({k:report[k] for k in ("status","checks","tests","failures","errors","skipped","synthetic_cpu_render_cost")},indent=2))
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
