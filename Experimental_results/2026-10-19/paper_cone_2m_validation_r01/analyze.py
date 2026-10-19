"""Fixed known-ROI CPU diagnostics, NOT YOLO inference or production ranging."""
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
for folder in (ROOT/"src", HERE.parent/"cone_support_extent_r01",
               HERE.parent/"cone_support_projection_r01", HERE.parent/"cone_virtual_pinhole_r01"):
    sys.path.insert(0, str(folder))
from cone_dataset import read_csv, sha256, write_csv
from cone_support_quality import ConeSupportQualityGate
from support import describe_support
import metric_support as direct
import virtual_pinhole as pinhole

spec = importlib.util.spec_from_file_location("frozen_paper", ROOT/"Experimental_results/2026-10-15/white_paper_visibility_r01/analyze.py")
paper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(paper)

WINDOWS = {"paper_before": (4., 17.), "cone_static": (28., 38.), "paper_after": (47., 55.)}
THRESHOLDS = (140, 170, 200)
PAPER_ROI = (305, 353, 20, 27)
CONE_ROI = (285, 290, 65, 95)


def phase(t):
    return next((name for name, (a, b) in WINDOWS.items() if a <= t <= b), "transition")


def local_paper_corner(image, threshold):
    if image.shape != (720, 1280, 3) or image.dtype != np.uint8:
        raise ValueError("native1280x720 BGR required")
    x, y, w, h = PAPER_ROI
    gray = cv2.cvtColor(image[y:y+h, x:x+w], cv2.COLOR_BGR2GRAY)
    contours = cv2.findContours(np.uint8(gray >= threshold), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)[0]
    contours = [c for c in contours if cv2.contourArea(c) >= 20]
    result = dict(candidate=False, reason="no_or_ambiguous_white_component", pixel_x=None, pixel_y=None,
                  floor_contact_verified=False, usable_for_ffb=False)
    if len(contours) != 1:
        return result
    points = contours[0][:, 0, :]
    if np.any(points[:, 0] == 0) or np.any(points[:, 1] == 0) or np.any(points[:, 1] == h-1):
        return dict(result, reason="local_roi_edge_truncation")
    left = points[points[:, 0] == points[:, 0].min()]
    ys = np.unique(left[:, 1])
    if len(ys) < 4 or np.max(np.diff(ys)) != 1:
        return dict(result, reason="insufficient_continuous_left_edge")
    return dict(result, candidate=True, reason="known_local_near_left_corner_HYPOTHESIS",
                pixel_x=int(left[0, 0]+x), pixel_y=int(ys[-1]+y))


def red_support(image):
    if image.shape != (720, 1280, 3) or image.dtype != np.uint8:
        raise ValueError("native1280x720 BGR required")
    x, y, w, h = CONE_ROI
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
        return None, "red_roi_edge_truncation"
    if bw < 5 or bh < 8:
        return None, "insufficient_red_extent"
    description, _, selected = describe_support(contours[0][:, 0, :]+[x, y])
    return selected, description["reason"]


def stat(values):
    v = np.asarray(values, dtype=float)
    return dict(count=len(v), min=float(v.min()), median=float(np.median(v)), max=float(v.max())) if len(v) else dict(count=0, min=None, median=None, max=None)


def compare(points, p):
    a, b = direct.project_columns(points, p), pinhole.project_columns(points, p)
    if len(a) != len(b):
        raise AssertionError("correspondence lost")
    errors = []
    for first, second in zip(a, b):
        if first["reason"] != second["reason"]:
            raise AssertionError("projection reason mismatch")
        if first["reason"] == "valid":
            errors.append(max(abs(first[k]-second[k]) for k in ("x_m", "z_m")))
    return a, max(errors, default=0.)


def main():
    output = HERE/"analysis_r01"
    if output.exists():
        raise ValueError("no output overwrite")
    intake = json.loads((HERE/"intake_summary.json").read_text())
    session = Path(intake["session"])
    frozen = HERE.parent/"cone_distance_methods_r01/results_r01/provenance.json"
    models = json.loads(frozen.read_text())["geometries"]
    assert set(models) == {"recorded58", "height_only59", "paper_centre2"}
    dependencies = [Path(__file__), HERE/"method.md", HERE/"intake_summary.json", frozen,
                    Path(paper.__file__), Path(direct.__file__), Path(pinhole.__file__),
                    ROOT/"src/cone_support_quality.py", ROOT/"src/ground_contact.py",
                    HERE.parent/"cone_support_extent_r01/support.py"]
    before = dict(intake["source_sha256"])
    before.update({str(p): sha256(p) for p in dependencies})
    rows = read_csv(session/"detections.csv")
    cap = cv2.VideoCapture(str(session/"raw.avi"))
    gate = ConeSupportQualityGate()
    corners, supports = [], []
    try:
        for row in rows:
            ok, im = cap.read()
            if not ok:
                raise AssertionError("missing raw frame")
            t = float(row["time_sec"])
            common = dict(frame=int(row["frame"]), time_sec=t, phase=phase(t))
            for threshold in THRESHOLDS:
                strict = paper.paper_corner(im, threshold, (300, 350, 60, 35))
                corners.append(dict(**common, threshold=threshold, **local_paper_corner(im, threshold),
                                    strict_candidate=strict["corner_candidate"], strict_reason=strict["reason"]))
            selected, reason = red_support(im)
            quality = gate.update(t, [dict(support=selected, unavailable_reason=reason)])
            supports.append(dict(**common, segmentation_reason=reason, **quality))
        assert not cap.read()[0]
    finally:
        cap.release()
    initial = [r for r in corners if r["phase"] == "paper_before" and r["threshold"] == 170 and r["candidate"]]
    if not initial:
        raise AssertionError("no primary paper reference; do not invent matching column")
    reference = Counter((r["pixel_x"], r["pixel_y"]) for r in initial).most_common(1)[0][0]
    projection, errors = [], []
    for row in corners:
        if row["phase"] not in ("paper_before", "paper_after") or not row["candidate"]:
            continue
        for name, p in models.items():
            points, error = compare([(row["pixel_x"], row["pixel_y"])], p)
            errors.append(error)
            projection.append(dict(frame=row["frame"], time_sec=row["time_sec"], phase=row["phase"],
                                   threshold=row["threshold"], model=name, kind="paper_local_corner", **points[0]))
    extent_rows, matched = [], []
    compared_support_columns = 0
    for row in supports:
        observed = row["observed_support"]
        if observed is None:
            continue
        for name, p in models.items():
            points, error = compare(observed, p)
            errors.append(error)
            compared_support_columns += len(points)
            extent_rows.append(dict(frame=row["frame"], time_sec=row["time_sec"], phase=row["phase"],
                                    model=name, **direct.bounds(points)))
            same = next((point for point in points if point["pixel_x"] == reference[0]), None)
            if same:
                matched.append(dict(frame=row["frame"], time_sec=row["time_sec"], phase=row["phase"], model=name,
                                    kind="cone_actual_same_x_column", threshold=None, **same))
    pixel_stats = []
    for window in WINDOWS:
        for threshold in THRESHOLDS:
            group = [r for r in corners if r["phase"] == window and r["threshold"] == threshold]
            good = [r for r in group if r["candidate"]]
            pixel_stats.append(dict(phase=window, threshold=threshold, frames=len(group), candidates=len(good),
                                    x=stat([r["pixel_x"] for r in good]), y=stat([r["pixel_y"] for r in good]),
                                    strict_reasons=dict(Counter(r["strict_reason"] for r in group))))
    metric_stats = []
    for window in WINDOWS:
        for name in models:
            group = [r for r in projection+matched if r["phase"] == window and r["model"] == name
                     and (r["threshold"] == 170 or r["threshold"] is None) and r["reason"] == "valid"]
            metric_stats.append(dict(phase=window, model=name, frames=len(group),
                                     x=stat([r["x_m"] for r in group]), z=stat([r["z_m"] for r in group]),
                                     pixel_y=stat([r["pixel_y"] for r in group])))
    checks = dict(all_native_frames_consumed=len(supports) == len(rows),
                  direct_pinhole_agreement=max(errors) < 1e-9,
                  sources_unchanged=all(sha256(Path(p)) == digest for p, digest in before.items()),
                  no_physical_permission=all(not r["usable_for_ffb"] for r in projection+matched))
    assert all(checks.values()), checks
    output.mkdir()
    write_csv(output/"paper_corner_diagnostics.csv", corners)
    write_csv(output/"support_quality.csv", [dict(r, observed_support=json.dumps(r["observed_support"])) for r in supports])
    write_csv(output/"paper_projection.csv", projection)
    write_csv(output/"cone_same_column_projection.csv", matched)
    write_csv(output/"cone_support_extent_projection.csv", extent_rows)
    make_plot(corners, projection+matched, output)
    result = dict(status="COMPLETED_KNOWN_ROI_DIAGNOSTIC_NOT_YOLO_OR_CALIBRATION_APPROVAL", checks=checks,
                  windows_sec=WINDOWS, frame_count=len(rows), paper_reference_native_xy=reference,
                  max_direct_pinhole_coordinate_difference_m=max(errors),
                  compared_accepted_support_columns_all_models=compared_support_columns,
                  models=models, paper_pixel_summary=pixel_stats, same_column_metric_summary=metric_stats,
                  static_cone_quality_reasons=dict(Counter(r["reason"] for r in supports if r["phase"] == "cone_static")),
                  thresholds=THRESHOLDS, physical_reference_z_m=2., reference_basis="requested placement, no independent surveyed uncertainty",
                  paper_not_removed_during_cone=True, yolo_reinference=False, new_calibration_fit=False,
                  physical_output=False, source_sha256=before,
                  output_sha256={p.name: sha256(p) for p in output.iterdir() if p.is_file()})
    (output/"summary.json").write_text(json.dumps(result, indent=2)+"\n")
    print(json.dumps(dict(reference=reference, checks=checks, metric=metric_stats, pixel=pixel_stats,
                         max_direct_pinhole_error=max(errors)), indent=2))


def make_plot(corners, projected, output):
    os.environ.setdefault("MPLCONFIGDIR", str(output/"matplotlib_config"))
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(2, 1, figsize=(10, 6), layout="constrained")
    for threshold in THRESHOLDS:
        group = [r for r in corners if r["candidate"] and r["phase"] in ("paper_before", "paper_after") and r["threshold"] == threshold]
        axes[0].plot([r["time_sec"] for r in group], [r["pixel_y"] for r in group], ".", ms=2, label=f"paper gray >= {threshold}")
    for name in ("recorded58", "height_only59", "paper_centre2"):
        group = [r for r in projected if r["model"] == name and r["phase"] != "transition"
                 and (r["threshold"] == 170 or r["threshold"] is None) and r["reason"] == "valid"]
        axes[1].plot([r["time_sec"] for r in group], [r["z_m"] for r in group], ".", ms=2, label=name)
    axes[1].axhline(2., c="k", ls="--", label="nominal reference 2 m")
    axes[0].set_ylabel("Paper local corner Y [native px]")
    axes[1].set_ylabel("Conditional floor Z [m]")
    for axis in axes:
        for a, b in WINDOWS.values():
            axis.axvspan(a, b, color="gray", alpha=.08)
        axis.legend(fontsize=8, loc="upper right")
        axis.grid(alpha=.25)
        axis.set_xlabel("Recording time [s]")
    axes[0].set_title("Paper before / stationary cone / paper after: known-ROI diagnostics")
    axes[1].set_title("Same source pixels: direct and pinhole_float overlap; NOT YOLO evaluation")
    fig.savefig(output/"paper_cone_same_column.png", dpi=150)
    plt.close(fig)


if __name__ == "__main__":
    main()
