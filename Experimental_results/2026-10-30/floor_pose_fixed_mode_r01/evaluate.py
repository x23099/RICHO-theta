#!/usr/bin/env python3
"""Build explicit session floor models and evaluate the isolated candidate.

Existing saved images and CPU detections only. No camera, GPU inference, ROS,
TF, FFB, model retraining or intrinsic refit. The user's approximate 1.5 m is
recorded as context but is never passed to fitting, model selection or scoring.
"""
import argparse
import csv
import json
from pathlib import Path
import sys

import cv2
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "src"))
from cone_colour_support_candidate import observe_separated_support
from cone_distance_core import digest, load_config
from cone_fixed_floor_candidate import (COORDINATE_FRAME, SCHEMA, measure_support)
from cone_support_completion_candidate import observe_lateral_completion

SESSION = "15ae673c24484d119952ae391df611aa"
FRAMES = (1259, 1655)
BOARD = ROOT / "Experimental_results/2026-10-30/floor_board_pair_r01"
INTRINSIC = BOARD / "intrinsic_consistency_r02/intrinsic_consistency.json"
EDGE = BOARD / "edge_refinement_r02/edge_refinement.json"
ORIGINALS = BOARD / "originals"
AUDITS = BOARD / "cone_same_session_r01"
INTAKE = ROOT / "recordings/2026-10-30_floor_board_intake_r01"
SAVED_PAIR = ROOT / "Experimental_results/2026-10-30/cone_completion_logging_r01/current_pair_r01/results.json"

ACTIVE_FALSE = dict(physical_metric_verified=False, floor_contact_verified=False,
                    usable_for_ffb=False, controlling_distance=False,
                    live_integrated=False, published_to_ros=False)


def sha_tree(paths):
    return {str(Path(p)): digest(Path(p)) for p in paths}


def image_path(frame):
    return ORIGINALS / f"decoded_{SESSION}_f{frame:06d}.png"


def audit_path(frame):
    return AUDITS / f"inference_f{frame:06d}/audit.json"


def build_models(case, config):
    free = case["shared_plane_best_local"]
    anchored = case["externally_anchored_printed_plane_0p575m"]
    heading = dict(path=config["floor_candidate"], sha256=config["floor_sha256"])
    common_assumptions = [
        "the board was flat on the floor and its printed surface is parallel to the floor",
        "the camera and capture geometry did not move within this session",
        "the heading reference supplies orientation only; the origin is the camera vertical floor projection",
        "radial range is independent of yaw; forward/lateral are NOT measured base_link axes",
    ]
    common_invalidation = [
        "camera mount, lens, USB capture or image geometry changes",
        "the board is not flat, is handheld, or is not on the same floor plane",
        "a frame from another session is evaluated with this model",
        "the model is used as a physical base_link transform or an FFB input",
    ]
    models = [
        dict(schema=SCHEMA, name="shared_free_plane_plus_approx_board_thickness",
             session=SESSION, normal_optical=free["normal_optical"],
             camera_to_floor_m=free["camera_to_printed_plane_m"]+.015,
             coordinate_frame=COORDINATE_FRAME, heading_reference=heading,
             evidence=["shared free-height printed-plane fit on two board frames",
                       "estimated printed-plane height %.9f m" % free["camera_to_printed_plane_m"],
                       "user supplied approximate board-plus-paper thickness 15 mm"],
             assumptions=common_assumptions+[
                 "adding the approximate 15 mm thickness gives the floor height"],
             invalidation_conditions=common_invalidation,
             role="conditional_primary", **ACTIVE_FALSE),
        dict(schema=SCHEMA, name="externally_anchored_height_and_normal",
             session=SESSION, normal_optical=anchored["normal_optical"],
             camera_to_floor_m=.590, coordinate_frame=COORDINATE_FRAME,
             heading_reference=heading,
             evidence=["printed-plane normal fitted with printed-plane height fixed to 575 mm",
                       "user reported lens-centre floor height 590 mm",
                       "575 mm = 590 mm minus approximate 15 mm board thickness"],
             assumptions=common_assumptions+[
                 "the external 590 mm height is treated as a fixed input, not an image result"],
             invalidation_conditions=common_invalidation,
             role="conditional_primary", **ACTIVE_FALSE),
        dict(schema=SCHEMA, name="external_height_only_free_fit_normal",
             session=SESSION, normal_optical=free["normal_optical"],
             camera_to_floor_m=.590, coordinate_frame=COORDINATE_FRAME,
             heading_reference=heading,
             evidence=["shared free-height printed-plane normal",
                       "user reported lens-centre floor height 590 mm"],
             assumptions=common_assumptions+[
                 "mixing a free-fit normal with the external height is a counterfactual control"],
             invalidation_conditions=common_invalidation,
             role="counterfactual_control", **ACTIVE_FALSE),
    ]
    return models


def per_frame_models(edge, heading):
    controls = []
    for comparison in edge["comparisons"]:
        if (comparison["threshold"] == 170 and comparison["method"] == "intensity_crossings"
                and comparison["trim_fraction"] == .15 and comparison["seed_edge_gate_px"] == 4):
            for row in comparison["frames"]:
                controls.append(dict(
                    schema=SCHEMA, name="per_frame_printed_plane_normal_external_height",
                    session=SESSION, frame=row["frame"],
                    normal_optical=row["normal_optical"], camera_to_floor_m=.590,
                    coordinate_frame=COORDINATE_FRAME,
                    heading_reference=heading,
                    evidence=["same-frame printed-plane edge refinement normal",
                              "external 590 mm height input"],
                    assumptions=["normal is parallel to the floor; same-frame board is not an independent holdout"],
                    invalidation_conditions=["use only as a sensitivity control, never as a selected model"],
                    role="sensitivity_only", **ACTIVE_FALSE))
            return controls
    raise ValueError("primary edge-refinement control not found")


def support_sources(frame, camera):
    image = cv2.imread(str(image_path(frame)))
    if image is None or image.shape != (720, 1280, 3):
        raise ValueError("native 1280x720 decoded image required")
    audit = json.loads(audit_path(frame).read_text())
    for path, expected in audit["source_sha256"].items():
        if Path(path).name == "cone_distance_core.py" and Path(path).parent == ROOT / "src":
            # The CPU inference audit predates the later comparison-logging
            # change. Its detector box/image/model hashes are still original;
            # the current core is audited separately against current_pair_r01.
            continue
        if digest(Path(path)) != expected:
            raise ValueError("changed CPU inference input or code: "+path)
    if len(audit["selected_audits"]) != 1:
        raise ValueError("one explicit scoped detector box required")
    box = audit["selected_audits"][0]["box"]
    baseline = observe_separated_support(image, box, camera)
    completion = observe_lateral_completion(image, box, camera)
    sources = [
        dict(source="baseline_colour_shadow", point=baseline["point"],
             reason=baseline["reason"], support_pixels=len(baseline["support"] or []),
             completion_granted=False, controlling_distance=False),
        dict(source="lateral_completion_shadow", point=completion["point"],
             reason=completion["reason"], support_pixels=len(completion["support"] or []),
             completion_granted=completion["completion_granted"],
             original_shadow_point=completion["original_shadow_point"],
             controlling_distance=False),
    ]
    return image, box, sources


def one_pixel_control(point, model, camera, transform):
    values = []
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            result = measure_support([point[0]+dx, point[1]+dy], model, camera, transform,
                                     session=SESSION)
            if result["range_available"]:
                values.append(result["horizontal_camera_foot_range_m"])
            else:
                raise ValueError("one-pixel control outside explicit model domain")
    return min(values), max(values)


def plot_height(path, rows):
    figure, axis = plt.subplots(figsize=(7.2, 4.4))
    groups = {}
    for row in rows:
        groups.setdefault((row["frame"], row["support_source"]), []).append(
            (row["camera_to_floor_m"], row["horizontal_camera_foot_range_m"]))
    for (frame, source), values in sorted(groups.items()):
        values.sort()
        axis.plot([v[0]*1000 for v in values], [v[1] for v in values],
                  label=f"frame {frame} / {source}")
    for height, label in ((560.9, "shared+b15"), (590., "external590")):
        axis.axvline(height, color="grey", linewidth=.8, linestyle="--")
        axis.text(height, axis.get_ylim()[1], label, rotation=90,
                  va="top", ha="right", fontsize=7)
    axis.set_xlabel("explicit camera-to-floor height (mm)")
    axis.set_ylabel("horizontal range from camera foot (m)")
    axis.set_title("Numerical height sensitivity: NOT a confidence interval")
    axis.grid(alpha=.25)
    axis.legend(fontsize=7)
    figure.tight_layout()
    figure.savefig(path, dpi=150)
    plt.close(figure)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=False)

    config, camera, transform, _ = load_config()
    intrinsic = json.loads(INTRINSIC.read_text())
    for path, expected in intrinsic["source_sha256"].items():
        if digest(Path(path)) != expected:
            raise ValueError("changed intrinsic-consistency input: "+path)
    edge = json.loads(EDGE.read_text())
    for path, expected in edge["input_source_sha256"].items():
        if digest(Path(path)) != expected:
            raise ValueError("changed edge-refinement input: "+path)
    case = next(c for c in intrinsic["cases"] if c["threshold"] == 170)
    heading = dict(path=config["floor_candidate"], sha256=config["floor_sha256"])
    models = build_models(case, config)
    frame_models = per_frame_models(edge, heading)
    saved = json.loads(SAVED_PAIR.read_text())
    for path, expected in saved["source_sha256"].items():
        if digest(Path(path)) != expected:
            raise ValueError("changed saved current-pair input or code: "+path)
    saved_points = {row["source_native_frame"]: row["result"] for row in saved["rows"]}

    sources, ranges, height_rows, support_rows = [], [], [], []
    for frame in FRAMES:
        image, box, frame_sources = support_sources(frame, camera)
        support_rows.append(dict(frame=frame, detector_box=box,
                                 image_sha256=digest(image_path(frame)),
                                 sources=frame_sources))
        saved_result = saved_points[frame]
        saved_completion = saved_result["support_completion_shadow"]["candidate"]["point"]
        saved_baseline = saved_result["colour_support_shadow"]["candidate"]["point"]
        for source in frame_sources:
            expected_saved = saved_completion if source["source"] == "lateral_completion_shadow" else saved_baseline
            if source["point"] != expected_saved:
                raise ValueError("recomputed support differs from saved current-pair result")
            if source["point"] is None:
                continue
            sources.append(dict(frame=frame, **source))
            point = source["point"]
            for model in models:
                result = measure_support(point, model, camera, transform, session=SESSION)
                low, high = one_pixel_control(point, model, camera, transform)
                ranges.append(dict(frame=frame, support_source=source["source"],
                    support_x=point[0], support_y=point[1], model=model["name"],
                    model_role=model["role"], horizontal_camera_foot_range_m=result["horizontal_camera_foot_range_m"],
                    forward_heading_reference_m=result["forward_heading_reference_m"],
                    lateral_right_heading_reference_m=result["lateral_right_heading_reference_m"],
                    lens_slant_range_m=result["lens_slant_range_m"],
                    incidence_cos=result["incidence_cos"],
                    support_1px_control_min_m=low, support_1px_control_max_m=high,
                    status=result["status"], reason=result["reason"],
                    yaw_measured=False, controlling_distance=False,
                    physical_metric_verified=False, floor_contact_verified=False,
                    usable_for_ffb=False))
            for model in frame_models:
                if model["frame"] != frame:
                    continue
                result = measure_support(point, model, camera, transform, session=SESSION)
                ranges.append(dict(frame=frame, support_source=source["source"],
                    support_x=point[0], support_y=point[1], model=model["name"],
                    model_role=model["role"], horizontal_camera_foot_range_m=result["horizontal_camera_foot_range_m"],
                    forward_heading_reference_m=result["forward_heading_reference_m"],
                    lateral_right_heading_reference_m=result["lateral_right_heading_reference_m"],
                    lens_slant_range_m=result["lens_slant_range_m"],
                    incidence_cos=result["incidence_cos"],
                    support_1px_control_min_m=None, support_1px_control_max_m=None,
                    status=result["status"], reason=result["reason"],
                    yaw_measured=False, controlling_distance=False,
                    physical_metric_verified=False, floor_contact_verified=False,
                    usable_for_ffb=False))
            shared = models[0]
            for height_mm in range(540, 621, 5):
                model = dict(shared, name="height_sensitivity_shared_free_normal",
                             camera_to_floor_m=height_mm/1000.)
                result = measure_support(point, model, camera, transform, session=SESSION)
                height_rows.append(dict(frame=frame, support_source=source["source"],
                    support_x=point[0], support_y=point[1],
                    camera_to_floor_m=height_mm/1000.,
                    horizontal_camera_foot_range_m=result["horizontal_camera_foot_range_m"],
                    forward_heading_reference_m=result["forward_heading_reference_m"],
                    status=result["status"], reason=result["reason"]))

    solution_controls = []
    for entry in case["individual_native_refinement"]:
        for branch in entry["branches"]:
            solution_controls.append(dict(frame=entry["frame"], **branch))

    models_doc = dict(schema="explicit_floor_models_v1", session=SESSION,
        heading_reference=heading, models=models, per_frame_models=frame_models,
        source_sha256=sha_tree([INTRINSIC, EDGE, Path(config["camera_candidate"]),
                                Path(config["floor_candidate"])]),
        user_reference=dict(approximate_range_m=1.5, basis="floor tile 0.50 m, roughly three tiles",
                            uncertainty_m=None, precise_measurement=False,
                            used_to_fit_or_select_model=False),
        physical_metric_verified=False, floor_contact_verified=False,
        live_integrated=False, usable_for_ffb=False)
    (args.output_dir / "explicit_floor_models.json").write_text(
        json.dumps(models_doc, indent=2, allow_nan=False)+"\n")

    fieldnames = ["frame", "support_source", "support_x", "support_y", "model", "model_role",
                  "horizontal_camera_foot_range_m", "forward_heading_reference_m",
                  "lateral_right_heading_reference_m", "lens_slant_range_m", "incidence_cos",
                  "support_1px_control_min_m", "support_1px_control_max_m", "status", "reason",
                  "yaw_measured", "controlling_distance", "physical_metric_verified",
                  "floor_contact_verified", "usable_for_ffb"]
    with (args.output_dir / "ranges.csv").open("x", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(ranges)
    with (args.output_dir / "height_sensitivity.csv").open("x", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(height_rows[0]))
        writer.writeheader()
        writer.writerows(height_rows)
    with (args.output_dir / "support_sources.csv").open("x", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["frame", "source", "support_x", "support_y",
                                                    "reason", "support_pixels", "completion_granted",
                                                    "controlling_distance"])
        writer.writeheader()
        for row in support_rows:
            for source in row["sources"]:
                writer.writerow(dict(frame=row["frame"], source=source["source"],
                    support_x=None if source["point"] is None else source["point"][0],
                    support_y=None if source["point"] is None else source["point"][1],
                    reason=source["reason"], support_pixels=source["support_pixels"],
                    completion_granted=source["completion_granted"],
                    controlling_distance=False))

    plot_height(args.output_dir / "height_sensitivity.png", height_rows)
    input_paths = [INTRINSIC, EDGE, AUDITS, ORIGINALS, INTAKE, SAVED_PAIR,
                   ROOT/"src/cone_fixed_floor_candidate.py", ROOT/"tests/test_cone_fixed_floor_candidate.py",
                   ROOT/config["camera_candidate"], ROOT/config["floor_candidate"]]
    source_hashes = {}
    for path in input_paths:
        path = Path(path)
        if path.is_dir():
            for child in sorted(path.rglob("*")):
                if child.is_file():
                    source_hashes[str(child)] = digest(child)
        else:
            source_hashes[str(path)] = digest(path)
    summary = dict(status="CONDITIONAL_EXPLICIT_FLOOR_RANGES_ONLY", session=SESSION,
        frames=list(FRAMES), heading_reference=heading,
        support_sources=support_rows, models=[dict(name=m["name"], role=m["role"],
            camera_to_floor_m=m["camera_to_floor_m"], normal_optical=m["normal_optical"],
            evidence=m["evidence"]) for m in models],
        per_frame_models=[dict(frame=m["frame"], name=m["name"], role=m["role"],
            camera_to_floor_m=m["camera_to_floor_m"], normal_optical=m["normal_optical"]) for m in frame_models],
        ranges=ranges, height_sensitivity_rows=len(height_rows),
        pose_solution_controls=solution_controls,
        user_reference=models_doc["user_reference"], source_sha256=source_hashes,
        physical_metric_verified=False, floor_contact_verified=False,
        independent_accuracy_validated=False, live_integrated=False, usable_for_ffb=False,
        interpretations=["radial range is yaw-invariant under this model",
                         "forward/lateral use the paper7 heading reference and are not base_link",
                         "support points are unverified colour observations, not physical contact points",
                         "model spread and one-pixel controls are numerical sensitivity, not confidence intervals"])
    (args.output_dir / "summary.json").write_text(json.dumps(summary, indent=2, allow_nan=False)+"\n")
    print(json.dumps(dict(status=summary["status"], ranges=len(ranges),
        height_rows=len(height_rows), sources=len(sources)), indent=2))


if __name__ == "__main__":
    main()
