"""Generate audit-backed graphs; never modify camera images or runtime settings."""
import csv
import hashlib
import json
import os
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", "/tmp/theta-contact-calibration-matplotlib")
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[2]
VARIANTS = ("baseline", "seeded_s130_nearest", "seeded_s130_bottom")
NAMES = ("Baseline", "S130 nearest", "S130 bottom")
COLORS = ("#444444", "#169a8d", "#cf3f53")


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(name):
    with (ROOT / name).open(newline="") as stream:
        return list(csv.DictReader(stream))


def main():
    provenance = json.loads((ROOT / "provenance.json").read_text())
    for path, expected in provenance["inputs_sha256"].items():
        if sha256(Path(path)) != expected:
            raise ValueError(f"input changed: {path}")
    for name, expected in provenance["implementation_sha256"].items():
        if sha256(REPO / "src" / name) != expected:
            raise ValueError(f"implementation changed: {name}")
    if sha256(REPO / "src/offline_box_contact_candidates.py") != provenance["candidate_implementation_sha256"]:
        raise ValueError("frozen detector changed")
    spans = read("paired_lateral_spans.csv")
    fig, axes = plt.subplots(1, 2, figsize=(12, 5))
    for i, (variant, name, color) in enumerate(zip(VARIANTS, NAMES, COLORS)):
        rows = sorted([r for r in spans if r["variant"] == variant], key=lambda r: float(r["expected_z_m"]))
        x = np.arange(2) + (i - 1) * .24
        axes[0].bar(x, [float(r["current_span_over_nominal"]) * 100 for r in rows], width=.24, label=name, color=color)
        axes[1].bar(x, [float(r["pair_midpoint_bias_m"]) * 100 for r in rows], width=.24, label=name, color=color)
    axes[0].axhline(100, color="black", linestyle="--", linewidth=1)
    axes[0].set_ylabel("Calibrated pair span / nominal 0.60m (%)")
    axes[1].axhline(0, color="black", linewidth=1)
    axes[1].set_ylabel("Pair midpoint minus nominal midpoint (cm)")
    for ax in axes:
        ax.set_xticks(np.arange(2), ("Nominal z=0.9m", "Nominal z=1.2m"))
        ax.grid(axis="y", alpha=.25)
    axes[0].legend(fontsize=9)
    fig.suptitle("Contact choice changes apparent lateral shrinkage with the SAME calibration\nNominal layouts only: reference point (box centre vs nearest edge) unconfirmed; no refit")
    fig.tight_layout()
    fig.savefig(ROOT / "lateral_span_decomposition.png", dpi=140)
    plt.close(fig)

    rows = read("geometry_sensitivity.csv")
    rows = [r for r in rows if "hardware_r02" in r["session"]]
    cases = (("pixel_y", -5), ("pixel_y", 5), ("pitch_deg", -1), ("pitch_deg", 1), ("camera_height", -.01), ("camera_height", .01))
    lookup = {(r["variant"], r["parameter"], float(r["delta"])): r for r in rows}
    fig, ax = plt.subplots(figsize=(13, 5))
    for i, (variant, name, color) in enumerate(zip(VARIANTS, NAMES, COLORS)):
        ax.bar(np.arange(len(cases)) + (i - 1) * .24,
               [100 * float(lookup[variant, p, d]["raw_z_change_m"]) for p, d in cases],
               width=.24, label=name, color=color)
    ax.set_xticks(np.arange(len(cases)), ("Pixel y -5px", "Pixel y +5px", "Pitch -1deg", "Pitch +1deg", "Height -1cm", "Height +1cm"))
    ax.axhline(0, color="black", linewidth=1)
    ax.set_ylabel("Raw z change at frozen median selected pixel (cm)")
    ax.grid(axis="y", alpha=.25)
    ax.legend(fontsize=9)
    ax.set_title("r02 initial interval: geometry sensitivity, NOT replay or proposed calibration\nSingle median pixel held fixed; no mask re-selection, no fitting to the 1.3m reference")
    fig.tight_layout()
    fig.savefig(ROOT / "r02_fixed_pixel_geometry_sensitivity.png", dpi=140)
    plt.close(fig)
    audit = read("calibration_audit.csv")
    numeric = [float(r["maximum_coordinate_difference_m"]) for r in audit if r["maximum_coordinate_difference_m"]]
    summary = {"scope": "OFFLINE_DIAGNOSIS_NOT_CALIBRATION_ADOPTION", "audit_groups": len(audit),
               "detected_frames_audited": sum(int(r["detected_audited"]) for r in audit),
               "max_stored_coordinate_difference_m": max(numeric),
               "range_valid_mismatches": sum(int(r["range_valid_mismatches"]) for r in audit),
               "implementation_and_inputs_unchanged": True, "coefficients_fitted": False, "runtime_changed": False,
               "historical_nominal_layouts_trusted": False, "geometry_sensitivity_is_full_pipeline_replay": False}
    inputs = ("calibration_audit.csv", "coordinate_decomposition.csv", "paired_lateral_spans.csv", "geometry_sensitivity.csv",
              "trusted_baseline_reference.csv", "provenance.json", "create_diagnosis_assets.py")
    summary["inputs_sha256"] = {n: sha256(ROOT / n) for n in inputs}
    summary["outputs_sha256"] = {n: sha256(ROOT / n) for n in ("lateral_span_decomposition.png", "r02_fixed_pixel_geometry_sensitivity.png")}
    (ROOT / "validation.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps({k: summary[k] for k in ("audit_groups", "detected_frames_audited", "max_stored_coordinate_difference_m", "range_valid_mismatches")}))


if __name__ == "__main__":
    main()
