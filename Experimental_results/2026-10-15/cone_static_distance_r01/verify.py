"""Independently recompute summaries and source hashes, not physical accuracy."""
import json
import math
from pathlib import Path
import statistics
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "src"))
from cone_dataset import read_csv, sha256
from cone_observation import ConeGroundProjector
from run_cone_review_frames import verify_frame


def main():
    target = HERE / "verification.json"
    if target.exists():
        raise ValueError("verification snapshot exists; no overwrite")
    intake = json.loads((HERE / "intake_summary.json").read_text())
    analysis = json.loads((HERE / "analysis_r01/analysis_summary.json").read_text())
    diagnosis = json.loads((HERE / "diagnosis_r01/provenance.json").read_text())
    inference = json.loads((HERE / "inference_r01/provenance.json").read_text())
    for report in (analysis, diagnosis, inference):
        for file, digest in report["source_sha256"].items():
            assert sha256(Path(file)) == digest, file
    assert sha256(Path(intake["archive"])) == intake["archive_sha256"]
    assert sha256(Path(intake["model"]["path"])) == intake["model"]["sha256"]
    assert sha256(HERE / "intake.py") == intake["script_sha256"]
    for source in intake["inputs"]:
        for file, digest in source["hashes"].items():
            assert sha256(Path(source["path"]) / file) == digest
    samples = read_csv(HERE / "raw_sample_manifest.csv")
    assert len(samples) == 24
    for row in samples:
        verify_frame(HERE, row)
    for row in read_csv(HERE / "diagnosis_r01/raw_manifest.csv"):
        verify_frame(HERE / "diagnosis_r01", row)
    positions = read_csv(HERE / "analysis_r01/positions.csv")
    summaries = read_csv(HERE / "analysis_r01/summary.csv")
    assert len(positions) == 3596
    assert len({(r["session"], r["frame"]) for r in positions}) == 3596
    assert sum(r["measurement_used"] == "True" for r in positions) == 3261
    assert sum(r["measurement_reason"] == "ambiguous_multiple_front_detections" for r in positions) == 3
    assert all(r["usable_for_ffb"] == "False" and r["floor_contact_verified"] == "False" for r in positions)
    expected = {r["condition"]:r for r in intake["inputs"]}
    checked = 0
    for row in summaries:
        series = [r for r in positions if r["condition"] == row["condition"]]
        valid = [r for r in series if r["measurement_used"] == "True"]
        assert len(series) == int(row["frames"]) and len(valid) == int(row["measurement_frames"])
        if row["condition"] == "none":
            assert len(series) == 332 and all(int(r["front_detections"]) == 0 for r in series)
            assert not valid
            continue
        assert all(int(r["front_detections"]) > 0 for r in series)
        for name in ("x_m", "z_m", "radial_distance_m", "error_x_m", "error_z_m", "position_error_m"):
            values = [float(r[name]) for r in valid]
            assert abs(statistics.median(values)-float(row[name+"_median"])) < 1e-12
            assert abs(statistics.pstdev(values)-float(row[name+"_std"])) < 1e-12
        projector = ConeGroundProjector(expected[row["condition"]]["metadata"]["parameters"],
                                        width=1280, height=720, front_lens="left", confidence_threshold=.5)
        for frame in valid:
            box = {key:float(frame["bbox_"+key]) for key in ("x1","y1","x2","y2")}
            box.update(class_id=0, confidence=float(frame["confidence"]))
            result = projector.project(box, frame_width=1280, frame_height=720)
            assert result["projection_candidate"]
            assert abs(result["x_m"]-float(frame["x_m"])) < 1e-12
            assert abs(result["z_m"]-float(frame["z_m"])) < 1e-12
            assert abs(float(frame["error_x_m"])-(result["x_m"]-float(frame["reference_x_m"]))) < 1e-12
            assert abs(float(frame["error_z_m"])-(result["z_m"]-float(frame["reference_z_m"]))) < 1e-12
            assert abs(float(frame["radial_distance_m"])-math.hypot(result["x_m"],result["z_m"])) < 1e-12
            checked += 1
    report = dict(status="PASS_BOOKKEEPING_HASH_AND_STATISTICS_NOT_DISTANCE_ACCURACY",
                  frames_retained=3596, raw_samples_verified=24, diagnostic_raw_verified=1,
                  position_rows_recomputed=checked, ambiguous_frames_retained=3,
                  independent_stats_recomputed=True, source_hashes_unchanged=True,
                  physical_output=False, physical_position_accuracy_approved=False,
                  graphs_sha256={name:sha256(HERE / "analysis_r01" / name) for name in
                                 ("position_comparison.png", "position_time_series.png")},
                  verification_script_sha256=sha256(Path(__file__)))
    target.write_text(json.dumps(report, indent=2)+"\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
