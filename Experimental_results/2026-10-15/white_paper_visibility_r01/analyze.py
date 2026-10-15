"""Known paper ROI corner visibility, not a generic detector or calibration."""
import json
import os
from pathlib import Path
import sys

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT/"src"))
from cone_dataset import read_csv, sha256, write_csv
from cone_observation import CAMERA_KEYS
from diagnose_box_contact_calibration import project_pixel

ROI = (295, 360, 60, 30)
THRESHOLDS = (140, 170, 200)


def paper_corner(image, threshold, roi=ROI):
    if image.shape != (720, 1280, 3) or image.dtype != np.uint8:
        raise ValueError("native1280x720 BGR required")
    if type(threshold) is not int or not 0 <= threshold <= 255:
        raise ValueError("integer grayscale threshold required")
    x, y, w, h = roi
    if (not all(type(v) is int for v in roi) or min(w, h) < 4
            or x < 0 or y < 0 or x+w > 1280 or y+h > 720):
        raise ValueError("valid native diagnostic ROI required")
    gray = cv2.cvtColor(image[y:y+h, x:x+w], cv2.COLOR_BGR2GRAY)
    mask = np.asarray(gray >= threshold, np.uint8)*255
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    selected = [c for c in contours if cv2.contourArea(c) >= 20]
    result = dict(corner_candidate=False, reason="", significant_contours=len(selected),
                  area_px=None, bbox_width_px=None, bbox_height_px=None, polygon_vertices=None,
                  pixel_x=None, pixel_y=None, physical_corner_verified=False, usable_for_ffb=False)
    if len(selected) != 1:
        return dict(result, reason="no_paper_contour" if not selected else "ambiguous_paper_contours")
    contour = selected[0]
    bx, by, bw, bh = cv2.boundingRect(contour)
    result.update(area_px=float(cv2.contourArea(contour)), bbox_width_px=bw, bbox_height_px=bh)
    if bx == 0 or by == 0 or bx+bw >= w or by+bh >= h:
        return dict(result, reason="roi_edge_truncation")
    polygon = cv2.approxPolyDP(contour, .02*cv2.arcLength(contour, True), True)
    result["polygon_vertices"] = len(polygon)
    if len(polygon) != 4 or not cv2.isContourConvex(polygon):
        return dict(result, reason="not_convex_quadrilateral")
    if bw < 10 or bh < 4:
        return dict(result, reason="insufficient_image_extent")
    points = polygon[:, 0, :]
    ordered = points[np.argsort(points[:, 1], kind="stable")]
    if ordered[2, 1]-ordered[1, 1] < 3:
        return dict(result, reason="front_rear_corners_not_separated")
    corner = min(ordered[2:], key=lambda p: p[0])
    return dict(result, corner_candidate=True, reason="known_roi_near_left_corner_hypothesis",
                pixel_x=int(corner[0]+x), pixel_y=int(corner[1]+y))


def main():
    output = HERE/"analysis_r01"
    if output.exists():
        raise ValueError("no result overwrite")
    intake = json.loads((HERE/"intake_summary.json").read_text())
    session = Path(intake["session"])
    frames = read_csv(session/"detections.csv")
    parameters = {k: intake["metadata"]["parameters"][k] for k in CAMERA_KEYS}
    models = dict(recorded58=parameters, measured59=dict(parameters, camera_height=.59))
    before = dict(intake["source_sha256"])
    paths = [Path(__file__), HERE/"method.md", HERE/"intake.py", HERE/"intake_summary.json",
             HERE/"raw_sample_manifest.csv", ROOT/"src/ground_contact.py", ROOT/"src/diagnose_box_contact_calibration.py"]
    paths.extend(HERE/r["file"] for r in read_csv(HERE/"raw_sample_manifest.csv"))
    before.update({str(p): sha256(p) for p in paths})
    capture = cv2.VideoCapture(str(session/"raw.avi"))
    observations = []
    try:
        for source in frames:
            ok, image = capture.read()
            if not ok:
                raise ValueError("short raw recording")
            for threshold in THRESHOLDS:
                result = paper_corner(image, threshold)
                observations.append(dict(frame=source["frame"], time_sec=source["time_sec"],
                                         threshold=threshold, **result))
        if capture.read()[0]:
            raise ValueError("raw frames beyond CSV")
    finally:
        capture.release()
    stats, projection = [], []
    for threshold in THRESHOLDS:
        group = [r for r in observations if r["threshold"] == threshold]
        accepted = [r for r in group if r["corner_candidate"]]
        stats.append(dict(threshold=threshold, frames=len(group), candidate_frames=len(accepted),
            pixel_x_median=float(np.median([r["pixel_x"] for r in accepted])) if accepted else None,
            pixel_y_median=float(np.median([r["pixel_y"] for r in accepted])) if accepted else None,
            pixel_x_min=min((r["pixel_x"] for r in accepted), default=None),
            pixel_x_max=max((r["pixel_x"] for r in accepted), default=None),
            pixel_y_min=min((r["pixel_y"] for r in accepted), default=None),
            pixel_y_max=max((r["pixel_y"] for r in accepted), default=None),
            bbox_width_median=float(np.median([r["bbox_width_px"] for r in accepted])) if accepted else None,
            bbox_height_median=float(np.median([r["bbox_height_px"] for r in accepted])) if accepted else None))
        for row in group:
            for model, p in models.items():
                point = project_pixel((row["pixel_x"], row["pixel_y"]), p) if row["corner_candidate"] else None
                projection.append(dict(frame=row["frame"], time_sec=row["time_sec"], threshold=threshold, model=model,
                    corner_candidate=row["corner_candidate"], projection_candidate=point is not None,
                    pixel_x=row["pixel_x"], pixel_y=row["pixel_y"], x_m=point[0] if point else None,
                    z_m=point[1] if point else None, nominal_reference_z_m=2.0,
                    reference_x_basis="approximately central per user, not surveyed uncertainty",
                    physical_corner_verified=False, usable_for_ffb=False))
    output.mkdir()
    write_csv(output/"corner_candidates.csv", observations)
    write_csv(output/"threshold_summary.csv", stats)
    write_csv(output/"fixed_projection_reference.csv", projection)
    plot(observations, output/"corner_pixel_stability.png")
    assert all(sha256(Path(p)) == digest for p, digest in before.items())
    report = dict(status="COMPLETED_PAPER_CORNER_VISIBILITY_DIAGNOSIS_NOT_METRIC_CALIBRATION_APPROVAL",
                  frames=len(frames), corner_rows=len(observations), projection_rows=len(projection),
                  roi_native_xywh=ROI, thresholds=THRESHOLDS, models=models, source_sha256=before,
                  fitted_parameters=False, thresholds_selected_by_distance_error=False,
                  runtime_detector_implemented=False, physical_output=False, production_settings_changed=False,
                  output_sha256={p.name: sha256(p) for p in output.iterdir() if p.is_file()})
    (output/"provenance.json").write_text(json.dumps(report, indent=2)+"\n")
    print(json.dumps(stats, indent=2))


def plot(rows, path):
    os.environ.setdefault("MPLCONFIGDIR", str(path.parent/"matplotlib_config"))
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(2, 1, figsize=(10, 5), sharex=True, layout="constrained")
    for threshold in THRESHOLDS:
        accepted = [r for r in rows if r["threshold"] == threshold and r["corner_candidate"]]
        for axis, coordinate in zip(axes, ("x", "y")):
            axis.plot([float(r["time_sec"]) for r in accepted], [r["pixel_"+coordinate] for r in accepted],
                      ".", markersize=2, label=f"gray >= {threshold}")
            axis.set_ylabel(coordinate.upper()+" corner hypothesis [px]")
            axis.grid(alpha=.3)
    axes[0].legend()
    axes[0].set_title("Known paper ROI: temporal/threshold repeatability, NOT physical corner accuracy")
    axes[-1].set_xlabel("Recording time [s]")
    fig.savefig(path, dpi=150)
    plt.close(fig)


if __name__ == "__main__":
    main()
