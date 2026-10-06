"""Reproduce CSV-backed graphs and whole, unmodified decoded camera PNGs."""
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", "/tmp/theta-box-validation-matplotlib")
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[2]
ASSETS = ROOT.parent / "report_assets"
VARIANTS = ("baseline", "seeded_s130_nearest", "seeded_s130_bottom")
NAMES = ("Baseline", "S130 nearest", "S130 bottom")
COLORS = ("#444444", "#169a8d", "#cf3f53")


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read(path):
    with path.open(newline="") as stream:
        return list(csv.DictReader(stream))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recording-root", type=Path,
                        help="relocated safely extracted 202608261410 archive; original hashes still required")
    args = parser.parse_args()
    provenance = json.loads((ROOT / "evaluation_provenance.json").read_text())
    for path, expected in provenance["inputs_sha256"].items():
        if sha256(Path(path)) != expected:
            raise ValueError(f"evaluation input changed: {path}")
    for name, expected in provenance["implementation_sha256"].items():
        if sha256(REPO / "src" / name) != expected:
            raise ValueError(f"evaluator changed: {name}; rerun evaluation")
    candidate = REPO / "src/offline_box_contact_candidates.py"
    if sha256(candidate) != provenance["candidate_implementation_sha256"]:
        raise ValueError("candidate changed since frozen comparison")
    positions = read(ROOT / "position_accuracy.csv")
    warning = read(ROOT / "warning_comparison.csv")
    dynamic = read(ROOT / "fixed_dynamic_profile_results.csv")
    events = read(ROOT / "occlusion_events.csv")
    sessions = [r["session"] for r in positions if r["variant"] == "baseline" and r["reference_kind"] == "static_layout"]
    lookup = {(r["session"], r["variant"]): r for r in positions}
    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
    for ax, axis in zip(axes, ("x", "z")):
        for i, (variant, name, color) in enumerate(zip(VARIANTS, NAMES, COLORS)):
            errors = [100 * float(lookup[s, variant][axis + "_mae_m"]) for s in sessions]
            ax.bar(np.arange(len(sessions)) + (i - 1) * .25, errors, width=.25, label=name, color=color)
        ax.set_xticks(np.arange(len(sessions)), ("Left 0.9m", "Right 0.9m", "Left 1.2m", "Right 1.2m"))
        ax.set_ylabel(f"{axis.upper()} mean absolute error (cm)")
        ax.grid(axis="y", alpha=.25)
    axes[0].legend(fontsize=9)
    fig.suptitle("Frozen offline detector: 4 recorded placements, all detected measurements\nNo calibration refit; stable detection does not imply accurate distance")
    fig.tight_layout()
    fig.savefig(ROOT / "spatial_position_error.png", dpi=140)
    plt.close(fig)

    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
    initial = [r for r in positions if r["reference_kind"] == "initial_distance_only"]
    initial_lookup = {r["variant"]: r for r in initial}
    axes[0].bar(NAMES, [100 * float(initial_lookup[v]["distance_mae_m"]) for v in VARIANTS], color=COLORS)
    axes[0].set_ylabel("Initial radial distance MAE (cm)")
    axes[0].set_title("10/06 r02: initial 1.30m only\nFirst 90 frames; no stopped-distance truth")
    approach = [r["session"] for r in warning if r["variant"] == "baseline" and "v0p20" in r["session"]]
    warn_lookup = {(r["session"], r["variant"]): r for r in warning}
    for i, (variant, name, color) in enumerate(zip(VARIANTS[1:], NAMES[1:], COLORS[1:])):
        values = [1000 * float(warn_lookup[s, variant]["warning_onset_delta_sec"]) for s in approach]
        axes[1].bar(np.arange(3) + (i - .5) * .32, values, width=.32, label=name, color=color)
    axes[1].set_xticks(np.arange(3), ("09/08 r01", "09/08 r02", "09/08 r03"))
    axes[1].axhline(0, color=COLORS[0], linewidth=1)
    axes[1].set_ylabel("First WARNING onset minus baseline (ms)")
    axes[1].set_title("Recorded-metadata risk replay\nPositive = later; not physical FFB latency")
    axes[1].legend(fontsize=9)
    for ax in axes:
        ax.grid(axis="y", alpha=.25)
    fig.suptitle("Offline trade-offs: absolute bias remains; no baseline WARNING lost\nSeparate frozen v6 dynamic profile: baseline 5/6 PASS, both candidates 6/6 PASS")
    fig.tight_layout()
    fig.savefig(ROOT / "distance_bias_and_warning_timing.png", dpi=140)
    plt.close(fig)

    spatial = json.loads((ROOT / "spatial_occlusion/provenance.json").read_text())
    sources = {s["session"]: s for s in spatial["sources"]}
    frame_rows = read(ROOT / "spatial_occlusion/frame_results.csv")
    frames = {(r["session"], r["variant"], int(r["frame"])): r for r in frame_rows}
    selections = (
        ("x0.0mz1.2m_shahei_20260826_140829_186", 431, "box_validation_occluded_raw_frame_0431.png"),
        ("x0.3mz0.9m_20260826_140106_996", 350, "box_validation_right_0p9m_raw_frame_0350.png"),
    )
    ASSETS.mkdir(parents=True, exist_ok=True)
    manifest = []
    for session, frame, name in selections:
        source = sources[session]
        session_path = args.recording_root / session if args.recording_root else Path(source["path"])
        video = session_path / "raw.avi"
        if sha256(video) != source["sha256"]["raw.avi"]:
            raise ValueError("source video changed")
        cap = cv2.VideoCapture(str(video))
        try:
            for _ in range(frame):
                ok, decoded = cap.read()
                if not ok:
                    raise ValueError("selected frame outside video")
        finally:
            cap.release()
        target = ASSETS / name
        if target.exists():
            if not np.array_equal(cv2.imread(str(target)), decoded):
                raise ValueError("existing PNG differs from original video")
        elif not cv2.imwrite(str(target), decoded):
            raise ValueError("cannot save PNG")
        if not np.array_equal(cv2.imread(str(target)), decoded):
            raise ValueError("saved PNG pixels changed")
        manifest.append({"session": session, "frame_one_based": frame,
                         "time_sec": frames[session, "baseline", frame]["time_sec"],
                         "raw_png": str(target.relative_to(REPO)), "raw_png_sha256": sha256(target),
                         "source_video_sha256": source["sha256"]["raw.avi"],
                         "width": decoded.shape[1], "height": decoded.shape[0],
                         "pixels_equal_original_decoded_frame": True})
    with (ROOT / "raw_assets_manifest.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(manifest[0]))
        writer.writeheader()
        writer.writerows(manifest)
    inputs = ("position_accuracy.csv", "warning_comparison.csv", "fixed_dynamic_profile_results.csv", "occlusion_events.csv",
              "phase_results.csv", "labelled_frames.csv", "evaluation_provenance.json", "create_validation_assets.py")
    outputs = ("spatial_position_error.png", "distance_bias_and_warning_timing.png", "raw_assets_manifest.csv")
    validation = {"scope": "OFFLINE_VALIDATION_NOT_RUNTIME_ADOPTION", "frozen_candidate_unchanged": True,
                  "evaluation_inputs_and_implementation_hashes_match": True,
                  "raw_png_pixels_match_decoded_video": True, "raw_png_count": len(manifest),
                  "dynamic_pass_cases": {v: sum(r["decision"] == "PASS" for r in dynamic if r["variant"] == v) for v in VARIANTS},
                  "fully_occluded_accepted": {v: sum(int(r["fully_occluded_accepted"]) for r in events if r["variant"] == v) for v in VARIANTS},
                  "baseline_warning_lost_cases": sum(int(r["baseline_warning_lost"]) for r in warning),
                  "all_approaches_final_clear": all(r["final_risk"] == "CLEAR" for r in warning),
                  "inputs_sha256": {n: sha256(ROOT / n) for n in inputs},
                  "outputs_sha256": {n: sha256(ROOT / n) for n in outputs},
                  "runtime_changed": False, "hardware_validation_performed": False}
    (ROOT / "validation.json").write_text(json.dumps(validation, indent=2) + "\n")
    print("Generated 2 graphs and verified 2 whole raw PNGs; runtime unchanged.")


if __name__ == "__main__":
    main()
