#!/usr/bin/env python3
"""Flatten a live --frame-evidence log into one CSV row per processed frame.

Read-only: no camera, inference, image decoding, pose fit, or distance control.
Rows are validated with the existing live-summary contract before flattening.
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
from summarize_cone_distance_live import load_frames  # noqa: E402

FIELDS = (
    "session", "frame", "source_time_sec", "media_time_sec", "distance_available",
    "reason", "bbox_count", "bbox_x1", "bbox_y1", "bbox_x2", "bbox_y2", "bbox_confidence",
    "support_x", "support_y", "support_columns", "support_reason", "quality_accepted",
    "quality_reason", "pose_initialized", "pose_available", "pose_reason", "up_x", "up_y",
    "up_z", "scene_reason", "scene_source_frame", "scene_age_sec", "scene_pending",
    "frame_age_ms", "freshness_limit_ms", "within_limit", "blockers",
    "floor_config_sha256", "crop_x1", "crop_y1", "crop_x2", "crop_y2", "mask_w", "mask_h",
    "contour_count", "contour_x1", "contour_y1", "contour_x2", "contour_y2", "touching_edges",
    "contour_areas",
)


def flatten(row):
    evidence = row.get("frame_evidence")
    if evidence is None:
        return None
    boxes = evidence["selected_detector_boxes"]
    box = boxes[0] if len(boxes) == 1 else {}
    support = evidence["support_observation"]
    point = support["point"] or [None, None]
    pose = evidence["pose"]
    up = pose["up_optical"] or [None, None, None]
    fresh = evidence["freshness"]
    mask = support.get("mask_diagnostics") or {}
    crop = mask.get("crop_bounds") or [None]*4
    shape = mask.get("mask_shape") or [None, None]
    bounds = mask.get("selected_contour_bounds") or [None]*4
    return dict(
        session=row["session"], frame=row["frame"], source_time_sec=row["source_time_sec"],
        media_time_sec=evidence["input"]["media_time_sec"],
        distance_available=row["distance_available"], reason=row["reason"],
        bbox_count=len(boxes), bbox_x1=box.get("x1"), bbox_y1=box.get("y1"),
        bbox_x2=box.get("x2"), bbox_y2=box.get("y2"), bbox_confidence=box.get("confidence"),
        support_x=point[0], support_y=point[1],
        support_columns=len(support["support"]) if support["support"] is not None else 0,
        support_reason=support["reason"], quality_accepted=support["quality_accepted"],
        quality_reason=support["quality_reason"], pose_initialized=pose["initialized"],
        pose_available=pose["pose_available"], pose_reason=pose["pose_reason"],
        up_x=up[0], up_y=up[1], up_z=up[2], scene_reason=pose["scene_reason"],
        scene_source_frame=pose["scene_source_frame"], scene_age_sec=pose["scene_age_sec"],
        scene_pending=pose["scene_pending"], frame_age_ms=fresh["age_ms"],
        freshness_limit_ms=fresh["limit_ms"], within_limit=fresh["within_limit"],
        blockers=";".join(fresh["blockers"]), floor_config_sha256=evidence["floor_model"]["config_sha256"],
        crop_x1=crop[0], crop_y1=crop[1], crop_x2=crop[2], crop_y2=crop[3],
        mask_w=shape[0], mask_h=shape[1], contour_count=mask.get("qualifying_contour_count"),
        contour_x1=bounds[0], contour_y1=bounds[1], contour_x2=bounds[2], contour_y2=bounds[3],
        touching_edges=";".join(mask.get("touching_edges") or []),
        contour_areas=";".join(str(value) for value in (mask.get("contour_areas") or [])))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.output_dir.exists():
        raise ValueError("new output directory required")
    rows, truncated, source_sha = load_frames(args.input_dir / "distance_frames.jsonl")
    flat = [item for item in (flatten(row) for row in rows) if item is not None]
    args.output_dir.mkdir(parents=True)
    with (args.output_dir / "frame_evidence.csv").open("x", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(flat)
    counts = dict(
        status=("COMPLETE_EVIDENCE_LOG" if flat and len(flat) == len(rows)
                else "NO_OR_PARTIAL_EVIDENCE_LOG"),
        processed_frames=len(rows), evidence_frames=len(flat),
        truncated_final_line_ignored=truncated,
        sessions=len({row["session"] for row in rows}),
        inference_sources=sorted({row["inference_source"] for row in rows}),
        contains_injected_or_unverified_predictor=any(
            row["inference_source"] != "live_cuda_yolo" for row in rows),
        distance_available_frames=sum(row["distance_available"] for row in rows),
        bbox_count_frames=dict(Counter(str(item["bbox_count"]) for item in flat)),
        support_point_frames=sum(item["support_x"] is not None for item in flat),
        mask_diagnostic_frames=sum(item["contour_count"] is not None for item in flat),
        touching_edge_frames=dict(Counter(
            edge for item in flat for edge in (item["touching_edges"].split(";")
                                               if item["touching_edges"] else []))),
        pose_available_frames=sum(bool(item["pose_available"]) for item in flat),
        within_freshness_limit_frames=sum(bool(item["within_limit"]) for item in flat),
        reasons=dict(Counter(row["reason"] for row in rows)),
        blockers=dict(Counter(blocker for row in rows for blocker in set(row["blockers"]))),
        support_reasons=dict(Counter(item["support_reason"] for item in flat)),
        quality_reasons=dict(Counter(item["quality_reason"] for item in flat)),
        pose_reasons=dict(Counter(item["pose_reason"] for item in flat)),
        scene_reasons=dict(Counter(item["scene_reason"] for item in flat)),
        floor_config_sha256=sorted({item["floor_config_sha256"] for item in flat}),
        source_sha256={str(args.input_dir / "distance_frames.jsonl"): source_sha},
        physical_metric_verified=False, floor_contact_verified=False,
        usable_for_ffb=False,
        meaning="same-frame evidence transcription only; NOT floor-contact proof or distance accuracy")
    (args.output_dir / "counts.json").write_text(
        json.dumps(counts, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({key: counts[key] for key in (
        "status", "processed_frames", "evidence_frames", "contains_injected_or_unverified_predictor",
        "distance_available_frames", "support_point_frames", "pose_available_frames")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
