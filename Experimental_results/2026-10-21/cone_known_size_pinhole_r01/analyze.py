"""Replay known-size hypotheses on frozen pixels; no fitting or live output."""
from collections import Counter, defaultdict
import importlib.util
import json
import os
from pathlib import Path
import sys

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
DAY19 = ROOT/"Experimental_results/2026-10-19"
for path in (ROOT/"src", DAY19/"cone_distance_methods_r01", DAY19/"cone_virtual_pinhole_r01"):
    sys.path.insert(0, str(path))
from cone_dataset import read_csv, sha256, write_csv
from cone_observation import ConeGroundProjector
from fisheye_floor_geometry import legacy_front_diagnostic_geometry
from virtual_pinhole import floor_intersections
from known_width import (BASE_SIDE_M, VIRTUAL_K, envelope_endpoints, estimate_native_span,
                         pinhole_width_position, raw_to_rectified, empty)

spec = importlib.util.spec_from_file_location("frozen_width_input_ledger", DAY19/"cone_distance_methods_r01/analyze.py")
old = importlib.util.module_from_spec(spec)
spec.loader.exec_module(old)


def key(row):
    return row["dataset"], row["session"], int(row["frame"])


def red_envelope(image):
    x, y, w, h = 285, 290, 65, 95  # previously frozen known-target diagnostic ROI
    hsv = cv2.cvtColor(image[y:y+h, x:x+w], cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, (0, 80, 30), (10, 255, 255)) | cv2.inRange(hsv, (170, 80, 30), (179, 255, 255))
    contours = sorted((c for c in cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)[0]
                       if cv2.contourArea(c) >= 20), key=cv2.contourArea, reverse=True)
    if not contours:
        return None, "no_red_component"
    if len(contours) > 1 and cv2.contourArea(contours[1]) >= .25*cv2.contourArea(contours[0]):
        return None, "ambiguous_red_components"
    bx, by, bw, bh = cv2.boundingRect(contours[0])
    if bx == 0 or by == 0 or bx+bw >= w or by+bh >= h:
        return None, "roi_edge_truncation"
    if bw < 5 or bh < 8:
        return None, "insufficient_red_extent"
    points = contours[0][:, 0, :]+[x, y]
    columns = np.array([(v, max(points[points[:, 0] == v, 1])) for v in np.unique(points[:, 0])])
    if len(columns) < 8:
        return None, "insufficient_envelope"
    return columns, "known_red_roi_NOT_YOLO"


def additional_recording():
    folder = DAY19/"paper_cone_2m_validation_r01"
    intake = json.loads((folder/"intake_summary.json").read_text())
    session = Path(intake["session"])
    quality = {int(r["frame"]):r for r in read_csv(folder/"analysis_r01/support_quality.csv")}
    frames = read_csv(session/"detections.csv")
    cap = cv2.VideoCapture(str(session/"raw.avi"))
    ledger, endpoints, points = [], {}, []
    try:
        for source in frames:
            ok, image = cap.read()
            if not ok or image.shape != (720, 1280, 3):
                raise ValueError("native raw/CSV mismatch")
            frame, t = int(source["frame"]), float(source["time_sec"])
            phase = quality[frame]["phase"]
            row = dict(dataset="paper_cone_20261019", session=session.name, frame=frame, time_sec=t, condition=phase,
                       reference_x_m=0. if phase == "cone_static" else None,
                       reference_z_m=2. if phase == "cone_static" else None,
                       quality_accepted=quality[frame]["quality_accepted"] == "True")
            envelope, reason = red_envelope(image)
            if envelope is not None:
                endpoints[key(row)] = envelope_endpoints(envelope)
                points.extend(dict(dataset=row["dataset"], session=session.name, frame=frame, x=int(x), y=int(y)) for x, y in envelope)
            row["envelope_reason"] = reason
            ledger.append(row)
        if cap.read()[0]:
            raise ValueError("extra raw frames")
    finally:
        cap.release()
    return ledger, endpoints, points, intake["source_sha256"]


def replay(ledger, endpoints, candidates, geometries):
    records = []
    for source in ledger:
        row_key = key(source)
        env = endpoints.get(row_key)
        boxes = candidates.get(row_key, [])
        for model, parameters in geometries.items():
            for method in ("visible_full_span", "bbox_bottom_span_control"):
                pixels = env if method == "visible_full_span" else (
                    np.array([[float(boxes[0]["x1"]), float(boxes[0]["y2"])],
                              [float(boxes[0]["x2"]), float(boxes[0]["y2"])]]) if len(boxes) == 1 else None)
                record = dict(**source, model=model, method=method, left_x=None, left_y=None, right_x=None, right_y=None,
                              rectified_endpoints_json=None, floor_x_m=None, floor_z_m=None, floor_reason="no_span")
                if pixels is None:
                    record.update(empty("no_observed_full_span" if method == "visible_full_span" else "no_unique_saved_bbox"))
                else:
                    record.update(left_x=float(pixels[0, 0]), left_y=float(pixels[0, 1]),
                                  right_x=float(pixels[1, 0]), right_y=float(pixels[1, 1]))
                    uv = raw_to_rectified(pixels, parameters)
                    if uv is None:
                        record.update(empty("outside_native_lens_or_virtual_view"))
                    else:
                        _, transform = legacy_front_diagnostic_geometry(parameters)
                        result = pinhole_width_position(uv, VIRTUAL_K, transform)
                        floor = floor_intersections([uv.mean(axis=0)], VIRTUAL_K, transform)[0]
                        record.update(result, rectified_endpoints_json=json.dumps(uv.tolist()), floor_x_m=floor["x_m"],
                                      floor_z_m=floor["z_m"], floor_reason=floor["reason"])
                records.append(record)
    return records


def summarize(rows):
    output = []
    groups = defaultdict(list)
    for row in rows:
        groups[row["dataset"], row["condition"], row["model"], row["method"]].append(row)
    for (dataset, condition, model, method), group in sorted(groups.items()):
        for population in ("all_estimates", "support_time_accepted", "same_frame_floor_comparison"):
            selected = [r for r in group if r["estimated"] and (
                population == "all_estimates" or
                population == "support_time_accepted" and r["quality_accepted"] or
                population == "same_frame_floor_comparison" and r["floor_z_m"] is not None)]
            z = np.array([r["z_forward_m"] for r in selected])
            x = np.array([r["x_right_m"] for r in selected])
            ref = group[0]["reference_z_m"]
            dz = z-ref if ref is not None else None
            floor = [r["floor_z_m"] for r in selected if r["floor_z_m"] is not None]
            output.append(dict(dataset=dataset, condition=condition, model=model, method=method, population=population,
                frames=len(group), estimated_frames=len(selected), reference_z_m=ref,
                z_median_m=float(np.median(z)) if len(z) else None, x_median_m=float(np.median(x)) if len(x) else None,
                z_bias_m=float(np.median(dz)) if dz is not None and len(dz) else None,
                z_abs_error_p95_m=float(np.percentile(abs(dz), 95)) if dz is not None and len(dz) else None,
                z_abs_error_max_m=float(max(abs(dz))) if dz is not None and len(dz) else None,
                floor_z_median_m=float(np.median(floor)) if floor else None,
                estimated_height_median_m=float(np.median([r["height_above_floor_m"] for r in selected])) if selected else None,
                width_px_median=float(np.median([r["width_rectified_px"] for r in selected])) if selected else None,
                outside_range_frames=sum(not r["in_diagnostic_range"] for r in selected),
                missing_reasons=json.dumps(dict(Counter(r["reason"] for r in group if not r["estimated"]))), usable_for_ffb=False))
    return output


def square_yaw_simulation():
    # Ideal square base on floor, nearest Z fixed at1.3m; no fisheye/model error.
    R0 = np.array([[0., 0., 1.], [-1., 0., 0.], [0., -1., 0.]])
    transform = np.eye(4)
    transform[:3, :3], transform[2, 3] = R0, .59
    local = np.array([[-1, -1], [1, -1], [1, 1], [-1, 1]])*BASE_SIDE_M/2
    result = []
    for yaw in (0, 15, 30, 45):
        angle = np.deg2rad(yaw)
        rotation = np.array([[np.cos(angle), -np.sin(angle)], [np.sin(angle), np.cos(angle)]])
        ground = local @ rotation.T
        ground[:, 1] += 1.3-ground[:, 1].min()
        target = np.column_stack((ground[:, 1], -ground[:, 0], np.zeros(4)))
        optical = (target-transform[:3, 3]) @ R0
        uv = optical @ VIRTUAL_K.T
        uv = uv[:, :2]/uv[:, 2, None]
        pixels = uv[[np.argmin(uv[:, 0]), np.argmax(uv[:, 0])]]
        estimate = pinhole_width_position(pixels, VIRTUAL_K, transform)
        result.append(dict(yaw_deg=yaw, reference_nearest_z_m=1.3, estimated_z_m=estimate["z_forward_m"],
                           error_z_m=estimate["z_forward_m"]-1.3, known_side_m=BASE_SIDE_M,
                           kind="synthetic_square_silhouette_not_real_yaw_estimation"))
    return result


def main():
    output = HERE/"results_r01"
    if output.exists():
        raise ValueError("new output required; no overwrite")
    sources, geometries, refs, conditions, phases, hashes = old.load_inputs()
    scope = ConeGroundProjector(geometries["recorded58"], width=1280, height=720, front_lens="left", confidence_threshold=.5)
    base_ledger, candidates = old.make_ledger(sources, scope, refs, conditions, phases)
    old_quality_path = DAY19/"cone_support_quality_r01/results_r02/observations.csv"
    qualities = {key(r):r for r in read_csv(old_quality_path)}
    ledger = [dict(r, reference_x_m=r["reference_x_m"], quality_accepted=qualities[key(r)]["quality_accepted"] == "True",
                   envelope_reason="previously_frozen_colour_envelope") for r in base_ledger]
    envelope_path = DAY19/"cone_support_extent_r01/results_r01/lower_envelopes.csv"
    grouped = defaultdict(list)
    for r in read_csv(envelope_path):
        grouped[key(r)].append((float(r["x"]), float(r["y"])))
    endpoints = {k:envelope_endpoints(v) for k,v in grouped.items()}
    extra, extra_endpoints, extra_points, extra_hashes = additional_recording()
    ledger.extend(extra)
    endpoints.update(extra_endpoints)
    hashes.update(extra_hashes)
    paths = [Path(__file__), HERE/"known_width.py", HERE/"method.md", old_quality_path, envelope_path,
             DAY19/"cone_virtual_pinhole_r01/virtual_pinhole.py", ROOT/"src/fisheye_floor_geometry.py",
             DAY19/"paper_cone_2m_validation_r01/intake_summary.json", DAY19/"paper_cone_2m_validation_r01/analysis_r01/support_quality.csv"]
    hashes.update({str(p):sha256(p) for p in paths})
    rows = replay(ledger, endpoints, candidates, geometries)
    summary = summarize(rows)
    evaluated = [r for r in summary if r["population"] == "all_estimates" and r["model"] == "height_only59"
                 and r["method"] == "visible_full_span" and r["reference_z_m"] is not None]
    failures = [dict(dataset=r["dataset"], condition=r["condition"], bias=r["z_bias_m"], p95=r["z_abs_error_p95_m"])
                for r in evaluated if r["z_bias_m"] is None or abs(r["z_bias_m"]) > .1 or r["z_abs_error_p95_m"] > .2]
    screen = dict(decision="DEFER_VISIBLE_SPAN_AS_KNOWN_WIDTH" if failures else "PROMISING_PROXY_NOT_PHYSICAL_APPROVAL",
                  evaluation_conditions=len(evaluated), median_bias_limit_m=.1, p95_limit_m=.2,
                  failures=failures, calibrated_intrinsics=False, physical_width_correspondence_verified=False, usable_for_ffb=False)
    simulations = square_yaw_simulation()
    assert len(ledger) == 5143+1733 and len(rows) == len(ledger)*6
    assert all(not r["usable_for_ffb"] for r in rows)
    assert all(sha256(Path(p)) == digest for p,digest in hashes.items())
    output.mkdir()
    write_csv(output/"all_frame_estimates.csv", rows)
    write_csv(output/"summary.csv", summary)
    write_csv(output/"additional_full_envelopes.csv", extra_points)
    write_csv(output/"square_yaw_simulation.csv", simulations)
    write_json = lambda name, value: (output/name).write_text(json.dumps(value, indent=2)+"\n")
    write_json("screen.json", screen)
    plot(summary, rows, simulations, output)
    provenance = dict(status="COMPLETED_KNOWN_SIZE_PINHOLE_PROXY_STUDY_NOT_RUNTIME_APPROVAL", frames=len(ledger),
        method_model_rows=len(rows), models=geometries, known_side_m=BASE_SIDE_M,
        virtual_K=VIRTUAL_K.tolist(), virtual_size=[960,960], geometry_or_size_fit=False,
        new_yolo_inference=False, live_tf=False, physical_output=False, production_settings_changed=False,
        source_sha256=hashes, output_sha256={p.name:sha256(p) for p in output.iterdir() if p.is_file()})
    write_json("provenance.json", provenance)
    print(json.dumps(dict(screen=screen, primary_summary=evaluated), indent=2))


def plot(summary, rows, simulations, output):
    os.environ.setdefault("MPLCONFIGDIR", str(output/"matplotlib_config"))
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    selected = [r for r in summary if r["population"] == "same_frame_floor_comparison" and r["model"] == "height_only59"
                and r["method"] == "visible_full_span" and r["reference_z_m"] is not None]
    x = np.arange(len(selected))
    fig, axes = plt.subplots(2, 1, figsize=(11, 7), layout="constrained")
    axes[0].bar(x-.18, [r["z_median_m"] for r in selected], .36, label="known-width hypothesis")
    axes[0].bar(x+.18, [r["floor_z_median_m"] for r in selected], .36, label="same centre ray / floor")
    axes[0].plot(x, [r["reference_z_m"] for r in selected], "k_", ms=20, label="nominal near-edge Z")
    axes[0].set(ylabel="Forward Z [m]", title="Same frames / same rectified centre ray")
    axes[1].bar(x, [r["z_bias_m"] for r in selected], label="known-width median bias")
    axes[1].plot(x, [r["z_abs_error_p95_m"] for r in selected], "o", label="known-width p95 absolute error")
    axes[1].axhline(0, c="k", lw=.7)
    axes[1].set(ylabel="Error to nominal Z [m]", title="Unverified silhouette span = 0.375 m assumption")
    for axis in axes:
        axis.set_xticks(x, [r["dataset"].replace("paper_cone_20261019", "new19")+"\n"+r["condition"] for r in selected], fontsize=8)
        axis.legend(fontsize=8)
        axis.grid(axis="y", alpha=.2)
    fig.savefig(output/"known_width_vs_floor.png", dpi=150)
    plt.close(fig)
    fig, axes = plt.subplots(1, 2, figsize=(10, 4), layout="constrained")
    group = [r for r in rows if r["dataset"] == "sequence" and r["method"] == "visible_full_span"
             and r["model"] == "height_only59" and 1110 <= r["frame"] <= 1155]
    axes[0].plot([r["frame"] for r in group], [r["z_forward_m"] if r["estimated"] else np.nan for r in group], ".-", label="raw width estimate")
    accepted = [r for r in group if r["estimated"] and r["quality_accepted"]]
    axes[0].plot([r["frame"] for r in accepted], [r["z_forward_m"] for r in accepted], "o", label="old support-time gate passed")
    axes[0].axvspan(1125, 1134, color="orange", alpha=.2)
    axes[0].axhline(2., c="k", ls="--")
    axes[0].set(xlabel="Source frame", ylabel="Forward Z [m]", title="Occlusion: missing base shrinks span")
    axes[0].legend(fontsize=8)
    axes[1].plot([r["yaw_deg"] for r in simulations], [r["estimated_z_m"] for r in simulations], "o-")
    axes[1].axhline(1.3, c="k", ls="--", label="nearest edge fixed at1.3 m")
    axes[1].set(xlabel="Synthetic square yaw [deg]", ylabel="Width-proxy forward Z [m]", title="Synthetic orientation sensitivity\nNOT measured recording yaw")
    axes[1].legend(fontsize=8)
    for axis in axes:
        axis.grid(alpha=.2)
    fig.savefig(output/"occlusion_and_square_yaw.png", dpi=150)
    plt.close(fig)


if __name__ == "__main__":
    main()
