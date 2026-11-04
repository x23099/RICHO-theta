"""Check this native image/bundle and source controls; never start hardware."""
import argparse
import json
from pathlib import Path
import sys
import unittest

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT/"src"))
from cone_distance_core import DEFAULT_CONFIG, digest, load_config
from cone_fixed_floor_live_load import validate_live_payload
from derive_fixed_floor_live_bundle import checkerboard_reference


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=False)
    folder = ROOT/"recordings/2026-11-04/floor_reference_df33e833_r01"
    image = folder/"decoded_df33e833acdf4e7d8b00d1ec37b7bcae_f002292.png"
    initial = digest(image)
    pixels = cv2.imread(str(image))
    gray = cv2.cvtColor(pixels[390:430,280:360],cv2.COLOR_BGR2GRAY)
    cases = [("references.json",170,.02), ("references_control_t150.json",150,.02),
             ("references_control_t190.json",190,.025), ("references_control_e030.json",170,.03)]
    observed = []
    for name, threshold, epsilon in cases:
        contours = cv2.findContours(cv2.inRange(gray,threshold,255),cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)[0]
        contours = [c for c in contours if cv2.contourArea(c)>=200]
        if len(contours) != 1:
            raise ValueError("one explicit paper contour required in board ROI")
        c = contours[0]
        points = cv2.approxPolyDP(c,epsilon*cv2.arcLength(c,True),True)[:,0,:]+[280,390]
        expected = json.loads((HERE/name).read_text())["frames"][0]["corners_native_xy"]
        if len(points)!=4 or sorted(map(tuple,points))!=sorted(map(tuple,expected)):
            raise ValueError("recorded corners differ from observed native contour")
        observed.append(dict(reference=name, threshold=threshold, epsilon=epsilon,
                             contour_area_px2=cv2.contourArea(c), vertices=points.tolist()))
    try:
        checkerboard_reference(image,20,(280,390,80,40))
        grid = "complete_checkerboard_detected"
    except ValueError as exc:
        grid = str(exc)
    settings = load_config()[0]
    model = HERE/"prepared_floor_df33e833_f002292.json"
    payload = model.read_bytes()
    session = "df33e833acdf4e7d8b00d1ec37b7bcae"
    adapter, evidence = validate_live_payload(payload,settings,digest(DEFAULT_CONFIG),folder,
        session,2292,"support_completion_shadow")
    negative = {}
    for name,current,frame,config in [("old_session_rejected","9b7d9a17f292490c96e697af31438fd1",2292,digest(DEFAULT_CONFIG)),
            ("future_evidence_rejected",session,2291,digest(DEFAULT_CONFIG)),
            ("wrong_config_rejected",session,2292,"0"*64)]:
        try:
            validate_live_payload(payload,settings,config,folder,current,frame,"support_completion_shadow")
            negative[name] = False
        except ValueError:
            negative[name] = True
    suite = unittest.TestSuite()
    for pattern in ("test_derive_fixed_floor_live_bundle.py", "test_cone_fixed_floor_live_load.py", "test_cone_fixed_floor_display.py"):
        suite.addTests(unittest.defaultTestLoader.discover(str(ROOT/"tests"), pattern=pattern))
    with (args.output_dir/"tests.log").open("x") as stream:
        tests = unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
    checks = dict(tests_pass=tests.wasSuccessful() and not tests.skipped,
        native_source_unmodified=initial==digest(image)=="375be11d55ad8db1aaa97c2bde07c095db45c63cd84b174d89f43978c963c11a",
        native_image_shape=pixels.shape==(720,1280,3), all_observed_quads_verified=len(observed)==4,
        eight_unselected_models=len(adapter.bundle["models"])==8,
        exact_current_evidence=[r["frame"] for r in evidence["source_frames"]]==[2292],
        distribution_is_primary_bytes=payload==(HERE/"derived_primary_r01/prepared_floor.json").read_bytes(), **negative)
    report = dict(status="PASS_CURRENT_BUNDLE_CHECKS_NOT_LIVE_GUI_OR_METRIC_APPROVAL" if all(checks.values()) else "FAIL",
        checks=checks, tests=tests.testsRun, failures=len(tests.failures), errors=len(tests.errors), skipped=len(tests.skipped),
        session=session, evidence_frame=2292, source_image_sha256=initial, distribution_sha256=digest(model),
        checkerboard_result=grid, contour_controls=observed, dimensions_carried_from_previous_user_measurement=True,
        prior_cone_distance_not_reused=True, physical_metric_verified=False, live_load_on_gpu_verified=False,
        physical_output=False, original_image_modified=False,
        source_sha256={str(p.relative_to(ROOT)):digest(p) for p in
            [Path(__file__).resolve(), model, *[HERE/name for name,_,_ in cases],
             ROOT/"src/derive_fixed_floor_live_bundle.py", ROOT/"src/cone_fixed_floor_display.py"]})
    (args.output_dir/"verification.json").write_text(json.dumps(report,indent=2)+"\n")
    print(json.dumps({k:report[k] for k in ("status","checks","tests","distribution_sha256","checkerboard_result")},indent=2))
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
