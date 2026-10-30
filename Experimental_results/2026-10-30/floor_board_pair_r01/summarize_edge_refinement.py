#!/usr/bin/env python3
"""Summary, numeric plots and verification for the saved offline controls."""
import csv
import json
from pathlib import Path
import subprocess
import sys

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "src"))
from cone_distance_core import digest


def main():
    out = HERE / "edge_refinement_r02"
    target = out / "verification.json"
    if target.exists():
        raise ValueError("new verification output required")
    source = out / "edge_refinement.json"
    data = json.loads(source.read_text())
    baseline = json.loads((HERE / "consistency_r02/pair_summary.json").read_text())
    seed_data = json.loads((HERE / "white_paper_quad_measured_r01.json").read_text())
    primary = [r for r in data["all_controls"] if r["threshold"] == 170 and r["method"] == "intensity_crossings"
               and r["trim_fraction"] == .15]
    checks = dict(source_hashes_unchanged=all(digest(Path(p)) == h for p, h in data["input_source_sha256"].items()),
        all_96_controls_preserved=len(data["all_controls"]) == 96,
        physical_metric_unapproved=data["physical_metric_verified"] is False and data["usable_for_ffb"] is False,
        no_height_fit=data["measured_height_used_in_estimation"] is False,
        no_live_integration=data["live_integrated"] is False,
        all_primary_controls_present=len(primary) == 6 and all("refinement" in r for r in primary))
    wide = [r for r in primary if r["seed_edge_gate_px"] == 4.]
    checks["full_observed_edge_recovered_at_4px"] = all(
        e["excluded_by_seed_gate_count"] == 0 for r in wide for e in r["refinement"]["edges"])
    checks["4px_6px_primary_observations_identical"] = all(
        r["refinement"] == next(x for x in primary if x["frame"] == r["frame"] and x["seed_edge_gate_px"] == 6.)["refinement"] for r in wide)
    records = []
    for r in data["all_controls"]:
        row = {k: r[k] for k in ("frame", "threshold", "method", "trim_fraction", "seed_edge_gate_px", "status")}
        row["reason"] = r.get("reason", "")
        if "poses" in r:
            c = r["poses"]["image_far_edge_long"]["candidates"][0]
            row.update(height_m=abs(c["camera_height_above_floor_m"]), reprojection_rmse_px=c["fit_native_rmse_px"],
                       max_seed_shift_px=max(r["refinement"]["seed_shift_px"]))
        records.append(row)
    fields = list(dict.fromkeys(k for row in records for k in row))
    with (out / "comparison.csv").open("x", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(records)
    fig, ax = plt.subplots(figsize=(9, 5))
    colours = {1259: "tab:blue", 1655: "tab:orange"}
    for frame in (1259, 1655):
        old = next(r for r in baseline["hypotheses"] if r["orientation_hypothesis"] == "image_far_edge_long" and r["solution_index"] == 0)
        base_h = next(r["height_to_printed_plane_m"] for r in old["frames"] if r["frame"] == frame)
        heights = [base_h]+[next(r for r in records if r["frame"] == frame and r["threshold"] == 170
                   and r["method"] == "intensity_crossings" and r["trim_fraction"] == .15 and r["seed_edge_gate_px"] == gate)["height_m"] for gate in (2.5, 4., 6.)]
        ax.plot(range(4), 100*np.asarray(heights), "o-", label=f"Frame {frame}", color=colours[frame])
    ax.axhline(59, linestyle="--", color="black", label="Reported lens-to-floor height (not fitted): 59cm")
    ax.set(xticks=range(4), xticklabels=["4 contour vertices", "Level crossings\n2.5px sampling gate", "Level crossings\n4px sampling gate", "Level crossings\n6px sampling gate"],
           ylabel="Camera-to-printed-plane height (cm)", ylim=(51, 61),
           title="Existing two frames: refined edges improve repeatability, not verified scale")
    ax.grid(axis="y", alpha=.2)
    ax.legend(fontsize=9)
    fig.text(.5, .02, "Primary threshold 170, endpoint trim 15%. Paper 296x210mm.\n"
             "Paper-to-floor thickness unknown; no physical approval or live use.", ha="center", fontsize=9)
    fig.tight_layout(rect=(0, .09, 1, 1))
    fig.savefig(out / "height_comparison.png", dpi=150)
    plt.close(fig)
    fig, axes = plt.subplots(2, 1, figsize=(9, 5), sharex=True)
    support_rows = []
    for ax, frame in zip(axes, (1259, 1655)):
        seed = np.asarray(next(r for r in seed_data["rows"] if r["frame"] == frame and r["threshold"] == 170)["quads"][0]["quad_xy"])
        a, v = seed[2], seed[3]-seed[2]
        for y, gate in enumerate((2.5, 4., 6.)):
            r = next(r for r in primary if r["frame"] == frame and r["seed_edge_gate_px"] == gate)
            edge = r["refinement"]["edges"][2]
            p = np.asarray(edge["native_samples_xy"])
            t = (p-a)@v/(v@v)
            ax.scatter(t, np.full(len(t), y), marker="|", s=150, label=f"{gate:g}px: {len(t)} points")
            support_rows.extend(dict(frame=frame, seed_edge_gate_px=gate, native_x=float(x), native_y=float(y0), edge_fraction=float(t0)) for (x, y0), t0 in zip(p, t))
        ax.set(yticks=range(3), yticklabels=["2.5px", "4px", "6px"], ylabel=f"Frame {frame}\nsampling gate", xlim=(0, 1), ylim=(-.6, 2.6))
        ax.axvspan(0, .15, alpha=.1, color="gray")
        ax.axvspan(.85, 1, alpha=.1, color="gray")
        ax.legend(fontsize=8, loc="upper right")
    axes[0].set_title("Near paper edge: missing samples were excluded by the seed gate")
    axes[1].set_xlabel("Position along initial near edge (right=0, left=1); grey endpoint trims excluded")
    fig.tight_layout()
    fig.savefig(out / "near_edge_sampling.png", dpi=150)
    plt.close(fig)
    with (out / "near_edge_samples.csv").open("x", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(support_rows[0]))
        writer.writeheader()
        writer.writerows(support_rows)
    tests = []
    suites = [("Experimental_results/2026-10-30/floor_board_pair_r01", "test_refine_paper_edges.py"),
              ("tests", "test_floor_reference_pose.py"), ("tests", "test_diagnose_floor_board_pose.py")]
    for folder, pattern in suites:
        cmd = [sys.executable, "-m", "unittest", "discover", "-s", folder, "-p", pattern]
        run = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=60)
        tests.append(dict(command=cmd, returncode=run.returncode, stdout=run.stdout, stderr=run.stderr))
    checks["all_focused_tests_passed"] = all(t["returncode"] == 0 for t in tests)
    result = dict(status="PASS" if all(checks.values()) else "FAIL", checks=checks, test_runs=tests,
        meaning="Input/numerical/software verification only; physical distance accuracy remains unverified",
        accepted_controls=sum(r["status"] != "REJECTED" for r in records), total_controls=len(records),
        source_sha256={str(p): digest(p) for p in (source, Path(__file__).resolve(), HERE / "test_refine_paper_edges.py")})
    with target.open("x") as f:
        json.dump(result, f, indent=2, allow_nan=False)
        f.write("\n")
    print(json.dumps({k: result[k] for k in ("status", "checks", "accepted_controls", "total_controls")}, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
