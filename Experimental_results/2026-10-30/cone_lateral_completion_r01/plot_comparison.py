#!/usr/bin/env python3
"""Plot numerical bbox translations, never modified camera imagery."""
import argparse
import csv
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=False)
    rows = [json.loads(line) for line in (args.input_dir / "bbox_translation_controls.jsonl").read_text().splitlines()]
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    counts = []
    for identity in ("native_pair:1259:0", "native_pair:1655:0", "native_pair:1259:1", "native_pair:1655:1"):
        group = [r for r in rows if r["identity"] == identity]
        counts.append(dict(identity=identity, perturbations=len(group),
            previous_available=sum(r["previous_point"] is not None for r in group),
            candidate_available=sum(r["candidate_point"] is not None for r in group)))
    fig, ax = plt.subplots(figsize=(9, 5))
    x = range(len(counts))
    ax.bar([i-.18 for i in x], [r["previous_available"] for r in counts], width=.36, label="Existing colour-shadow candidate")
    ax.bar([i+.18 for i in x], [r["candidate_available"] for r in counts], width=.36, label="Bounded lateral completion candidate")
    ax.set(xticks=list(x), xticklabels=["Frame 1259\nred target", "Frame 1655\nred target", "Frame 1259\nyellow/floor", "Frame 1655\nyellow/floor"],
           yticks=list(range(10)), ylim=(0, 10), ylabel="Available support observations / 9 bbox translations",
           title="Same native pixels, detector bbox translated by +/-1px in x/y")
    for i, r in enumerate(counts):
        ax.text(i-.18, r["previous_available"]+.12, str(r["previous_available"]), ha="center")
        ax.text(i+.18, r["candidate_available"]+.12, str(r["candidate_available"]), ha="center")
    ax.legend(fontsize=8, loc="upper right")
    ax.grid(axis="y", alpha=.15)
    fig.text(.5, .02, "Translations are synthetic bbox controls, NOT new video frames. Native images unchanged.\n"
             "Support availability is NOT contact correctness/distance accuracy. No live/FFB integration.", ha="center", fontsize=9)
    fig.tight_layout(rect=(0, .10, 1, 1))
    fig.savefig(args.output_dir / "support_availability.png", dpi=150)
    plt.close(fig)
    with (args.output_dir / "pair_translation_counts.csv").open("x", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(counts[0]))
        writer.writeheader()
        writer.writerows(counts)


if __name__ == "__main__":
    main()
