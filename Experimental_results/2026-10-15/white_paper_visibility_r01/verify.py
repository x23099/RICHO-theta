"""Full raw replay, native PNG comparison, direct projection equations."""
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np

from analyze import HERE, ROOT, THRESHOLDS, paper_corner, read_csv, sha256
from ground_contact import dual_fisheye_pixels_to_vehicle_rays


def main():
    target = HERE/"verification.json"
    if target.exists():
        raise ValueError("no verification overwrite")
    output = HERE/"analysis_r01"
    p = json.loads((output/"provenance.json").read_text())
    for path, digest in p["source_sha256"].items():
        assert sha256(Path(path)) == digest, path
    for name, digest in p["output_sha256"].items():
        assert sha256(output/name) == digest, name
    intake = json.loads((HERE/"intake_summary.json").read_text())
    assert sha256(HERE/"intake.py") == intake["intake_script_sha256"]
    assert intake["integrity"]["decision"] == "PASS"
    corners = read_csv(output/"corner_candidates.csv")
    projections = read_csv(output/"fixed_projection_reference.csv")
    assert len(corners) == 467*3 and len(projections) == 467*3*2
    keyed = {(int(r["frame"]), int(r["threshold"])): r for r in corners}
    manifest = {int(r["frame"]): r for r in read_csv(HERE/"raw_sample_manifest.csv")}
    cap = cv2.VideoCapture(str(Path(intake["session"])/"raw.avi"))
    try:
        for frame in range(1, 468):
            ok, image = cap.read()
            assert ok and image.shape == (720, 1280, 3)
            if frame in manifest:
                row = manifest[frame]
                path = HERE/row["file"]
                assert sha256(path) == row["png_sha256"]
                assert hashlib.sha256(image.tobytes()).hexdigest() == row["decoded_bgr_sha256"]
                np.testing.assert_array_equal(image, cv2.imread(str(path)))
            for threshold in THRESHOLDS:
                actual = paper_corner(image, threshold)
                expected = keyed[frame, threshold]
                assert all(expected[key] == ("" if value is None else str(value)) for key, value in actual.items())
        assert not cap.read()[0]
    finally:
        cap.release()
    for row in projections:
        if row["projection_candidate"] == "True":
            geometry = p["models"][row["model"]]
            _, ray = dual_fisheye_pixels_to_vehicle_rays(
                [[float(row["pixel_x"]), float(row["pixel_y"])]], 1280, 720, geometry)
            ground = -geometry["camera_height"]*ray[0, [0, 2]]/ray[0, 1]
            np.testing.assert_allclose(ground, [float(row["x_m"]), float(row["z_m"])], atol=1e-12, rtol=0)
        else:
            assert not row["x_m"] and not row["z_m"]
        assert row["physical_corner_verified"] == row["usable_for_ffb"] == "False"
    previous = HERE.parent/"floor_cone_same_pose_analysis_r01/analysis_r01/summary.json"
    for path, digest in json.loads(previous.read_text())["source_sha256"].items():
        assert sha256(Path(path)) == digest, path
    report = dict(status="PASS_RAW_PNG_AND_REPLAY_CHECKS_NOT_DISTANCE_CALIBRATION_APPROVAL",
                  raw_frames=467, native_pngs_verified=8, corner_rows_replayed=1401,
                  projection_rows_checked=2802, images_unedited=True, missing_candidates_not_filled=True,
                  previous_sources_and_runtime_configs_unchanged=True, physical_output=False,
                  source_sha256={str(f): sha256(f) for f in (Path(__file__), HERE/"test_paper_visibility.py")})
    target.write_text(json.dumps(report, indent=2)+"\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
