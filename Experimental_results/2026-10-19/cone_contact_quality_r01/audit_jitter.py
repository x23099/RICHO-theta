"""Post-replay evaluation only: consecutive-frame candidate X/Z differences."""
import argparse
from collections import defaultdict
import json
import math
import os
from pathlib import Path
import sys

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "src"))
from cone_dataset import read_csv, sha256, write_csv


def differences(rows):
    previous, output = {}, []
    for row in rows:
        group = row["dataset"], row["session"], row["model"], row["method"]
        last = previous.get(group)
        # Never bridge a missing projection or a condition boundary to claim static jitter.
        if (last is not None and int(row["frame"]) == int(last["frame"])+1
                and row["condition"] == last["condition"]
                and row["candidate_x_m"] != "" and last["candidate_x_m"] != ""):
            dx = float(row["candidate_x_m"])-float(last["candidate_x_m"])
            dz = float(row["candidate_z_m"])-float(last["candidate_z_m"])
            output.append(dict(dataset=row["dataset"], session=row["session"], condition=row["condition"],
                model=row["model"], method=row["method"], previous_frame=int(last["frame"]), frame=int(row["frame"]),
                dx_m=dx, dz_m=dz, step_m=math.hypot(dx, dz), reason=row["reason"],
                quality_accepted=row["quality_accepted"], usable_for_ffb=False))
        previous[group] = row
    return output


def summarize(rows):
    groups = defaultdict(list)
    for row in rows:
        groups[row["dataset"], row["condition"], row["model"], row["method"]].append(row)
    output = []
    for (dataset, condition, model, method), group in sorted(groups.items()):
        output.append(dict(dataset=dataset, condition=condition, model=model, method=method,
            consecutive_valid_pairs=len(group), abs_dx_p95_m=float(np.percentile([abs(r["dx_m"]) for r in group], 95)),
            abs_dz_p95_m=float(np.percentile([abs(r["dz_m"]) for r in group], 95)),
            step_over_015m=sum(r["step_m"] > .15 for r in group),
            mostly_x_steps_over_015m=sum(abs(r["dx_m"]) > .15 and abs(r["dz_m"]) < .03 for r in group),
            usable_for_ffb=False))
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.output_dir.exists():
        raise ValueError("new output required")
    source = args.input_dir / "observations.csv"
    provenance = json.loads((args.input_dir / "provenance.json").read_text())
    if sha256(source) != provenance["output_sha256"][source.name]:
        raise ValueError("source observations differ from frozen replay")
    hashes = {str(p): sha256(p) for p in (Path(__file__), source, args.input_dir / "provenance.json")}
    rows = read_csv(source)
    steps = differences(rows)
    summary = summarize(steps)
    args.output_dir.mkdir(parents=True)
    write_csv(args.output_dir / "consecutive_steps.csv", steps)
    write_csv(args.output_dir / "jitter_summary.csv", summary)
    os.environ.setdefault("MPLCONFIGDIR", "/tmp/cone_contact_quality_matplotlib")
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(2, 1, figsize=(12, 7), sharex=True, layout="constrained")
    for method in ("bbox", "colour"):
        chosen = [r for r in rows if r["dataset"] == "static" and r["condition"] == "left_130"
                  and r["model"] == "height_only59" and r["method"] == method]
        for ax, coordinate in zip(axes, ("x", "z")):
            ax.plot([int(r["frame"]) for r in chosen],
                    [float(r["candidate_"+coordinate+"_m"]) if r["candidate_"+coordinate+"_m"] != "" else np.nan for r in chosen],
                    ".", ms=2, alpha=.65, label=method+" raw floor hypothesis")
            ax.set_ylabel(coordinate.upper()+" candidate [m]")
            ax.grid(alpha=.3)
            ax.legend()
    axes[0].set_title("Static left recording / fixed h59: color-bottom X instability; no threshold changes")
    axes[-1].set_xlabel("Original frame; missing values are not interpolated")
    fig.savefig(args.output_dir / "left_position_instability.png", dpi=150)
    plt.close(fig)
    assert all(sha256(Path(p)) == h for p, h in hashes.items())
    report = dict(status="POST_REPLAY_DIAGNOSTIC_NOT_GATE_INPUT", source_sha256=hashes,
                  metric_definition="adjacent original frames with both projections and same condition; no missing-value bridge",
                  no_parameter_fitting=True, usable_for_ffb=False,
                  output_sha256={p.name: sha256(p) for p in args.output_dir.iterdir() if p.is_file()})
    (args.output_dir / "provenance.json").write_text(json.dumps(report, indent=2)+"\n")
    for row in summary:
        if row["model"] == "height_only59" and row["condition"] in ("left_130", "center_130", "center_200", "cone_200"):
            print(row)


if __name__ == "__main__":
    main()
