"""Reproduce an ALL-frame review join without modifying historical labels.

Visual classifications in full_manual_review.csv were entered after inspecting
every old fully-labelled raw frame. This script cannot automate that judgement.
"""
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import sys

os.environ.setdefault("MPLCONFIGDIR", "/tmp/theta-occlusion-review-matplotlib")
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[2]
sys.path.insert(0, str(REPO / "src"))
from evaluate_reviewed_occlusion import join_reviews, review_summary

VARIANTS = ("baseline", "seeded_s130_nearest", "seeded_s130_bottom")
SESSION = "x0.0mz1.2m_shahei_20260826_140829_186"


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read(path):
    with path.open(newline="") as stream:
        return list(csv.DictReader(stream))


def write(path, rows):
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recording-root", type=Path, required=True)
    args = parser.parse_args()
    comparison = ROOT.parent / "box_contact_validation"
    old_validation = json.loads((comparison / "validation.json").read_text())
    evaluation = json.loads((comparison / "evaluation_provenance.json").read_text())
    labelled_path = comparison / "labelled_frames.csv"
    result_path = comparison / "spatial_occlusion/frame_results.csv"
    provenance_path = comparison / "spatial_occlusion/provenance.json"
    if sha256(labelled_path) != old_validation["inputs_sha256"]["labelled_frames.csv"]:
        raise ValueError("historical labelled result changed")
    for path in (result_path, provenance_path):
        if sha256(path) != evaluation["inputs_sha256"][str(path.resolve())]:
            raise ValueError(f"frozen comparison changed: {path}")
    if sha256(REPO / "src/offline_box_contact_candidates.py") != evaluation["candidate_implementation_sha256"]:
        raise ValueError("candidate implementation changed")
    provenance = json.loads(provenance_path.read_text())
    source = next(s for s in provenance["sources"] if s["session"] == SESSION)
    video = args.recording_root / SESSION / "raw.avi"
    if sha256(video) != source["sha256"]["raw.avi"]:
        raise ValueError("raw source video changed")
    manual = read(ROOT / "full_manual_review.csv")
    joined = join_reviews(manual, read(labelled_path), read(result_path), VARIANTS)
    ids = {int(r["frame_one_based"]) for r in manual}
    decoded_hashes = {}
    representative = 800
    capture = cv2.VideoCapture(str(video))
    raw = None
    try:
        for frame in range(1, max(ids) + 1):
            ok, decoded = capture.read()
            if not ok:
                raise ValueError("review frame outside raw video")
            if frame in ids:
                if decoded.shape != (720, 1280, 3):
                    raise ValueError("unexpected raw geometry")
                decoded_hashes[frame] = hashlib.sha256(decoded.tobytes()).hexdigest()
            if frame == representative:
                raw = decoded.copy()
    finally:
        capture.release()
    if raw is None or set(decoded_hashes) != ids:
        raise ValueError("incomplete source frame verification")
    for row in joined:
        row["decoded_bgr_pixels_sha256"] = decoded_hashes[int(row["frame"])]
        row["source_video_sha256"] = source["sha256"]["raw.avi"]
    phases, events = review_summary(joined, VARIANTS)
    write(ROOT / "full_reviewed_frames.csv", joined)
    write(ROOT / "full_review_phase_metrics.csv", phases)
    write(ROOT / "full_review_event_metrics.csv", events)
    asset = ROOT.parent / "report_assets/box_validation_partial_top_raw_frame_0800.png"
    if not cv2.imwrite(str(asset), raw) or not np.array_equal(cv2.imread(str(asset)), raw):
        raise ValueError("saved raw PNG pixels differ from source")
    reference_row = next(r for r in joined if r["variant"] == "baseline" and int(r["frame"]) == representative)
    write(ROOT / "full_review_raw_assets_manifest.csv", [dict(
        session=SESSION, frame_one_based=representative, time_sec=reference_row["time_sec"],
        raw_png=str(asset.relative_to(REPO)), raw_png_sha256=sha256(asset),
        source_video_sha256=source["sha256"]["raw.avi"],
        decoded_bgr_pixels_sha256=decoded_hashes[representative],
        width=1280, height=720, pixels_equal_original_decoded_frame=True)])
    selected_events = [r for r in events if r["variant"] == "baseline"]
    fig, ax = plt.subplots(figsize=(9, 5))
    xs = np.arange(len(selected_events))
    ax.bar(xs - .18, [r["reviewed_frames"] for r in selected_events], width=.34,
           color="#777777", label="Old label: fully occluded")
    ax.bar(xs + .18, [r["partial_occlusion_frames"] for r in selected_events], width=.34,
           color="#169a8d", label="Raw-frame review: partial occlusion")
    ax.set_xticks(xs, ["Event " + str(r["occlusion_event"]) for r in selected_events])
    ax.set_ylabel("Number of individually reviewed frames")
    ax.set_title("All 182 old fully-labelled frames reviewed independently of detections\n"
                 "Confirmed fully hidden frames: 0; full-occlusion performance NOT EVALUATED")
    ax.legend()
    ax.grid(axis="y", alpha=.25)
    fig.tight_layout()
    fig.savefig(ROOT / "full_review_label_coverage.png", dpi=140)
    plt.close(fig)
    inputs = [ROOT / "full_manual_review.csv", labelled_path, result_path, provenance_path,
              comparison / "evaluation_provenance.json", comparison / "validation.json",
              REPO / "src/evaluate_reviewed_occlusion.py", Path(__file__)]
    outputs = [ROOT / name for name in ("full_reviewed_frames.csv", "full_review_phase_metrics.csv",
               "full_review_event_metrics.csv", "full_review_raw_assets_manifest.csv", "full_review_label_coverage.png")]
    outputs.append(asset)
    (ROOT / "full_review_validation.json").write_text(json.dumps(dict(
        scope="ALL_OLD_FULLY_LABELLED_FRAMES_VISUALLY_REVIEWED_NOT_RUNTIME_ADOPTION",
        reviewed_source_frames=len(ids), joined_variant_rows=len(joined),
        review_method="whole_raw_frame_visual_review_independent_of_detection",
        phase_metrics=phases, event_metrics=events,
        fully_occluded_assessment={r["variant"]: r["assessment"] for r in phases
                                   if r["reviewed_phase"] == "fully_occluded"},
        frame_indexing="one-based manual/recorded frames; video index = frame - 1",
        unreviewed_old_fully_occluded_frames=0,
        other_video_phases_reviewed=False,
        frozen_candidate_unchanged=True, historical_labels_modified=False,
        runtime_changed=False, hardware_validation_performed=False,
        raw_png_pixels_match_original=True,
        source_video_sha256=source["sha256"]["raw.avi"],
        inputs_sha256={str(p.relative_to(REPO)): sha256(p) for p in inputs},
        outputs_sha256={str(p.relative_to(REPO)): sha256(p) for p in outputs}), indent=2) + "\n")
    print(f"Reviewed {len(ids)} source frames; full-occlusion assessment: "
          + str({r['variant']: r['assessment'] for r in phases if r['reviewed_phase'] == 'fully_occluded'}))


if __name__ == "__main__":
    main()
