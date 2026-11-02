#!/usr/bin/env python3
"""Separate REAL incompatible-session replay from SYNTHETIC lifecycle success."""
import argparse
from collections import Counter
import csv
import importlib.util
import json
from pathlib import Path
import sys

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path[:0] = [str(ROOT/"src"), str(HERE)]
from angular_fisheye_geometry import project
from cone_distance_core import ConeDistanceEngine, DEFAULT_CONFIG, digest, load_config
from derive_fixed_floor_live_bundle import main as derive_main
from summarize_cone_distance_live import load_frames
from theta_rtc_frames import NativeFrame
from replay import run_case

REAL_INPUT = ROOT.parent/"recordings/2026-10-30/live_frame_evidence_r02_20261030_185348/distance_frames.jsonl"
MODELS = HERE.parent/"fixed_floor_derivation_r01/results_r02/prepared_floor.json"
BOARD_IMAGES = ROOT/"Experimental_results/2026-10-30/floor_board_pair_r01/originals"


def inventory():
    """Check known saved recording roots; do not rename/copy session identities."""
    model = json.loads(MODELS.read_text())
    target = model["session"]
    paths = sorted({p.resolve() for base in (ROOT/"recordings", ROOT.parent/"recordings")
                    if base.exists() for p in base.rglob("distance_frames.jsonl")})
    matches, inspected = [], []
    for path in paths:
        sessions = Counter()
        with path.open() as stream:
            for line in stream:
                row = json.loads(line)
                sessions[row["session"]] += 1
                if row["session"] == target:
                    matches.append(dict(path=str(path), frame=row["frame"]))
        inspected.append(dict(path=str(path), sha256=digest(path), sessions=dict(sessions)))
    images = []
    for path in sorted(BOARD_IMAGES.glob(f"decoded_{target}_f*.png")):
        images.append(dict(path=str(path), frame=int(path.stem.rsplit("_f", 1)[1]), sha256=digest(path)))
    last = max(r["frame"] for r in model["live_evidence"]["source_frames"])
    return dict(model_session=target, evidence_frames=[r["frame"] for r in model["live_evidence"]["source_frames"]],
        last_model_evidence_frame=last, unique_saved_image_frames=[r["frame"] for r in images], images=images,
        inspected_logs=inspected, matching_session_log_rows=len(matches),
        real_post_model_image_frames=[r["frame"] for r in images if r["frame"] > last],
        real_post_model_log_frames=[r["frame"] for r in matches if r["frame"] > last],
        existing_model_positive_time_series_available=bool(any(r["frame"] > last for r in matches)),
        no_other_session_model_transfer=True)


def synthetic_inputs(output):
    """New explicitly synthetic geometry; never relabel a real frame/session."""
    folder = output/"synthetic_inputs"
    folder.mkdir()
    settings, camera, _, _ = load_config()
    world = np.array([[0., 0, 0], [.296, 0, 0], [.296, .210, 0], [0, .210, 0]])
    rotation = np.array([[0., 0, 1], [-1., 0, 0], [0, -1., 0]])
    pixels, valid = project((world-[-.8, -.1, .575])@rotation, camera)
    if not valid.all():
        raise ValueError("synthetic grid outside camera model")
    board = np.zeros((720, 1280, 3), np.uint8)
    cv2.fillConvexPoly(board, np.rint(pixels).astype(np.int32), (255, 255, 255))
    session = "synthetic_lifecycle_only"
    png = folder/f"decoded_{session}_f000001.png"
    if not cv2.imwrite(str(png), board):
        raise ValueError("synthetic PNG save failed")
    spec = folder/"references.json"
    spec.write_text(json.dumps(dict(schema="native_floor_rectangles_v1", frames=[dict(file=png.name,
        sha256=digest(png), corners_native_xy=pixels.tolist(), side_lengths_mm=[296, 210],
        side_assignment="both", coordinates_source="synthetic projected rectangle; NOT real board evidence")]), indent=2)+"\n")
    derived = output/"synthetic_derived"
    derive_main(["--references", str(spec), "--image-dir", str(folder), "--board-thickness-mm", "15",
        "--external-height-mm", "590", "--board-on-floor", "--rigid-board", "--static-camera",
        "--output-dir", str(derived)])
    bad = folder/"deliberately_invalid_model.json"
    bad.write_text('{"negative_control":"intentionally not a model bundle"}\n')
    cone = np.zeros_like(board)
    cv2.fillPoly(cone, [np.array([[320, 310], [295, 400], [345, 400]], np.int32)], (0, 0, 255))
    empty = np.zeros_like(board)
    box = dict(x1=290., y1=305., x2=350., y2=405., confidence=.95, class_id=0)
    engine = ConeDistanceEngine(support_completion_shadow=True, frame_evidence=True)
    engine.reset(session)
    rows = []
    for number in range(1, 181):
        # A 600 ms processing stall is followed by a declared input pause.
        # Never fabricate back-in-time completion records or claim live FPS.
        t = 100.+number/30+(.6 if number >= 61 else 0.)
        absent = number == 1 or 35 <= number <= 44
        image = board if number == 1 else empty if absent else cone
        frame = NativeFrame(session, number, t, t, image)
        row = engine.measure(frame, [] if absent else [box], t+(.6 if number == 60 else .01))
        row.update(predict_ms=0., support_geometry_ms=600. if number == 60 else 10.,
                   cone_service_ms=600. if number == 60 else 10.,
                   inference_source="SYNTHETIC_injected_boxes_NOT_YOLO_or_camera")
        rows.append(row)
    schedule = [dict(after_frame=10, action="request"), dict(after_frame=70, action="disconnect"),
        dict(after_frame=85, action="request"), dict(after_frame=110, action="request", models=str(bad)),
        dict(after_frame=130, action="request"), dict(after_frame=160, action="disconnect")]
    with (folder/"distance_frames.jsonl").open("x") as stream:
        for row in rows:
            stream.write(json.dumps(row)+"\n")
    return rows, derived/"prepared_floor.json", folder, schedule


def plot(output, real, synthetic):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(3, 1, figsize=(11, 8))
    axes[0].step([r["frame"] for r in real], [int(r["comparison_available"]) for r in real], where="post")
    axes[0].set(title="REAL saved observations: wrong-session model rejected (no valid-distance claim)",
                xlabel="Original received frame ID", ylabel="Comparison available", ylim=(-.1, 1.1))
    axes[1].plot([r["frame"] for r in synthetic], [r["comparison_min_m"] if r["comparison_available"] else np.nan for r in synthetic], label="min unselected hypothesis")
    axes[1].plot([r["frame"] for r in synthetic], [r["comparison_max_m"] if r["comparison_available"] else np.nan for r in synthetic], label="max unselected hypothesis")
    axes[1].set(title="SYNTHETIC ONLY: conditional comparison span, NOT error or confidence interval",
                xlabel="Synthetic frame index", ylabel="Horizontal range (m)")
    axes[1].legend()
    states = {"waiting": 0, "loading": 1, "ready": 2, "active": 3, "rejected": 4}
    axes[2].step([r["frame"] for r in synthetic], [states[r["load_state"]] for r in synthetic], where="post")
    axes[2].set(xlabel="Synthetic frame index", ylabel="Loader state", yticks=list(states.values()), yticklabels=list(states))
    for axis in axes:
        axis.grid(alpha=.25)
    fig.tight_layout()
    fig.savefig(output/"lifecycle_timeline.png", dpi=130)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=False)
    coverage = inventory()
    (output/"data_inventory.json").write_text(json.dumps(coverage, indent=2)+"\n")
    rows, truncated, _ = load_frames(REAL_INPUT)
    if truncated:
        raise ValueError("complete input rows required")
    hashes = {str(p): digest(p) for p in (REAL_INPUT, MODELS, DEFAULT_CONFIG, Path(__file__).resolve(), HERE/"replay.py")}
    hashes.update({r["path"]: r["sha256"] for r in coverage["images"]})
    real_schedule = [dict(after_frame=rows[i]["frame"], action="request") for i in (10, 500, len(rows)-30)]
    real_rows, real_flat, real_summary = run_case(rows, MODELS, BOARD_IMAGES, output/"real_wrong_session",
        real_schedule, kind="REAL_saved_observations_NEGATIVE_wrong_session_ONLY")
    fake, fake_models, fake_images, fake_schedule = synthetic_inputs(output)
    synthetic_rows, synthetic_flat, synthetic_summary = run_case(fake, fake_models, fake_images, output/"synthetic_lifecycle",
        fake_schedule, kind="SYNTHETIC_ONLY_positive_lifecycle_NOT_real_camera")
    plot(output, real_flat, synthetic_flat)
    if any(digest(Path(p)) != h for p, h in hashes.items()):
        raise ValueError("original input/source bytes changed")
    summary = dict(status="PARTIAL_REAL_NEGATIVE_AND_SYNTHETIC_POSITIVE_NOT_REAL_POST_LOAD_VALIDATION",
        real=real_summary, synthetic=synthetic_summary,
        same_session_real_post_load_images=len(coverage["real_post_model_image_frames"]),
        same_session_real_post_load_log_rows=len(coverage["real_post_model_log_frames"]),
        real_model_positive_continuous_output_verified=False,
        original_source_sha256=hashes, physical_metric_verified=False, floor_contact_verified=False,
        usable_for_ffb=False, camera_gpu_ros_started=False, git_commit_or_push_performed=False)
    (output/"summary.json").write_text(json.dumps(summary, indent=2)+"\n")
    print(json.dumps(dict(status=summary["status"], real_rows=len(real_rows),
        real_comparison_rows=real_summary["comparison_available_rows"], synthetic_rows=len(synthetic_rows),
        synthetic_comparison_rows=synthetic_summary["comparison_available_rows"],
        real_post_load_images=summary["same_session_real_post_load_images"]), indent=2))


if __name__ == "__main__":
    main()
