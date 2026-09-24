#!/usr/bin/env python3
"""Plot challenge delivery against camera-side publish availability."""

import argparse
import csv
from datetime import datetime
import os
from pathlib import Path
import tempfile

os.environ.setdefault("MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "theta-report-mpl"))

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402


def read_rows(path):
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def parse_time(value):
    return datetime.fromisoformat(value).timestamp()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--detections", type=Path, required=True)
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    camera = read_rows(args.detections)
    events = read_rows(args.events)
    commands = {
        int(row["sequence"]): parse_time(row["bag_time_jst"])
        for row in events
        if row["topic"] == "/collision/ffb_command" and row["sequence"]
    }
    offsets = sorted(
        commands[int(row["collision_ffb_sequence"])] - float(row["time_sec"])
        for row in camera
        if int(row["collision_ffb_sequence"]) in commands
    )
    if not offsets:
        raise ValueError("No camera sequence matched a recorded command")
    wall_offset = offsets[len(offsets) // 2]

    duration = float(camera[-1]["time_sec"])
    seconds = list(range(int(duration) + 1))
    challenge_counts = []
    skip_rates = []
    for second in seconds:
        challenge_counts.append(sum(
            row["topic"] == "/collision/ffb_challenge"
            and second <= parse_time(row["bag_time_jst"]) - wall_offset < second + 1
            for row in events
        ))
        frame_rows = [
            row for row in camera
            if second <= float(row["time_sec"]) < second + 1
        ]
        skip_rates.append(
            sum(row["collision_ffb_publish_success"] == "0" for row in frame_rows)
            / len(frame_rows)
            if frame_rows else 0.0
        )

    fig, left = plt.subplots(figsize=(10, 4.5))
    left.bar(seconds, challenge_counts, width=0.85, color="#5792c6", label="Challenge received by Kobuki bag")
    left.set(xlabel="Elapsed time in camera recording (s)", ylabel="Challenge messages per second", ylim=(0, 58))
    left.axhline(50, color="#214f78", linestyle="--", linewidth=1, label="Nominal 50 Hz")
    right = left.twinx()
    right.plot(seconds, skip_rates, color="#d85747", marker="o", markersize=3, label="Camera publish-skip rate")
    right.set(ylabel="Publish-skip fraction", ylim=(-0.03, 1.08))
    handles1, labels1 = left.get_legend_handles_labels()
    handles2, labels2 = right.get_legend_handles_labels()
    left.legend(handles1 + handles2, labels1 + labels2, loc="lower right")
    left.grid(axis="y", alpha=0.2)
    fig.tight_layout()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.output, dpi=160)
    plt.close(fig)


if __name__ == "__main__":
    main()
