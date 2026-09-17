#!/usr/bin/env python3
"""Generate reproducible Phase 5 daily-report graphs from archived evidence."""

import argparse
import csv
import io
import json
import os
from pathlib import Path
import tarfile
import tempfile

os.environ.setdefault("MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "theta-report-mpl"))

import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402


def read_camera_rows(archive_path):
    with tarfile.open(archive_path, "r:xz") as archive:
        members = [
            member
            for member in archive.getmembers()
            if member.isfile() and Path(member.name).name == "detections.csv"
        ]
        if len(members) != 1:
            raise ValueError(f"Expected one detections.csv, found {len(members)}")
        source = archive.extractfile(members[0])
        if source is None:
            raise ValueError("Could not read detections.csv")
        with io.TextIOWrapper(source, encoding="utf-8", newline="") as stream:
            return list(csv.DictReader(stream))


def plot_challenge_availability(rows, output_path):
    buckets = {}
    warning_times = []
    active_times = []
    for row in rows:
        elapsed = float(row["time_sec"])
        second = int(elapsed)
        bucket = buckets.setdefault(second, [0, 0])
        bucket[0] += 1
        if row["collision_ffb_publish_success"] == "0":
            bucket[1] += 1
        if row["collision_risk_level"] == "WARNING":
            warning_times.append(elapsed)
        if row["collision_ffb_active"] == "1":
            active_times.append(elapsed)

    seconds = sorted(buckets)
    missed_rates = [buckets[second][1] / buckets[second][0] for second in seconds]
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.bar(seconds, missed_rates, width=0.9, color="#d65a4a", label="No recent challenge")
    if warning_times:
        ax.axvspan(min(warning_times), max(warning_times), color="#f1bc52", alpha=0.4, label="WARNING")
    if active_times:
        ax.scatter(active_times, [1.04] * len(active_times), marker="v", color="#174c8a", label="Active FFB command")
    ax.set(xlabel="Elapsed time in recording (s)", ylabel="Publish-skip fraction per second", ylim=(0, 1.12))
    ax.grid(axis="y", alpha=0.2)
    ax.legend(loc="upper right")
    fig.tight_layout()
    fig.savefig(output_path, dpi=160)
    plt.close(fig)


def plot_trial_outcomes(results_dir, output_path):
    trials = [
        ("r03 clock\ndry-run", "phase5_live_dryrun_r03_bag_summary.json"),
        ("r05 clock\nhardware", "phase5_live_r05_bag_summary.json"),
        ("r06 challenge\ndry-run", "phase5_challenge_live_r06_bag_summary.json"),
    ]
    summaries = [json.loads((results_dir / name).read_text(encoding="utf-8")) for _, name in trials]
    sent = [item["bag_active_command_count"] for item in summaries]
    applied = [item["bag_active_status_count"] for item in summaries]
    positions = range(len(trials))
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.bar([index - 0.18 for index in positions], sent, 0.36, label="Active commands received", color="#7da4d0")
    ax.bar([index + 0.18 for index in positions], applied, 0.36, label="Active adapter status", color="#2869a8")
    ax.set_xticks(list(positions), [label for label, _ in trials])
    ax.set(ylabel="Count", ylim=(0, max(sent) + 2))
    ax.grid(axis="y", alpha=0.2)
    ax.legend(loc="upper right")
    for index, (received, accepted) in enumerate(zip(sent, applied)):
        ax.text(index - 0.18, received + 0.15, str(received), ha="center")
        ax.text(index + 0.18, accepted + 0.15, str(accepted), ha="center")
    fig.tight_layout()
    fig.savefig(output_path, dpi=160)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--camera-archive", type=Path, required=True)
    parser.add_argument("--results-dir", type=Path, default=Path("Experimental_results/2026-09-17"))
    parser.add_argument("--output-dir", type=Path, default=Path("Experimental_results/2026-09-17/report_assets"))
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    plot_challenge_availability(read_camera_rows(args.camera_archive), args.output_dir / "challenge_availability_r06.png")
    plot_trial_outcomes(args.results_dir, args.output_dir / "active_command_status_comparison.png")


if __name__ == "__main__":
    main()
