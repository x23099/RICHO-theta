"""Reproduce an independently labelled sparse/continuous visual comparison.

Missing visual labels remain unreviewed. No interval label is interpolated.
"""
import argparse
from collections import Counter
import csv
import hashlib
import json
import os
from pathlib import Path
import sys

os.environ.setdefault("MPLCONFIGDIR", "/tmp/theta-v12-occlusion-matplotlib")
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[2]
sys.path.insert(0, str(REPO / "src"))
from evaluate_reviewed_occlusion import flag, phase_metrics
from compare_offline_box_contacts import verify_frozen_candidate
from offline_box_contact_candidates import BoxCandidateSettings

PHASES = ("visible", "partial_occlusion", "fully_occluded", "uncertain")


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read(path):
    with path.open(newline="") as stream:
        return list(csv.DictReader(stream))


def write(path, rows):
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session-dir", type=Path, action="append", required=True)
    parser.add_argument("--export-root", type=Path, required=True)
    args = parser.parse_args()
    protocol = json.loads((ROOT / "review_protocol.json").read_text())
    require(sha256(ROOT / "manual_review.csv") == protocol["manual_review_sha256"], "visual labels changed")
    sessions = {p.name: p for p in args.session_dir}
    require(len(sessions) == len(args.session_dir) and set(sessions) == set(protocol["sessions"]), "session mismatch")
    expected = {(s, n) for s, frames in protocol["expected_review_frames"].items() for n in frames}
    manual_rows = read(ROOT / "manual_review.csv")
    manual = {(r["session"], int(r["frame_one_based"])): r for r in manual_rows}
    require(len(manual) == len(manual_rows) and set(manual) == expected, "visual review coverage mismatch")
    dense = {(s, n) for s, windows in protocol["continuous_windows"].items()
             for start, end in windows for n in range(start, end + 1)}
    for key, row in manual.items():
        require(row["reviewed_phase"] in PHASES and row["review_method"] == "whole_raw_frame_visual_review"
                and row["visible_evidence"], "invalid visual evidence")
        require((row["review_scope"] == "continuous_window_review") == (key in dense), "review scope mismatch")
        relative = Path(row["reviewed_png_relative_to_export_root"])
        require(not relative.is_absolute() and ".." not in relative.parts, "unsafe reviewed PNG path")
    require({key for key, r in manual.items() if r["reviewed_phase"] == "fully_occluded"} ==
            {(s, n) for s, frames in protocol["fully_hidden_frames"].items() for n in frames}, "full label mismatch")
    prov_path = ROOT / "video_comparison/provenance.json"
    provenance = json.loads(prov_path.read_text())
    variants = protocol["variants"]
    require(provenance["variants"] == variants, "variant mismatch")
    sources = {s["session"]: s for s in provenance["sources"]}
    require(set(sources) == set(sessions), "provenance source mismatch")
    frozen_path = ROOT.parent / "box_contact_candidates/provenance.json"
    verify_frozen_candidate(frozen_path, BoxCandidateSettings())
    frozen = json.loads(frozen_path.read_text())
    require(frozen["settings"] == provenance["settings"], "comparison candidate settings changed")
    require(frozen["implementation_sha256"]["offline_box_contact_candidates.py"] ==
            provenance["implementation_sha256"]["offline_box_contact_candidates.py"], "comparison candidate code changed")
    for name, digest in provenance["implementation_sha256"].items():
        require(sha256(REPO / "src" / name) == digest, "comparison implementation changed")
    require(sha256(REPO / "src/bird_eye_config_ttc_v12_ffb_reliability_20260929.json") ==
            provenance["detector_config_sha256"], "detector config changed")
    results = read(ROOT / "video_comparison/frame_results.csv")
    lookup = {(r["session"], r["variant"], int(r["frame"])): r for r in results}
    require(len(lookup) == len(results), "duplicate comparison row")
    live, pixel_hashes, assets = {}, {}, []
    for session, path in sessions.items():
        for name, digest in sources[session]["sha256"].items():
            require(sha256(path / name) == digest, "original source changed")
        live[session] = read(path / "detections.csv")
        require([int(r["frame"]) for r in live[session]] == list(range(1, len(live[session]) + 1)), "source discontinuity")
        for variant in variants:
            for n, original in enumerate(live[session], 1):
                row = lookup.get((session, variant, n))
                require(row is not None and all(float(row[k]) == float(original[k])
                        for k in ("time_sec", "monotonic_time_sec")), "missing row or clock mismatch")
                require(not flag(row, "measurement_accepted") or flag(row, "detected"), "accepted without detection")
        ids = {n for s, n in expected if s == session}
        capture = cv2.VideoCapture(str(path / "raw.avi"))
        try:
            for n in range(1, max(ids) + 1):
                ok, frame = capture.read()
                require(ok, "short video")
                if n not in ids:
                    continue
                row = manual[session, n]
                png = args.export_root / row["reviewed_png_relative_to_export_root"]
                require(frame.shape == (720, 1280, 3) and np.array_equal(frame, cv2.imread(str(png))), "reviewed pixels mismatch")
                pixel_hashes[session, n] = hashlib.sha256(frame.tobytes()).hexdigest()
                if (session.endswith("162234_202") and n == 763) or (session.endswith("184546_956") and n == 900):
                    alias = "dry" if session.endswith("162234_202") else "hardware"
                    asset = ROOT.parent / "report_assets" / f"v12_occlusion_{alias}_raw_frame_{n:04d}.png"
                    require(cv2.imwrite(str(asset), frame) and np.array_equal(cv2.imread(str(asset)), frame), "asset pixel mismatch")
                    assets.append(dict(session=session, frame_one_based=n, time_sec=live[session][n-1]["time_sec"],
                                       reviewed_phase=row["reviewed_phase"], raw_png=str(asset.relative_to(REPO)),
                                       png_sha256=sha256(asset), source_video_sha256=sources[session]["sha256"]["raw.avi"],
                                       decoded_bgr_pixels_sha256=pixel_hashes[session, n], width=1280, height=720))
        finally:
            capture.release()
    require(len(results) == sum(len(rows) for rows in live.values()) * len(variants), "extra comparison rows")
    joined = []
    for session, n in sorted(expected):
        for variant in variants:
            row = dict(lookup[session, variant, n])
            row.update(manual[session, n], video_index_zero_based=n - 1,
                       decoded_bgr_pixels_sha256=pixel_hashes[session, n], source_video_sha256=sources[session]["sha256"]["raw.avi"])
            joined.append(row)
    metrics = []
    for session in sessions:
        for scope in ("all_reviewed_points", "continuous_window_review", "sparse_screening"):
            selected = [r for r in joined if r["session"] == session and (scope == "all_reviewed_points" or r["review_scope"] == scope)]
            for variant in variants:
                for phase in PHASES:
                    metrics.append(dict(session=session, review_scope=scope, **phase_metrics(selected, variant, phase)))
    write(ROOT / "reviewed_frames.csv", joined)
    write(ROOT / "phase_metrics.csv", metrics)
    write(ROOT / "raw_assets_manifest.csv", assets)
    counts = Counter(r["reviewed_phase"] for r in manual_rows)
    fig, ax = plt.subplots(figsize=(9, 4))
    ax.bar(PHASES, [counts[p] for p in PHASES], color=["#5084be", "#169a8d", "#aa4371", "#9b9b9b"])
    ax.set_ylabel("Reviewed raw frames (not interval duration)")
    ax.set_title("v12: 72 unique reviewed points, including 42 continuous frames\n"
                 "Sparse gaps are UNREVIEWED; long full-occlusion response NOT EVALUATED")
    fig.tight_layout()
    fig.savefig(ROOT / "review_coverage.png", dpi=140)
    plt.close(fig)
    dense_session = next(s for s, windows in protocol["continuous_windows"].items() if windows)
    fig, axes = plt.subplots(4, 2, figsize=(12, 8), sharex="col")
    phase_colors = dict(zip(PHASES, ["#5084be", "#169a8d", "#aa4371", "#9b9b9b"]))
    for column, (start, end) in enumerate(protocol["continuous_windows"][dense_session]):
        frames = list(range(start, end + 1))
        codes = [PHASES.index(manual[dense_session, n]["reviewed_phase"]) for n in frames]
        axes[0, column].step(frames, codes, where="mid", color="#555555")
        axes[0, column].scatter(frames, codes,
                               c=[phase_colors[manual[dense_session,n]["reviewed_phase"]] for n in frames], s=18)
        axes[0, column].set_yticks(range(4), ["visible", "partial", "fully hidden", "uncertain"])
        axes[0, column].set_ylim(-.4, 3.4)
        axes[0, column].set_title(f"Raw-image labels: frames {start}-{end}")
        for index, variant in enumerate(variants, 1):
            rows = [lookup[dense_session, variant, n] for n in frames]
            ax = axes[index, column]
            ax.step(frames, [flag(r, "detected") for r in rows], where="mid", color="#5084be", label="detected")
            ax.step(frames, [flag(r, "measurement_accepted") for r in rows], where="mid", color="#169a8d", linestyle="--", label="accepted")
            ax.set_yticks([0,1])
            ax.set_ylim(-.15,1.15)
            ax.set_ylabel(variant.replace("seeded_s130_", "S130 "), fontsize=9)
            ax.grid(alpha=.2)
        axes[-1,column].set_xlabel("One-based source frame (each individually reviewed)")
    axes[1,1].legend(loc="upper left", fontsize=8)
    fig.suptitle("Frozen detector recovery versus independently reviewed visibility\n"
                 "Selected short windows; NOT a long full-occlusion timing test")
    fig.tight_layout(rect=(0,0,1,.94))
    fig.savefig(ROOT / "continuous_window_recovery.png", dpi=140)
    plt.close(fig)
    recovery = []
    for variant in variants:
        # Visible onset is fixed by raw-image review, independently of results.
        first = next((n for n in range(773, 781) if flag(lookup[dense_session, variant, n], "measurement_accepted")), None)
        post_hidden = next((n for n in range(765, 781) if flag(lookup[dense_session, variant, n], "measurement_accepted")), None)
        recovery.append(dict(session=dense_session, variant=variant, visible_onset_frame=773,
                             first_accepted_after_visible_onset_frame=first,
                             delay_sec=float(live[dense_session][first-1]["time_sec"]) - float(live[dense_session][772]["time_sec"]) if first else None,
                             first_accepted_after_hidden_window_frame=post_hidden,
                             reviewed_phase_at_first_accepted_after_hidden_window=manual[dense_session,post_hidden]["reviewed_phase"] if post_hidden else None,
                             assessment="OBSERVED_VISIBLE_RECOVERY_NOT_FULL_OCCLUSION_LATENCY" if first else "RIGHT_CENSORED_REVIEW_WINDOW"))
    write(ROOT / "visible_recovery_metrics.csv", recovery)
    full_times = [float(live[dense_session][n - 1]["time_sec"]) for n in protocol["fully_hidden_frames"][dense_session]]
    inputs = [ROOT / "manual_review.csv", ROOT / "review_protocol.json", prov_path,
              ROOT / "video_comparison/frame_results.csv", ROOT.parent / "box_contact_candidates/provenance.json",
              REPO / "src/evaluate_reviewed_occlusion.py", Path(__file__), ROOT / "export_review_frames.py"]
    outputs = [ROOT / name for name in ("reviewed_frames.csv", "phase_metrics.csv", "raw_assets_manifest.csv",
                                       "review_coverage.png", "continuous_window_recovery.png", "visible_recovery_metrics.csv")]
    summary = dict(scope=protocol["scope"], reviewed_frames=len(manual), continuous_review_frames=len(dense),
                   phase_counts=dict(counts), comparison_rows=len(results), source_frames={s:len(r) for s,r in live.items()},
                   reviewed_joined_rows=len(joined), fully_hidden_timestamp_span_sec=max(full_times)-min(full_times),
                   short_full_occlusion_motion=[{k:live[dense_session][n-1][k] for k in
                                                ("frame","time_sec","odom_available","odom_linear_mps")}
                                                for n in protocol["fully_hidden_frames"][dense_session]],
                   long_full_occlusion_assessment="NOT_EVALUATED_INSUFFICIENT_CONFIRMED_DURATION",
                   visible_recovery=recovery, reviewed_pixels_verified_frames=len(pixel_hashes),
                   physical_ffb_tested=False, limits=protocol["limits"],
                   inputs_sha256={str(p.relative_to(REPO)):sha256(p) for p in inputs},
                   outputs_sha256={str(p.relative_to(REPO)):sha256(p) for p in outputs})
    (ROOT / "review_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
