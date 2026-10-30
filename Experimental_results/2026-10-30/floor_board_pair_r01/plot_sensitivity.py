#!/usr/bin/env python3
"""Numeric plot only; never modifies the source photographs."""
import argparse
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-summary", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("new output required")
    data = json.loads(args.input_summary.read_text())
    fig, ax = plt.subplots(figsize=(9, 5))
    colours = {.5: "tab:blue", 1.: "tab:orange"}
    for row in data["pixel_sensitivity"]:
        x = (0 if row["frame"] == 1259 else 1) + (-.12 if row["amplitude_px"] == .5 else .12)
        lo, hi, base = [100*v for v in (row["min_height_m"], row["max_height_m"], row["baseline_height_m"])]
        colour = colours[row["amplitude_px"]]
        ax.vlines(x, lo, hi, color=colour, linewidth=3)
        ax.hlines([lo, hi], x-.035, x+.035, color=colour)
        ax.plot(x, base, "o", color=colour)
        ax.text(x, hi+.5, f"+/-{row['amplitude_px']:g}px\n{lo:.1f}-{hi:.1f}cm", ha="center", fontsize=9)
    ax.axhline(59, color="black", linestyle="--", label="Independently reported lens-to-floor height: 59cm")
    ax.set(xticks=[0, 1], xticklabels=["Frame 1259", "Frame 1655"], xlim=(-.45, 1.45),
           ylim=(44, 69), ylabel="Camera-to-printed-plane height (cm)",
           title="Paper perimeter PnP: native-pixel sensitivity (diagnostic only)")
    ax.grid(axis="y", alpha=.2)
    ax.legend(loc="lower center", fontsize=9)
    fig.text(.5, .02, "Ranges: extrema of 256 sign combinations each; NOT confidence intervals.\n"
             "Board thickness unknown; camera-to-paper is not camera-to-floor. No physical approval.",
             ha="center", fontsize=9)
    fig.tight_layout(rect=(0, .09, 1, 1))
    fig.savefig(args.output, dpi=150)
    plt.close(fig)


if __name__ == "__main__":
    main()
