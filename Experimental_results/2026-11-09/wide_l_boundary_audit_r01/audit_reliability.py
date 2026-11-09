"""小数座標が出たことと、入力に依存せず角を定位できたことを区別する。"""
import argparse
import importlib.util
import json
from pathlib import Path

import numpy as np

SPEC = importlib.util.spec_from_file_location("l_expanded_reliability", Path(__file__).with_name("audit_expanded_roi.py"))
expanded = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(expanded)
base = expanded.base


def classify_refinement(seed_rows, integer_point):
    p = np.asarray(integer_point, float)
    valid = [r for r in seed_rows if r["available"]]
    returned = sum(np.array_equal(np.asarray(r["point"]), p+np.asarray(r["seed_offset"])) for r in valid)
    outputs = np.array([r["point"] for r in valid])
    span = float(np.linalg.norm(outputs[:, None]-outputs[None, :], axis=2).max()) if len(outputs) else None
    if len(valid) != len(seed_rows) or not len(valid):
        reason = "some_seed_refinements_unavailable"
    elif returned:
        reason = "input_returned_without_independent_refinement_evidence"
    elif span > .1:
        reason = "multiple_seed_dependent_outputs"
    else:
        reason = "seed_stable_observation_NOT_physical_corner_approval"
    return dict(valid_seeds=len(valid), total_seeds=len(seed_rows), input_returned_count=returned,
        maximum_pair_distance_px=span, reason=reason,
        passed_seed_consistency_only=reason.startswith("seed_stable_observation"),
        physical_outer_corner_identity_verified=False, physical_metric_verified=False, usable_for_ffb=False)


def synthetic_l(width, angle_deg, corner=(320.25, 390.6)):
    """既知の外角を持つ合成L。元カメラ画像には適用せず、画像を保存しない。"""
    if width not in (1., 2., 3., 4.) or angle_deg not in (0., 20.):
        raise ValueError("predeclared synthetic widths/angles only")
    cx, cy = corner
    left, top, w, h = 292, 365, 60, 45
    y, x, sy, sx = np.meshgrid(np.arange(h), np.arange(w), np.arange(16), np.arange(16), indexing="ij")
    dx = left+x+(sx+.5)/16-.5-cx
    dy = top+y+(sy+.5)/16-.5-cy
    angle = np.deg2rad(angle_deg)
    u = np.cos(angle)*dx+np.sin(angle)*dy
    v = -np.sin(angle)*dx+np.cos(angle)*dy
    dark = ((u >= 0) & (u <= 14) & (v >= -width) & (v <= 0)) | (
        (u >= 0) & (u <= width) & (v >= -12) & (v <= 0))
    intensity = np.rint(200-180*dark.mean(axis=(2, 3))).astype(np.uint8)
    image = np.full((720, 1280), 200, np.uint8)
    image[top:top+h, left:left+w] = intensity
    return image, np.asarray(corner, float)


def synthetic_observations(camera):
    rows = []
    for width in (1., 2., 3., 4.):
        for angle in (0., 20.):
            gray, truth = synthetic_l(width, angle)
            contour, selected, reason = expanded.expanded_contour(gray, truth, 110, (24, 16))
            if selected is None:
                rows.append(dict(width_px=width, angle_deg=angle, method="all", available=False,
                                 reason=reason, synthetic=True))
                continue
            methods = [("integer_convex", dict(available=True, point=[selected["x"], selected["y"]]))]
            for length, refine in ((4, False), (4, True), (5, False), (5, True)):
                result = (dict(available=False, reason=reason) if reason else
                    base.edge_corner(gray, contour, selected, length, refine, 110, camera))
                methods.append((f"{'isocross' if refine else 'raster'}_arc{length}", result))
            for window in (2, 3):
                methods.append((f"cornerSubPix_w{window}", base.local_subpixel(gray, selected, window)))
            for name, result in methods:
                point = result.get("point")
                rows.append(dict(width_px=width, angle_deg=angle, method=name, synthetic=True,
                    true_outer_corner_native_xy=truth.tolist(), available=result["available"],
                    point=point, error_to_known_outer_corner_px=None if point is None else
                        float(np.linalg.norm(np.asarray(point)-truth)),
                    reason=result.get("reason", "synthetic_integer_pixel_center"),
                    physical_metric_verified=False, usable_for_ffb=False))
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.output_dir.exists():
        raise ValueError("new output directory required")
    folder = Path(__file__).parent
    inputs = {}
    for sub in ("results_r01", "expanded_roi_r01"):
        manifest = folder/sub/"input_provenance.json"
        inputs.update(json.loads(manifest.read_text()))
        inputs[str(manifest)] = base.digest(manifest)
    for name, sha in inputs.items():
        if base.digest(name) != sha:
            raise ValueError("fixed source/input changed: " + name)
    paths = [Path(__file__), folder/"results_r01/boundary_observations.json", folder/"expanded_roi_r01/seed_stress.json"]
    inputs.update({str(p): base.digest(p) for p in paths})
    original = json.loads(paths[1].read_text())
    seed_rows = json.loads(paths[2].read_text())
    results = []
    for frame, label, window in sorted({(r["frame"], r["label"], r["window"]) for r in seed_rows}):
        rows = [r for r in seed_rows if (r["frame"], r["label"], r["window"]) == (frame, label, window)]
        point = next(r["integer_native_xy"] for r in original if r["frame"] == frame and r["label"] == label and r["threshold"] == 110)
        results.append(dict(frame=frame, label=label, window=window, **classify_refinement(rows, point)))
    synthetic = synthetic_observations(base.load_config()[1])
    summary = dict(status="SUBPIXEL_OUTPUT_IS_NOT_REFINEMENT_OR_PHYSICAL_PROOF", observations=len(results),
        passed_seed_consistency=sum(r["passed_seed_consistency_only"] for r in results),
        input_returned_observations=sum(r["input_returned_count"] > 0 for r in results),
        all_seeds_returned_unchanged=sum(r["input_returned_count"] == r["total_seeds"] for r in results),
        synthetic_rows=len(synthetic), selected_method=None,
        camera_images_edited_or_exported=False, runtime_changed=False,
        physical_metric_verified=False, usable_for_ffb=False)
    args.output_dir.mkdir(parents=True)
    base.original.dump(args.output_dir/"input_provenance.json", inputs)
    base.original.dump(args.output_dir/"summary.json", summary)
    base.original.dump(args.output_dir/"refinement_reliability.json", results)
    base.original.dump(args.output_dir/"synthetic_controls.json", synthetic)
    base.original.table(args.output_dir/"refinement_reliability.csv", results)
    print(json.dumps(summary, indent=2))
    for r in synthetic:
        if r.get("angle_deg") == 0 and r.get("method") in ("cornerSubPix_w2", "cornerSubPix_w3", "isocross_arc4"):
            print(r)


if __name__ == "__main__":
    main()
