#!/usr/bin/env python3
"""Saved-data-only evaluation of what a cone support point physically represents.

No image decoding, YOLO inference, HSV re-extraction, calibration fit, or live
integration.  Every number is derived from previously saved CSV/JSON evidence.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
ER = ROOT / "Experimental_results"

POSITIONS = ER / "2026-10-19/cone_contact_reuse_r01/full_replay_r01/positions.csv"
PIXELS = ER / "2026-10-19/cone_contact_reuse_r01/full_replay_r01/pixels.csv"
PAIRED = ER / "2026-10-19/cone_contact_reuse_r01/results_r01/paired_anchors.csv"
ENVELOPES = ER / "2026-10-19/cone_support_extent_r01/results_r01/lower_envelopes.csv"
EXTENT_OBS = ER / "2026-10-19/cone_support_extent_r01/results_r01/observations.csv"
QUALITY_OBS = ER / "2026-10-19/cone_support_quality_r01/results_r02/observations.csv"
CONTACT_CANDIDATES = ER / "2026-10-15/floor_cone_same_pose_analysis_r01/contact_candidates.csv"
PAPER_PROJECTION = ER / "2026-10-19/paper_cone_2m_validation_r01/analysis_r01/paper_projection.csv"
CONE_SAME_COLUMN = ER / "2026-10-19/paper_cone_2m_validation_r01/analysis_r01/cone_same_column_projection.csv"
FIXED_RANGES = ER / "2026-10-30/floor_pose_fixed_mode_r01/evaluation_r01/ranges.csv"
FIXED_SUPPORT = ER / "2026-10-30/floor_pose_fixed_mode_r01/evaluation_r01/support_sources.csv"
HEIGHT_SENSITIVITY = ER / "2026-10-30/floor_pose_fixed_mode_r01/evaluation_r01/height_sensitivity.csv"
CURRENT_PAIR = ER / "2026-10-30/cone_completion_logging_r01/current_pair_r01/results.json"
COLOUR_CONTROLS = ER / "2026-10-30/cone_saved_frame_audit_r01/findings_r01/colour_controls.json"
FIXED_SUMMARY = ER / "2026-10-30/floor_pose_fixed_mode_r01/evaluation_r01/summary.json"

SESSION_SEQUENCE = "floor_cone_same_pose_r01_20261015_160621_378"
MEASURED_HEIGHT_MM = 590.0
BASE_SIDE_M = 0.375
APPROX_TILE_M = 1.5

INPUTS = [
    POSITIONS,
    PIXELS,
    PAIRED,
    ENVELOPES,
    EXTENT_OBS,
    QUALITY_OBS,
    CONTACT_CANDIDATES,
    PAPER_PROJECTION,
    CONE_SAME_COLUMN,
    FIXED_RANGES,
    FIXED_SUPPORT,
    HEIGHT_SENSITIVITY,
    CURRENT_PAIR,
    COLOUR_CONTROLS,
    FIXED_SUMMARY,
]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict]) -> None:
    if not rows:
        raise ValueError(f"refusing to write empty table: {path}")
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fields})


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fnum(value):
    if value is None or value == "":
        return None
    return float(value)


def inum(value):
    if value is None or value == "":
        return None
    return int(float(value))


def median(values):
    return float(np.median(values)) if values is not None and len(values) else None


def pct(values, q):
    return float(np.percentile(values, q)) if values is not None and len(values) else None


def implied_height_mm(model_height_m: float, reference_m: float, projected_m: float) -> float:
    if projected_m is None or projected_m <= 0 or reference_m is None:
        raise ValueError("invalid projection for implied height")
    return model_height_m * reference_m / projected_m * 1000.0


# ---------------------------------------------------------------- implied height


def implied_height_rows(positions: list[dict]) -> list[dict]:
    grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in positions:
        if row["v_min"] != "30" or row["model"] != "height_only59":
            continue
        if row["colour_z_m"] and row["reference_z_m"]:
            grouped[(row["dataset"], row["condition"])].append(row)

    output = []
    for (dataset, condition), rows in sorted(grouped.items()):
        reference = fnum(rows[0]["reference_z_m"])
        colour = np.array([fnum(r["colour_z_m"]) for r in rows])
        bbox = np.array([fnum(r["bbox_z_m"]) for r in rows if r["bbox_z_m"]])
        heights = 590.0 * reference / colour
        bbox_heights = 590.0 * reference / bbox if len(bbox) else np.array([])
        by_frame = sorted(rows, key=lambda r: inum(r["frame"]))
        adjacent = []
        for previous, current in zip(by_frame, by_frame[1:]):
            if inum(current["frame"]) - inum(previous["frame"]) != 1:
                continue
            adjacent.append(abs(fnum(current["colour_z_m"]) - fnum(previous["colour_z_m"])))
        support_width = None
        support_widths = [
            fnum(r["span_px"])
            for r in read_csv(EXTENT_OBS)
            if r["dataset"] == dataset
            and r["condition"] == condition
            and r["envelope_available"] == "True"
            and r["span_px"]
        ]
        if support_widths:
            support_width = median(support_widths)
        required_distance = reference * 590.0 / median(heights) if median(heights) else None
        output.append(
            {
                "dataset": dataset,
                "condition": condition,
                "model": "height_only59",
                "reference_z_m": round(reference, 6),
                "colour_frames": len(colour),
                "colour_z_median_m": round(float(np.median(colour)), 6),
                "colour_z_p05_m": round(pct(colour, 5), 6),
                "colour_z_p95_m": round(pct(colour, 95), 6),
                "colour_implied_height_median_mm": round(float(np.median(heights)), 3),
                "colour_implied_height_p05_mm": round(pct(heights, 5), 3),
                "colour_implied_height_p95_mm": round(pct(heights, 95), 3),
                "adjacent_frame_abs_delta_median_mm": round(median(adjacent) * 1000.0, 4),
                "bbox_implied_height_median_mm": round(float(np.median(bbox_heights)), 3)
                if len(bbox_heights)
                else None,
                "support_span_median_px": support_width,
                "distance_required_for_590mm_m": round(required_distance, 6),
                "offset_required_from_label_m": round(required_distance - reference, 6),
                "required_offset_exceeds_base_side": bool(
                    abs(required_distance - reference) > BASE_SIDE_M
                ),
                "interpretation": (
                    "relative_floor_correspondence_supported_but_absolute_geometry_not_checked"
                    if dataset == "sequence"
                    else "nominal_label_only_no_same_session_floor_marker"
                ),
                "floor_contact_verified": False,
                "usable_for_ffb": False,
            }
        )
    return output


# ------------------------------------------------------- same-session floor checks


def envelope_y_at(rows: list[dict], dataset: str, session: str, frame: int, x: int):
    values = [
        fnum(r["y"])
        for r in rows
        if r["dataset"] == dataset
        and r["session"] == session
        and inum(r["frame"]) == frame
        and abs(fnum(r["x"]) - x) < 1e-9
    ]
    return median(values)


def within_session_rows() -> list[dict]:
    envelopes = read_csv(ENVELOPES)
    paired = [
        r
        for r in read_csv(PAIRED)
        if r["model"] == "height_only59" and r["dataset"] == "sequence"
    ]
    floor_candidates = {
        r["point_id"]: r
        for r in read_csv(CONTACT_CANDIDATES)
        if r["kind"] == "floor"
    }
    cone_candidates = {
        r["point_id"]: r
        for r in read_csv(CONTACT_CANDIDATES)
        if r["kind"] == "cone"
    }
    positions = [
        r
        for r in read_csv(POSITIONS)
        if r["v_min"] == "30"
        and r["model"] == "height_only59"
        and r["dataset"] == "sequence"
        and r["colour_z_m"]
    ]

    output = []
    for point_id, anchor_frame, window in (
        ("C130", 563, (563, 780)),
        ("C200", 1265, (1000, 1547)),
    ):
        anchor = next(r for r in paired if r["condition"] == f"cone_{point_id[1:]}")
        floor = floor_candidates[point_id]
        cone_anchor = cone_candidates.get(point_id, {})
        floor_x = inum(floor["pixel_x"])
        floor_y = inum(floor["pixel_y"])
        reference = fnum(anchor["reference_z_m"])
        floor_z = fnum(anchor["floor_z_m"])
        cone_z = fnum(anchor["colour_z_m"])
        cone_y = envelope_y_at(envelopes, "sequence", SESSION_SEQUENCE, anchor_frame, floor_x)
        window_rows = [
            r for r in positions if window[0] <= inum(r["frame"]) <= window[1]
        ]
        window_cone_z = median([fnum(r["colour_z_m"]) for r in window_rows])
        window_cone_y = median(
            [
                y
                for y in (
                    envelope_y_at(
                        envelopes,
                        "sequence",
                        SESSION_SEQUENCE,
                        inum(r["frame"]),
                        floor_x,
                    )
                    for r in window_rows
                )
                if y is not None
            ]
        )
        output.append(
            {
                "session": "2026-10-15 same-pose",
                "case": point_id,
                "reference_kind": "same_recording_floor_V_tip",
                "reference_pixel": f"({floor_x},{floor_y})",
                "reference_candidate_kind": floor["kind"],
                "cone_candidate_pixel": (
                    f"({cone_anchor['pixel_x']},{cone_anchor['pixel_y']})"
                    if cone_anchor
                    else None
                ),
                "cone_support_column_x": floor_x,
                "cone_envelope_y_at_reference_column": cone_y,
                "window_cone_envelope_y_median": window_cone_y,
                "pixel_row_delta_cone_minus_floor": (
                    round(cone_y - floor_y, 3) if cone_y is not None else None
                ),
                "reference_z_m": round(reference, 6),
                "floor_z_m": round(floor_z, 6),
                "cone_z_m": round(cone_z, 6),
                "window_cone_z_median_m": round(window_cone_z, 6),
                "cone_minus_floor_equivalent_distance_m": round(cone_z - floor_z, 6),
                "floor_implied_height_mm": round(
                    implied_height_mm(0.59, reference, floor_z), 3
                ),
                "cone_implied_height_mm": round(
                    implied_height_mm(0.59, reference, cone_z), 3
                ),
                "delta_implied_height_mm": round(
                    implied_height_mm(0.59, reference, cone_z)
                    - implied_height_mm(0.59, reference, floor_z),
                    3,
                ),
                "reference_is_physical_gt": False,
                "reference_note": "assistant non-blind visual candidate; camera static within recording",
                "floor_contact_verified": False,
                "usable_for_ffb": False,
            }
        )

    paper_rows = [
        r
        for r in read_csv(PAPER_PROJECTION)
        if r["model"] == "height_only59"
        and r["threshold"] == "170"
        and r["phase"] == "paper_before"
        and r["kind"] == "paper_local_corner"
    ]
    paper = paper_rows[0]
    cone_rows = [
        r
        for r in read_csv(CONE_SAME_COLUMN)
        if r["model"] == "height_only59"
        and r["phase"] == "cone_static"
        and r["kind"] == "cone_actual_same_x_column"
        and r["pixel_x"] == paper["pixel_x"]
    ]
    cone = cone_rows[0]
    paper_z = fnum(paper["z_m"])
    cone_z = fnum(cone["z_m"])
    nominal = 2.0
    output.append(
        {
            "session": "2026-10-19 paper+cone",
            "case": "paper_corner_same_column",
            "reference_kind": "same_recording_floor_level_paper_corner",
            "reference_pixel": f"({paper['pixel_x']},{paper['pixel_y']})",
            "reference_candidate_kind": "paper_local_corner",
            "cone_candidate_pixel": f"({cone['pixel_x']},{cone['pixel_y']})",
            "cone_support_column_x": inum(cone["pixel_x"]),
            "cone_envelope_y_at_reference_column": inum(cone["pixel_y"]),
            "window_cone_envelope_y_median": inum(cone["pixel_y"]),
            "pixel_row_delta_cone_minus_floor": 0,
            "reference_z_m": nominal,
            "floor_z_m": round(paper_z, 6),
            "cone_z_m": round(cone_z, 6),
            "window_cone_z_median_m": round(cone_z, 6),
            "cone_minus_floor_equivalent_distance_m": round(cone_z - paper_z, 6),
            "floor_implied_height_mm": round(
                implied_height_mm(0.59, nominal, paper_z), 3
            ),
            "cone_implied_height_mm": round(
                implied_height_mm(0.59, nominal, cone_z), 3
            ),
            "delta_implied_height_mm": 0.0,
            "paper_frames": len(paper_rows),
            "cone_frames": len(cone_rows),
            "reference_is_physical_gt": False,
            "reference_note": (
                "floor-level paper corner; exact same-column pixel identity, "
                "but corner-to-base correspondence not surveyed"
            ),
            "floor_contact_verified": False,
            "usable_for_ffb": False,
        }
    )
    return output


# -------------------------------------------------------------- category audit


def category_rows() -> list[dict]:
    pixels = [r for r in read_csv(PIXELS) if r["v_min"] == "30"]
    reasons = Counter(r["colour_reason"] for r in pixels)
    ambiguous = [
        r
        for r in pixels
        if r["candidates"] not in ("", "0", "1")
    ]
    quality = read_csv(QUALITY_OBS)
    sequence_quality = {
        inum(r["frame"]): r
        for r in quality
        if r["dataset"] == "sequence"
        and r["session"] == SESSION_SEQUENCE
    }
    extent = {
        (inum(r["frame"])): r
        for r in read_csv(EXTENT_OBS)
        if r["dataset"] == "sequence" and r["session"] == SESSION_SEQUENCE
    }
    positions = {
        inum(r["frame"]): r
        for r in read_csv(POSITIONS)
        if r["v_min"] == "30"
        and r["model"] == "height_only59"
        and r["dataset"] == "sequence"
        and r["session"] == SESSION_SEQUENCE
    }
    occlusion = [f for f in range(1124, 1140)]
    occluded_rejected = [
        f for f in occlusion if sequence_quality.get(f, {}).get("quality_accepted") == "False"
    ]
    occluded_with_support = [
        f
        for f in occlusion
        if extent.get(f, {}).get("envelope_available") == "True"
        and sequence_quality.get(f, {}).get("quality_accepted") == "False"
    ]
    occl_1133 = positions.get(1133, {})
    occl_1134 = positions.get(1134, {})

    controls = json.loads(COLOUR_CONTROLS.read_text())
    red_box, yellow_box = controls["boxes"]
    yellow_control = next(c for c in yellow_box["colour_controls"] if c["colour"] == "yellow" and c["margin"] == 4)
    red_in_yellow = next(c for c in yellow_box["colour_controls"] if c["colour"] == "red" and c["margin"] == 4)
    red_mixed = next(c for c in red_box["colour_controls"] if c["colour"] == "both" and c["margin"] == 4)
    red_only = next(c for c in red_box["colour_controls"] if c["colour"] == "red" and c["margin"] == 4)

    fixed_support = read_csv(FIXED_SUPPORT)
    support_map = {
        (inum(r["frame"]), r["source"]): r["support_x"] and f"({r['support_x']},{r['support_y']})" or None
        for r in fixed_support
    }

    rows = []

    def add(category, case, observation, accepted, reference, result, interpretation):
        rows.append(
            {
                "category": category,
                "case": case,
                "saved_observation": observation,
                "support_accepted_for_evaluation": accepted,
                "physical_reference": reference,
                "result": result,
                "interpretation": interpretation,
                "floor_contact_verified": False,
                "usable_for_ffb": False,
            }
        )

    add(
        "baseline",
        "10/15 central static 0.80/1.30/2.00 m",
        "saved colour support, 682/651/632 frames at V30",
        True,
        "nominal installation label only; reference point and placement error not measured",
        "implied height 531.7/502.0/446.1 mm vs measured 590 mm",
        "not independently evaluable; at 2.00 m the required +0.646 m offset exceeds the 0.375 m base side",
    )
    add(
        "lateral",
        "10/15 left/right static 1.30 m",
        "saved colour support, 621/626 frames at V30",
        True,
        "nominal label; lateral reference ±0.40 m is an inner-edge convention, not base centre",
        "implied height 538.3/490.4 mm; adjacent-frame median change 15.0/23.1 mm",
        "not independently evaluable; lateral geometry and reference-point definition are not separable",
    )
    add(
        "same-session floor reference",
        "10/15 continuous 1.30/2.00 m",
        "saved colour support and same-recording floor V tip",
        True,
        "floor V tip in the same recording, different frame; non-blind visual candidate",
        "support-floor pixel delta +1/0 px; equivalent distance -1.9/+0.8 cm; implied height 589.9/592.7 mm",
        "relative floor correspondence is supported in this session; absolute height is supplied, not independently measured",
    )
    add(
        "same-session floor reference",
        "10/19 paper+cone 2.00 m",
        "saved same-column cone lower edge and floor-level paper corner",
        True,
        "paper local corner on the floor; same column X=313, exact pixel identity",
        "both at (313,371) and 3.5692 m; implied height 330.6 mm at nominal 2.00 m",
        "relative floor correspondence is exact, but the absolute geometry is inconsistent; the support point is not the cause of the metric error",
    )
    add(
        "completion",
        "10/30 frame1259 lateral completion shadow",
        f"baseline withheld (ROI edge); completion shadow {support_map.get((1259, 'lateral_completion_shadow'))} with 40 support pixels",
        True,
        "no independent floor marker at the contact; fixed-floor models and approximate 1.5 m tiles only",
        "conditional union range 1.404-1.528 m (per-frame control excluded); "
        "primary 1 px control 1.428-1.476 m at 590 mm, so 1.5 m lies in the union "
        "but in no single model's control",
        "completion fixes image coverage, not physical contact; union containment is "
        "not agreement between models; do not promote to controlling distance",
    )
    add(
        "baseline still",
        "10/30 frame1655 baseline colour shadow",
        f"baseline colour support {support_map.get((1655, 'baseline_colour_shadow'))}; completion keeps the same point",
        True,
        "no independent floor marker at the contact; fixed-floor models and approximate 1.5 m tiles only",
        "conditional union range 1.403-1.526 m; primary 1 px control "
        "1.428-1.475 m at 590 mm",
        "same limitation as frame1259; stability across two stills is not proof of "
        "floor contact, and union containment is not model agreement",
    )
    add(
        "yellow + same-colour floor",
        "10/30 saved image f004903 yellow cone",
        f"yellow-only mask bounds {yellow_control['contour_bounds_xyxy']} touches {yellow_control['touches']}; "
        f"red sub-blob {red_in_yellow['contour_bounds_xyxy']} area {red_in_yellow['contour_areas'][0]} px2",
        False,
        "none accepted; the full yellow region is connected to the surrounding floor",
        "red sub-blob bottom y=359 vs full yellow envelope bottom y=401 (42 px above)",
        "using the red sub-blob would create a false support point; withholding is correct",
    )
    add(
        "occluded",
        "10/15 sequence frames 1124-1139",
        f"{len(occluded_rejected)} of {len(occlusion)} frames rejected by the image-quality gate; "
        f"{len(occluded_with_support)} rejected frames still had a visible support boundary",
        False,
        "normal floor contact row is y≈393; occlusion boundary at y=360/367 in frames 1133/1134",
        f"frame1133 colour point ({occl_1133.get('pixel_x')},{occl_1133.get('pixel_y')}); "
        f"frame1134 ({occl_1134.get('pixel_x')},{occl_1134.get('pixel_y')}); both outside the 4 m diagnostic range",
        "a visible support boundary is not a floor contact; quality rejection is correct",
    )
    add(
        "small/distant",
        "10/15 2.00 m static vs continuous",
        "support span median 27 px static / 31 px continuous; 632/539 accepted frames",
        True,
        "same nominal 2.00 m, different session",
        "implied height 446.1 mm static vs 592.7 mm continuous",
        "small size alone does not invalidate the point; the same nominal distance yields different implied heights across sessions",
    )
    add(
        "multiple candidates",
        "10/15 right_130 frames 54/56/57",
        f"{len(ambiguous)} frames with {sorted(set(r['candidates'] for r in ambiguous))} candidates; all colour_reason=ambiguous_candidates",
        False,
        "no support point selected",
        "withheld rather than choosing the largest score",
        "correct non-selection; no physical correspondence can be evaluated",
    )
    add(
        "crop/ROI edge",
        "10/15 V30 colour contour reaches ROI edge",
        f"{reasons.get('colour_contour_reaches_roi_edge', 0)} frames; "
        f"no_candidate {reasons.get('no_candidate', 0)} frames",
        False,
        "no support point from the baseline path",
        "10/30 frame1259 is the only current still recovered by the lateral-completion shadow",
        "edge contact is not floor contact; completion is an unverified coverage fix",
    )
    add(
        "top/bottom crop contact",
        "10/30 saved image f004903 red mixed and yellow masks",
        f"red mixed touches bottom={red_mixed['touches']['bottom']}; "
        f"red-only touches bottom={red_only['touches']['bottom']}; "
        f"yellow touches bottom={yellow_control['touches']['bottom']}",
        False,
        "crop boundary, not a physical reference",
        "bottom contact cannot be separated from floor contact by the mask alone",
        "rejecting bottom-connected masks is appropriate; no top contact was observed in this saved image",
    )
    return rows


# ----------------------------------------------------------- fixed-floor 10/30


def fixed_floor_rows() -> tuple[list[dict], dict]:
    ranges = [
        r
        for r in read_csv(FIXED_RANGES)
        if r["horizontal_camera_foot_range_m"]
    ]
    output = []
    for row in ranges:
        output.append(
            {
                "frame": inum(row["frame"]),
                "support_source": row["support_source"],
                "support_point": f"({row['support_x']},{row['support_y']})",
                "model": row["model"],
                "model_role": row["model_role"],
                "horizontal_camera_foot_range_m": round(
                    fnum(row["horizontal_camera_foot_range_m"]), 6
                ),
                "one_pixel_control_min_m": (
                    round(fnum(row["support_1px_control_min_m"]), 6)
                    if fnum(row["support_1px_control_min_m"]) is not None
                    else None
                ),
                "one_pixel_control_max_m": (
                    round(fnum(row["support_1px_control_max_m"]), 6)
                    if fnum(row["support_1px_control_max_m"]) is not None
                    else None
                ),
                "approximate_tile_reference_m": APPROX_TILE_M,
                "approximate_reference_used_for_selection": False,
                "approximate_reference_agreement": (
                    bool(
                        fnum(row["support_1px_control_min_m"])
                        <= APPROX_TILE_M
                        <= fnum(row["support_1px_control_max_m"])
                    )
                    if fnum(row["support_1px_control_min_m"]) is not None
                    and fnum(row["support_1px_control_max_m"]) is not None
                    else None
                ),
                "status": row["status"],
                "physical_metric_verified": False,
                "floor_contact_verified": False,
                "usable_for_ffb": False,
            }
        )

    sensitivity = read_csv(HEIGHT_SENSITIVITY)
    compatibility = {}
    for frame, source in ((1259, "lateral_completion_shadow"), (1655, "baseline_colour_shadow")):
        rows = [
            r
            for r in sensitivity
            if inum(r["frame"]) == frame and r["support_source"] == source
        ]
        closest = min(
            rows,
            key=lambda r: abs(fnum(r["horizontal_camera_foot_range_m"]) - APPROX_TILE_M),
        )
        compatibility[f"{frame}/{source}"] = {
            "closest_input_height_mm": round(fnum(closest["camera_to_floor_m"]) * 1000.0, 3),
            "range_at_closest_height_m": round(
                fnum(closest["horizontal_camera_foot_range_m"]), 6
            ),
            "measured_height_range_m": round(
                next(
                    fnum(r["horizontal_camera_foot_range_m"])
                    for r in rows
                    if abs(fnum(r["camera_to_floor_m"]) - 0.59) < 1e-9
                ),
                6,
            ),
            "used_for_model_selection": False,
        }
    return output, compatibility


# ------------------------------------------------------------------- plot


def make_plot(output_dir: Path, implied: list[dict], within: list[dict]) -> None:
    import os

    os.environ.setdefault("MPLCONFIGDIR", "/tmp/support_point_physical_eval_matplotlib")
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    labels = []
    medians = []
    lows = []
    highs = []
    for row in implied:
        if row["dataset"] == "sequence":
            label = "seq " + row["condition"]
        else:
            label = "static " + row["condition"]
        labels.append(label)
        medians.append(row["colour_implied_height_median_mm"])
        lows.append(row["colour_implied_height_median_mm"] - row["colour_implied_height_p05_mm"])
        highs.append(row["colour_implied_height_p95_mm"] - row["colour_implied_height_median_mm"])

    fig, axes = plt.subplots(1, 2, figsize=(13, 5.2), layout="constrained")
    x = np.arange(len(labels))
    axes[0].errorbar(x, medians, yerr=[lows, highs], fmt="o", capsize=3, color="#1f4e79")
    axes[0].axhline(MEASURED_HEIGHT_MM, color="black", lw=1.2, ls="--", label="user measured 590 mm")
    axes[0].set_xticks(x, labels, rotation=35, ha="right", fontsize=8)
    axes[0].set_ylabel("implied lens height [mm]")
    axes[0].set_title("If the support point were the floor contact at the label distance")
    axes[0].grid(alpha=0.3)
    axes[0].legend(fontsize=8)

    wx = np.arange(len(within))
    floor_h = [row["floor_implied_height_mm"] for row in within]
    cone_h = [row["cone_implied_height_mm"] for row in within]
    axes[1].bar(wx - 0.18, floor_h, 0.36, label="same-session floor reference")
    axes[1].bar(wx + 0.18, cone_h, 0.36, label="cone support point")
    axes[1].axhline(MEASURED_HEIGHT_MM, color="black", lw=1.2, ls="--", label="user measured 590 mm")
    axes[1].set_xticks(wx, [row["case"] for row in within], fontsize=9)
    axes[1].set_ylabel("implied lens height [mm]")
    axes[1].set_title("Relative floor correspondence vs absolute geometry")
    axes[1].grid(axis="y", alpha=0.3)
    axes[1].legend(fontsize=8)

    fig.savefig(output_dir / "support_point_physical_meaning.png", dpi=150)
    plt.close(fig)


# --------------------------------------------------------------------- main


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    output_dir = Path(args.output_dir)
    if output_dir.exists():
        raise ValueError("new output directory required; do not overwrite frozen results")
    output_dir.mkdir(parents=True)

    input_hashes = {str(path.relative_to(ROOT)): sha256(path) for path in INPUTS}

    positions = read_csv(POSITIONS)
    implied = implied_height_rows(positions)
    within = within_session_rows()
    categories = category_rows()
    fixed, compatibility = fixed_floor_rows()

    write_csv(output_dir / "implied_height_by_condition.csv", implied)
    write_csv(output_dir / "within_session_floor_check.csv", within)
    write_csv(output_dir / "category_audit.csv", categories)
    write_csv(output_dir / "fixed_floor_1030.csv", fixed)
    make_plot(output_dir, implied, within)

    by_condition = {
        f"{row['dataset']}/{row['condition']}": {
            "implied_height_median_mm": row["colour_implied_height_median_mm"],
            "implied_height_p05_mm": row["colour_implied_height_p05_mm"],
            "implied_height_p95_mm": row["colour_implied_height_p95_mm"],
            "adjacent_abs_delta_median_mm": row["adjacent_frame_abs_delta_median_mm"],
            "offset_required_from_label_m": row["offset_required_from_label_m"],
            "required_offset_exceeds_base_side": row["required_offset_exceeds_base_side"],
        }
        for row in implied
    }
    within_by_case = {
        row["case"]: {
            "reference_kind": row["reference_kind"],
            "reference_pixel": row["reference_pixel"],
            "pixel_row_delta_cone_minus_floor": row["pixel_row_delta_cone_minus_floor"],
            "cone_minus_floor_equivalent_distance_m": row[
                "cone_minus_floor_equivalent_distance_m"
            ],
            "floor_implied_height_mm": row["floor_implied_height_mm"],
            "cone_implied_height_mm": row["cone_implied_height_mm"],
            "delta_implied_height_mm": row["delta_implied_height_mm"],
        }
        for row in within
    }
    summary = {
        "status": "COMPLETED_SAVED_DATA_SUPPORT_POINT_PHYSICAL_MEANING_AUDIT",
        "measured_lens_height_mm": MEASURED_HEIGHT_MM,
        "base_side_m": BASE_SIDE_M,
        "approximate_tile_reference_m": APPROX_TILE_M,
        "inputs_are_saved_data_only": True,
        "new_yolo_inference": False,
        "new_image_decoding": False,
        "hsv_reextraction": False,
        "calibration_or_pose_fit": False,
        "support_point_moved_to_reference": False,
        "reference_distance_used_for_model_or_point_selection": False,
        "approximate_tile_used_for_model_selection": False,
        "completion_shadow_promoted_to_controlling_distance": False,
        "yellow_rescued_by_red_subblob": False,
        "implied_height_by_condition": by_condition,
        "within_session_floor_check": within_by_case,
        "fixed_floor_1030_compatibility": compatibility,
        "counts": {
            "implied_height_rows": len(implied),
            "within_session_rows": len(within),
            "category_rows": len(categories),
            "fixed_floor_rows": len(fixed),
        },
        "conclusion": {
            "relative_floor_correspondence": (
                "supported within two sessions with a same-session floor marker "
                "(0 px at the 10/19 paper column; +1/0 px vs the 10/15 floor V at 1.30/2.00 m)"
            ),
            "absolute_metric": (
                "not verified: implied height is 589.9/592.7 mm in the 10/15 continuous session "
                "but 446.1 mm for the 10/15 static 2.00 m and 330.6 mm for the 10/19 paper+cone 2.00 m"
            ),
            "temporal_smoothness": (
                "adjacent-frame change is sub-mm for the continuous 1.30 m and 0.6 mm for 2.00 m, "
                "yet the static 2.00 m session is also smooth (2.6 mm) while implying 446.1 mm; "
                "smoothness is not correctness"
            ),
            "completion_and_yellow": (
                "lateral completion is an image-coverage fix, not a contact proof; "
                "the approximate 1.5 m lies only in the union of conditional ranges, "
                "not in any single model's 1 px control; the yellow cone connected to "
                "the same-colour floor remains withheld"
            ),
            "fundamental_limit": (
                "a single support pixel cannot separate height above the floor from depth along the ray; "
                "a same-ray floor marker is necessary but not sufficient evidence"
            ),
        },
        "physical_metric_verified": False,
        "floor_contact_verified": False,
        "usable_for_ffb": False,
    }
    (output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    output_hashes = {
        path.name: sha256(path)
        for path in sorted(output_dir.iterdir())
        if path.is_file()
    }
    provenance = {
        "status": "SAVED_DATA_ONLY_NO_INFERENCE_NO_LIVE_INTEGRATION",
        "method": str((HERE / "method.md").relative_to(ROOT)),
        "method_sha256": sha256(HERE / "method.md"),
        "analysis": str(Path(__file__).relative_to(ROOT)),
        "analysis_sha256": sha256(Path(__file__)),
        "input_sha256": input_hashes,
        "output_sha256": output_hashes,
        "physical_metric_verified": False,
        "floor_contact_verified": False,
        "usable_for_ffb": False,
    }
    (output_dir / "provenance.json").write_text(
        json.dumps(provenance, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    print("implied height [mm] by condition")
    for row in implied:
        print(
            f"  {row['dataset']:8} {row['condition']:10} "
            f"median={row['colour_implied_height_median_mm']:7.1f} "
            f"p05-p95={row['colour_implied_height_p05_mm']:7.1f}-{row['colour_implied_height_p95_mm']:7.1f} "
            f"adj_delta={row['adjacent_frame_abs_delta_median_mm']:6.2f} mm "
            f"required_offset={row['offset_required_from_label_m']:+.3f} m"
        )
    print("within-session floor checks")
    for row in within:
        print(
            f"  {row['session']:26} {row['case']:24} "
            f"pixel_delta={row['pixel_row_delta_cone_minus_floor']} "
            f"distance_delta={row['cone_minus_floor_equivalent_distance_m']:+.4f} m "
            f"implied={row['floor_implied_height_mm']:.1f}/{row['cone_implied_height_mm']:.1f} mm"
        )
    print(f"wrote {output_dir}")


if __name__ == "__main__":
    main()
