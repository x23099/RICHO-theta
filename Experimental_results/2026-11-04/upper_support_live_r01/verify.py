"""Regression for opt-in wiring. No real receiver, GPU, network, ROS, or FFB."""
import argparse
import copy
import csv
import importlib.util
import json
from pathlib import Path
import sys
import unittest

import cv2
import numpy as np

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
sys.path.insert(0,str(ROOT/"src"))
from cone_distance_core import DEFAULT_CONFIG,digest,load_config
from cone_fixed_floor_shadow import FixedFloorShadow
from cone_upper_support_live import UpperSupportLiveComparison,validate_record,summarize
from summarize_cone_distance_live import load_frames
from theta_rtc_frames import NativeFrame


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir",type=Path,required=True)
    args=parser.parse_args()
    args.output_dir.mkdir(parents=True,exist_ok=False)
    previous_path=HERE.parent/"upper_support_comparator_r01/verification_r01/verification.json"
    previous=json.loads(previous_path.read_text())
    patterns=[*previous["patterns"],"test_cone_upper_support_live.py"]
    helper=ROOT/"Experimental_results/2026-10-27/cone_distance_runtime_r01/verify_runtime.py"
    spec=importlib.util.spec_from_file_location("upper_live_test_recording",helper)
    helpers=importlib.util.module_from_spec(spec);spec.loader.exec_module(helpers)
    suite=unittest.TestSuite()
    for pattern in patterns:suite.addTests(unittest.defaultTestLoader.discover(str(ROOT/"tests"),pattern=pattern))
    with (args.output_dir/"tests.log").open("x") as stream:
        result=unittest.TextTestRunner(stream=stream,verbosity=2,resultclass=helpers.RecordedResult).run(suite)
    with (args.output_dir/"tests.csv").open("x",newline="") as stream:
        writer=csv.DictWriter(stream,fieldnames=("test","status","detail"));writer.writeheader();writer.writerows(result.rows)
    changed=("src/cone_distance_worker.py","src/run_cone_distance_live.py")
    mismatches=[]
    for name,hashed in previous["prior_runtime_sha256"].items():
        path=HERE/"source_snapshot"/Path(name).name if name in changed else ROOT/name
        if digest(path)!=hashed:mismatches.append(name)
    for name in ("src/cone_upper_support_candidate.py","tests/test_cone_upper_support_candidate.py"):
        if digest(ROOT/name)!=previous["source_sha256"][name]:mismatches.append(name)
    cases_path=HERE.parent/"floor_df33e833_multidistance_r01/cases.json"
    cases=json.loads(cases_path.read_text())
    settings,camera,heading,_=load_config()
    model=HERE.parent/"floor_reference_df33e833_r01/prepared_floor_df33e833_f002292.json"
    adapter=FixedFloorShadow(model,settings,"support_completion_shadow")
    folder=args.output_dir/"RECORDED_RECOMPUTATION_NOT_LIVE";folder.mkdir()
    comparator=UpperSupportLiveComparison(settings,digest(DEFAULT_CONFIG),folder)
    reports=[];image_hashes={}
    with (folder/"upper_support_comparison.jsonl").open("x") as stream:
        for case in cases["cases"]:
            if case["image"] is None:continue
            path=ROOT/case["image"]
            if digest(path)!=case["image_sha256"]:raise ValueError("native image changed")
            image=cv2.imread(str(path));before=image.copy()
            rows,_,hashed=load_frames(ROOT/case["input"])
            if hashed!=case["sha256"]:raise ValueError("log input changed")
            original=next(r for r in rows if r["frame"]==case["image_frame"])
            baseline=copy.deepcopy(original)
            baseline["inference_source"]="recorded_boxes_and_injected_historical_clock_NOT_LIVE"
            frame=NativeFrame(baseline["session"],baseline["frame"],baseline["source_time_sec"],baseline["source_time_sec"],image)
            row=comparator.observe(frame,baseline,adapter,camera,heading)
            comparator.finish(row,baseline["completed_time_sec"],baseline=baseline)
            row["recorded_recomputation_not_live"]=True
            validate_record(row);stream.write(json.dumps(row)+"\n")
            reports.append(dict(frame=frame.sequence,source_image=case["image"],
                upper_point=row["upper_candidate"]["point"],reason=row["reason"],
                legacy_unchanged=baseline==dict(original,inference_source=baseline["inference_source"]),
                source_pixels_unchanged=np.array_equal(image,before),
                numeric=row["status"]=="UNVERIFIED_UPPER_COMPARISON"))
            image_hashes[case["image"]]=digest(path)
    summary=summarize(folder,args.output_dir/"recorded_log_report")
    checks=dict(tests_pass=result.wasSuccessful() and not result.skipped,
        old_sources_preserved_except_explicit_worker_and_entrypoint=not mismatches,
        original_comparator_unchanged="src/cone_upper_support_candidate.py" not in mismatches,
        two_exact_recorded_frames=len(reports)==2,
        legacy_and_native_inputs_preserved=all(r["legacy_unchanged"] and r["source_pixels_unchanged"] for r in reports),
        two_sparse_recorded_frames_not_claimed_as_new_temporal_confirmation=all(not r["numeric"] for r in reports),
        report_marks_recorded_predictor=summary["contains_injected_or_unverified_predictor"])
    paths=[Path(__file__).resolve(),ROOT/"src/cone_upper_support_live.py",ROOT/"tests/test_cone_upper_support_live.py",
        *[ROOT/p for p in changed],*[HERE/"source_snapshot"/Path(p).name for p in changed],previous_path,cases_path,model]
    report=dict(status="PASS_UPPER_LIVE_WIRING_SOFTWARE_ONLY_NOT_SCHOOL_GPU_APPROVAL" if all(checks.values()) else "FAIL",
        checks=checks,tests=result.testsRun,failures=len(result.failures),errors=len(result.errors),skipped=len(result.skipped),
        patterns=patterns,prior_hash_mismatches=mismatches,recorded_frame_results=reports,image_sha256=image_hashes,
        source_sha256={str(p.relative_to(ROOT)):digest(p) for p in paths},
        changed_existing_runtime=list(changed),new_runtime="src/cone_upper_support_live.py",
        primary_gui_or_distance_algorithm_changed=False,default_enabled=False,
        school_gpu_latency_measured=False,real_missing_frames_recovery_measured=False,
        physical_metric_verified=False,usable_for_ffb=False,hardware_started=False,git_commit_or_push_performed=False)
    (args.output_dir/"verification.json").write_text(json.dumps(report,indent=2)+"\n")
    print(json.dumps({k:report[k] for k in ("status","checks","tests","failures","errors","skipped")},indent=2))
    return 0 if all(checks.values()) else 1


if __name__=="__main__":
    raise SystemExit(main())
