"""Join human-reviewed frames to frozen detections, verifying original video pixels.

Selection is the 13 S130 detections inside old fully_occluded labels, NOT an
unbiased re-labelling of all 182 frames. Never rewrite historical phase labels.
"""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import sys

import cv2

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[2]
sys.path.insert(0, str(REPO / "src"))
from evaluate_raw_velocity_confidence_replay import sha256
from evaluate_velocity_confidence_replay import write_csv


def read(path):
    with path.open(newline="") as stream:
        return list(csv.DictReader(stream))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recording-root", type=Path, required=True)
    args = parser.parse_args()
    comparison = ROOT.parent / "box_contact_validation"
    session = "x0.0mz1.2m_shahei_20260826_140829_186"
    provenance = json.loads((comparison / "spatial_occlusion/provenance.json").read_text())
    source = next(s for s in provenance["sources"] if s["session"] == session)
    video = args.recording_root / session / "raw.avi"
    if sha256(video) != source["sha256"]["raw.avi"]:
        raise ValueError("source video changed")
    labelled = read(comparison / "labelled_frames.csv")
    expected = {int(r["frame"]) for r in labelled if r["session"] == session and r["variant"] == "seeded_s130_bottom"
                and r["phase_label"] == "fully_occluded" and r["detected"] == "1"}
    manual = read(ROOT / "manual_review.csv")
    ids = [int(r["frame_one_based"]) for r in manual]
    if len(set(ids)) != len(ids) or set(ids) != expected:
        raise ValueError("review must cover exactly the selected frozen detections once")
    frame_rows = read(comparison / "spatial_occlusion/frame_results.csv")
    lookup = {(r["variant"], int(r["frame"])): r for r in frame_rows if r["session"] == session}
    decoded_hashes = {}
    capture = cv2.VideoCapture(str(video))
    try:
        for frame in range(1, max(ids) + 1):
            ok, decoded = capture.read()
            if not ok:
                raise ValueError("frame outside video")
            if frame in expected:
                if decoded.shape != (720, 1280, 3):
                    raise ValueError("unexpected raw geometry")
                decoded_hashes[frame] = hashlib.sha256(decoded.tobytes()).hexdigest()
    finally:
        capture.release()
    results = []
    for review in manual:
        frame = int(review["frame_one_based"])
        row = lookup["seeded_s130_bottom", frame]
        nearest = lookup["seeded_s130_nearest", frame]
        if any(row[k] != nearest[k] for k in ("bbox_x", "bbox_y", "bbox_width", "bbox_height", "measurement_accepted")):
            raise ValueError("candidate regions differ; cannot share visual review")
        results.append(dict(session=session, **review, original_phase="fully_occluded", time_sec=row["time_sec"],
                            baseline_detected=lookup["baseline", frame]["detected"], candidate_detected=row["detected"],
                            candidate_measurement_accepted=row["measurement_accepted"], rejection_reason=row["rejection_reason"],
                            bbox_x=row["bbox_x"], bbox_y=row["bbox_y"], bbox_width=row["bbox_width"], bbox_height=row["bbox_height"],
                            decoded_bgr_pixels_sha256=decoded_hashes[frame], source_video_sha256=source["sha256"]["raw.avi"]))
    write_csv(ROOT / "reviewed_detections.csv", results)
    inputs = [ROOT / "manual_review.csv", Path(__file__), comparison / "labelled_frames.csv",
              comparison / "spatial_occlusion/frame_results.csv", comparison / "spatial_occlusion/provenance.json"]
    (ROOT / "validation.json").write_text(json.dumps({
        "scope": "SELECTED_FRAME_VISUAL_REVIEW_NOT_GLOBAL_FALSE_POSITIVE_EVALUATION",
        "reviewed_frames": len(results), "candidate_regions_equal": True,
        "partially_visible_box_frames": sum(r["reviewed_phase"] == "partial_occlusion" for r in results),
        "accepted_reviewed_frames": sum(r["candidate_measurement_accepted"] == "1" for r in results),
        "unreviewed_old_fully_occluded_frames": 182 - len(results),
        "historical_labels_modified": False, "runtime_changed": False,
        "inputs_sha256": {str(p.resolve()): sha256(p) for p in inputs},
        "output_sha256": sha256(ROOT / "reviewed_detections.csv")}, indent=2) + "\n")
    print(f"Joined {len(results)} reviewed detections; historical labels and runtime unchanged.")


if __name__ == "__main__":
    main()
