"""Plot CSV counts only; no camera image processing or model execution."""
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evaluation", type=Path, required=True)
    args = parser.parse_args()
    root = args.evaluation.resolve()
    target = root / "front_scope_comparison.png"
    provenance = root / "graph_provenance.json"
    if target.exists() or provenance.exists():
        raise ValueError("graph already exists; no overwrite")
    rows = list(csv.DictReader((root / "metrics.csv").open()))
    os.environ["MPLCONFIGDIR"] = str(root / "matplotlib_config")
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    models = ("baseline_35", "augmented_36", "negative_52", "friend_yolo11n")
    fig, axes = plt.subplots(2, 3, figsize=(13, 7))
    for i, scope in enumerate(("front_centre_detection", "front_projection_hypotheses")):
        for j, group in enumerate(("b", "d", "e")):
            selected = [next(r for r in rows if r["model"] == model and r["set"] == group
                             and r["scope"] == scope and r["confidence_threshold"] == "0.25") for model in models]
            axis = axes[i, j]
            x = list(range(4))
            axis.bar([v-.17 for v in x], [int(r["fp"]) for r in selected], .34, label="FP")
            axis.bar([v+.17 for v in x], [int(r["fn"]) for r in selected], .34, label="FN")
            axis.set_xticks(x, ("35", "36", "52", "friend"))
            axis.set_title(f'{group.upper()} / {"front detection" if i == 0 else "projection hypotheses"} / GT={selected[0]["gt_count"]}')
            axis.set_ylabel("Box count"); axis.legend()
    fig.suptitle("Fixed confidence 0.25 / 960px / same front GT before and after geometry")
    fig.text(.5, .015, "B: legacy visual labels; D: train reuse for 52; E: human labels. Floor contact NOT verified. No FFB approval.",
             ha="center", fontsize=9)
    fig.tight_layout(rect=(0, .05, 1, .95)); fig.savefig(target, dpi=150); plt.close(fig)
    digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    provenance.write_text(json.dumps(dict(csv_sha256=digest(root / "metrics.csv"),
                                          graph_sha256=digest(target), script_sha256=digest(Path(__file__))), indent=2) + "\n")
    print(target)


if __name__ == "__main__":
    main()
