#!/usr/bin/env python3
"""Compare source-origin time grids, not camera geometry or physical accuracy."""
import argparse
import csv
import json
import os
from pathlib import Path

import numpy as np

from cone_distance_core import ROOT, digest
from run_cone_distance_replay import read_rows
from scene_sampling_clock import FixedSceneCadence

PLAN = ROOT / "Experimental_results/2026-10-22/scene_uniform_validation_r01/intake_r01/sampling_plan.json"
OLD = ROOT / "Experimental_results/2026-10-26/cone_distance_replay_r03"


def schedules(rows):
    fixed, rolling, last = [], [], None
    clock = FixedSceneCadence()
    for index, row in enumerate(rows, 1):
        t = float(row["time_sec"])
        if int(row["frame"]) != index or not np.isfinite(t):
            raise ValueError("contiguous frame/time source ledger required")
        if last is None or t-last >= 1.:
            rolling.append((index, t))
            last = t
        if clock.due(t):
            timing = clock.take(t)
            fixed.append((index, t, timing["target_time_sec"]))
    return fixed, rolling


def audit(output):
    output = Path(output)
    if output.exists():
        raise ValueError("new audit output required")
    plan = json.loads(PLAN.read_text())
    sources = {str(p.resolve()): digest(p) for p in (PLAN, Path(__file__), ROOT/"src/scene_sampling_clock.py")}
    comparisons, sessions = [], []
    computed = {}
    for entry in plan["sessions"]:
        path = Path(entry["session_path"]) / "detections.csv"
        sources[str(path)] = digest(path)
        fixed, rolling = schedules(read_rows(path))
        expected = [(r["frame"], r["time_sec"], r["target_time_sec"]) for r in entry["selected"]]
        if fixed != expected:
            raise ValueError("fixed clock differs from preexisting 1s plan")
        computed[entry["session"]] = rolling
        for index in range(max(len(fixed), len(rolling))):
            a = fixed[index] if index < len(fixed) else None
            b = rolling[index] if index < len(rolling) else None
            comparisons.append(dict(session=entry["session"], sample_index=index,
                target_time_sec=a[2] if a else None, fixed_frame=a[0] if a else None,
                fixed_source_time_sec=a[1] if a else None, rolling_frame=b[0] if b else None,
                rolling_source_time_sec=b[1] if b else None,
                same_frame=bool(a and b and a[0] == b[0]),
                rolling_minus_fixed_source_ms=1000*(b[1]-a[1]) if a and b else None,
                fixed_grid_lateness_ms=1000*(a[1]-a[2]) if a else None,
                rolling_grid_lateness_ms=1000*(b[1]-a[2]) if a and b else None))
        overlap = min(len(fixed), len(rolling))
        sessions.append(dict(session=entry["session"], raw_frames=entry["raw_frames"],
            fixed_samples=len(fixed), rolling_samples=len(rolling),
            differing_frame_pairs=sum(fixed[i][0] != rolling[i][0] for i in range(overlap)),
            paired_samples=overlap, fixed_only_sample_slots=max(0, len(fixed)-len(rolling)),
            last_paired_source_shift_ms=1000*(rolling[overlap-1][1]-fixed[overlap-1][1]),
            max_fixed_lateness_ms=max(1000*(r[1]-r[2]) for r in fixed)))
    old_checks = []
    for case in ("static_center130", "static_no_central_cone", "declared_central_scope", "full_front_control"):
        proof_path = OLD/case/"summary.json"
        jobs_path = OLD/case/"scene_jobs.csv"
        proof = json.loads(proof_path.read_text())
        if digest(jobs_path) != proof["output_sha256"]["scene_jobs.csv"]:
            raise ValueError("changed previous job ledger")
        observed = [(int(r["frame"]), float(r["source_time_sec"])) for r in read_rows(jobs_path)]
        if computed[proof["session"]] != observed:
            raise ValueError("rolling reference differs from recorded r03 job selection")
        for key in ("cone_distance_core.py", "run_cone_distance_replay.py"):
            snapshot = ROOT/"Experimental_results/2026-10-26/cone_distance_report_r01/source_snapshot"/key
            expected = proof["source_sha256"][str(ROOT/"src"/key)]
            if digest(snapshot) != expected:
                raise ValueError("previous-code snapshot hash mismatch")
            sources[str(snapshot)] = digest(snapshot)
        sources.update({str(proof_path): digest(proof_path), str(jobs_path): digest(jobs_path)})
        old_checks.append(dict(case=case, recorded_jobs=len(observed), rolling_job_mismatches=0))
    output.mkdir(parents=True, exist_ok=False)
    def write(name, rows):
        with (output/name).open("x", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    write("paired_sampling.csv", comparisons)
    write("session_sampling_summary.csv", sessions)
    os.environ.setdefault("MPLCONFIGDIR", str(output/"matplotlib_config"))
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(2, 1, figsize=(10, 7), layout="constrained")
    central = next(s["session"] for s in sessions if s["session"].startswith("cone_static_center_z1p30_"))
    selected = [r for r in comparisons if r["session"] == central]
    axes[0].plot([r["target_time_sec"] for r in selected], [r["rolling_grid_lateness_ms"] for r in selected], "o-", label="previous selected-frame + 1s")
    axes[0].plot([r["target_time_sec"] for r in selected], [r["fixed_grid_lateness_ms"] for r in selected], "o-", label="source origin + k*1s")
    axes[0].set(xlabel="Original source-time target [s]", ylabel="Sampling lateness [ms]",
                title="Static centre 1.3m recording: frame quantization accumulated in the previous cadence")
    axes[0].legend()
    labels = [s["session"].replace("_r01_", "\n").split("\n")[0] for s in sessions]
    axes[1].barh(range(len(sessions)), [s["last_paired_source_shift_ms"] for s in sessions])
    axes[1].set_yticks(range(len(sessions)), labels, fontsize=7)
    axes[1].set(xlabel="Last paired rolling minus fixed source time [ms]",
                title="All nine recordings; this is sampling drift, NOT cross-PC latency")
    for axis in axes:
        axis.grid(alpha=.2)
    fig.savefig(output/"sampling_drift.png", dpi=130)
    plt.close(fig)
    result = dict(status="COMPLETED_SOURCE_TIME_CADENCE_AUDIT_NOT_METRIC_VALIDATION", source_sha256=sources,
        recordings=len(sessions), original_frames=sum(s["raw_frames"] for s in sessions),
        fixed_samples=sum(s["fixed_samples"] for s in sessions), rolling_samples=sum(s["rolling_samples"] for s in sessions),
        fixed_vs_historical_plan_mismatches=0, previous_rolling_checks=old_checks,
        source_images_edited=False, thresholds_changed=False, physical_output=False, usable_for_ffb=False,
        output_sha256={p.name: digest(p) for p in output.iterdir() if p.is_file()})
    (output/"summary.json").write_text(json.dumps(result, indent=2)+"\n")
    print(json.dumps({k: v for k, v in result.items() if k not in ("source_sha256", "output_sha256")}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    audit(parser.parse_args().output_dir)
