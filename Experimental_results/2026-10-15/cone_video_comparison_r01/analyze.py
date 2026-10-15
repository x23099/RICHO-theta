"""Postprocess the frozen video run, preserving sparse-GT and floor limits."""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
import os
from pathlib import Path
import sys

import cv2

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "src"))
from cone_dataset import read_csv, sha256, write_csv
from cone_detection_diagnostics import aggregate
from cone_observation import ConeGroundProjector
from cone_video_readiness import summarize_stream
from run_cone_video import stats
from run_comparison import pinned_inputs


def numeric_prediction(row):
    result = dict(row, prediction_index=int(row["prediction_index"]), class_id=int(row["class_id"]))
    for key in ("confidence", "x1", "y1", "x2", "y2"):
        result[key] = float(row[key])
    return result


def export_raw_examples(output, selection, sessions):
    """Decode sequentially; save whole native frames, without overlays/crops."""
    manifest = []
    folder = output / "raw_examples"
    folder.mkdir()
    selected = defaultdict(dict)
    for item in selection:
        key = (item["session"], int(item["frame"]))
        if key[1] in selected[key[0]]:
            selected[key[0]][key[1]]["reason"] += "; " + item["reason"]
        else:
            selected[key[0]][key[1]] = dict(item)
    for session, by_frame in selected.items():
        path = Path(sessions[session]["path"])
        capture = cv2.VideoCapture(str(path / "raw.avi"))
        if not capture.isOpened():
            raise ValueError("cannot open raw source")
        try:
            for frame in range(1, max(by_frame)+1):
                ok, pixels = capture.read()
                if not ok or pixels.shape != (720, 1280, 3):
                    raise ValueError("source geometry/decode mismatch")
                if frame not in by_frame:
                    continue
                row = by_frame[frame]
                name = f"{session}_f{frame:06d}.png"
                target = folder / name
                if not cv2.imwrite(str(target), pixels):
                    raise ValueError("raw PNG export failed")
                digest = hashlib.sha256(pixels.tobytes()).hexdigest()
                if hashlib.sha256(cv2.imread(str(target)).tobytes()).hexdigest() != digest:
                    raise ValueError("saved PNG changed raw pixels")
                manifest.append(dict(file=f"raw_examples/{name}", session=session, frame=frame,
                    time_sec=row["time_sec"], reason=row["reason"], width=1280, height=720,
                    source_raw_sha256=sessions[session]["files_sha256"]["raw.avi"],
                    decoded_bgr_sha256=digest, png_sha256=sha256(target)))
        finally:
            capture.release()
    write_csv(output / "raw_example_manifest.csv", manifest)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    source, output = args.input_dir.resolve(), args.output_dir.resolve()
    if (output.exists() or source.is_relative_to(output) or output.is_relative_to(source)
            or not output.is_relative_to(ROOT / "Experimental_results/2026-10-15")):
        raise ValueError("new separate dated output required")
    provenance = json.loads((source / "comparison_provenance.json").read_text())
    if provenance["status"] != "COMPLETED_OFFLINE_VIDEO_COMPARISON_NOT_DEPLOYMENT":
        raise ValueError("completed frozen comparison required")
    for file, digest in provenance["source_sha256"].items():
        if sha256(Path(file)) != digest:
            raise ValueError("source input/model/conditions changed")
    (images, truths), _ = pinned_inputs()
    frozen = json.loads((HERE / "profiles.json").read_text())
    camera_path = ROOT / "Experimental_results/2026-10-12/cone_yolo_preparation/cone_capture_config.json"
    camera = json.loads(camera_path.read_text())
    anchor_by_frame = {(r["session"], int(r["frame"])): r for r in images}
    group_by_image = {r["image"]: ("b" if r["group_id"].startswith("block_b") else
                                   "d" if r["group_id"].startswith("block_d") else "e") for r in images}
    counts_all, decisions_all, summary_all, runs_all, metrics, reasons, matches, timing = [], [], [], [], [], [], [], []
    anchor_change_rows, source_hashes, sessions, review_candidates = [], {}, {}, []
    prior_metrics = read_csv(HERE.parent / "cone_ffb_readiness_r01/evaluation_r01/metrics.csv")
    for profile in frozen["profiles"]:
        name, threshold = profile["name"], profile["confidence"]
        run = source / name
        report = json.loads((run / "video_summary.json").read_text())
        if report["annotated_anchor_images"] != 78 or report["anchor_pixel_mismatches"]:
            raise ValueError("sparse anchor pixels not all verified")
        raw_frames, raw_predictions = read_csv(run / "frames.csv"), read_csv(run / "predictions.csv")
        projector = ConeGroundProjector(camera, width=1280, height=720, front_lens="left", confidence_threshold=threshold)
        counts, decisions, summaries, runs = summarize_stream(raw_frames, raw_predictions, projector)
        counts_all.extend(dict(profile=name, **r) for r in counts)
        decisions_all.extend(dict(profile=name, **r) for r in decisions)
        summary_all.extend(dict(profile=name, **r) for r in summaries)
        runs_all.extend(dict(profile=name, **r) for r in runs)
        reasons.extend(dict(profile=name, reason=reason, count=count)
                       for reason, count in Counter(r["reason"] for r in decisions).items())
        anchor_predictions = [dict(numeric_prediction(r), image=anchor_by_frame[(r["session"], int(r["frame"]))]["image"])
                              for r in raw_predictions if (r["session"], int(r["frame"])) in anchor_by_frame]
        for group in ("b", "d", "e"):
            ii = [r for r in images if group_by_image[r["image"]] == group]
            tt = [r for r in truths if group_by_image[r["image"]] == group]
            pp = [r for r in anchor_predictions if group_by_image[r["image"]] == group]
            for scope in ("all_view_detection", "front_centre_detection"):
                gt, predictions = tt, pp
                if scope == "front_centre_detection":
                    gt = [r for r in tt if projector.centre_in_front_lens(r)]
                    predictions = [r for r in pp if projector.centre_in_front_lens(r)]
                _, mm, totals, _ = aggregate(ii, gt, predictions, dict(confidence_thresholds=[threshold], match_iou=.5))
                metrics.append(dict(profile=name, set=group, scope=scope, **totals[0]))
                matches.extend(dict(profile=name, set=group, scope=scope, **r) for r in mm)
                old_model = "augmented_36" if name.startswith("augmented36") else "negative_52"
                old = next(r for r in prior_metrics if r["model"] == old_model and r["set"] == group
                           and r["scope"] == scope and float(r["confidence_threshold"]) == threshold)
                anchor_change_rows.append(dict(profile=name, set=group, scope=scope,
                    counts_match_previous=all(int(old[k]) == totals[0][k] for k in ("tp", "fp", "fn")),
                    previous_tp=int(old["tp"]), previous_fp=int(old["fp"]), previous_fn=int(old["fn"]),
                    current_tp=totals[0]["tp"], current_fp=totals[0]["fp"], current_fn=totals[0]["fn"]))
        for session in report["sessions"]:
            ff = [r for r in raw_frames if r["session"] == session["session"] and r["first_call"] == "0"]
            pipeline = stats([float(r["pipeline_ms"]) for r in ff])
            timing.append(dict(profile=name, session=session["session"], frames=session["frames"],
                               sequential_processing_fps=session["sequential_processing_fps"],
                               post_first_pipeline_p50_ms=pipeline["p50"], post_first_pipeline_p95_ms=pipeline["p95"],
                               post_first_pipeline_max_ms=pipeline["max"],
                               frames_over_33p3ms=sum(float(r["pipeline_ms"]) > 1000/30 for r in ff)))
        # Select unexpected-candidate examples from intended negative clips.
        negative_sessions = {r["session"] for r in images if "negative_" in r["session"]}
        suspects = [r for r in decisions if r["session"] in negative_sessions and r["front_centre"]]
        if suspects:
            worst = max(suspects, key=lambda r: r["confidence"])
            review_candidates.append(dict(session=worst["session"], frame=int(worst["frame"]), time_sec=worst["time_sec"],
                                          reason=f"{name}: highest-confidence front candidate in intended-negative clips; not automatic FP"))
        for prefix in ("cone_positive_eval_e03", "cone_train_block_b"):
            internal = [r for r in runs if r["scope"] == "front_centre" and r["bounded_by_detection"]
                        and r["session"].startswith(prefix)]
            if internal:
                longest = max(internal, key=lambda r: r["sample_span_sec"])
                frame = (longest["start_frame"]+longest["end_frame"])//2
                row = next(r for r in counts if r["session"] == longest["session"] and r["frame"] == frame)
                review_candidates.append(dict(session=row["session"], frame=frame, time_sec=row["time_sec"],
                    reason=f"{name}: midpoint of longest internal front-zero run; visibility not automatically classified"))
        for file in ("frames.csv", "predictions.csv", "video_summary.json", "anchor_pixels.csv", "conditions.json"):
            source_hashes[str(run / file)] = sha256(run / file)
    # Original sessions are preserved by the run's pre/post input hash checks.
    for row in read_csv(HERE / "video_plan.csv"):
        root = (HERE / row["session_dir"]).resolve()
        sessions[root.name] = dict(path=str(root), files_sha256={"raw.avi": sha256(root / "raw.avi")})
    source_hashes[str(source / "comparison_provenance.json")] = sha256(source / "comparison_provenance.json")
    source_hashes[str(camera_path)] = sha256(camera_path)
    source_hashes[str(Path(__file__))] = sha256(Path(__file__))
    source_hashes[str(ROOT / "src/cone_video_readiness.py")] = sha256(ROOT / "src/cone_video_readiness.py")
    output.mkdir(parents=True, exist_ok=False)
    for name, rows in (("frame_counts.csv", counts_all), ("projection_hypotheses.csv", decisions_all),
                       ("candidate_summary.csv", summary_all), ("zero_runs.csv", runs_all),
                       ("anchor_metrics.csv", metrics), ("anchor_matches.csv", matches),
                       ("reasons.csv", reasons), ("timing.csv", timing), ("anchor_reproduction.csv", anchor_change_rows)):
        write_csv(output / name, rows)
    # One stable-floor example, then up to three distinct diagnostic examples.
    e02 = next(r for r in counts_all if r["session"].startswith("cone_positive_eval_e02") and r["frame"] == 578)
    selection = [dict(session=e02["session"], frame=e02["frame"], time_sec=e02["time_sec"],
                      reason="E02 stationary reference image; floor/distance accuracy not automatically established")]
    seen = {(e02["session"], e02["frame"])}
    for row in sorted(review_candidates, key=lambda r: (
            "negative_" not in r["session"], not r["session"].startswith("cone_positive_eval_e03"))):
        key = (row["session"], int(row["frame"]))
        if key in seen:
            existing = next(r for r in selection if (r["session"], int(r["frame"])) == key)
            existing["reason"] += "; " + row["reason"]
        elif len(selection) < 4:
            selection.append(dict(row)); seen.add(key)
    export_raw_examples(output, selection, sessions)
    os.environ["MPLCONFIGDIR"] = str(output / "matplotlib_config")
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(2, 2, figsize=(12, 7))
    for index, prefix in enumerate(("cone_train_block_b", "cone_positive_eval_e02")):
        axis = axes[0, index]
        for profile in frozen["profiles"]:
            rows = [r for r in counts_all if r["profile"] == profile["name"] and r["session"].startswith(prefix)]
            axis.step([float(r["time_sec"]) for r in rows], [r["front_detections"] for r in rows],
                      where="post", label=profile["name"], alpha=.8)
        axis.set_title("B moving / front candidates" if index == 0 else "E02 stationary / front candidates")
        axis.set_xlabel("Recording time (s)"); axis.set_ylabel("Candidates, not visible GT"); axis.legend(fontsize=8)
    groups = ("cone_negative_train_d01", "cone_negative_train_d02", "cone_negative_eval_e01")
    for i, profile in enumerate(frozen["profiles"]):
        selected = [next(r for r in summary_all if r["profile"] == profile["name"]
                         and r["scope"] == "front_centre" and r["session"].startswith(prefix)) for prefix in groups]
        axes[1, 0].bar([j+(i-.5)*.35 for j in range(3)], [r["frames_with_candidates"] for r in selected], .35, label=profile["name"])
    axes[1, 0].set_xticks(range(3), ("D01", "D02", "E01")); axes[1, 0].set_ylabel("Frames with front output, NOT all-frame FP GT")
    axes[1, 0].legend(fontsize=8); axes[1, 0].set_title("Intended-negative clips / D reused in 52 training")
    for profile in frozen["profiles"]:
        rows = [r for r in timing if r["profile"] == profile["name"]]
        axes[1, 1].plot(range(7), [r["post_first_pipeline_p95_ms"] for r in rows], marker="o", label=profile["name"])
    axes[1, 1].axhline(1000/30, color="black", linestyle="--", label="33.3 ms reference")
    axes[1, 1].set_xticks(range(7), ("B+", "B-red", "D01", "D02", "E01", "E02", "E03"))
    axes[1, 1].set_ylabel("Offline pipeline p95 (ms)"); axes[1, 1].set_title("Not live camera/ROS/FFB latency"); axes[1, 1].legend(fontsize=8)
    fig.tight_layout(); fig.savefig(output / "video_readiness_comparison.png", dpi=150); plt.close(fig)
    summary = dict(status="COMPLETED_OFFLINE_TEMPORAL_DIAGNOSTICS_NOT_DEPLOYMENT", physical_output=False,
                   adopted=False, floor_contact_verified=False, source_sha256=source_hashes,
                   frames_per_profile=11397, sparse_anchors_per_profile=78,
                   all_anchor_counts_match_previous=all(r["counts_match_previous"] for r in anchor_change_rows),
                   graph_sha256=sha256(output / "video_readiness_comparison.png"),
                   limitations=["Full video candidate coverage is not target recall or all-frame FP precision.",
                                "D/E negative truth is human-confirmed on sparse anchor frames only.",
                                "B labels include legacy assistant visual review; not new human GT.",
                                "D is training reuse for negative52; all clips are development, not blind test.",
                                "No persistent target identity or real-world distance GT.",
                                "Offline timing does not include camera buffering, GUI, ROS, relay, or hardware."])
    (output / "analysis_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(dict(status=summary["status"], anchor_reproduced=summary["all_anchor_counts_match_previous"],
                          output=str(output)), indent=2))


if __name__ == "__main__":
    main()
