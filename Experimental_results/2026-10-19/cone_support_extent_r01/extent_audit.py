"""Audit observed envelope ranges INCLUDING single-line-inconsistent frames."""
import argparse
from collections import defaultdict
import json
import os
from pathlib import Path

import numpy as np

import analyze_support as source
from cone_dataset import read_csv, sha256, write_csv


def typed(row):
    text = {"dataset", "session", "condition", "reason"}
    integers = {"frame", "candidates", "envelope_columns", "support_columns"}
    result = {}
    for k, v in row.items():
        if v == "":
            result[k] = None
        elif k in text:
            result[k] = v
        elif v in ("True", "False"):
            result[k] = v == "True"
        else:
            result[k] = int(v) if k in integers else float(v)
    return result


def key(row):
    return row["dataset"], row["session"], int(row["frame"])


def audit_ranges(rows, points):
    curves = defaultdict(dict)
    for p in points:
        if p["in_observed_support"] == "True":
            k, x, y = key(p), float(p["x"]), float(p["y"])
            if x in curves[k]:
                raise ValueError("duplicate envelope column")
            curves[k][x] = y
    output, steps, previous = [], [], {}
    for row in rows:
        k = key(row)
        curve = curves.get(k, {})
        if bool(curve) != row["envelope_available"]:
            raise ValueError("all existing image envelopes require retained observed support")
        record = dict(dataset=k[0], session=k[1], frame=k[2], condition=row["condition"],
                      time_sec=row["time_sec"], envelope_available=row["envelope_available"],
                      line_consistent=row["line_consistent"],
                      x_lo=min(curve) if curve else None, x_hi=max(curve) if curve else None,
                      observed_y_min=min(curve.values()) if curve else None,
                      observed_y_max=max(curve.values()) if curve else None,
                      legacy_pixel_x=row["legacy_pixel_x"], legacy_pixel_y=row["legacy_pixel_y"],
                      floor_contact_verified=False, usable_for_ffb=False)
        output.append(record)
        session_key = k[:2]
        last = previous.get(session_key)
        if (last and k[2] == last["frame"]+1 and row["condition"] == last["condition"]
                and curve and curves.get(key(last))):
            before = curves[key(last)]
            shared = sorted(set(curve) & set(before))
            delta = [abs(curve[x]-before[x]) for x in shared]
            steps.append(dict(dataset=k[0], session=k[1], condition=row["condition"], previous_frame=last["frame"], frame=k[2],
                shared_observed_columns=len(shared), support_column_iou=len(shared)/len(set(curve) | set(before)),
                dx_lo_px=min(curve)-min(before), dx_hi_px=max(curve)-max(before),
                envelope_dy_abs_median_px=float(np.median(delta)) if delta else None,
                envelope_dy_abs_p95_px=float(np.percentile(delta, 95)) if delta else None,
                legacy_dx_px=row["legacy_pixel_x"]-last["legacy_pixel_x"],
                both_line_consistent=row["line_consistent"] and last["line_consistent"], usable_for_ffb=False))
        previous[session_key] = row
    return output, steps


def summarize(steps):
    groups = defaultdict(list)
    for row in steps:
        groups[row["dataset"], row["condition"]].append(row)
    output = []
    for (dataset, condition), group in sorted(groups.items()):
        result = dict(dataset=dataset, condition=condition, adjacent_envelope_pairs=len(group),
                      also_both_line_consistent=sum(r["both_line_consistent"] for r in group),
                      support_column_iou_median=float(np.median([r["support_column_iou"] for r in group])),
                      usable_for_ffb=False)
        for field in ("dx_lo_px", "dx_hi_px", "legacy_dx_px", "envelope_dy_abs_median_px", "envelope_dy_abs_p95_px"):
            values = [abs(r[field]) for r in group if r[field] is not None]
            result[field+"_p95"] = float(np.percentile(values, 95)) if values else None
        output.append(result)
    return output


def plot(records, all_rows, output):
    os.environ.setdefault("MPLCONFIGDIR", "/tmp/cone_support_extent_matplotlib")
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    chosen = [r for r in records if r["dataset"] == "static" and r["condition"] == "left_130"]
    fig, axes = plt.subplots(2, 1, figsize=(12, 6), sharex=True, layout="constrained")
    for field in ("x_lo", "x_hi", "legacy_pixel_x"):
        axes[0].plot([r["frame"] for r in chosen], [r[field] if r[field] is not None else np.nan for r in chosen], ".", ms=2, label=field)
    for field in ("observed_y_min", "observed_y_max"):
        axes[1].plot([r["frame"] for r in chosen], [r[field] if r[field] is not None else np.nan for r in chosen], ".", ms=2, label=field)
    for ax in axes:
        ax.grid(alpha=.3)
        ax.legend(fontsize=8)
    axes[0].set(ylabel="Native X [px]", title="All observed support ranges (not limited to line-consistent frames)")
    axes[1].set(ylabel="Observed boundary Y range [px]", xlabel="Original frame; no missing-value fill")
    fig.savefig(output / "all_envelope_ranges.png", dpi=150)
    plt.close(fig)
    summary = source.summarize(all_rows)
    order = [("static", c) for c in ("center_080", "center_130", "center_200", "left_130", "right_130", "none")]
    order += [("sequence", "cone_130"), ("sequence", "cone_200")]
    chosen = [next(r for r in summary if (r["dataset"], r["condition"]) == k) for k in order]
    fig, ax = plt.subplots(figsize=(11, 4), layout="constrained")
    x = np.arange(len(order))
    ax.bar(x-.18, [r["envelopes"]/r["frames"] for r in chosen], .36, label="Observed envelope / ALL frames")
    ax.bar(x+.18, [r["line_consistent"]/r["frames"] for r in chosen], .36, label="Single-line consistent / ALL frames")
    ax.set_xticks(x, [d+"\n"+c for d, c in order], fontsize=8)
    ax.set(ylabel="Fraction of all frames", title="Image shape counts ONLY: not physical contact accuracy or detection recall")
    ax.grid(axis="y", alpha=.3)
    ax.legend(fontsize=8)
    fig.savefig(output / "observed_range_coverage.png", dpi=150)
    plt.close(fig)
    chosen = [r for r in records if r["dataset"] == "sequence" and 1110 <= r["frame"] <= 1155]
    fig, axes = plt.subplots(2, 1, figsize=(11, 6), sharex=True, layout="constrained")
    for ax, fields in zip(axes, (("x_lo", "x_hi"), ("observed_y_min", "observed_y_max"))):
        for field in fields:
            ax.plot([r["frame"] for r in chosen], [r[field] if r[field] is not None else np.nan for r in chosen], ".-", label=field)
        ax.axvspan(1125, 1134, alpha=.15, color="orange", label="Previously reviewed occlusion, evaluation only")
        ax.grid(alpha=.3)
        ax.legend(fontsize=8)
    axes[0].set(ylabel="Observed X extent [px]", title="Visible contour edge during occlusion does NOT prove a visible base")
    axes[1].set(ylabel="Observed Y extent [px]", xlabel="Original frame; no metric projection")
    fig.savefig(output / "occlusion_observed_ranges.png", dpi=150)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.output_dir.exists():
        raise ValueError("new output required")
    provenance = json.loads((args.input_dir / "provenance.json").read_text())
    for name, digest in provenance["output_sha256"].items():
        if sha256(args.input_dir / name) != digest:
            raise ValueError("frozen image results changed")
    paths = [Path(__file__), args.input_dir / "provenance.json", args.input_dir / "observations.csv",
             args.input_dir / "lower_envelopes.csv", source.HERE / "analyze_support.py", source.HERE / "support.py"]
    hashes = {str(p): sha256(p) for p in paths}
    rows = [typed(r) for r in read_csv(args.input_dir / "observations.csv")]
    records, steps = audit_ranges(rows, read_csv(args.input_dir / "lower_envelopes.csv"))
    args.output_dir.mkdir(parents=True)
    write_csv(args.output_dir / "observed_ranges.csv", records)
    write_csv(args.output_dir / "adjacent_envelopes.csv", steps)
    write_csv(args.output_dir / "range_stability_summary.csv", summarize(steps))
    plot(records, rows, args.output_dir)
    assert all(sha256(Path(p)) == h for p, h in hashes.items())
    report = dict(status="IMAGE_RANGE_DIAGNOSIS_INCLUDES_NONLINEAR_ENVELOPES", source_sha256=hashes,
                  source_frames=len(rows), no_line_consistency_filter=True,
                  correspondence="actual shared integer image columns only; no interpolation or missing-frame bridge",
                  geometry_or_metric_projection_used=False, usable_for_ffb=False,
                  output_sha256={p.name: sha256(p) for p in args.output_dir.iterdir() if p.is_file()})
    (args.output_dir / "provenance.json").write_text(json.dumps(report, indent=2)+"\n")
    for row in summarize(steps):
        print(row)


if __name__ == "__main__":
    main()
