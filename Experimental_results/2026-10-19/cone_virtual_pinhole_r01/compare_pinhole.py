"""Same-column comparison: direct fisheye vs virtual pinhole plus rigid transform."""
import argparse
from collections import Counter, defaultdict
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import sys

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PROJECTION = HERE.parent / "cone_support_projection_r01"
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(PROJECTION))
from cone_dataset import read_csv, sha256, write_csv
import run_projection as upstream
import virtual_pinhole as virtual

VIEW = virtual.VirtualView()
TOLERANCE_M = 1e-9
FIELDS = ("x_min_m", "x_max_m", "z_min_m", "z_max_m", "z_span_m", "z_median_m")


def load_inputs():
    source, curves, status, models, refs, hashes = upstream.load_inputs()
    path = PROJECTION / "results_r01/provenance.json"
    provenance = json.loads(path.read_text())
    upstream.check_hashes(provenance["source_sha256"])
    for name, digest in provenance["output_sha256"].items():
        if sha256(PROJECTION / "results_r01" / name) != digest:
            raise ValueError("frozen support projection result changed")
    paths = [Path(__file__), HERE / "virtual_pinhole.py", HERE / "method.md", HERE / "test_pinhole.py",
             path, PROJECTION / "results_r01/projected_ranges.csv"]
    hashes.update({str(p): sha256(p) for p in paths})
    return source, curves, status, models, refs, hashes


def compare_points(direct, other):
    if [(p["pixel_x"], p["pixel_y"]) for p in direct] != [(p["pixel_x"], p["pixel_y"]) for p in other]:
        raise ValueError("same input columns required")
    finite = [(a, b) for a, b in zip(direct, other) if a["x_m"] is not None and b["x_m"] is not None]
    valid = [(a, b) for a, b in finite if a["reason"] == b["reason"] == "valid"]
    dx = [abs(a["x_m"]-b["x_m"]) for a, b in finite]
    dz = [abs(a["z_m"]-b["z_m"]) for a, b in finite]
    mismatches = sum(a["reason"] != b["reason"] for a, b in zip(direct, other) if b["in_virtual_view"])
    return dict(finite_pair_columns=len(finite), valid_pair_columns=len(valid),
                dx_abs_max_m=max(dx, default=None), dz_abs_max_m=max(dz, default=None),
                floor_reason_mismatches_within_view=mismatches)


def replay(source, curves, status, models):
    records, examples = [], []
    seen = set()
    if set(curves)-{upstream.quality.key(r) for r in source}:
        raise ValueError("orphan support")
    for r in source:
        key = upstream.quality.key(r)
        if key in seen:
            raise ValueError("duplicate source frame")
        seen.add(key)
        columns = curves.get(key, [])
        if bool(columns) != r["envelope_available"]:
            raise ValueError("source/curve mismatch")
        accepted = status[key]["quality_accepted"] == "True"
        if accepted and not columns:
            raise ValueError("missing curve cannot be accepted")
        for model, p in models.items():
            direct = upstream.project_columns(columns, p)
            full = virtual.project_columns(columns, p, VIEW)
            rounded = virtual.project_columns(columns, p, VIEW, quantized=True)
            groups = dict(direct=direct, pinhole_float=full, pinhole_rounded=rounded)
            bounds = {name: upstream.bounds(rows) for name, rows in groups.items()}
            base = dict(dataset=key[0], session=key[1], frame=key[2], time_sec=r["time_sec"], condition=r["condition"],
                        model=model, quality_accepted=accepted, quality_reason=status[key]["reason"],
                        input_columns=len(columns), floor_contact_verified=False, usable_for_ffb=False)
            row = dict(base, outside_virtual_view_columns=sum(v["reason"] == "outside_virtual_view" for v in full))
            for name, b in bounds.items():
                row[name + "_complete"] = b["projection_complete"]
                row[name + "_invalid_reasons"] = json.dumps(b["invalid_reasons"], sort_keys=True)
                row[name + "_observation_available"] = accepted and b["projection_complete"]
                for field in FIELDS:
                    row[name + "_candidate_" + field] = b[field]
                    row[name + "_observed_" + field] = b[field] if row[name + "_observation_available"] else None
            for name, other in (("float", full), ("rounded", rounded)):
                row.update({name + "_" + k: v for k, v in compare_points(direct, other).items()})
            records.append(row)
            if (r["dataset"], r["condition"], r["frame"]) in upstream.EXAMPLES:
                for a, b, c in zip(direct, full, rounded):
                    examples.append(dict(base, pixel_x=a["pixel_x"], pixel_y=a["pixel_y"],
                        virtual_u=b["virtual_u"], virtual_v=b["virtual_v"], rounded_u=c["used_u"], rounded_v=c["used_v"],
                        **{name + "_" + field: record[field] for name, record in
                           (("direct", a), ("float", b), ("rounded", c)) for field in ("x_m", "z_m", "reason")}))
    return records, examples


def summarize(records, refs):
    groups = defaultdict(list)
    for r in records:
        groups[r["dataset"], r["condition"], r["model"]].append(r)
    results = []
    for (dataset, condition, model), group in sorted(groups.items()):
        for population in ("all_input", "time_accepted"):
            selected = [r for r in group if population == "all_input" or r["quality_accepted"]]
            common = [r for r in selected if r["direct_complete"] and r["pinhole_float_complete"] and r["pinhole_rounded_complete"]]
            out = dict(dataset=dataset, condition=condition, model=model, population=population, total_frames=len(group),
                       population_frames=len(selected), input_envelope_frames=sum(r["input_columns"] > 0 for r in selected),
                       common_complete_frames=len(common), input_columns=sum(r["input_columns"] for r in selected),
                       outside_virtual_view_columns=sum(r["outside_virtual_view_columns"] for r in selected),
                       **refs[dataset, condition], floor_contact_verified=False, usable_for_ffb=False)
            for method in ("direct", "pinhole_float", "pinhole_rounded"):
                out[method + "_complete_frames"] = sum(r[method + "_complete"] for r in selected)
                for field in ("z_min_m", "z_max_m", "z_median_m"):
                    values = [r[method + "_candidate_" + field] for r in common]
                    out[method + "_" + field + "_frame_median"] = float(np.median(values)) if values else None
            for method in ("float", "rounded"):
                for field in ("finite_pair_columns", "valid_pair_columns", "floor_reason_mismatches_within_view"):
                    out[method + "_" + field] = sum(r[method + "_" + field] for r in selected)
                for axis in ("x", "z"):
                    values = [r[method + "_d" + axis + "_abs_max_m"] for r in selected if r[method + "_d" + axis + "_abs_max_m"] is not None]
                    out[method + "_d" + axis + "_abs_max_m"] = max(values, default=None)
                    out[method + "_d" + axis + "_abs_max_frame_p95_m"] = float(np.percentile(values, 95)) if values else None
            results.append(out)
    return results


def memory_views(models):
    old = ROOT / "Experimental_results/2026-10-15"
    paths = [old / "cone_static_distance_r01/raw_samples/center_200_f000211.png",
             old / "floor_cone_same_pose_analysis_r01/raw_samples/same_pose_f000563.png",
             old / "floor_cone_same_pose_analysis_r01/raw_samples/same_pose_f001265.png"]
    hashes = {str(p): sha256(p) for p in paths}
    records = []
    for model, p in models.items():
        maps = virtual.inverse_maps(p, VIEW)
        for path in paths:
            image = cv2.imread(str(path))
            before = hashlib.sha256(image.tobytes()).hexdigest()
            converted = virtual.rectify_in_memory(image, maps)
            if hashlib.sha256(image.tobytes()).hexdigest() != before or sha256(path) != hashes[str(path)]:
                raise ValueError("rectification modified source image")
            records.append(dict(model=model, native_png=str(path), native_png_sha256=hashes[str(path)],
                native_width=1280, native_height=720, virtual_width=converted.shape[1], virtual_height=converted.shape[0],
                valid_map_pixels=int(maps[2].sum()), total_map_pixels=VIEW.width*VIEW.height,
                rectified_bgr_sha256=hashlib.sha256(converted.tobytes()).hexdigest(),
                original_pixels_unchanged=True, rectified_image_saved=False, yolo_rerun=False, usable_for_ffb=False))
    return records, hashes


def plot(summary, output):
    os.environ.setdefault("MPLCONFIGDIR", "/tmp/cone_virtual_pinhole_matplotlib")
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    rows = [r for r in summary if r["population"] == "time_accepted" and r["condition"] in ("center_200", "cone_200")]
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.5), layout="constrained")
    x = np.arange(len(rows))
    for method, label, marker in (("direct", "Direct fisheye", "o"), ("pinhole_float", "Pinhole + rigid transform (float)", "x"),
                                   ("pinhole_rounded", "Nearest virtual pixel (sensitivity only)", "+")):
        axes[0].plot(x, [r[method + "_z_median_m_frame_median"] for r in rows], marker, label=label)
    axes[0].axhline(2., color="black", ls="--", label="Declared near-edge Z; NOT all columns' GT")
    axes[0].set(ylabel="Conditional Z [m]", title="Same geometry + same rays preserve the existing metric bias")
    axes[0].legend(fontsize=7)
    axes[1].bar(x, [1000*r["rounded_dz_abs_max_m"] for r in rows])
    axes[1].set(ylabel="Maximum paired-column |delta Z| [mm]", title="Virtual pixel rounding only; NOT detector or physical distance error")
    for ax in axes:
        ax.set_xticks(x, [r["dataset"]+"\n"+r["model"] for r in rows], fontsize=7, rotation=15)
        ax.grid(axis="y", alpha=.3)
    fig.savefig(output / "pinhole_geometry_and_rounding.png", dpi=150)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.output_dir.exists():
        raise ValueError("new output directory required")
    source, curves, status, models, refs, hashes = load_inputs()
    rows, examples = replay(source, curves, status, models)
    summary = summarize(rows, refs)
    views, view_hashes = memory_views(models)
    hashes.update(view_hashes)
    upstream.check_hashes(hashes)
    args.output_dir.mkdir(parents=True)
    for name, data in (("frame_comparison.csv", rows), ("summary.csv", summary),
                       ("representative_columns.csv", examples), ("memory_rectification.csv", views)):
        write_csv(args.output_dir / name, data)
    transforms = {name: dict(ground_from_virtual_optical=virtual.optical_to_ground_transform(p).tolist(),
                            source_frame="virtual_front_optical", target_frame="camera_ground_reference_ROS_axes",
                            actual_tf_published=False, measured_robot_extrinsic=False,
                            assumed_equidistant_K=virtual.equidistant_K(p)[0].tolist(), assumed_fisheye_D=[0, 0, 0, 0])
                  for name, p in models.items()}
    (args.output_dir / "virtual_camera_and_transforms.json").write_text(json.dumps(dict(view=asdict(VIEW),
        virtual_K=VIEW.K.tolist(), models=transforms), indent=2)+"\n")
    plot(summary, args.output_dir)
    upstream.check_hashes(hashes)
    worst = max(r["float_dz_abs_max_m"] for r in rows if r["float_dz_abs_max_m"] is not None)
    report = dict(status="OFFLINE_VIRTUAL_PINHOLE_GEOMETRY_ONLY_NOT_PHYSICAL_ACCURACY_OR_ROS_APPROVAL",
                  frames=len(source), model_frame_rows=len(rows), observed_columns=sum(map(len, curves.values())),
                  compared_model_column_pairs=sum(r["float_finite_pair_columns"] for r in rows),
                  max_float_delta_z_m=worst, equivalence_tolerance_m=TOLERANCE_M,
                  numerical_equivalence_within_tolerance=worst <= TOLERANCE_M,
                  float_floor_reason_mismatches_within_view=sum(r["float_floor_reason_mismatches_within_view"] for r in rows),
                  outside_virtual_view_columns=sum(r["outside_virtual_view_columns"] for r in rows),
                  virtual_view=asdict(VIEW), geometries=models, opencv_version=cv2.__version__,
                  new_metric_fit=False, new_yolo_inference=False, ros_tf_broadcast=False, physical_output=False,
                  usable_for_ffb=False, original_images_edited=False, rectified_images_saved=False,
                  source_sha256=hashes, output_sha256={p.name: sha256(p) for p in args.output_dir.iterdir() if p.is_file()})
    (args.output_dir / "provenance.json").write_text(json.dumps(report, indent=2)+"\n")
    print(json.dumps({k: v for k, v in report.items() if k not in ("geometries", "source_sha256", "output_sha256")}, indent=2))


if __name__ == "__main__":
    main()
