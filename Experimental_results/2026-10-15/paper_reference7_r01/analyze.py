"""Seven paper poses: frozen visual windows, existing corner reader, offline only."""
from collections import Counter
import importlib.util
import json
import os
from pathlib import Path
import sys

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT/"src"))
sys.path.insert(0, str(HERE.parent/"cone_geometry_candidates_r01"))
from cone_dataset import read_csv, sha256, write_csv
from cone_observation import CAMERA_KEYS
from geometry_models import fit_model, project_floor_to_pixels, project_pixels_to_floor

HELPER = HERE.parent/"white_paper_visibility_r01/analyze.py"
spec = importlib.util.spec_from_file_location("previous_paper_reader", HELPER)
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)

THRESHOLDS = (140, 170, 200)
PRIMARY = 170
POSES = [
    ("C080", 1, 15, (300,385,100,65), 0., .8, "diagnostic"),
    ("C130", 27, 34, (300,370,80,45), 0., 1.3, "diagnostic"),
    ("C200", 46, 51, (300,355,65,35), 0., 2., "diagnostic"),
    ("L130", 126, 130, (247,370,75,45), -.4, 1.3, "diagnostic"),
    ("R130", 146, 151, (338,365,85,45), .4, 1.3, "diagnostic"),
    ("H100", 205, 209, (300,380,90,50), 0., 1., "held_out_from_future_fit"),
    ("H160", 231, 238, (300,362,70,40), 0., 1.6, "held_out_from_future_fit"),
    ("right_preliminary", 104, 108, (338,365,85,45), None, None, "unassigned_no_fit"),
]


def metric_rows(points, model_name, parameters):
    records = []
    for row in points:
        world = np.array([[row["reference_x_m"], row["reference_z_m"]]])
        pixels = np.array([[row["pixel_x"], row["pixel_y"]]])
        pixel_delta = project_floor_to_pixels(world, parameters)[0]-pixels[0]
        floor = project_pixels_to_floor(pixels, parameters)[0]
        delta = floor-world[0]
        records.append(dict(point_id=row["point_id"], role=row["role"], model=model_name,
            reference_x_m=world[0,0], reference_z_m=world[0,1], pixel_x=pixels[0,0], pixel_y=pixels[0,1],
            projected_x_m=floor[0], projected_z_m=floor[1], error_x_m=delta[0], error_z_m=delta[1],
            error_norm_m=float(np.linalg.norm(delta)), pixel_error_norm=float(np.linalg.norm(pixel_delta)),
            usable_for_ffb=False))
    return records


def main():
    output = HERE/"analysis_r01"
    if output.exists():
        raise ValueError("new output directory required, no overwrite")
    intake = json.loads((HERE/"intake_summary.json").read_text())
    session = Path(intake["session"])
    sources = dict(intake["source_sha256"])
    paths = [Path(__file__), HERE/"method.md", HERE/"intake_summary.json", HELPER,
        HERE.parent/"cone_geometry_candidates_r01/geometry_models.py", ROOT/"src/ground_contact.py"]
    for name in ("raw_sample_manifest.csv", "interval_review_manifest.csv"):
        paths.append(HERE/name)
        paths.extend(HERE/r["file"] for r in read_csv(HERE/name))
    sources.update({str(path): sha256(path) for path in paths})
    assert all(sha256(Path(path)) == digest for path, digest in sources.items())
    frames = read_csv(session/"detections.csv")
    ledger, observations = [], []
    capture = cv2.VideoCapture(str(session/"raw.avi"))
    try:
        for source in frames:
            ok, raw = capture.read()
            if not ok or raw.shape != (720,1280,3):
                raise ValueError("native input mismatch")
            t = float(source["time_sec"])
            matches = [p for p in POSES if p[1] <= t <= p[2]]
            assert len(matches) <= 1
            phase = matches[0][0] if matches else ("paper_absent_end" if 249 <= t <= 256
                                                    else "other_transition_handling_or_unused")
            ledger.append(dict(frame=source["frame"], time_sec=t, phase=phase))
            if not matches:
                continue
            pose = matches[0]
            for threshold in THRESHOLDS:
                observation = helper.paper_corner(raw, threshold, roi=pose[3])
                observations.append(dict(frame=source["frame"], time_sec=t, phase=phase,
                    threshold=threshold, role=pose[6], **observation))
            if int(source["frame"]) % 1000 == 0:
                print(f"Decoded {source['frame']}/{len(frames)}", flush=True)
        if capture.read()[0]:
            raise ValueError("extra raw frames")
    finally:
        capture.release()
    stats, points = [], []
    for pose in POSES:
        for threshold in THRESHOLDS:
            group = [r for r in observations if r["phase"] == pose[0] and r["threshold"] == threshold]
            accepted = [r for r in group if r["corner_candidate"]]
            record = dict(point_id=pose[0], role=pose[6], threshold=threshold, start_sec=pose[1],
                end_sec=pose[2], frames=len(group), candidate_frames=len(accepted),
                failure_counts_json=json.dumps(dict(Counter(r["reason"] for r in group if not r["corner_candidate"]))),
                reference_x_m=pose[4], reference_z_m=pose[5], physical_corner_verified=False, usable_for_ffb=False)
            for axis in ("x", "y"):
                values = [r["pixel_"+axis] for r in accepted]
                record["pixel_"+axis] = float(np.median(values)) if values else None
                record["pixel_"+axis+"_min"] = min(values, default=None)
                record["pixel_"+axis+"_max"] = max(values, default=None)
            stats.append(record)
            if threshold == PRIMARY and pose[4] is not None and accepted:
                points.append(record.copy())
    base58 = {k:intake["metadata"]["parameters"][k] for k in CAMERA_KEYS}
    base59 = dict(base58, camera_height=.59)
    metrics, fitted = [], None
    if len(points) == 7:
        metrics.extend(metric_rows(points, "recorded_h58", base58))
        metrics.extend(metric_rows(points, "height_only_h59", base59))
        train = [r for r in points if r["role"] == "diagnostic"]
        assert {r["point_id"] for r in train} == {"C080","C130","C200","L130","R130"}
        fitted = fit_model(train, base59, "centre2")
        # This generic helper's original docstring referred to the earlier V-tip data;
        # current provenance explicitly describes paper-based, offline observations.
        fitted["interpretation"] = "offline paper near-left corner candidate; not physical intrinsics/pose or runtime approval"
        metrics.extend(metric_rows(points, "paper_centre2_candidate", fitted["parameters"]))
    summaries = []
    for model in sorted({r["model"] for r in metrics}):
        for role in ("diagnostic", "held_out_from_future_fit"):
            selected = [r for r in metrics if r["model"] == model and r["role"] == role]
            summaries.append(dict(model=model, role=role, points=len(selected),
                floor_point_rmse_m=float(np.sqrt(np.mean([r["error_norm_m"]**2 for r in selected]))),
                max_floor_error_m=max(r["error_norm_m"] for r in selected),
                pixel_point_rmse=float(np.sqrt(np.mean([r["pixel_error_norm"]**2 for r in selected])))))
    output.mkdir()
    write_csv(output/"frame_ledger.csv", ledger)
    write_csv(output/"corner_candidates.csv", observations)
    write_csv(output/"threshold_summary.csv", stats)
    write_csv(output/"reference_points_primary170.csv", points)
    write_csv(output/"projection_comparison.csv", metrics)
    write_csv(output/"projection_summary.csv", summaries)
    if fitted:
        (output/"centre2_offline_candidate.json").write_text(json.dumps(fitted, indent=2)+"\n")
    plot(observations, metrics, output)
    assert all(sha256(Path(path)) == digest for path, digest in sources.items())
    result = dict(status="COMPLETED_PAPER7_OFFLINE_AUDIT_NOT_RUNTIME_CALIBRATION_APPROVAL",
        source_sha256=sources, total_frames=len(ledger), phase_counts=dict(Counter(r["phase"] for r in ledger)),
        evaluated_corner_rows=len(observations), reference_points=len(points), primary_threshold=PRIMARY,
        threshold_selected_by_metric_error=False, holdouts_in_solver=False, fitted=bool(fitted),
        physical_output=False, production_settings_changed=False, usable_for_ffb=False,
        scope="native seven-pose visibility and provisional same-recording geometry comparison",
        output_sha256={p.name:sha256(p) for p in output.iterdir() if p.is_file()})
    (output/"provenance.json").write_text(json.dumps(result, indent=2)+"\n")
    print(json.dumps(dict(stats=stats, model_summaries=summaries), indent=2))


def plot(observations, metrics, output):
    os.environ.setdefault("MPLCONFIGDIR", "/tmp/paper7_matplotlib")
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(2,1,figsize=(11,6),sharex=True,layout="constrained")
    for threshold in THRESHOLDS:
        accepted = [r for r in observations if r["threshold"] == threshold and r["corner_candidate"]]
        for axis, name in zip(axes,("x","y")):
            axis.plot([r["time_sec"] for r in accepted], [r["pixel_"+name] for r in accepted], ".", ms=2,
                label=f"gray >= {threshold}")
            axis.set_ylabel(f"near-left {name} [native px]")
            axis.grid(alpha=.3)
    for pose in POSES:
        axes[0].text((pose[1]+pose[2])/2, 1.02, pose[0], transform=axes[0].get_xaxis_transform(),
                     ha="center", fontsize=8, rotation=40)
    axes[0].legend(loc="lower left")
    axes[-1].set_xlabel("Recording elapsed time [s]; gaps are retained in frame_ledger.csv")
    fig.savefig(output/"paper_corner_timeline.png",dpi=150)
    plt.close(fig)
    if not metrics:
        return
    fig, ax = plt.subplots(figsize=(10,4), layout="constrained")
    ids = [p[0] for p in POSES[:7]]
    models = list(dict.fromkeys(r["model"] for r in metrics))
    x = np.arange(len(ids))
    for i, model in enumerate(models):
        values = [next(r["error_norm_m"] for r in metrics if r["model"]==model and r["point_id"]==key) for key in ids]
        ax.bar(x+(i-(len(models)-1)/2)*.24,values,.24,label=model)
    ax.set_xticks(x, ids)
    ax.axvline(4.5,color="gray",ls="--")
    ax.set_ylabel("Floor error to nominal paper corner [m]")
    ax.set_title("Same recording only; H100/H160 not fitted; NOT runtime approval")
    ax.grid(axis="y",alpha=.3)
    ax.legend()
    fig.savefig(output/"projection_comparison.png",dpi=150)
    plt.close(fig)


if __name__ == "__main__":
    main()
