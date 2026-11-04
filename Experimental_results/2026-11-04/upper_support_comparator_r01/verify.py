"""Offline upper-boundary comparator benchmark; never a live recovery claim."""
import argparse
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
from cone_distance_core import digest,load_config
from cone_support_completion_candidate import observe_lateral_completion
from cone_upper_support_candidate import observe_upper_completion
from summarize_cone_distance_live import load_frames


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir",required=True,type=Path)
    args=parser.parse_args()
    args.output_dir.mkdir(parents=True,exist_ok=False)
    previous_path=HERE.parent/"fixed_floor_display_roi_fix_r01/verification_r01/verification.json"
    previous=json.loads(previous_path.read_text())
    patterns=[*previous["patterns"],"test_cone_upper_support_candidate.py"]
    helper=ROOT/"Experimental_results/2026-10-27/cone_distance_runtime_r01/verify_runtime.py"
    spec=importlib.util.spec_from_file_location("upper_test_recording",helper)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    suite=unittest.TestSuite()
    for pattern in patterns:
        suite.addTests(unittest.defaultTestLoader.discover(str(ROOT/"tests"),pattern=pattern))
    with (args.output_dir/"tests.log").open("x") as stream:
        tests=unittest.TextTestRunner(stream=stream,verbosity=2,resultclass=module.RecordedResult).run(suite)
    with (args.output_dir/"tests.csv").open("x",newline="") as stream:
        writer=csv.DictWriter(stream,fieldnames=("test","status","detail"));writer.writeheader();writer.writerows(tests.rows)
    cases_path=HERE.parent/"floor_df33e833_multidistance_r01/cases.json"
    cases=json.loads(cases_path.read_text())
    camera=load_config()[1]
    actual=[];counterfactual=[];traces=[];image_hashes={}
    for case in cases["cases"]:
        if not case["image"]:continue
        path=ROOT/case["image"]
        if digest(path)!=case["image_sha256"]:raise ValueError("native PNG changed")
        rows,_,hashed=load_frames(ROOT/case["input"])
        if hashed!=case["sha256"]:raise ValueError("log changed")
        row=next(r for r in rows if r["frame"]==case["image_frame"])
        image=cv2.imread(str(path));before=image.copy();box=row["selected_detector_boxes"][0]
        old=observe_lateral_completion(image,box,camera)
        new=observe_upper_completion(image,box,camera)
        if old!=row["support_completion_shadow"]["candidate"]:raise ValueError("original same-frame mismatch")
        preserved=all(old[k]==new[k] for k in ("point","support","reason","selected_colour"))
        actual.append(dict(case=case["id"],frame=row["frame"],old_point=old["point"],new_point=new["point"],
            prior_observation_preserved=preserved,upper_granted=new["upper_completion_granted"]))
        for dy1 in (-1,0,1):
            for dy2 in (-1,0,1):
                changed=dict(box,y1=box["y1"]+dy1,y2=box["y2"]+dy2)
                old=observe_lateral_completion(image,changed,camera)
                new=observe_upper_completion(image,changed,camera)
                kept=old["point"] is None or all(new[k]==old[k] for k in ("point","support","reason","selected_colour"))
                fields=dict(case=case["id"],source_frame=row["frame"],dy1=dy1,dy2=dy2,
                    old_available=old["point"] is not None,new_available=new["point"] is not None,
                    old_observation_preserved=kept,upper_granted=new["upper_completion_granted"],
                    upper_reason=new["upper_completion_reason"],actual_extra_frame=False)
                counterfactual.append(fields)
                traces.append(dict(**fields,candidate=new))
                if any(new.get(k) is not False for k in ("controlling_distance","physical_metric_verified","floor_contact_verified","usable_for_ffb")):
                    raise ValueError("authority flags changed")
        if not np.array_equal(before,image) or digest(path)!=case["image_sha256"]:
            raise ValueError("native input modified")
        image_hashes[case["image"]]=digest(path)
    with (args.output_dir/"bbox_counterfactual.csv").open("x",newline="") as stream:
        writer=csv.DictWriter(stream,fieldnames=list(counterfactual[0]));writer.writeheader();writer.writerows(counterfactual)
    (args.output_dir/"counterfactual_traces.json").write_text(json.dumps(traces,indent=2)+"\n")
    old_diag_path=HERE.parent/"floor_df33e833_diagnosis_r01/results_r01/diagnosis.json"
    old_diag=json.loads(old_diag_path.read_text())
    prior_runtime={k:v for k,v in old_diag["source_sha256"].items() if k.startswith("src/")}
    prior_runtime.update({k:v for k,v in previous["source_sha256"].items() if k.startswith("src/")})
    mismatches=[k for k,v in prior_runtime.items() if digest(ROOT/k)!=v]
    checks=dict(tests_pass=tests.wasSuccessful() and not tests.skipped,
        original_runtime_hashes_unchanged=not mismatches,
        both_actual_saved_observations_preserved=len(actual)==2 and all(r["prior_observation_preserved"] for r in actual),
        no_new_actual_frame_acceptance=all(not r["upper_granted"] for r in actual),
        all_existing_counterfactual_points_preserved=all(r["old_observation_preserved"] for r in counterfactual),
        counterfactual_count=len(counterfactual)==18,
        native_hashes_unchanged=all(digest(ROOT/k)==v for k,v in image_hashes.items()))
    report=dict(status="PASS_OFFLINE_UPPER_COMPARATOR_NOT_LIVE_RECOVERY_APPROVAL" if all(checks.values()) else "FAIL",
        checks=checks,tests=tests.testsRun,failures=len(tests.failures),errors=len(tests.errors),skipped=len(tests.skipped),patterns=patterns,
        actual_saved_frame_results=actual,counterfactual_conditions=len(counterfactual),
        counterfactual_old_available=sum(r["old_available"] for r in counterfactual),
        counterfactual_new_available=sum(r["new_available"] for r in counterfactual),
        counterfactual_newly_observed_points=sum(r["upper_granted"] for r in counterfactual),
        runtime_source_hash_mismatches=mismatches,prior_runtime_sha256=prior_runtime,image_sha256=image_hashes,
        live_missing_frame_images_available=False,live_81_withheld_rows_recovery_measured=False,
        live_wiring_changed=False,physical_metric_verified=False,usable_for_ffb=False,
        actual_camera_images_modified=False,camera_gpu_ros_started=False,git_commit_or_push_performed=False,
        source_sha256={str(p.relative_to(ROOT)):digest(p) for p in (Path(__file__).resolve(),ROOT/"src/cone_upper_support_candidate.py",
            ROOT/"tests/test_cone_upper_support_candidate.py",cases_path,previous_path,old_diag_path)})
    (args.output_dir/"verification.json").write_text(json.dumps(report,indent=2)+"\n")
    print(json.dumps({k:report[k] for k in ("status","checks","tests","failures","errors","skipped",
        "counterfactual_old_available","counterfactual_new_available","counterfactual_newly_observed_points")},indent=2))
    return 0 if all(checks.values()) else 1


if __name__=="__main__":
    raise SystemExit(main())
