#!/usr/bin/env python3
"""Create a callback-health graph from one bird_eye recording archive."""

from __future__ import annotations

import argparse
import csv
import io
import tarfile
from pathlib import Path

import matplotlib.pyplot as plt


def load_rows(archive_path):
    with tarfile.open(archive_path, "r:xz") as archive:
        members = [
            member
            for member in archive
            if member.name.endswith("/detections.csv")
        ]
        if len(members) != 1:
            raise ValueError(
                f"expected one detections.csv, found {len(members)}"
            )
        stream = archive.extractfile(members[0])
        if stream is None:
            raise ValueError("could not read detections.csv")
        with stream, io.TextIOWrapper(
            stream, encoding="utf-8", newline=""
        ) as text_stream:
            return list(csv.DictReader(text_stream))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    rows = load_rows(args.input)
    elapsed = [float(row["time_sec"]) for row in rows]
    ages_ms = [
        float(row["collision_ffb_challenge_age_sec"]) * 1000.0
        for row in rows
    ]
    counts = [
        int(row["collision_ffb_challenge_received_count"])
        for row in rows
    ]
    count_delta = [value - counts[0] for value in counts]
    ideal = [(value - elapsed[0]) * 50.0 for value in elapsed]
    active_x = [
        elapsed[index]
        for index, row in enumerate(rows)
        if row["collision_ffb_active"] == "1"
    ]
    active_y = [ages_ms[index] for index, row in enumerate(rows)
                if row["collision_ffb_active"] == "1"]

    figure, axes = plt.subplots(2, 1, figsize=(10, 6), sharex=True)
    axes[0].plot(elapsed, ages_ms, color="#2878b5", linewidth=1.0,
                 label="Latest challenge age")
    axes[0].axhline(60.0, color="#d9534f", linestyle="--",
                    label="Sender limit (60 ms)")
    axes[0].scatter(active_x, active_y, color="#d62728", s=24,
                    label="FFB active frame", zorder=3)
    axes[0].set_ylabel("Age [ms]")
    axes[0].set_ylim(bottom=0.0)
    axes[0].grid(alpha=0.25)
    axes[0].legend(loc="upper right")

    axes[1].plot(elapsed, count_delta, color="#2ca02c", linewidth=1.5,
                 label="Received challenge count")
    axes[1].plot(elapsed, ideal, color="#555555", linestyle="--",
                 linewidth=1.0, label="Ideal 50 Hz")
    axes[1].set_xlabel("Recording elapsed time [s]")
    axes[1].set_ylabel("Count since first frame")
    axes[1].grid(alpha=0.25)
    axes[1].legend(loc="upper left")

    figure.suptitle("Phase 5 callback fix r02: challenge reception and FFB")
    figure.tight_layout()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(args.output, dpi=160)
    plt.close(figure)


if __name__ == "__main__":
    main()
