#!/usr/bin/env python3
"""Same-session cone support/range hypotheses. Rough user range is NOT truth.

Plane range is yaw-free camera-foot horizontal range, not base_link forward Z.
No pixel/corner/plane is selected by proximity to the user's approximate 1.5m.
"""
import argparse
import csv
import json
from pathlib import Path
import sys

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "src"))
from angular_fisheye_geometry import unproject
from cone_colour_support_candidate import observe_separated_support
from cone_distance_core import digest, load_config


def horizontal_range(ray, normal, height_m):
    """Intersect a unit ray with n dot P + h = 0; no vehicle yaw invented."""
    ray, normal = np.asarray(ray, float), np.asarray(normal, float)
    if (ray.shape != (3,) or normal.shape != (3,) or not np.isfinite(ray).all()
            or not np.isfinite(normal).all() or not np.isfinite(height_m) or height_m <= 0
            or not np.isclose(np.linalg.norm(ray), 1, atol=1e-10, rtol=0)
            or not np.isclose(np.linalg.norm(normal), 1, atol=1e-10, rtol=0)):
        raise ValueError("finite unit ray/normal and positive plane height required")
    incidence = -float(normal@ray)
    if incidence <= .03:
        raise ValueError("ray does not intersect floor with sufficient incidence")
    slant = height_m/incidence
    point = slant*ray
    camera_foot = -height_m*normal
    rho = float(np.linalg.norm(point-camera_foot))
    return dict(horizontal_camera_foot_range_m=rho, lens_slant_range_m=slant,
                incidence_cos=incidence, point_optical_m=point.tolist(),
                camera_foot_optical_m=camera_foot.tolist(),
                physical_metric_verified=False, floor_contact_verified=False, usable_for_ffb=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=False)
    config, camera, _, _ = load_config()
    audit_path = HERE / "intrinsic_consistency_r02/intrinsic_consistency.json"
    audit = json.loads(audit_path.read_text())
    case = next(c for c in audit["cases"] if c["threshold"] == 170)
    free, anchored = case["shared_plane_best_local"], case["externally_anchored_printed_plane_0p575m"]
    models = [dict(name="shared_plane_height_free_plus_approx_board", normal=free["normal_optical"],
                   height_m=free["camera_to_printed_plane_m"]+.015),
              dict(name="externally_anchored_height_and_normal", normal=anchored["normal_optical"], height_m=.590),
              dict(name="external_height_only_free_fit_normal_counterfactual", normal=free["normal_optical"], height_m=.590)]
    sources = {str(p): digest(p) for p in (audit_path, Path(__file__).resolve(),
        ROOT/"src/cone_colour_support_candidate.py", ROOT/"src/cone_distance_core.py",
        ROOT/"src/angular_fisheye_geometry.py", ROOT/config["camera_candidate"])}
    rows, table = [], []
    for frame in (1259, 1655):
        image_path = HERE / "originals" / f"decoded_15ae673c24484d119952ae391df611aa_f{frame:06d}.png"
        inference_path = HERE / f"cone_same_session_r01/inference_f{frame:06d}/audit.json"
        pred = json.loads(inference_path.read_text())
        for path, expected in pred["source_sha256"].items():
            if digest(Path(path)) != expected:
                raise ValueError("changed CPU inference input or code: "+path)
        image = cv2.imread(str(image_path))
        if image is None or image.shape != (720, 1280, 3) or len(pred["selected_audits"]) != 1:
            raise ValueError("native image and one scoped frozen detector box required")
        sources.update({str(p): digest(p) for p in (image_path, inference_path)})
        detector = pred["selected_audits"][0]
        separated = observe_separated_support(image, detector["box"], camera)
        row = dict(frame=frame, detector_box=detector["box"], cpu_inference_software=pred["software"],
            frozen_baseline=detector["frozen_baseline"], separated_shadow=separated,
            state="SUPPORT_WITHHELD", range_hypotheses=[], controlling_distance=False)
        if separated["point"] is not None:
            ray, valid = unproject([separated["point"]], camera, image_size=(1280, 720))
            if not valid[0]:
                raise ValueError("observed support outside current front calibration")
            for model in models:
                result = horizontal_range(ray[0], model["normal"], model["height_m"])
                sensitivity = []
                x, y = separated["point"]
                for dx in (-1, 0, 1):
                    for dy in (-1, 0, 1):
                        rays, ok = unproject([[x+dx, y+dy]], camera, image_size=(1280, 720))
                        if not ok[0]:
                            raise ValueError("pixel sensitivity control outside calibrated domain")
                        sensitivity.append(horizontal_range(rays[0], model["normal"], model["height_m"])["horizontal_camera_foot_range_m"])
                result.update(model=model["name"], plane_normal_optical=model["normal"], camera_floor_height_m=model["height_m"],
                    numerical_1px_support_control_range_m=[min(sensitivity), max(sensitivity)],
                    sensitivity_is_confidence_interval=False)
                row["range_hypotheses"].append(result)
                table.append(dict(frame=frame, model=model["name"], support_x=x, support_y=y,
                    horizontal_range_m=result["horizontal_camera_foot_range_m"],
                    slant_range_m=result["lens_slant_range_m"],
                    support_1px_control_min_m=min(sensitivity), support_1px_control_max_m=max(sensitivity)))
            row["state"] = "OFFLINE_CONDITIONAL_RANGE_ONLY"
        rows.append(row)
    report = dict(status="CONDITIONAL_SAME_SESSION_RANGES_NOT_ACCURACY_VALIDATION",
        session="15ae673c24484d119952ae391df611aa", rows=rows, plane_models=models,
        user_distance_reference=dict(approximate_range_m=1.5, basis="user: floor tile 0.50m, roughly three tiles",
                                     uncertainty_m=None, precise_measurement=False, used_to_fit_or_select_model=False),
        source_sha256=sources, physical_metric_verified=False, independent_accuracy_validated=False,
        live_integrated=False, usable_for_ffb=False)
    with (args.output_dir / "same_session_cone_comparison.json").open("x") as f:
        json.dump(report, f, indent=2, allow_nan=False)
        f.write("\n")
    with (args.output_dir / "conditional_ranges.csv").open("x", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["frame", "model", "support_x", "support_y", "horizontal_range_m", "slant_range_m", "support_1px_control_min_m", "support_1px_control_max_m"])
        writer.writeheader()
        writer.writerows(table)
    print(json.dumps(dict(states=[dict(frame=r["frame"], state=r["state"], reason=r["separated_shadow"]["reason"]) for r in rows], ranges=table), indent=2))


if __name__ == "__main__":
    main()
