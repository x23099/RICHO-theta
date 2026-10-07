#!/usr/bin/env python3
"""Visualize historical bag-recording intervals; never publish ROS messages."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sqlite3
import sys
import tempfile
from datetime import datetime
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "src"))
from analyze_field_recording import safe_extract_archive

ARCHIVE_HASHES = {
    "kobuki": "b8cdc958ec694d78bacd5a72bd1a1ef6eaeee40550411ba07c3794c6ff695eb9",
    "hsr": "c61d5ab47f2b3fe59b523bd8ebae372476139a8455850a0cec8b313bf3df6cbc",
}


def sha(path):
    with Path(path).open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256") if hasattr(hashlib, "file_digest") else None
        if digest is None:
            stream.seek(0)
            digest = hashlib.sha256()
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


def ns(iso):
    value = datetime.fromisoformat(iso)
    return int(value.timestamp()) * 1_000_000_000 + value.microsecond * 1000


def save_csv(path, rows):
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def get_intervals(archive, pc, start, end):
    if sha(archive) != ARCHIVE_HASHES[pc]:
        raise ValueError(f"unexpected historical archive for {pc}")
    with tempfile.TemporaryDirectory(prefix=f"theta_challenge_{pc}_") as temp:
        safe_extract_archive(archive, Path(temp), 256 * 1024 * 1024)
        databases = list(Path(temp).rglob("*.db3"))
        if len(databases) != 1:
            raise ValueError("expected one database")
        with sqlite3.connect(databases[0].as_uri() + "?mode=ro", uri=True) as db:
            topics = db.execute("SELECT id FROM topics WHERE name=?", ("/collision/ffb_challenge",)).fetchall()
            if len(topics) != 1:
                raise ValueError("expected challenge topic exactly once")
            stamps = [r[0] for r in db.execute(
                "SELECT timestamp FROM messages WHERE topic_id=? ORDER BY timestamp, id", topics[0])]
        rows = []
        for previous, current in zip(stamps, stamps[1:]):
            if start <= current <= end:
                rows.append({"pc": pc, "previous_bag_timestamp_ns": previous,
                             "bag_timestamp_ns": current, "elapsed_sec": (current-start)/1e9,
                             "interval_ms": (current-previous)/1e6})
        return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kobuki-archive", type=Path, required=True)
    parser.add_argument("--hsr-archive", type=Path, required=True)
    args = parser.parse_args()
    out = Path(__file__).resolve().parent
    old = REPO / "Experimental_results/2026-09-29"
    replay_path = old / "phase5_v12_relay_offline_replay.json"
    replay = json.loads(replay_path.read_text())
    window = replay["camera_recording_window"]
    start, end = ns(window["start_jst"]), ns(window["end_jst"])
    all_rows, stats, inputs = [], {}, {}
    for pc, archive in [("hsr", args.hsr_archive), ("kobuki", args.kobuki_archive)]:
        rows = get_intervals(archive.resolve(), pc, start, end)
        if len(rows) != 4051:
            raise ValueError("unexpected window challenge count")
        values = np.array([r["interval_ms"] for r in rows])
        stats[pc] = {"count": len(rows), "median_ms": float(np.median(values)),
                     "p95_ms": float(np.percentile(values, 95)), "max_ms": float(max(values)),
                     "over_60ms_count": int(sum(values > 60)),
                     "over_200ms_count": int(sum(values > 200))}
        all_rows.extend(rows)
        inputs[str(archive.resolve())] = sha(archive)
    if stats["kobuki"]["over_60ms_count"] != 25:
        raise ValueError("historical threshold-crossing count mismatch")
    save_csv(out / "challenge_intervals.csv", all_rows)

    events = old / "phase5_v11_reliability_kobuki_r01_events.csv"
    with events.open(newline="") as stream:
        diag = [r for r in csv.DictReader(stream)
                if r["topic"] == "/collision/ffb_relay_diagnostics"
                and start <= ns(r["bag_time_jst"]) <= end]
    diag_rows = [{"elapsed_sec": (ns(r["bag_time_jst"])-start)/1e9,
                  "sequence": r["sequence"], "reason": r["reason"],
                  "relay_accepted": r["relay_accepted"],
                  "challenge_stable_age_sec": r["challenge_stable_age_sec"]} for r in diag]
    if sum(r["reason"] == "receiver_challenge_stream_not_stable" for r in diag_rows) != 567:
        raise ValueError("historical relay rejection count mismatch")
    save_csv(out / "recorded_relay_diagnostics.csv", diag_rows)

    plt.rcParams.update({"font.family": "Noto Sans CJK JP", "axes.unicode_minus": False,
                         "font.size": 10})
    fig, axes = plt.subplots(3, 1, figsize=(12, 8.4), sharex=True, constrained_layout=True)
    for ax, pc, title in [(axes[0], "hsr", "ハンコン接続PC：発行元側bagの記録間隔"),
                           (axes[1], "kobuki", "Kobuki PC：受信側bagの記録間隔")]:
        rows = [r for r in all_rows if r["pc"] == pc]
        x = np.array([r["elapsed_sec"] for r in rows]); y = np.array([r["interval_ms"] for r in rows])
        ax.plot(x, y, linewidth=0.5, color="#3378af")
        ax.scatter(x[y > 60], y[y > 60], s=14, color="#c52d29", zorder=3)
        ax.axhline(20, color="#36844a", linestyle=":", label="50 Hzの目安：20 ms")
        ax.axhline(60, color="#c52d29", linestyle="--", label="v11のstreamリセット基準：60 ms")
        ax.set(ylim=(-3, 145), ylabel="記録間隔 [ms]", title=title)
        ax.grid(alpha=0.2)
        s = stats[pc]
        ax.text(0.99, 0.95, f"最大 {s['max_ms']:.3f} ms / 60 ms超 {s['over_60ms_count']}回",
                transform=ax.transAxes, ha="right", va="top", bbox={"facecolor": "white", "alpha": 0.9})
    axes[0].legend(loc="center right", fontsize=9)
    valid = [r for r in diag_rows if r["challenge_stable_age_sec"]]
    axes[2].plot([r["elapsed_sec"] for r in valid], [float(r["challenge_stable_age_sec"]) for r in valid],
                 color="#3378af", linewidth=0.7, label="記録されたstream安定経過時間")
    rejected = [r for r in diag_rows if r["reason"] == "receiver_challenge_stream_not_stable"]
    axes[2].scatter([r["elapsed_sec"] for r in rejected], [0.05]*len(rejected),
                    s=3, color="#c52d29", label="安定待ちによるintent見送り：567件")
    axes[2].axhline(1, color="#c52d29", linestyle="--", label="転送に必要な連続安定：1秒")
    axes[2].set(xlabel="カメラ録画開始からの経過 [秒]", ylabel="安定経過 [秒]",
                title="v11 relay：短い間隔の伸びで安定時間がリセットされる", xlim=(0, (end-start)/1e9))
    axes[2].grid(alpha=0.2)
    axes[2].legend(loc="upper right", fontsize=8)
    fig.suptitle("2026-09-29 v11：challengeの間隔揺らぎと転送見送り\n"
                 "同じ録画窓の各PC内のbag記録間隔（通信だけの遅延・callback実行間隔ではない）", fontsize=13)
    fig.savefig(out / "challenge_interval_and_stability.png", dpi=170)
    plt.close(fig)

    comparison = replay["comparison"]
    values = [comparison["v11_recorded_active_command_count"], comparison["v12_replayed_active_authorized_count"]]
    fig, ax = plt.subplots(figsize=(8, 4.7), constrained_layout=True)
    ax.bar([0, 1], values, color=["#b45743", "#387ba5"], width=0.5)
    ax.set(xticks=[0, 1], xticklabels=["v11：実記録のactive command", "v12：オフラインゲート再生の許可"],
           ylim=(0, 31), ylabel="active intent 27件のうちの件数",
           title="個別tokenの鮮度60 msは維持／stream断の判定だけ200 msへ分離")
    for x, y in enumerate(values):
        ax.text(x, y+0.5, f"{y}/27", ha="center", fontsize=16)
    ax.axhline(27, color="gray", linestyle=":")
    ax.text(0.5, 0.03, "残る1件は古いtokenのため安全拒否。\n実機振動回数・独立試験の成功率・通信遅延改善の比較ではない。",
            transform=ax.transAxes, ha="center", va="bottom", fontsize=9,
            bbox={"facecolor": "white", "alpha": 0.95})
    fig.savefig(out / "relay_gate_recorded_vs_offline.png", dpi=170)
    plt.close(fig)
    inputs.update({str(events.relative_to(REPO)): sha(events), str(replay_path.relative_to(REPO)): sha(replay_path),
                   str(Path(__file__).resolve().relative_to(REPO)): sha(__file__)})
    outputs = {p.name: sha(p) for p in out.iterdir() if p.suffix in {".csv", ".png"}}
    (out / "summary.json").write_text(json.dumps({
        "analysis_date": "2026-10-07", "source_experiment_date": "2026-09-29",
        "window": window, "interval_statistics": stats,
        "stream_not_stable_count": 567, "comparison": comparison,
        "clock_scope": "within each PC, bag receipt timestamps; not cross-PC one-way latency",
        "root_cause_of_arrival_jitter": "NOT_DETERMINED_NO_NETWORK_CPU_DDS_TRACE",
        "diagnostic_csv_time_precision": "millisecond-rounded historical export",
        "interval_time_precision": "original sqlite bag nanoseconds",
        "inputs_sha256": inputs, "outputs_sha256": outputs,
    }, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(stats, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
