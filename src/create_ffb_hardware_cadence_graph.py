#!/usr/bin/env python3
"""Plot measured adapter latency for hardware cadence trials."""

from __future__ import annotations

import argparse
import csv
import os
import tempfile
from pathlib import Path

os.environ.setdefault(
    "MPLCONFIGDIR",
    str(Path(tempfile.gettempdir()) / "richo-theta-matplotlib"),
)

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402


def read_rows(path: Path) -> list[dict]:
    """Read the hardware cadence summary CSV."""
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ValueError(f"hardware cadence summary is empty: {path}")
    return rows


def plot_latency(rows: list[dict], output: Path) -> None:
    """Plot response and final CLEAR latency from measured trial reports."""
    labels = [row["cadence"] for row in rows]
    response = [float(row["response_latency_p95_ms"]) for row in rows]
    stop = [float(row["final_clear_stop_latency_ms"]) for row in rows]
    positions = list(range(len(rows)))
    width = 0.36

    figure, axis = plt.subplots(figsize=(8, 4.5))
    axis.bar(
        [position - width / 2 for position in positions],
        response,
        width,
        label="Response p95",
    )
    axis.bar(
        [position + width / 2 for position in positions],
        stop,
        width,
        label="Final CLEAR stop",
    )
    axis.set_xticks(positions, labels)
    axis.set_ylabel("Latency [ms]")
    axis.set_title("Collision FFB hardware cadence latency (0.05, 0.5 s)")
    axis.set_ylim(0.0, max(response + stop) * 1.25)
    axis.grid(axis="y", alpha=0.3)
    axis.legend()
    figure.tight_layout()
    output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output, dpi=160)
    plt.close(figure)


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(args=None) -> int:
    """Create one reproducible hardware cadence graph."""
    parsed = build_parser().parse_args(args)
    plot_latency(read_rows(parsed.input), parsed.output)
    print(f"Graph: {parsed.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
