#!/usr/bin/env python3
"""Saved-data audit of the red-only shadow support candidate from r02.

Reads the existing live JSONL only. No inference, image decoding, HSV
re-extraction, pose fit, or distance computation.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def read_rows(path: Path) -> list[dict]:
    rows = []
    with path.open(encoding="utf-8") as stream:
        for index, line in enumerate(stream, 1):
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSON on line {index}") from exc
            if not isinstance(row, dict):
                raise ValueError(f"frame line {index} is not an object")
            rows.append(row)
    return rows


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def quantile(values, fraction):
    values = sorted(values)
    if not values:
        return None
    position = (len(values)-1)*fraction
    lo, hi = math.floor(position), math.ceil(position)
    return values[lo]+(values[hi]-values[lo])*(position-lo)


def stats(values):
    values = [value for value in values if value is not None]
    if not values:
        return dict(count=0, median=None, p95=None, minimum=None, maximum=None)
    return dict(count=len(values), median=round(quantile(values, .5), 4),
                p95=round(quantile(values, .95), 4), minimum=round(min(values), 4),
                maximum=round(max(values), 4))


def candidate_row(row):
    shadow = row.get("colour_support_shadow")
    candidate = shadow.get("candidate") if isinstance(shadow, dict) else None
    evidence = row.get("frame_evidence") or {}
    boxes = evidence.get("selected_detector_boxes") or []
    box = boxes[0] if len(boxes) == 1 else None
    pose = evidence.get("pose") or {}
    point = candidate.get("point") if isinstance(candidate, dict) else None
    support = candidate.get("support") if isinstance(candidate, dict) else None
    completion = (row.get("support_completion_shadow") or {}).get("candidate") or {}
    out = dict(
        session=row.get("session"), frame=row.get("frame"),
        distance_available=row.get("distance_available"),
        pose_available=pose.get("pose_available"), scene_reason=pose.get("scene_reason"),
        baseline_support_reason=(evidence.get("support_observation") or {}).get("reason"),
        shadow_status=(shadow or {}).get("status"),
        candidate_reason=(candidate or {}).get("reason"),
        selected_colour=(candidate or {}).get("selected_colour"),
        seed_dominant_fraction=(candidate or {}).get("seed_dominant_fraction"),
        point_x=point[0] if point else None, point_y=point[1] if point else None,
        support_columns=len(support) if support else 0,
        support_span=(max(p[0] for p in support)-min(p[0] for p in support)) if support else None,
        point_in_support=(point in support) if point and support else None,
        bbox_x1=box.get("x1") if box else None, bbox_y1=box.get("y1") if box else None,
        bbox_x2=box.get("x2") if box else None, bbox_y2=box.get("y2") if box else None,
        completion_point_x=(completion.get("point") or [None, None])[0],
        completion_point_y=(completion.get("point") or [None, None])[1])
    if point and box:
        out["point_inside_bbox_x"] = box["x1"] <= point[0] <= box["x2"]
        out["y_above_bbox_bottom_px"] = box["y2"]-point[1]
        out["x_from_bbox_center_px"] = point[0]-(box["x1"]+box["x2"])/2
    else:
        out.update(point_inside_bbox_x=None, y_above_bbox_bottom_px=None,
                   x_from_bbox_center_px=None)
    if point and completion.get("point"):
        out["completion_dx_px"] = point[0]-completion["point"][0]
        out["completion_dy_px"] = point[1]-completion["point"][1]
        out["completion_same_point"] = point == completion["point"]
    else:
        out.update(completion_dx_px=None, completion_dy_px=None, completion_same_point=None)
    return out


def adjacent_deltas(rows):
    deltas = []
    previous = None
    for row in sorted(rows, key=lambda r: r["frame"]):
        if previous is not None and row["frame"]-previous["frame"] == 1:
            if (row["point_x"] is not None and previous["point_x"] is not None):
                dx = row["point_x"]-previous["point_x"]
                dy = row["point_y"]-previous["point_y"]
                deltas.append(dict(frame=row["frame"], dx=dx, dy=dy,
                                   distance=math.hypot(dx, dy)))
        previous = row
    return deltas


def build_summary(rows, deltas, input_sha):
    points = [row for row in rows if row["point_x"] is not None]
    reasons = Counter(row["candidate_reason"] or "no_candidate" for row in rows)
    inside = sum(row["point_inside_bbox_x"] is True for row in points)
    summary = dict(
        status="SAVED_DATA_RED_ONLY_SHADOW_AUDIT_NOT_PROMOTION",
        processed_frames=len(rows), candidate_point_frames=len(points),
        candidate_reasons=dict(reasons),
        baseline_support_reasons=dict(Counter(row["baseline_support_reason"] for row in rows)),
        selected_colours=dict(Counter(row["selected_colour"] or "none" for row in rows)),
        pose_available_frames=sum(row["pose_available"] is True for row in rows),
        distance_available_frames=sum(row["distance_available"] is True for row in rows),
        point_inside_bbox_x_frames=inside,
        point_in_support_frames=sum(row["point_in_support"] is True for row in points),
        y_above_bbox_bottom_px=stats([row["y_above_bbox_bottom_px"] for row in points]),
        x_from_bbox_center_px=stats([row["x_from_bbox_center_px"] for row in points]),
        support_columns=stats([row["support_columns"] for row in points]),
        support_span_px=stats([row["support_span"] for row in points]),
        seed_dominant_fraction=stats([row["seed_dominant_fraction"] for row in points]),
        adjacent_pairs=len(deltas),
        adjacent_dx_px=stats([item["dx"] for item in deltas]),
        adjacent_dy_px=stats([item["dy"] for item in deltas]),
        adjacent_distance_px=stats([item["distance"] for item in deltas]),
        completion_same_point_frames=sum(row["completion_same_point"] is True for row in points),
        completion_dx_px=stats([row["completion_dx_px"] for row in points]),
        completion_dy_px=stats([row["completion_dy_px"] for row in points]),
        physical_reference=(
            "none in this session: no same-frame or same-session surveyed floor marker; "
            "absolute distance and support-floor contact are not evaluable"),
        conclusion=dict(
            availability=(
                f"red-only shadow yields a point in {len(points)}/{len(rows)} frames while "
                "the union-mask baseline support is withheld in all frames"),
            geometry=(
                f"{inside}/{len(points)} points lie inside the bbox x-range; "
                "the point is an observed support column, not the bbox bottom"),
            temporal=(
                "adjacent-frame pixel movement is reported as image stability only; "
                "it is not contact correctness or metric accuracy"),
            promotion=(
                "not promoted: no independent physical reference, pose is unavailable, "
                "and the shadow is a different non-controlling path"),
        ),
        input_sha256=input_sha,
        controlling_distance=False, physical_metric_verified=False,
        floor_contact_verified=False, usable_for_ffb=False)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.output_dir.exists():
        raise ValueError("new output directory required")
    input_path = args.input_dir/"distance_frames.jsonl"
    rows = [candidate_row(row) for row in read_rows(input_path)]
    deltas = adjacent_deltas(rows)
    args.output_dir.mkdir(parents=True)
    fields = list(rows[0])
    with (args.output_dir/"candidate_frames.csv").open("x", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    summary = build_summary(rows, deltas, {str(input_path): sha256(input_path)})
    (args.output_dir/"summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False)+"\n", encoding="utf-8")
    provenance = dict(
        status="SAVED_DATA_ONLY_NO_INFERENCE",
        method=str((Path(__file__).resolve().parent/"method.md").relative_to(ROOT)),
        method_sha256=sha256(Path(__file__).resolve().parent/"method.md"),
        analysis=str(Path(__file__).resolve().relative_to(ROOT)),
        analysis_sha256=sha256(Path(__file__).resolve()),
        input_sha256=summary["input_sha256"],
        physical_metric_verified=False, floor_contact_verified=False, usable_for_ffb=False)
    (args.output_dir/"provenance.json").write_text(
        json.dumps(provenance, indent=2, ensure_ascii=False)+"\n", encoding="utf-8")
    print(json.dumps({key: summary[key] for key in (
        "processed_frames", "candidate_point_frames", "candidate_reasons",
        "point_inside_bbox_x_frames", "point_in_support_frames",
        "y_above_bbox_bottom_px", "support_columns", "adjacent_distance_px",
        "completion_same_point_frames", "pose_available_frames",
        "distance_available_frames")}, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
