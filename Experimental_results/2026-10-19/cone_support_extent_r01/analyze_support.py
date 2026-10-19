"""All-frame image-space support diagnosis, deliberately WITHOUT metric projection."""
import argparse
from collections import Counter, defaultdict
import importlib.util
import json
import os
from pathlib import Path
import sys

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
TIES = HERE.parent / "cone_bottom_ties_r01"
QUALITY = HERE.parent / "cone_contact_quality_r01"
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(TIES))
from cone_dataset import read_csv, sha256, write_csv
from bottom_points import extract_bottoms
from support import SETTINGS, describe_support, line_y_at, native_contour

spec = importlib.util.spec_from_file_location("frozen_support_quality_inputs", QUALITY / "replay.py")
quality = importlib.util.module_from_spec(spec)
spec.loader.exec_module(quality)


def original_sessions():
    old = ROOT / "Experimental_results/2026-10-15"
    a = json.loads((old / "cone_static_distance_r01/intake_summary.json").read_text())
    b = json.loads((old / "floor_cone_same_pose_analysis_r01/intake_summary.json").read_text())
    return [("static", Path(r["path"])) for r in a["inputs"]]+[("sequence", Path(b["session"]))]


def inspect_image(image, candidates):
    if image.shape != (720, 1280, 3) or image.dtype != np.uint8:
        raise ValueError("native uint8 BGR frames required")
    if len(candidates) != 1:
        return dict(envelope_available=False, line_consistent=False, line_fitted=False,
                    reason="no_candidate" if not candidates else "ambiguous_candidates",
                    legacy_pixel_x=None, legacy_pixel_y=None,
                    floor_contact_verified=False, usable_for_ffb=False), [], []
    contour, legacy = native_contour(image, candidates[0], extract_bottoms)
    if contour is None:
        return dict(envelope_available=False, line_consistent=False, line_fitted=False,
                    reason=legacy["reason"], legacy_pixel_x=None, legacy_pixel_y=None,
                    floor_contact_verified=False, usable_for_ffb=False), [], []
    description, envelope, selected = describe_support(contour)
    box = candidates[0]
    query = (float(box["x1"])+float(box["x2"]))/2
    description.update(legacy_pixel_x=legacy["pixel_x"], legacy_pixel_y=legacy["pixel_y"],
                       bbox_centre_x=query, diagnostic_line_y_at_bbox_x=line_y_at(description, query))
    return description, envelope.tolist(), selected.tolist()


def summarize(rows):
    groups = defaultdict(list)
    for row in rows:
        groups[row["dataset"], row["condition"]].append(row)
    result = []
    for (dataset, condition), group in sorted(groups.items()):
        summary = dict(dataset=dataset, condition=condition, frames=len(group),
                       envelopes=sum(r["envelope_available"] for r in group),
                       line_fitted=sum(r["line_fitted"] for r in group),
                       line_consistent=sum(r["line_consistent"] for r in group),
                       withheld_reasons=json.dumps(dict(Counter(r["reason"] for r in group if not r["line_consistent"])), sort_keys=True),
                       physical_support_gt_available=False, usable_for_ffb=False)
        for field in ("span_px", "perpendicular_residual_p90_px", "slope"):
            values = [r[field] for r in group if r.get(field) is not None]
            summary[field+"_median"] = float(np.median(values)) if values else None
        result.append(summary)
    return result


def adjacent(rows):
    previous, output = {}, []
    for row in rows:
        k = row["dataset"], row["session"]
        a = previous.get(k)
        if (a is not None and row["frame"] == a["frame"]+1 and row["condition"] == a["condition"]
                and row["line_consistent"] and a["line_consistent"]):
            intersection = max(0., min(row["x_hi"], a["x_hi"])-max(row["x_lo"], a["x_lo"])+1)
            union = max(row["x_hi"], a["x_hi"])-min(row["x_lo"], a["x_lo"])+1
            lo, hi = max(row["x_lo"], a["x_lo"]), min(row["x_hi"], a["x_hi"])
            query = (lo+hi)/2 if lo <= hi else None
            dy = line_y_at(row, query)-line_y_at(a, query) if query is not None else None
            output.append(dict(dataset=k[0], session=k[1], condition=row["condition"],
                previous_frame=a["frame"], frame=row["frame"],
                dx_lo_px=row["x_lo"]-a["x_lo"], dx_hi_px=row["x_hi"]-a["x_hi"], x_interval_iou=intersection/union,
                common_query_x=query, dy_same_x_px=dy,
                legacy_dx_px=row["legacy_pixel_x"]-a["legacy_pixel_x"],
                legacy_dy_px=row["legacy_pixel_y"]-a["legacy_pixel_y"], usable_for_ffb=False))
        previous[k] = row
    return output


def summarize_steps(steps):
    groups = defaultdict(list)
    for row in steps:
        groups[row["dataset"], row["condition"]].append(row)
    output = []
    for (dataset, condition), group in sorted(groups.items()):
        result = dict(dataset=dataset, condition=condition, adjacent_consistent_pairs=len(group), usable_for_ffb=False)
        for field in ("dx_lo_px", "dx_hi_px", "dy_same_x_px", "legacy_dx_px", "legacy_dy_px"):
            values = [abs(r[field]) for r in group if r[field] is not None]
            result[field+"_abs_p95"] = float(np.percentile(values, 95)) if values else None
        result["x_interval_iou_median"] = float(np.median([r["x_interval_iou"] for r in group]))
        output.append(result)
    return output


def plot(rows, points, summary, output):
    os.environ.setdefault("MPLCONFIGDIR", "/tmp/cone_support_extent_matplotlib")
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    # Fixed previously used native-image sample frames, not selected by fit outcome.
    choices = [("static", "left_130", 210), ("static", "center_200", 211), ("sequence", "cone_200", 1134)]
    fig, axes = plt.subplots(1, 3, figsize=(14, 4), layout="constrained")
    for ax, (dataset, condition, frame) in zip(axes, choices):
        row = next(r for r in rows if r["dataset"] == dataset and r["condition"] == condition and r["frame"] == frame)
        chosen = [p for p in points if p["dataset"] == dataset and p["session"] == row["session"] and p["frame"] == frame]
        ax.plot([p["x"] for p in chosen], [p["y"] for p in chosen], ".-", label="Observed lower envelope")
        if row["line_fitted"]:
            x = np.linspace(row["x_lo"], row["x_hi"], 80)
            y = row["line_y_lo"]+row["slope"]*(x-row["x_lo"])
            ax.plot(x, y, label="Huber line (not verified contact)")
            band = row["display_band_halfwidth_px"]
            ax.fill_between(x, y-band, y+band, alpha=.15, label="Residual display band, not confidence interval")
        if row["legacy_pixel_x"] is not None:
            ax.scatter([row["legacy_pixel_x"]], [row["legacy_pixel_y"]], marker="x", s=60, label="Old single representative")
        ax.invert_yaxis()
        ax.grid(alpha=.3)
        ax.set(xlabel="Native image X [px]", ylabel="Native image Y [px]",
               title=f"{dataset}/{condition}/f{frame}\nconsistent={row['line_consistent']}")
        ax.legend(fontsize=6)
    fig.suptitle("Numeric boundaries only: a visible lower edge may be an occlusion boundary, not the floor")
    fig.savefig(output / "observed_support_examples.png", dpi=150)
    plt.close(fig)
    fig, axes = plt.subplots(3, 1, figsize=(12, 8), sharex=True, layout="constrained")
    chosen = [r for r in rows if r["dataset"] == "static" and r["condition"] == "left_130"]
    for field in ("x_lo", "x_hi", "legacy_pixel_x"):
        axes[0].plot([r["frame"] for r in chosen], [r.get(field) if r.get(field) is not None else np.nan for r in chosen], ".", ms=2, label=field)
    for field in ("line_y_lo", "line_y_hi", "legacy_pixel_y"):
        axes[1].plot([r["frame"] for r in chosen], [r.get(field) if r.get(field) is not None else np.nan for r in chosen], ".", ms=2, label=field)
    axes[2].plot([r["frame"] for r in chosen], [r.get("perpendicular_residual_p90_px", np.nan) for r in chosen], ".", ms=2, label="Perpendicular residual p90")
    axes[2].axhline(SETTINGS["max_perpendicular_p90_px"], ls="--", color="black", label="Frozen screen")
    for ax in axes:
        ax.grid(alpha=.3)
        ax.legend(fontsize=8)
    axes[0].set(ylabel="X support [px]", title="Static left: interval endpoints retained; no conversion to metres")
    axes[1].set_ylabel("Y boundaries [px]")
    axes[2].set(xlabel="Original frame; missing not interpolated", ylabel="Residual [px]")
    fig.savefig(output / "support_extent_timeline.png", dpi=150)
    plt.close(fig)
    fig, ax = plt.subplots(figsize=(10, 4), layout="constrained")
    order = [("static", c) for c in ("center_080", "center_130", "center_200", "left_130", "right_130", "none")]
    order += [("sequence", "cone_130"), ("sequence", "cone_200")]
    chosen = [next(r for r in summary if (r["dataset"], r["condition"]) == k) for k in order]
    x = np.arange(len(order))
    ax.bar(x-.18, [r["envelopes"]/r["frames"] for r in chosen], .36, label="Visible lower envelope / ALL frames")
    ax.bar(x+.18, [r["line_consistent"]/r["frames"] for r in chosen], .36, label="Single-line consistent / ALL frames")
    ax.set_xticks(x, [d+"\n"+c for d, c in order], fontsize=8)
    ax.set(ylabel="Fraction (NOT detection recall or physical contact accuracy)", title="Frozen image-space shape screen; irregular envelopes are still saved")
    ax.grid(axis="y", alpha=.3)
    ax.legend(fontsize=8)
    fig.savefig(output / "support_coverage.png", dpi=150)
    plt.close(fig)


def run_all():
    ledger, selected, _, hashes = quality.load_inputs()
    cache = {quality.key(p): p for p in read_csv(quality.CONTACT / "full_replay_r01/pixels.csv") if p["v_min"] == "30"}
    paths = [Path(__file__), HERE / "support.py", HERE / "method.md", TIES / "bottom_points.py"]
    paths.extend(ROOT / "Experimental_results/2026-10-15" / name / "intake_summary.json"
                 for name in ("cone_static_distance_r01", "floor_cone_same_pose_analysis_r01"))
    hashes.update({str(p): sha256(p) for p in paths})
    groups = defaultdict(list)
    for row in ledger:
        groups[row["dataset"], row["session"]].append(row)
    observations, envelope_points = [], []
    for dataset, directory in original_sessions():
        frames = groups[dataset, directory.name]
        raw = read_csv(directory / "detections.csv")
        if len(raw) != len(frames):
            raise ValueError("raw CSV/frozen frame count mismatch")
        cap = cv2.VideoCapture(str(directory / "raw.avi"))
        if not cap.isOpened():
            raise ValueError("raw not readable")
        try:
            for source, original in zip(frames, raw):
                ok, image = cap.read()
                if not ok:
                    raise ValueError("missing raw frame")
                if int(original["frame"]) != source["frame"] or float(original["time_sec"]) != source["time_sec"]:
                    raise ValueError("source frame/time differs")
                k = quality.key(source)
                candidates = selected[k]
                description, envelope, support = inspect_image(image, candidates)
                old = cache[k]
                if description["envelope_available"] != quality.flag(old["colour_candidate"]):
                    raise ValueError("frozen segmentation guard changed")
                for new_field, old_field in (("legacy_pixel_x", "pixel_x"), ("legacy_pixel_y", "pixel_y")):
                    expected = float(old[old_field]) if old[old_field] else None
                    if description[new_field] != expected:
                        raise ValueError("frozen legacy pixel changed")
                row = dict(dataset=dataset, session=directory.name, frame=source["frame"], time_sec=source["time_sec"],
                           condition=source["condition"], candidates=len(candidates), **description)
                observations.append(row)
                included = {tuple(p) for p in support}
                envelope_points.extend(dict(dataset=dataset, session=directory.name, frame=source["frame"], x=x, y=y,
                                             in_observed_support=(x, y) in included, usable_for_ffb=False) for x, y in envelope)
            if cap.read()[0]:
                raise ValueError("extra raw frames")
        finally:
            cap.release()
        print("Decoded image support", dataset, directory.name, len(frames), flush=True)
    if len(observations) != 5143:
        raise ValueError("all frames required")
    return observations, envelope_points, hashes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.output_dir.exists():
        raise ValueError("new output required; old results are immutable")
    rows, points, hashes = run_all()
    summary, steps = summarize(rows), adjacent(rows)
    args.output_dir.mkdir(parents=True)
    write_csv(args.output_dir / "observations.csv", rows)
    write_csv(args.output_dir / "lower_envelopes.csv", points)
    write_csv(args.output_dir / "summary.csv", summary)
    write_csv(args.output_dir / "adjacent_support.csv", steps)
    write_csv(args.output_dir / "adjacent_summary.csv", summarize_steps(steps))
    write_csv(args.output_dir / "occlusion_rows.csv", [r for r in rows if r["dataset"] == "sequence" and 1110 <= r["frame"] <= 1155])
    plot(rows, points, summary, args.output_dir)
    if not all(sha256(Path(p)) == digest for p, digest in hashes.items()):
        raise ValueError("source changed during processing")
    report = dict(status="IMAGE_SUPPORT_FEASIBILITY_ONLY_NOT_PHYSICAL_CONTACT_OR_FFB_APPROVAL",
                  source_frames=len(rows), envelope_points=len(points), settings=SETTINGS,
                  geometry_fitted_or_metric_projection_performed=False, reference_distances_used=False,
                  runtime_changed=False, physical_output=False, source_images_edited=False, new_camera_images_saved=False,
                  usable_for_ffb=False, source_sha256=hashes,
                  output_sha256={p.name: sha256(p) for p in args.output_dir.iterdir() if p.is_file()})
    (args.output_dir / "provenance.json").write_text(json.dumps(report, indent=2)+"\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
