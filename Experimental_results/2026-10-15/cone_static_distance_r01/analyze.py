"""Static bbox-to-floor diagnostics against nominal placement, no fitting/FFB."""
import json
import math
import os
from pathlib import Path
import sys

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "src"))
from cone_dataset import read_csv, sha256, write_csv
from cone_observation import ConeGroundProjector
from cone_video_readiness import summarize_stream


def distribution(values, prefix):
    if not values:
        return {prefix+suffix:None for suffix in ("_median", "_mean", "_std", "_p05", "_p95", "_min", "_max")}
    data = np.asarray(values, dtype=float)
    if not np.isfinite(data).all():
        raise ValueError("nonfinite measurement cannot enter statistics")
    return dict(zip((prefix+suffix for suffix in ("_median", "_mean", "_std", "_p05", "_p95", "_min", "_max")),
                    map(float, (np.median(data), np.mean(data), np.std(data),
                                np.percentile(data, 5), np.percentile(data, 95), min(data), max(data)))))


def main():
    output = HERE / "analysis_r01"
    if output.exists():
        raise ValueError("new analysis required; no output overwrite")
    intake = json.loads((HERE / "intake_summary.json").read_text())
    run = HERE / "inference_r01"
    provenance = json.loads((run / "provenance.json").read_text())
    if provenance["status"] != "COMPLETED_STATIC_CONE_INFERENCE_NOT_DISTANCE_OR_FFB_APPROVAL":
        raise ValueError("completed all-frame inference required")
    for file, digest in provenance["source_sha256"].items():
        if sha256(Path(file)) != digest:
            raise ValueError("inference source/code changed")
    raw_frames, raw_predictions = read_csv(run / "frames.csv"), read_csv(run / "predictions.csv")
    conditions = {row["session"]:row for row in read_csv(HERE / "session_conditions.csv")}
    frame_rows, decision_rows, summaries, zero_rows, hashes = [], [], [], [], {}
    for source in intake["inputs"]:
        root = Path(source["path"])
        condition = conditions[root.name]
        if any(sha256(root / file) != digest for file, digest in source["hashes"].items()):
            raise ValueError("received original session changed")
        projector = ConeGroundProjector(source["metadata"]["parameters"], width=1280, height=720,
                                        front_lens="left", confidence_threshold=intake["model"]["confidence"])
        frames = [r for r in raw_frames if r["session"] == root.name]
        predictions = [r for r in raw_predictions if r["session"] == root.name]
        counts, decisions, stream_summary, gaps = summarize_stream(frames, predictions, projector)
        by_frame = {}
        for row in decisions:
            by_frame.setdefault(int(row["frame"]), []).append(row)
        none = condition["condition"] == "none"
        ref_x = None if none else float(condition["reference_x_m"])
        ref_z = None if none else float(condition["reference_z_m"])
        reference_distance = None if none else math.hypot(ref_x, ref_z)
        current = []
        for frame in counts:
            row = dict(condition=condition["condition"], **frame, reference_x_m=ref_x, reference_z_m=ref_z,
                reference_radial_distance_m=reference_distance, measurement_used=False,
                measurement_reason="", prediction_index=None, confidence=None, x_m=None, z_m=None,
                radial_distance_m=None, error_x_m=None, error_z_m=None, radial_error_m=None,
                position_error_m=None, bbox_x1=None, bbox_y1=None, bbox_x2=None, bbox_y2=None,
                bottom_pixel_x=None, bottom_pixel_y=None, floor_contact_verified=False, usable_for_ffb=False)
            front = [p for p in by_frame.get(frame["frame"], []) if p["front_centre"]]
            if none:
                row["measurement_reason"] = "expected_no_cone" if not front else "unexpected_front_output_in_no_cone_capture"
            elif len(front) != 1:
                row["measurement_reason"] = "no_front_detection" if not front else "ambiguous_multiple_front_detections"
            elif not front[0]["projection_candidate"]:
                row["measurement_reason"] = front[0]["reason"]
            else:
                p = front[0]
                row.update(measurement_used=True, measurement_reason="single_unverified_bbox_floor_hypothesis",
                    prediction_index=p["prediction_index"], confidence=p["confidence"], x_m=p["x_m"], z_m=p["z_m"],
                    radial_distance_m=p["distance_m"], error_x_m=p["x_m"]-ref_x, error_z_m=p["z_m"]-ref_z,
                    radial_error_m=p["distance_m"]-reference_distance,
                    position_error_m=math.hypot(p["x_m"]-ref_x, p["z_m"]-ref_z),
                    bbox_x1=p["x1"], bbox_y1=p["y1"], bbox_x2=p["x2"], bbox_y2=p["y2"],
                    bottom_pixel_x=p["pixel_x"], bottom_pixel_y=p["pixel_y"])
            current.append(row)
        valid = [r for r in current if r["measurement_used"]]
        summary = dict(condition=condition["condition"], session=root.name, frames=len(current),
                       reference_x_m=ref_x, reference_z_m=ref_z, reference_radial_distance_m=reference_distance,
                       frames_with_front_output=sum(r["front_detections"] > 0 for r in current),
                       frames_with_multiple_front_output=sum(r["front_detections"] > 1 for r in current),
                       measurement_frames=len(valid), zero_front_frames=sum(r["front_detections"] == 0 for r in current),
                       projection_candidates=sum(r["projection_candidates"] for r in current),
                       reference_kind=condition["reference_kind"], floor_contact_verified=False, usable_for_ffb=False)
        for key in ("x_m", "z_m", "radial_distance_m", "error_x_m", "error_z_m", "radial_error_m",
                    "position_error_m", "bottom_pixel_x", "bottom_pixel_y", "confidence"):
            summary.update(distribution([r[key] for r in valid], key))
        summaries.append(summary)
        frame_rows.extend(current)
        decision_rows.extend(dict(condition=condition["condition"], **r) for r in decisions)
        zero_rows.extend(dict(condition=condition["condition"], **r) for r in gaps)
        for file, digest in source["hashes"].items():
            hashes[str(root / file)] = digest
    if len(frame_rows) != intake["total_frames"]:
        raise ValueError("every original frame must remain in position diagnostics")
    output.mkdir(exist_ok=False)
    write_csv(output / "positions.csv", frame_rows)
    write_csv(output / "summary.csv", summaries)
    write_csv(output / "projection_hypotheses.csv", decision_rows)
    write_csv(output / "zero_runs.csv", zero_rows)
    os.environ["MPLCONFIGDIR"] = str(output / "matplotlib_config")
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.5))
    central = sorted((r for r in summaries if r["condition"].startswith("center") and r["measurement_frames"]),
                     key=lambda r:r["reference_z_m"])
    if central:
        x = [r["reference_z_m"] for r in central]
        y = [r["z_m_median"] for r in central]
        axes[0].errorbar(x, y, yerr=[[r["z_m_median"]-r["z_m_p05"] for r in central],
                                   [r["z_m_p95"]-r["z_m_median"] for r in central]],
                         fmt="o-", capsize=4, label="bbox-floor median / p05-p95")
        upper = max(*x, *y)+.2
        axes[0].plot([0, upper], [0, upper], "k--", label="nominal reference")
    axes[0].set_xlabel("Nominal forward z (m)"); axes[0].set_ylabel("Projected forward z (m)")
    axes[0].set_title("Central positions / no calibration fit"); axes[0].legend(fontsize=8)
    for row in summaries:
        if not row["measurement_frames"]:
            continue
        axes[1].scatter(row["reference_x_m"], row["reference_z_m"], marker="x", color="black")
        axes[1].scatter(row["x_m_median"], row["z_m_median"], label=row["condition"])
        axes[1].plot([row["reference_x_m"], row["x_m_median"]], [row["reference_z_m"], row["z_m_median"]], alpha=.5)
    axes[1].set_xlabel("x right-positive (m)"); axes[1].set_ylabel("z forward-positive (m)")
    axes[1].set_title("Nominal reference crosses vs projected medians"); axes[1].legend(fontsize=8)
    fig.text(.5, .01, "One capture/condition; nominal label reference; base dimensions/placement uncertainty unspecified. NOT FFB approval.",
             ha="center", fontsize=8)
    fig.tight_layout(rect=(0,.06,1,1)); fig.savefig(output / "position_comparison.png", dpi=150); plt.close(fig)
    fig, axes = plt.subplots(2, 3, figsize=(12, 6))
    order = ("none", "center_080", "center_130", "center_200", "left_130", "right_130")
    for axis, key in zip(axes.flat, order):
        rows = [r for r in frame_rows if r["condition"] == key]
        if key == "none":
            axis.plot([r["time_sec"] for r in rows], [r["front_detections"] for r in rows])
            axis.set_ylabel("Front candidates"); axis.set_ylim(bottom=0, top=max(1,max(r["front_detections"] for r in rows)))
        else:
            axis.plot([r["time_sec"] for r in rows], [r["z_m"] if r["measurement_used"] else float("nan") for r in rows])
            axis.axhline(rows[0]["reference_z_m"], color="black", linestyle="--")
            axis.set_ylabel("Projected z (m)")
        axis.set_title(key); axis.set_xlabel("Recording time (s)")
    fig.tight_layout(); fig.savefig(output / "position_time_series.png", dpi=150); plt.close(fig)
    for path in (HERE / "intake_summary.json", HERE / "session_conditions.csv", run / "provenance.json",
                 run / "frames.csv", run / "predictions.csv", Path(__file__),
                 ROOT / "src/cone_observation.py", ROOT / "src/ground_contact.py"):
        hashes[str(path)] = sha256(path)
    result = dict(status="COMPLETED_STATIC_CONE_POSITION_DIAGNOSTICS_NOT_DEPLOYMENT_APPROVAL",
        source_sha256=hashes, frames=len(frame_rows), calibration_fitted=False, reference_user_note=intake["reference_user_note"],
        blue_box_corrections_used=False, confidence=intake["model"]["confidence"],
        floor_contact_verified=False, physical_output=False, adopted=False,
        limits=["Nominal x/z from labels; user confirms customary measurement; fine uncertainty/base dimensions unspecified.",
                "No bbox GT: front-output coverage is NOT per-object recall or all-frame precision.",
                "Only exactly one front bbox with a valid floor hypothesis enters position statistics; every missing/ambiguous frame retained.",
                "Reference radial distance is hypot(x,z), not forward z for lateral placements.",
                "One run per position; temporal spread is not independent-placement accuracy.",
                "No correction fitting, TTC, ROS or physical FFB output."])
    (output / "analysis_summary.json").write_text(json.dumps(result, indent=2)+"\n")
    print(json.dumps(summaries, indent=2))


if __name__ == "__main__":
    main()
