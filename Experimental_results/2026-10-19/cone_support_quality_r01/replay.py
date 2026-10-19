"""All-frame support-quality replay from frozen image-column CSVs; no inference/ROS."""
import argparse
from collections import Counter, defaultdict
from dataclasses import asdict
import json
import math
import os
from pathlib import Path
import sys

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SUPPORT = HERE.parent / "cone_support_extent_r01"
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(SUPPORT))
from cone_dataset import read_csv, sha256, write_csv
from cone_support_quality import ConeSupportQualityGate, SupportQualitySettings
from extent_audit import typed, key


def index_curves(points):
    curves = defaultdict(list)
    seen = set()
    for p in points:
        if p["in_observed_support"] != "True":
            continue
        k, x, y = key(p), float(p["x"]), float(p["y"])
        if (k, x) in seen or not all(math.isfinite(v) for v in (x, y)):
            raise ValueError("finite unique observed columns required")
        seen.add((k, x))
        curves[k].append((x, y))
    return dict(curves)


def replay_frames(rows, curves, settings=None):
    frame_keys = [key(row) for row in rows]
    if len(set(frame_keys)) != len(frame_keys) or set(curves)-set(frame_keys):
        raise ValueError("duplicate frames or orphan curve")
    gates, last_frame, output = {}, {}, []
    for source in rows:
        k = key(source)
        session = k[:2]
        if k[2] != last_frame.get(session, 0)+1:
            raise ValueError("complete consecutive original frames required")
        last_frame[session] = k[2]
        curve = curves.get(k)
        if bool(curve) != source["envelope_available"]:
            raise ValueError("source envelope/observed-column mismatch")
        n = source["candidates"]
        if n == 1:
            candidates = [dict(support=curve, unavailable_reason=source["reason"])]
        else:
            if curve:
                raise ValueError("ambiguous/no source detection cannot supply a selected curve")
            candidates = [dict(support=None) for _ in range(n)]
        if session not in gates:
            gates[session] = ConeSupportQualityGate(settings)
        r = gates[session].update(source["time_sec"], candidates)
        observation = r.pop("observed_support")
        r["observed_columns"] = len(observation) if observation is not None else 0
        r["comparison_failures"] = json.dumps(r["comparison_failures"])
        r["pending_comparison_failures"] = json.dumps(r["pending_comparison_failures"])
        # The following labels are appended ONLY AFTER the causal gate update.
        output.append(dict(dataset=k[0], session=k[1], frame=k[2], time_sec=source["time_sec"],
                           condition=source["condition"], input_envelope_available=source["envelope_available"],
                           input_line_consistent=source["line_consistent"], candidates=n, **r))
    return output


def summarize(rows):
    groups = defaultdict(list)
    for row in rows:
        groups[row["dataset"], row["condition"]].append(row)
    output = []
    for (dataset, condition), group in sorted(groups.items()):
        output.append(dict(dataset=dataset, condition=condition, frames=len(group),
            envelopes=sum(r["input_envelope_available"] for r in group),
            shape_line_consistent=sum(r["input_line_consistent"] for r in group),
            support_quality_accepted=sum(r["quality_accepted"] for r in group),
            accepted_without_single_line_consistency=sum(r["quality_accepted"] and not r["input_line_consistent"] for r in group),
            withheld_reasons=json.dumps(dict(Counter(r["reason"] for r in group if not r["quality_accepted"])), sort_keys=True),
            floor_contact_verified=False, usable_for_ffb=False))
    return output


def withheld_runs(rows):
    groups = defaultdict(list)
    for row in rows:
        groups[row["dataset"], row["session"]].append(row)
    output = []
    for (dataset, session), group in sorted(groups.items()):
        i, before = 0, None
        while i < len(group):
            if group[i]["quality_accepted"]:
                before = group[i]
                i += 1
                continue
            start = i
            while i < len(group) and not group[i]["quality_accepted"]:
                i += 1
            run, after = group[start:i], group[i] if i < len(group) else None
            output.append(dict(dataset=dataset, session=session, start_frame=run[0]["frame"], end_frame=run[-1]["frame"],
                               withheld_frames=len(run), previous_accepted_frame=before["frame"] if before else None,
                               next_accepted_frame=after["frame"] if after else None,
                               accepted_gap_sec=after["time_sec"]-before["time_sec"] if after and before else None,
                               reasons=json.dumps(dict(Counter(r["reason"] for r in run)), sort_keys=True), usable_for_ffb=False))
    return output


def load_inputs():
    directory = SUPPORT / "results_r01"
    original = json.loads((directory / "provenance.json").read_text())
    for path, digest in original["source_sha256"].items():
        if sha256(Path(path)) != digest:
            raise ValueError("frozen image source changed: "+path)
    for name, digest in original["output_sha256"].items():
        if sha256(directory / name) != digest:
            raise ValueError("frozen image result changed: "+name)
    rows = [typed(r) for r in read_csv(directory / "observations.csv")]
    curves = index_curves(read_csv(directory / "lower_envelopes.csv"))
    if len(rows) != 5143 or len(curves) != 4354:
        raise ValueError("complete frozen image observations required")
    paths = [Path(__file__), HERE / "method.md", ROOT / "src/cone_support_quality.py",
             ROOT / "tests/test_cone_support_quality.py", SUPPORT / "extent_audit.py",
             directory / "observations.csv", directory / "lower_envelopes.csv", directory / "provenance.json"]
    hashes = dict(original["source_sha256"])
    hashes.update({str(p): sha256(p) for p in paths})
    return rows, curves, hashes


def plot(rows, summary, output):
    os.environ.setdefault("MPLCONFIGDIR", "/tmp/cone_support_quality_matplotlib")
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    chosen = [r for r in rows if r["dataset"] == "sequence" and 1110 <= r["frame"] <= 1155]
    fig, axes = plt.subplots(3, 1, figsize=(12, 8), sharex=True, layout="constrained")
    for ax, candidates, observed in ((axes[0], ("candidate_x_lo", "candidate_x_hi"), ("observed_x_lo", "observed_x_hi")),
                                      (axes[1], ("candidate_y_min", "candidate_y_max"), ("observed_y_min", "observed_y_max"))):
        for name in candidates:
            ax.plot([r["frame"] for r in chosen], [r[name] if r[name] is not None else np.nan for r in chosen], ".", color=".65", label=name)
        for name in observed:
            ax.plot([r["frame"] for r in chosen], [r[name] if r[name] is not None else np.nan for r in chosen], ".", label=name)
        ax.axvspan(1125, 1134, color="orange", alpha=.15)
        ax.grid(alpha=.3)
        ax.legend(fontsize=7)
    axes[0].set(ylabel="Native X [px]", title="Support continuity ONLY: rejected boundaries are never filled by an old anchor")
    axes[1].set_ylabel("Native boundary Y [px]")
    axes[2].plot([r["frame"] for r in chosen], [r["confirmation_count"] for r in chosen], ".-", label="Consecutive confirmations")
    axes[2].plot([r["frame"] for r in chosen], [int(r["quality_accepted"]) for r in chosen], ".-", label="Accepted image observation")
    axes[2].axvspan(1125, 1134, color="orange", alpha=.15, label="Prior occlusion annotation, evaluation only")
    axes[2].set(xlabel="Original frame; no metric projection or FFB output", ylabel="Count / boolean")
    axes[2].grid(alpha=.3)
    axes[2].legend(fontsize=7)
    fig.savefig(output / "support_occlusion_recovery.png", dpi=150)
    plt.close(fig)
    order = [("static", c) for c in ("center_080", "center_130", "center_200", "left_130", "right_130", "none")]
    order += [("sequence", "cone_130"), ("sequence", "cone_200")]
    chosen = [next(r for r in summary if (r["dataset"], r["condition"]) == k) for k in order]
    fig, ax = plt.subplots(figsize=(11, 4), layout="constrained")
    x = np.arange(len(order))
    for shift, field, label in ((-.25, "envelopes", "Observed envelope"), (0, "shape_line_consistent", "Single-line shape screen"),
                                (.25, "support_quality_accepted", "Temporal image support")):
        ax.bar(x+shift, [r[field]/r["frames"] for r in chosen], .25, label=label)
    ax.set_xticks(x, [d+"\n"+c for d, c in order], fontsize=8)
    ax.set(ylabel="Fraction of ALL frames", title="Image-space comparisons: NOT detection recall, physical contact accuracy or distance precision")
    ax.legend(fontsize=8)
    ax.grid(axis="y", alpha=.3)
    fig.savefig(output / "support_quality_coverage.png", dpi=150)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.output_dir.exists():
        raise ValueError("new output required; do not overwrite frozen replay")
    source, curves, hashes = load_inputs()
    settings = SupportQualitySettings()
    rows = replay_frames(source, curves, settings)
    summary = summarize(rows)
    sequence = [r for r in rows if r["dataset"] == "sequence"]
    after = next((r for r in sequence if r["frame"] > 1134 and r["quality_accepted"]), None)
    before = next((r for r in reversed(sequence) if r["frame"] < 1125 and r["quality_accepted"]), None)
    return_source = next(r for r in sequence if r["frame"] == 1135)
    evaluation = dict(accepted_during_reviewed_occlusion=[r["frame"] for r in sequence if 1125 <= r["frame"] <= 1134 and r["quality_accepted"]],
                      first_accepted_after_1134=after["frame"] if after else None,
                      timestamp_since_frame1135_sec=after["time_sec"]-return_source["time_sec"] if after else None,
                      last_accepted_before_1125=before["frame"] if before else None,
                      accepted_gap_sec=after["time_sec"]-before["time_sec"] if after and before else None)
    args.output_dir.mkdir(parents=True)
    write_csv(args.output_dir / "observations.csv", rows)
    write_csv(args.output_dir / "summary.csv", summary)
    write_csv(args.output_dir / "withheld_runs.csv", withheld_runs(rows))
    write_csv(args.output_dir / "occlusion_rows.csv", [r for r in sequence if 1110 <= r["frame"] <= 1155])
    plot(rows, summary, args.output_dir)
    if not all(sha256(Path(p)) == digest for p, digest in hashes.items()):
        raise ValueError("inputs changed during replay")
    report = dict(status="SUPPORT_CONTINUITY_REPLAY_ONLY_NOT_CONTACT_OR_FFB_APPROVAL", source_frames=len(rows),
                  settings=asdict(settings), occlusion_evaluation=evaluation,
                  line_consistency_used_by_gate=False, metric_projection_used=False,
                  thresholds_changed_after_replay=False, physical_output=False, usable_for_ffb=False,
                  runtime_integration_performed=False, new_camera_images_saved=False,
                  source_sha256=hashes, output_sha256={p.name: sha256(p) for p in args.output_dir.iterdir() if p.is_file()})
    (args.output_dir / "provenance.json").write_text(json.dumps(report, indent=2)+"\n")
    print(json.dumps(evaluation, indent=2))
    for row in summary:
        print(row)


if __name__ == "__main__":
    main()
