#!/usr/bin/env python3
"""Evaluate independently surveyed floor pixels with recorded camera geometry.

Offline only: no colour detector, fitting, box-specific affine correction,
ROS initialization, device opening or runtime configuration writes.
"""
import argparse
import csv
import hashlib
import json
import math
from pathlib import Path

import cv2

from diagnose_box_contact_calibration import project_pixel

GEOMETRY_KEYS = ("camera_height", "pitch_deg", "roll_deg", "yaw_deg", "radius_scale",
                 "front_cx_offset", "front_cy_offset", "back_cx_offset", "back_cy_offset")
FIELDS = ("point_id", "frame", "pixel_x", "pixel_y", "measured_x_m", "measured_z_m",
          "x_half_width_m", "z_half_width_m", "pixel_half_width_px", "measurement_note")


def sha256(path):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def finite(row, key):
    try:
        result = float(row[key])
    except (KeyError, ValueError, TypeError) as exc:
        raise ValueError(f"{row.get('point_id', '?')}: finite {key} required; no inferred truth") from exc
    if not math.isfinite(result):
        raise ValueError(f"nonfinite {key}")
    return result


def validate_points(rows, width, height):
    if not rows:
        raise ValueError("nonempty floor-reference table required")
    result, ids = [], set()
    for row in rows:
        if set(FIELDS) - set(row):
            raise ValueError("floor-reference CSV fields missing")
        identity = row["point_id"].strip()
        if not identity or identity in ids:
            raise ValueError("unique nonempty point_id required")
        ids.add(identity)
        normalized = dict(row, point_id=identity)
        for key in FIELDS[1:-1]:
            normalized[key] = finite(row, key)
        frame = normalized["frame"]
        if frame < 1 or not frame.is_integer():
            raise ValueError("positive one-based integer frame required")
        normalized["frame"] = int(frame)
        x, y = normalized["pixel_x"], normalized["pixel_y"]
        margin = normalized["pixel_half_width_px"]
        if margin < 0 or not (margin <= x <= width - 1 - margin and margin <= y <= height - 1 - margin):
            raise ValueError("pixel and its declared band must lie inside the whole raw image")
        if normalized["measured_z_m"] <= 0 or any(normalized[k] < 0 for k in ("x_half_width_m", "z_half_width_m")):
            raise ValueError("positive forward Z and nonnegative measurement half widths required")
        if not row["measurement_note"].strip():
            raise ValueError("independent measurement method/note required")
        result.append(normalized)
    return result


def evaluate_point(row, parameters, width, height):
    """No true-coordinate-dependent pixel selection and no parameter mutation."""
    result = dict(row)
    projected = project_pixel((row["pixel_x"], row["pixel_y"]), parameters, width, height)
    result.update(projection_status="VALID" if projected else "INVALID_FLOOR_RAY",
                  raw_x_m=None, raw_z_m=None, error_x_m=None, error_z_m=None,
                  position_error_m=None, x_within_measured_band=None, z_within_measured_band=None)
    if projected:
        x, z = projected
        ex, ez = x-row["measured_x_m"], z-row["measured_z_m"]
        result.update(raw_x_m=x, raw_z_m=z, error_x_m=ex, error_z_m=ez,
                      position_error_m=math.hypot(ex, ez),
                      x_within_measured_band=int(abs(ex) <= row["x_half_width_m"]),
                      z_within_measured_band=int(abs(ez) <= row["z_half_width_m"]))
    # Nine samples illustrate pixel sensitivity. Not guaranteed extrema or CI.
    margin = row["pixel_half_width_px"]
    samples = [project_pixel((row["pixel_x"]+dx, row["pixel_y"]+dy), parameters, width, height)
               for dx in (-margin, 0., margin) for dy in (-margin, 0., margin)]
    valid = [p for p in samples if p is not None]
    result["sensitivity_valid_samples"] = len(valid)
    for index, axis in enumerate(("x", "z")):
        result[f"sampled_{axis}_min_m"] = min(p[index] for p in valid) if valid else None
        result[f"sampled_{axis}_max_m"] = max(p[index] for p in valid) if valid else None
    return result


def write_csv(path, rows):
    keys = list(dict.fromkeys(k for row in rows for k in row))
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=keys, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def load_raw_frames(session, frame_ids):
    with (session/"detections.csv").open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    if [int(r["frame"]) for r in rows] != list(range(1, len(rows)+1)) or max(frame_ids) > len(rows):
        raise ValueError("frame table mismatch or selected frame beyond source")
    capture = cv2.VideoCapture(str(session/"raw.avi"))
    if not capture.isOpened():
        raise ValueError("cannot open recorded raw.avi")
    selected = {}
    try:
        for number in range(1, max(frame_ids)+1):
            ok, frame = capture.read()
            if not ok:
                raise ValueError("video ends before selected frame")
            if number in frame_ids:
                selected[number] = frame
    finally:
        capture.release()
    return selected, rows


def evaluate_session(session, points_path, output):
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError("output must be a new or empty directory; existing results are not overwritten")
    metadata_path = session/"metadata.json"
    metadata = json.loads(metadata_path.read_text())
    parameters = metadata["parameters"]
    for key in GEOMETRY_KEYS:
        finite(parameters, key)
    if parameters["camera_height"] <= 0 or parameters["radius_scale"] <= 0:
        raise ValueError("positive recorded height and radius required")
    width, height = int(metadata["requested_camera_width"]), int(metadata["requested_camera_height"])
    if width <= 0 or height <= 0:
        raise ValueError("positive recorded image dimensions required")
    with points_path.open(newline="") as stream:
        points = validate_points(list(csv.DictReader(stream)), width, height)
    frames, timestamps = load_raw_frames(session, {r["frame"] for r in points})
    if any(frame.shape[:2] != (height, width) for frame in frames.values()):
        raise ValueError("decoded raw image size differs from metadata")
    results = [dict(evaluate_point(r, parameters, width, height), session=session.name,
                    time_sec=timestamps[r["frame"]-1]["time_sec"]) for r in points]
    output.mkdir(parents=True, exist_ok=True)
    manifests = []
    for number, frame in sorted(frames.items()):
        filename = f"{session.name}_raw_frame_{number:06d}.png"
        path = output/filename
        if not cv2.imwrite(str(path), frame):
            raise ValueError("PNG export failed")
        digest = hashlib.sha256(frame.tobytes()).hexdigest()
        saved = cv2.imread(str(path))
        if saved is None or saved.shape != frame.shape or hashlib.sha256(saved.tobytes()).hexdigest() != digest:
            raise ValueError("exported PNG differs from decoded raw pixels")
        manifests.append(dict(session=session.name, frame=number, png=filename,
                              decoded_bgr_pixels_sha256=digest))
    write_csv(output/"floor_point_errors.csv", results)
    write_csv(output/"raw_frame_manifest.csv", manifests)
    summary = dict(scope="INDEPENDENT_FLOOR_PIXEL_DIAGNOSTIC_ONLY", session=session.name,
        decision="DIAGNOSTIC_ONLY_NO_CALIBRATION_PROMOTION", points=len(points),
        valid_floor_rays=sum(r["projection_status"]=="VALID" for r in results),
        coordinate_definition="camera-ground-projection origin; X right, Z forward; marker centre on floor",
        geometry={k:parameters[k] for k in GEOMETRY_KEYS}, fitted_coefficients=False,
        box_lateral_affine_applied=False, production_settings_changed=False,
        inputs_sha256={str(p.resolve()):sha256(p) for p in (metadata_path,session/"raw.avi",session/"detections.csv",points_path)},
        implementation_sha256={p.name:sha256(p) for p in (Path(__file__),Path(__file__).with_name("ground_contact.py"),
                                Path(__file__).with_name("diagnose_box_contact_calibration.py"))},
        limits=["Independent measurement and visibility are operator attestations, not automatically proved.",
                "Nine pixel-band samples are illustrative, not guaranteed bounds or confidence intervals.",
                "Within-band flags compare the central ray only; they are not an accuracy PASS.",
                "No detector, tracking, TTC, ROS, network or physical FFB evaluated.",
                "Selected frames decoded sequentially; full-session integrity is not evaluated here."])
    (output/"summary.json").write_text(json.dumps(summary,indent=2)+"\n")
    (output/"README.md").write_text(
        "# 床面基準点の固定モデル診断\n\n"
        f"session: `{session.name}`。点数{len(points)}、有効床面光線{summary['valid_floor_rays']}。\n\n"
        "元録画の幾何を保持し、箱専用X補正・係数フィット・ROS送信は行っていない。\n"
        "結果は[floor_point_errors.csv](floor_point_errors.csv)、来歴と限界は[summary.json](summary.json)。\n"
        "誤差は推定−実測。pixel幅内の9サンプルは説明用で、保証区間や信頼区間ではない。\n"
        "保存PNGは全画角・元解像度・無加工。画素hashは[raw_frame_manifest.csv](raw_frame_manifest.csv)。\n")
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", type=Path, required=True)
    parser.add_argument("--points", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        summary = evaluate_session(args.session.expanduser(), args.points.expanduser(), args.output_dir.expanduser())
    except (ValueError, KeyError, OSError) as exc:
        parser.exit(2, f"[ERROR] {exc}\n")
    print(f"[INFO] Diagnostic only: {summary['valid_floor_rays']}/{summary['points']} valid floor rays")
    print(f"[INFO] Report: {args.output_dir/'README.md'}")


if __name__ == "__main__":
    main()
