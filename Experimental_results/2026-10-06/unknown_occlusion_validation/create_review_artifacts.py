"""Join frozen visual labels to offline results; never generate visual labels.

The reviewed windows are selected examples, not independent/random holdout.
No ROS publication, hardware action, detector or calibration tuning occurs.
"""
import argparse
from collections import Counter
import csv
import hashlib
import json
import os
from pathlib import Path
import sys

os.environ.setdefault("MPLCONFIGDIR", "/tmp/theta-unknown-review-matplotlib")
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[2]
sys.path.insert(0, str(REPO / "src"))
from evaluate_reviewed_occlusion import flag, phase_metrics

PHASES = ("visible", "partial_occlusion", "fully_occluded", "uncertain")


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


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session-dir", type=Path, required=True)
    parser.add_argument("--reviewed-png-dir", type=Path, required=True)
    args = parser.parse_args()
    protocol = json.loads((ROOT / "review_protocol.json").read_text())
    require(sha256(ROOT / "manual_review.csv") == protocol["manual_review_sha256"],
            "manual labels changed after pre-comparison freeze")
    provenance_path = ROOT / "video_comparison/provenance.json"
    provenance = json.loads(provenance_path.read_text())
    variants = protocol["variants"]
    require(provenance["variants"] == variants, "variant mismatch")
    require(len(provenance["sources"]) == 1, "unexpected sources")
    source = provenance["sources"][0]
    require(args.session_dir.name == source["session"] == protocol["session"], "session mismatch")
    for name, digest in source["sha256"].items():
        require(sha256(args.session_dir / name) == digest, "source changed: " + name)
    for name, digest in provenance["implementation_sha256"].items():
        require(sha256(REPO / "src" / name) == digest, "comparison code changed: " + name)
    require(sha256(REPO / "src/bird_eye_config_ttc_v12_ffb_reliability_20260929.json") ==
            provenance["detector_config_sha256"], "detector config changed")
    frozen = json.loads((ROOT.parent / "box_contact_candidates/provenance.json").read_text())
    require(frozen["settings"] == provenance["settings"], "candidate settings changed")
    require(frozen["implementation_sha256"]["offline_box_contact_candidates.py"] ==
            provenance["implementation_sha256"]["offline_box_contact_candidates.py"], "candidate changed")
    expected = {n for start, end in protocol["windows_one_based"] for n in range(start, end + 1)}
    manual_rows = read(ROOT / "manual_review.csv")
    manual = {int(r["frame_one_based"]): r for r in manual_rows}
    require(len(manual) == len(manual_rows) == protocol["reviewed_frames"], "duplicate/missing manual row")
    require(set(manual) == expected, "incomplete visual window coverage")
    for n, row in manual.items():
        require(row["session"] == source["session"] and row["reviewed_phase"] in PHASES and
                row["review_method"] == "whole_raw_frame_visual_review" and row["visible_evidence"],
                "invalid independent visual review")
        require(row["selection_window"] == ("window_1" if n <= 985 else "window_2"), "window mismatch")
    live = read(args.session_dir / "detections.csv")
    require([int(r["frame"]) for r in live] == list(range(1, len(live) + 1)), "source frame discontinuity")
    results = read(ROOT / "video_comparison/frame_results.csv")
    lookup = {(r["variant"], int(r["frame"])): r for r in results}
    require(len(lookup) == len(results) == len(live) * len(variants), "comparison duplicate/missing rows")
    require(set(lookup) == {(v, n) for v in variants for n in range(1, len(live) + 1)}, "variant coverage mismatch")
    for (variant, n), row in lookup.items():
        require(row["session"] == source["session"] and
                float(row["time_sec"]) == float(live[n - 1]["time_sec"]) and
                float(row["monotonic_time_sec"]) == float(live[n - 1]["monotonic_time_sec"]), "clock/source mismatch")
        require(not flag(row, "measurement_accepted") or flag(row, "detected"), "accepted without detection")
    pixels, representatives = {}, {}
    capture = cv2.VideoCapture(str(args.session_dir / "raw.avi"))
    try:
        for n in range(1, max(expected) + 1):
            ok, frame = capture.read()
            require(ok, "short video")
            if n not in expected:
                continue
            require(frame.shape == (720, 1280, 3), "unexpected raw frame geometry")
            reviewed = cv2.imread(str(args.reviewed_png_dir / f"v11_raw_frame_{n:04d}.png"))
            require(reviewed is not None and np.array_equal(frame, reviewed), "viewed PNG differs from source")
            pixels[n] = hashlib.sha256(frame.tobytes()).hexdigest()
            if n in (963, 1120):
                representatives[n] = frame.copy()
    finally:
        capture.release()
    joined = []
    for n in sorted(expected):
        for variant in variants:
            row = dict(lookup[variant, n])
            row.update({k: v for k, v in manual[n].items() if k != "frame_one_based"})
            row.update(video_index_zero_based=n - 1, decoded_bgr_pixels_sha256=pixels[n],
                       source_video_sha256=source["sha256"]["raw.avi"])
            joined.append(row)
    metrics = [phase_metrics(joined, v, phase) for v in variants for phase in PHASES]
    write(ROOT / "reviewed_frames.csv", joined)
    write(ROOT / "phase_metrics.csv", metrics)
    counts = Counter(r["reviewed_phase"] for r in manual_rows)
    assets = []
    for n, frame in representatives.items():
        path = ROOT.parent / "report_assets" / f"unknown_review_v11_raw_frame_{n:04d}.png"
        require(cv2.imwrite(str(path), frame) and np.array_equal(cv2.imread(str(path)), frame), "raw PNG write mismatch")
        assets.append(dict(session=source["session"], frame_one_based=n,
                           time_sec=live[n - 1]["time_sec"], reviewed_phase=manual[n]["reviewed_phase"],
                           raw_png=str(path.relative_to(REPO)), png_sha256=sha256(path),
                           decoded_bgr_pixels_sha256=pixels[n], source_video_sha256=source["sha256"]["raw.avi"],
                           width=1280, height=720, pixels_equal_original_decoded_frame=True))
    write(ROOT / "raw_assets_manifest.csv", assets)
    colors = ["#5084be", "#169a8d", "#aa4371", "#9b9b9b"]
    fig, ax = plt.subplots(figsize=(9, 4))
    ax.bar(PHASES, [counts[p] for p in PHASES], color=colors)
    ax.set_ylabel("Individually reviewed raw frames")
    ax.set_title("Selected historical UNKNOWN windows: 107 frames\n"
                 "Only 4 confirmed fully hidden frames; long-occlusion response NOT CERTIFIED")
    ax.grid(axis="y", alpha=.25)
    fig.tight_layout()
    fig.savefig(ROOT / "visual_review_coverage.png", dpi=140)
    plt.close(fig)
    full = sorted(n for n, r in manual.items() if r["reviewed_phase"] == "fully_occluded")
    inputs = [ROOT / "manual_review.csv", ROOT / "review_protocol.json", provenance_path,
              ROOT / "video_comparison/frame_results.csv", ROOT.parent / "box_contact_candidates/provenance.json",
              REPO / "src/evaluate_reviewed_occlusion.py", Path(__file__)]
    outputs = [ROOT / n for n in ("reviewed_frames.csv", "phase_metrics.csv", "raw_assets_manifest.csv", "visual_review_coverage.png")]
    summary = dict(scope=protocol["scope"], source=source, variants=variants, full_video_frames=len(live),
                   comparison_rows=len(results), reviewed_frames=len(manual), joined_review_rows=len(joined),
                   phase_counts=dict(counts), phase_metrics=metrics,
                   confirmed_fully_hidden_frames=full,
                   fully_hidden_timestamp_span_sec=float(live[full[-1] - 1]["time_sec"]) - float(live[full[0] - 1]["time_sec"]) if full else None,
                   loss_recovery_delay_assessment="NOT_EVALUATED_SHORT_VISUAL_WINDOW",
                   png_pixels_checked_frames=len(pixels), physical_ffb_tested=False,
                   inputs_sha256={str(p.relative_to(REPO)): sha256(p) for p in inputs},
                   outputs_sha256={str(p.relative_to(REPO)): sha256(p) for p in outputs},
                   limitations=protocol["limits"])
    (ROOT / "review_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({k: summary[k] for k in ("full_video_frames", "comparison_rows", "reviewed_frames", "phase_counts", "fully_hidden_timestamp_span_sec")}, indent=2))


if __name__ == "__main__":
    main()
