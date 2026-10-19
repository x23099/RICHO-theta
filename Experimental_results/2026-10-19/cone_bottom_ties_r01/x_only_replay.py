"""Second prespecified diagnostic: repair X ties, preserve the ORIGINAL Y estimator."""
import argparse
import json
import math
from pathlib import Path

import numpy as np

import analyze as first
from cone_dataset import read_csv, sha256, write_csv

HERE = Path(__file__).resolve().parent


def candidates_from_pixels(ledger, selected, pixels):
    index = {first.quality.key(r): r for r in pixels}
    if len(index) != len(pixels) or set(index) != {first.quality.key(r) for r in ledger}:
        raise ValueError("exactly one pixel record per original frame required")
    output = {}
    for source in ledger:
        k = first.quality.key(source)
        p = index[k]
        if float(p["time_sec"]) != source["time_sec"] or int(p["candidates"]) != len(selected[k]):
            raise ValueError("source frame/time/association mismatch")
        valid = first.quality.flag(p["colour_candidate"])
        if valid and len(selected[k]) != 1:
            raise ValueError("valid point requires one source detection")
        x = float(p["tie_inclusive_pixel_x"]) if valid else None
        y = float(p["legacy_pixel_y"]) if valid else None
        if valid and (not all(math.isfinite(v) for v in (x, y))
                      or selected[k][0]["_colour"]["y"] != y):
            raise ValueError("finite point and identical legacy Y required")
        evidence = dict(valid=valid, reason=p["reason"], x=x, y=y)
        output[k] = [dict(b, _colour=evidence.copy()) for b in selected[k]]
    return output


def common_comparison(rows):
    groups = {}
    for row in rows:
        groups.setdefault((first.quality.key(row), row["model"]), {})[row["method"]] = row
    result = []
    for (_, model), group in groups.items():
        old, new = group["legacy"], group["tie_x_only"]
        result.append(dict(dataset=new["dataset"], session=new["session"], condition=new["condition"],
                           frame=new["frame"], model=model, reference_z_m=new["reference_z_m"],
                           common_projection=old["projection_candidate"] and new["projection_candidate"],
                           common_quality=old["quality_accepted"] and new["quality_accepted"],
                           legacy_x_m=old["candidate_x_m"], legacy_z_m=old["candidate_z_m"],
                           tie_x_only_x_m=new["candidate_x_m"], tie_x_only_z_m=new["candidate_z_m"],
                           legacy_accepted=old["quality_accepted"], tie_x_only_accepted=new["quality_accepted"],
                           tie_x_only_reason=new["reason"], usable_for_ffb=False))
    return result


def plot(rows, summary, output):
    import os
    os.environ.setdefault("MPLCONFIGDIR", "/tmp/cone_bottom_ties_matplotlib")
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    modes = ("legacy", "tie_inclusive", "tie_x_only")
    fig, axes = plt.subplots(2, 2, figsize=(13, 7), sharex="col", layout="constrained")
    for col, condition in enumerate(("left_130", "center_200")):
        for mode in modes:
            chosen = [r for r in rows if r["dataset"] == "static" and r["condition"] == condition
                      and r["model"] == "height_only59" and r["method"] == mode]
            for ax, coordinate in zip(axes[:, col], ("x", "z")):
                ax.plot([r["frame"] for r in chosen],
                        [r["candidate_"+coordinate+"_m"] if r["candidate_"+coordinate+"_m"] is not None else np.nan for r in chosen],
                        ".", ms=2, alpha=.6, label=mode)
                ax.set_ylabel(coordinate.upper()+" hypothesis [m]")
                ax.grid(alpha=.3)
                ax.legend(fontsize=7)
        axes[0, col].set_title(condition+" / fixed h59 / no gate relaxation")
        axes[-1, col].set_xlabel("Original frame (missing not filled)")
    fig.savefig(output / "x_only_xy_comparison.png", dpi=150)
    plt.close(fig)
    order = [("static", c) for c in ("center_080", "center_130", "center_200", "left_130", "right_130")]
    order += [("sequence", "cone_130"), ("sequence", "cone_200")]
    fig, axes = plt.subplots(2, 1, figsize=(12, 7), sharex=True, layout="constrained")
    for mode in ("bbox",)+modes:
        chosen = [next(r for r in summary if (r["dataset"], r["condition"], r["model"], r["method"])
                       == (d, c, "height_only59", mode)) for d, c in order]
        axes[0].plot(range(len(order)), [r["quality_accepted"]/r["frames"] for r in chosen], "o-", label=mode)
        axes[1].plot(range(len(order)), [r["accepted_z_bias_m"] for r in chosen], "o-", label=mode)
    for ax in axes:
        ax.set_xticks(range(len(order)), [d+"\n"+c for d, c in order], fontsize=8)
        ax.grid(alpha=.3)
        ax.legend(fontsize=8)
    axes[0].set(ylabel="Quality accepted / ALL frames", title="Development replay only: stable hypotheses can still be biased")
    axes[1].axhline(0, color="black", lw=.8)
    axes[1].set_ylabel("Accepted median Z - nominal reference [m]")
    fig.savefig(output / "x_only_coverage_bias.png", dpi=150)
    plt.close(fig)


def run():
    ledger, old_candidates, models, hashes = first.quality.load_inputs()
    prior_dir = HERE / "results_r01"
    report = json.loads((prior_dir / "provenance.json").read_text())
    for path, digest in report["source_sha256"].items():
        if sha256(Path(path)) != digest:
            raise ValueError("previous input changed")
    for name, digest in report["output_sha256"].items():
        if sha256(prior_dir / name) != digest:
            raise ValueError("previous output changed")
    pixels = read_csv(prior_dir / "pixels.csv")
    candidates = candidates_from_pixels(ledger, old_candidates, pixels)
    raw = first.quality.replay(ledger, candidates, models)
    first.quality.bbox_regression(raw, first.quality.PREVIOUS / "results_r01/observations.csv")
    new = [dict(r, method="tie_x_only") for r in raw if r["method"] == "colour"]
    old = first.quality.replay(ledger, old_candidates, models)
    if first.csv_rows(old) != read_csv(first.QUALITY / "results_r02/observations.csv"):
        raise ValueError("old replay did not reproduce")
    for r in old:
        if r["method"] == "colour":
            r["method"] = "legacy"
    # Recompute the first candidate, rather than trusting untyped CSV booleans.
    pixel_index = {first.quality.key(p): p for p in pixels}
    inclusive_candidates = {}
    for k, selected in candidates.items():
        inclusive_candidates[k] = [dict(b, _colour=dict(b["_colour"],
            y=float(pixel_index[k]["tie_inclusive_pixel_y"]) if b["_colour"]["valid"] else None)) for b in selected]
    inclusive_raw = first.quality.replay(ledger, inclusive_candidates, models)
    inclusive = [dict(r, method="tie_inclusive") for r in inclusive_raw if r["method"] == "colour"]
    if first.csv_rows(inclusive) != read_csv(prior_dir / "observations.csv"):
        raise ValueError("first candidate replay did not reproduce")
    hashes.update(report["source_sha256"])
    paths = [Path(__file__), HERE / "method_x_only.md", prior_dir / "pixels.csv",
             prior_dir / "observations.csv", prior_dir / "provenance.json"]
    hashes.update({str(p): sha256(p) for p in paths})
    return ledger, pixels, models, old+inclusive+new, new, hashes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.output_dir.exists():
        raise ValueError("new output required")
    ledger, pixels, models, rows, new, hashes = run()
    args.output_dir.mkdir(parents=True)
    summary = first.quality.summarize(rows)
    write_csv(args.output_dir / "observations.csv", new)
    write_csv(args.output_dir / "summary.csv", summary)
    write_csv(args.output_dir / "frame_pairs.csv", common_comparison(rows))
    write_csv(args.output_dir / "jitter_summary.csv", first.jitter.summarize(first.jitter.differences(first.csv_rows(rows))))
    write_csv(args.output_dir / "occlusion_rows.csv", [r for r in rows if r["dataset"] == "sequence" and 1110 <= r["frame"] <= 1155])
    plot(rows, summary, args.output_dir)
    assert all(sha256(Path(p)) == h for p, h in hashes.items())
    result = dict(status="X_TIE_ONLY_DEVELOPMENT_CANDIDATE_NOT_FFB_APPROVAL", source_frames=len(ledger),
                  new_observation_rows=len(new), models=models,
                  original_y_preserved=True, thresholds_or_geometry_changed=False,
                  runtime_changed=False, physical_output=False, source_images_edited=False,
                  new_inference=False, usable_for_ffb=False, source_sha256=hashes,
                  output_sha256={p.name: sha256(p) for p in args.output_dir.iterdir() if p.is_file()})
    (args.output_dir / "provenance.json").write_text(json.dumps(result, indent=2)+"\n")
    for r in summary:
        if r["model"] == "height_only59" and r["reference_z_m"] is not None and r["method"] == "tie_x_only":
            print(r["dataset"], r["condition"], r["projection_candidates"], r["quality_accepted"], r["frames"], r["accepted_z_median_m"], flush=True)


if __name__ == "__main__":
    main()
