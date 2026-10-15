"""Verify source/native pixels and candidate equations, not physical accuracy."""
import json
from pathlib import Path
import sys

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0,str(ROOT/"src"))
from cone_dataset import read_csv, sha256
from cone_observation import ConeGroundProjector
from run_cone_review_frames import verify_frame


def main():
    target = HERE / "verification.json"
    if target.exists():
        raise ValueError("verification snapshot already exists; no overwrite")
    intake = json.loads((HERE/"intake_summary.json").read_text())
    analysis = json.loads((HERE/"analysis_r01/summary.json").read_text())
    confirmed = json.loads((HERE/"reference_confirmation.json").read_text())
    assert sha256(Path(intake["archive"])) == intake["archive_sha256"]
    assert sha256(HERE/"intake.py") == intake["script_sha256"]
    for file,digest in analysis["source_sha256"].items():
        assert sha256(Path(file)) == digest,file
    for name,digest in analysis["output_sha256"].items():
        assert sha256(HERE/"analysis_r01"/name) == digest,name
    manifest = read_csv(HERE/"raw_sample_manifest.csv")
    assert len(manifest) == 6
    for sample in manifest:
        verify_frame(HERE,sample)
    original_rows = read_csv(Path(intake["session"])/"detections.csv")
    assert len(original_rows) == intake["frames"] == 467
    assert [int(r["frame"]) for r in original_rows] == list(range(1,468))
    assert intake["all_raw_frames_decoded"] and intake["max_abs_odom_linear_mps"] == 0
    assert intake["max_abs_odom_angular_radps"] == 0
    p = intake["metadata"]["parameters"]
    assert all(p[key] == 0 for key in ("enable_ai","collision_ffb_publish_enabled","collision_ffb_relay_enabled"))
    rows = read_csv(HERE/"analysis_r01/floor_candidate_errors.csv")
    assert len(rows) == len(confirmed["placements_m"]) == 7
    for row in rows:
        reference = [float(row["reference_x_m"]),float(row["reference_z_m"])]
        assert reference == confirmed["placements_m"][row["point_id"]]
        assert float(row["reported_measured_height_m"]) == confirmed["reported_lens_centre_height_m"] == .59
        for field in ("placement_uncertainty_m","reported_height_uncertainty_m"):
            assert row[field] == ""  # Never invent physical uncertainty.
        x,y = float(row["pixel_x"]),float(row["pixel_y"])
        projector = ConeGroundProjector(p,width=1280,height=720,front_lens="left")
        projected = projector.project(dict(x1=x-2,x2=x+2,y1=y-5,y2=y,confidence=1,class_id=0),
                                      frame_width=1280,frame_height=720)
        assert projected["projection_candidate"]
        expected = [float(row["raw_x_m"]),float(row["raw_z_m"])]
        assert np.allclose([projected["x_m"],projected["z_m"]],expected,rtol=0,atol=1e-12)
        scale = .59 / p["camera_height"]
        assert np.allclose([float(row["measured_height_only_x_m"]),float(row["measured_height_only_z_m"])],
                           np.asarray(expected)*scale,rtol=0,atol=1e-12)
        assert abs(float(row["raw_error_z_m"])-(expected[1]-reference[1])) < 1e-12
        assert float(row["hypothetical_2px_z_min_m"]) <= expected[1] <= float(row["hypothetical_2px_z_max_m"])
        assert all(row[name] == "False" for name in ("fit_eligible","usable_for_ffb","physical_apex_verified"))
    assert analysis["fit_points_used"] == 0 and not analysis["production_settings_changed"]
    result = dict(status="PASS_INTERNAL_HASH_PIXEL_AND_EQUATION_CHECKS_NOT_CALIBRATION_ACCURACY",
        frames_retained=467,native_pngs_verified=6,point_equations_verified=7,
        source_hashes_unchanged=True,confirmation_matches_all_rows=True,
        unknown_measurement_uncertainty_preserved=True,physical_output=False,
        physical_apex_verified=False,calibration_promoted=False,
        reference_confirmation_sha256=sha256(HERE/"reference_confirmation.json"),
        verification_script_sha256=sha256(Path(__file__)))
    target.write_text(json.dumps(result,indent=2)+"\n")
    print(json.dumps(result,indent=2))


if __name__ == "__main__":
    main()
