#!/usr/bin/env python3
"""Validate current saved-board model file; no GPU receiver or physical output."""
import argparse
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
from cone_fixed_floor_live_load import validate_live_payload
from derive_fixed_floor_live_bundle import checkerboard_reference


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir",type=Path,required=True)
    args=parser.parse_args()
    args.output_dir.mkdir(parents=True,exist_ok=False)
    image=ROOT/"recordings/2026-11-04/floor_reference_9b7d9a17_r01/decoded_9b7d9a17f292490c96e697af31438fd1_f061717.png"
    before=digest(image)
    pixels=cv2.imread(str(image))
    gray=cv2.cvtColor(pixels[390:425,285:355],cv2.COLOR_BGR2GRAY)
    contours=[]
    for threshold in (170,190,210):
        components=cv2.findContours(cv2.inRange(gray,threshold,255),cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)[0]
        components=[c for c in components if cv2.contourArea(c)>=200]
        for component in components:
            for epsilon in (.02,.025,.03,.04):
                poly=cv2.approxPolyDP(component,epsilon*cv2.arcLength(component,True),True)[:,0,:]+[285,390]
                contours.append(dict(threshold=threshold,epsilon_fraction=epsilon,vertices_native_xy=poly.tolist()))
    try:
        checkerboard_reference(image,20,(270,375,100,70))
        grid="detected"
    except ValueError as exc:
        grid=str(exc)
    settings=load_config()[0]
    payload=(HERE/"prepared_floor_9b7d9a17_f061717.json").read_bytes()
    session="9b7d9a17f292490c96e697af31438fd1"
    adapter,evidence=validate_live_payload(payload,settings,digest(DEFAULT_CONFIG),image.parent,session,61717,"support_completion_shadow")
    controls=[]
    for name in ("derived_primary_r01","derived_pixel_control_r01"):
        report=json.loads((HERE/name/"derivation_report.json").read_text())
        for pose in report["poses"]:
            controls.append(dict(case=name,assignment=pose["assignment"],solutions=[dict(
                index=s["solution_index"],printed_plane_height_m=abs(s["camera_height_above_floor_m"]),
                native_reprojection_rmse_px=s["fit_native_rmse_px"],up_optical=s["up_optical"])
                for s in pose["pose"]["candidates"]]))
    rejected={}
    for label,current,frame in (("different_session","other",61717),("future_reference",session,61716)):
        try:
            validate_live_payload(payload,settings,digest(DEFAULT_CONFIG),image.parent,current,frame,"support_completion_shadow")
            rejected[label]=False
        except ValueError:
            rejected[label]=True
    helper=ROOT/"Experimental_results/2026-10-27/cone_distance_runtime_r01/verify_runtime.py"
    spec=importlib.util.spec_from_file_location("current_floor_test_helpers",helper)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    suite=unittest.TestSuite()
    for pattern in ("test_derive_fixed_floor_live_bundle.py","test_cone_fixed_floor_live_load.py"):
        suite.addTests(unittest.defaultTestLoader.discover(str(ROOT/"tests"),pattern=pattern))
    with (args.output_dir/"tests.log").open("x") as stream:
        result=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
    checks=dict(tests_pass=result.wasSuccessful() and not result.skipped,
        source_unmodified=before==digest(image)=="29dc0be0279f7aa93a525a5032050c1071d7c3e6fd699a807b416b27425332da",
        eight_unselected_models=len(adapter.bundle["models"])==8,
        exact_current_reference=[r["frame"] for r in evidence["source_frames"]]==[61717],
        same_session_only=rejected["different_session"],no_future_reference=rejected["future_reference"],
        transfer_bytes_identical=payload==(HERE/"derived_primary_r01/prepared_floor.json").read_bytes())
    data=dict(status="PASS_MODEL_FILE_CHECKS_NOT_GPU_OR_PHYSICAL_APPROVAL" if all(checks.values()) else "FAIL",
        checks=checks,tests=result.testsRun,failures=len(result.failures),errors=len(result.errors),
        source_image_sha256=before,model_sha256=digest(HERE/"prepared_floor_9b7d9a17_f061717.json"),
        checkerboard_result=grid,contour_controls=contours,plane_controls=controls,
        approximate_dimensions_carried_from_previous_user_measurement=True,
        corners_are_perimeter_hypotheses_not_approved_physical_points=True,
        contour_simplification_changed_from_0p02_to_0p03=True,
        metric_accuracy_verified=False,live_model_loaded_on_gpu=False,physical_output=False,
        source_sha256={str(p.relative_to(ROOT)):digest(p) for p in (Path(__file__).resolve(),HERE/"references.json",
            HERE/"references_control_t190.json",HERE/"prepared_floor_9b7d9a17_f061717.json")})
    (args.output_dir/"verification.json").write_text(json.dumps(data,indent=2)+"\n")
    print(json.dumps({k:data[k] for k in ("status","checks","tests","model_sha256","checkerboard_result")},indent=2))
    return 0 if all(checks.values()) else 1


if __name__=="__main__":
    raise SystemExit(main())
