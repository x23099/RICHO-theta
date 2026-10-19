"""Frozen tie-inclusive contour experiment: raw videos in, CSV/plots only out."""
from collections import defaultdict
import argparse
import importlib.util
import json
import os
from pathlib import Path
import sys

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
QUALITY = HERE.parent / "cone_contact_quality_r01"
OLD = ROOT / "Experimental_results/2026-10-15"
sys.path.insert(0, str(ROOT / "src"))
from cone_dataset import read_csv, sha256, write_csv
from bottom_points import extract_bottoms, select_bottom


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


quality = load_module("frozen_colour_quality_replay", QUALITY / "replay.py")
jitter = load_module("frozen_colour_jitter", QUALITY / "audit_jitter.py")


def csv_rows(rows):
    return [{k: "" if v is None else str(v) for k, v in row.items()} for row in rows]


def sessions():
    static = json.loads((OLD / "cone_static_distance_r01/intake_summary.json").read_text())
    sequence = json.loads((OLD / "floor_cone_same_pose_analysis_r01/intake_summary.json").read_text())
    return [("static", Path(r["path"])) for r in static["inputs"]] + [("sequence", Path(sequence["session"]))]


def extract_all(ledger, selected, cache):
    """All raw frames; assert exact LEGACY extraction against original per-frame cache."""
    groups = defaultdict(list)
    for row in ledger:
        groups[row["dataset"], row["session"]].append(row)
    new_candidates, output = {}, []
    for dataset, directory in sessions():
        source = groups[dataset, directory.name]
        raw_rows = read_csv(directory / "detections.csv")
        if len(source) != len(raw_rows):
            raise ValueError("original CSV and frozen frame count differ")
        capture = cv2.VideoCapture(str(directory / "raw.avi"))
        if not capture.isOpened():
            raise ValueError("original raw video unreadable")
        try:
            for frame, raw in zip(source, raw_rows):
                ok, image = capture.read()
                if not ok or image.shape != (720, 1280, 3):
                    raise ValueError("all original native frames required")
                if int(raw["frame"]) != frame["frame"] or float(raw["time_sec"]) != frame["time_sec"]:
                    raise ValueError("original source frame/time mismatch")
                k = quality.key(frame)
                candidates = selected[k]
                if len(candidates) == 1:
                    results = extract_bottoms(image, candidates[0])
                else:
                    result = dict(colour_candidate=False, reason="no_candidate" if not candidates else "ambiguous_candidates",
                                  pixel_x=None, pixel_y=None)
                    results = {name: dict(result) for name in ("legacy", "tie_inclusive")}
                old = cache[k]
                legacy = results["legacy"]
                if (legacy["colour_candidate"] != quality.flag(old["colour_candidate"])
                        or legacy["reason"] != old["colour_reason"]):
                    raise ValueError("legacy contour guard did not reproduce frozen cache")
                for field in ("pixel_x", "pixel_y"):
                    expected = float(old[field]) if old[field] != "" else None
                    if legacy[field] != expected:
                        raise ValueError("legacy pixel did not reproduce frozen cache")
                new = results["tie_inclusive"]
                if new["colour_candidate"] != legacy["colour_candidate"]:
                    raise ValueError("only point choice may change; contour guards must be identical")
                new_candidates[k] = [dict(b, _colour=dict(valid=new["colour_candidate"], reason=new["reason"],
                                        x=new["pixel_x"], y=new["pixel_y"])) for b in candidates]
                row = dict(dataset=dataset, session=directory.name, frame=frame["frame"], time_sec=frame["time_sec"],
                           condition=frame["condition"], reference_z_m=frame["reference_z_m"], candidates=len(candidates),
                           colour_candidate=new["colour_candidate"], reason=new["reason"],
                           floor_contact_verified=False, usable_for_ffb=False)
                for mode, result in results.items():
                    for field in ("pixel_x", "pixel_y", "selected_points", "excluded_cutoff_ties"):
                        row[mode+"_"+field] = result.get(field)
                for field in ("contour_points", "nominal_bottom_count", "cutoff_y", "cutoff_ties", "bottom_span_px"):
                    row[field] = new.get(field)
                output.append(row)
            if capture.read()[0]:
                raise ValueError("extra original frames beyond source CSV")
        finally:
            capture.release()
        print("Decoded and legacy-verified", dataset, directory.name, len(source), flush=True)
    if len(output) != len(ledger) or set(new_candidates) != {quality.key(r) for r in ledger}:
        raise ValueError("raw decoding did not cover all frames")
    return new_candidates, output


def compare_common(rows):
    indexed = defaultdict(dict)
    for row in rows:
        indexed[quality.key(row), row["model"]][row["method"]] = row
    comparisons = []
    for (k, model), methods in indexed.items():
        old, new = methods["legacy"], methods["tie_inclusive"]
        comparisons.append(dict(dataset=k[0], session=k[1], frame=k[2], model=model,
            condition=new["condition"], reference_z_m=new["reference_z_m"],
            legacy_projection=old["projection_candidate"], tie_inclusive_projection=new["projection_candidate"],
            legacy_accepted=old["quality_accepted"], tie_inclusive_accepted=new["quality_accepted"],
            legacy_x_m=old["candidate_x_m"], legacy_z_m=old["candidate_z_m"],
            tie_inclusive_x_m=new["candidate_x_m"], tie_inclusive_z_m=new["candidate_z_m"],
            legacy_reason=old["reason"], tie_inclusive_reason=new["reason"], usable_for_ffb=False))
    groups = defaultdict(list)
    for row in comparisons:
        groups[row["dataset"], row["condition"], row["model"]].append(row)
    summary = []
    for (dataset, condition, model), group in sorted(groups.items()):
        for scope in ("common_projection", "common_quality_accepted"):
            fields = ("legacy_projection", "tie_inclusive_projection") if scope == "common_projection" else ("legacy_accepted", "tie_inclusive_accepted")
            common = [r for r in group if all(r[field] for field in fields)]
            result = dict(dataset=dataset, condition=condition, model=model, scope=scope, frames=len(common), usable_for_ffb=False)
            for mode in ("legacy", "tie_inclusive"):
                values = [r[mode+"_z_m"] for r in common]
                result[mode+"_z_median_m"] = float(np.median(values)) if values else None
                reference = group[0]["reference_z_m"]
                result[mode+"_z_bias_m"] = float(np.median(values)-reference) if values and reference is not None else None
            summary.append(result)
    return comparisons, summary


def synthetic_demo():
    mask = np.zeros((720, 1280, 3), np.uint8)
    mask[304:397, 304:337] = (0, 0, 200)
    result = extract_bottoms(mask, dict(x1=300, y1=300, x2=340, y2=400))
    # Numeric point/representative CSV only, never save a synthetic camera image.
    binary = np.zeros((100, 50), np.uint8)
    binary[2:95, 2:35] = 255
    contour = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)[0][0][:, 0, :] + [302, 302]
    points = [dict(x=int(x), y=int(y)) for x, y in contour]
    return result, points


def plot(rows, summary, output, demo, points):
    os.environ.setdefault("MPLCONFIGDIR", "/tmp/cone_bottom_ties_matplotlib")
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(2, 1, figsize=(12, 7), sharex=True, layout="constrained")
    for mode in ("bbox", "legacy", "tie_inclusive"):
        chosen = [r for r in rows if r["dataset"] == "static" and r["condition"] == "left_130"
                  and r["model"] == "height_only59" and r["method"] == mode]
        for ax, coordinate in zip(axes, ("x", "z")):
            ax.plot([r["frame"] for r in chosen],
                    [r["candidate_"+coordinate+"_m"] if r["candidate_"+coordinate+"_m"] is not None else np.nan for r in chosen],
                    ".", ms=2, alpha=.65, label=mode)
            ax.set_ylabel(coordinate.upper()+" hypothesis [m]")
            ax.grid(alpha=.3)
            ax.legend()
    axes[0].set_title("Same static left recording: only bottom-quantile tie handling changed / fixed h59")
    axes[-1].set_xlabel("Original frame (missing not filled)")
    fig.savefig(output / "left_xy_comparison.png", dpi=150)
    plt.close(fig)
    order = [("static", c) for c in ("center_080", "center_130", "center_200", "left_130", "right_130")]
    order += [("sequence", "cone_130"), ("sequence", "cone_200")]
    fig, axes = plt.subplots(2, 1, figsize=(12, 7), sharex=True, layout="constrained")
    for mode in ("bbox", "legacy", "tie_inclusive"):
        chosen = [next(r for r in summary if (r["dataset"], r["condition"], r["model"], r["method"])
                       == (d, c, "height_only59", mode)) for d, c in order]
        axes[0].plot(range(len(order)), [r["quality_accepted"]/r["frames"] for r in chosen], "o-", label=mode)
        axes[1].plot(range(len(order)), [r["accepted_z_bias_m"] for r in chosen], "o-", label=mode)
    for ax in axes:
        ax.grid(alpha=.3)
        ax.legend()
        ax.set_xticks(range(len(order)), [d+"\n"+c for d, c in order], fontsize=8)
    axes[0].set(ylabel="Quality accepted / ALL frames", title="No gate relaxation: temporal acceptance does not prove contact or accuracy")
    axes[1].axhline(0, color="black", lw=.8)
    axes[1].set_ylabel("Accepted median Z - nominal reference [m]")
    fig.savefig(output / "coverage_bias_comparison.png", dpi=150)
    plt.close(fig)
    fig, ax = plt.subplots(figsize=(8, 5), layout="constrained")
    ax.scatter([p["x"] for p in points], [p["y"] for p in points], s=8, color=".7", label="Numeric synthetic rectangle contour")
    for mode, r in demo.items():
        ax.scatter([r["pixel_x"]], [r["pixel_y"]], marker="x", s=90,
                   label=mode+f" (x={r['pixel_x']}, selected={r['selected_points']})")
    ax.axvline(320, color="black", ls="--", label="Rectangle symmetry axis")
    ax.invert_yaxis()
    ax.set(xlabel="Synthetic X coordinate", ylabel="Synthetic Y coordinate",
           title="Same-height points cut by X order: legacy x=313.5 vs symmetry-neutral x=320")
    ax.legend(fontsize=8)
    ax.grid(alpha=.3)
    fig.savefig(output / "synthetic_tie_selection.png", dpi=150)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.output_dir.exists():
        raise ValueError("new output directory required; no previous result overwrite")
    ledger, old_candidates, models, hashes = quality.load_inputs()
    prior_dir = QUALITY / "results_r02"
    prior = json.loads((prior_dir / "provenance.json").read_text())
    for path, digest in prior["source_sha256"].items():
        if sha256(Path(path)) != digest:
            raise ValueError("previous quality source changed: " + path)
    for name, digest in prior["output_sha256"].items():
        if sha256(prior_dir / name) != digest:
            raise ValueError("previous quality result changed: " + name)
    hashes.update(prior["source_sha256"])
    paths = [Path(__file__), HERE / "bottom_points.py", HERE / "method.md", QUALITY / "audit_jitter.py",
             prior_dir / "provenance.json", prior_dir / "observations.csv"]
    paths.extend(OLD / folder / "intake_summary.json" for folder in ("cone_static_distance_r01", "floor_cone_same_pose_analysis_r01"))
    hashes.update({str(p): sha256(p) for p in paths})
    cache = {quality.key(r): r for r in read_csv(quality.CONTACT / "full_replay_r01/pixels.csv") if r["v_min"] == "30"}
    new_candidates, pixels = extract_all(ledger, old_candidates, cache)
    baseline = quality.replay(ledger, old_candidates, models)
    if csv_rows(baseline) != read_csv(prior_dir / "observations.csv"):
        raise ValueError("prior quality replay did not reproduce all decisions")
    for row in baseline:
        if row["method"] == "colour":
            row["method"] = "legacy"
    replay = quality.replay(ledger, new_candidates, models)
    quality.bbox_regression(replay, quality.PREVIOUS / "results_r01/observations.csv")
    new_rows = [dict(row, method="tie_inclusive") for row in replay if row["method"] == "colour"]
    rows = baseline + new_rows
    if len(pixels) != 5143 or len(new_rows) != 5143*3:
        raise ValueError("all original frames and models required")
    pairs, common = compare_common(rows)
    summary = quality.summarize(rows)
    steps = jitter.differences(csv_rows(rows))
    demo, demo_points = synthetic_demo()
    args.output_dir.mkdir(parents=True)
    write_csv(args.output_dir / "pixels.csv", pixels)
    write_csv(args.output_dir / "observations.csv", new_rows)
    write_csv(args.output_dir / "summary.csv", summary)
    write_csv(args.output_dir / "frame_pairs.csv", pairs)
    write_csv(args.output_dir / "common_frame_summary.csv", common)
    write_csv(args.output_dir / "jitter_summary.csv", jitter.summarize(steps))
    write_csv(args.output_dir / "occlusion_rows.csv", [r for r in rows if r["dataset"] == "sequence" and 1110 <= r["frame"] <= 1155])
    write_csv(args.output_dir / "synthetic_contour.csv", demo_points)
    write_csv(args.output_dir / "synthetic_representatives.csv", [dict(method=m, **r) for m, r in demo.items()])
    plot(rows, summary, args.output_dir, demo, demo_points)
    if not all(sha256(Path(p)) == h for p, h in hashes.items()):
        raise ValueError("input changed during replay")
    evaluation = []
    for model in models:
        group = [r for r in new_rows if r["dataset"] == "sequence" and r["model"] == model]
        after = next((r for r in group if r["frame"] > 1134 and r["quality_accepted"]), None)
        evaluation.append(dict(model=model, accepted_during_reviewed_interval=[r["frame"] for r in group
                    if 1125 <= r["frame"] <= 1134 and r["quality_accepted"]], first_accepted_after_1134=after["frame"] if after else None))
    report = dict(status="OFFLINE_TIE_INCLUSIVE_CANDIDATE_NOT_PHYSICAL_CONTACT_OR_FFB_APPROVAL",
        source_frames=5143, legacy_pixels_reproduced=5143, previous_quality_rows_reproduced=30858,
        new_quality_rows=len(new_rows), primary_v_min=30, bottom_fraction=.08,
        algorithm_change="include all Y ties at the old bottom quantile cutoff; XY median",
        thresholds_or_geometry_changed=False, settings=prior["settings"], models=models,
        development_recordings_not_independent_holdout=True, occlusion_evaluation=evaluation,
        runtime_changed=False, physical_output=False, new_inference=False, source_images_edited=False,
        new_camera_images_saved=False, usable_for_ffb=False, source_sha256=hashes,
        output_sha256={p.name: sha256(p) for p in args.output_dir.iterdir() if p.is_file()})
    (args.output_dir / "provenance.json").write_text(json.dumps(report, indent=2)+"\n")
    print(json.dumps(dict(occlusion_evaluation=evaluation), indent=2))
    for row in summary:
        if row["model"] == "height_only59" and row["reference_z_m"] is not None:
            print(row["dataset"], row["condition"], row["method"], row["projection_candidates"],
                  row["quality_accepted"], row["frames"], row["accepted_z_median_m"], flush=True)


if __name__ == "__main__":
    main()
