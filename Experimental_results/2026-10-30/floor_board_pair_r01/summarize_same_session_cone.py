#!/usr/bin/env python3
"""Numeric chart and recorded software checks; never an accuracy verdict."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "src"))
from cone_distance_core import digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=False)
    source = args.input_dir / "same_session_cone_comparison.json"
    data = json.loads(source.read_text())
    by_frame = {r["frame"]: r for r in data["rows"]}
    valid = by_frame[1655]["range_hypotheses"]
    checks = dict(input_hashes_unchanged=all(digest(Path(p)) == h for p, h in data["source_sha256"].items()),
        rejected_frame_has_no_distance=by_frame[1259]["state"] == "SUPPORT_WITHHELD" and not by_frame[1259]["range_hypotheses"],
        accepted_support_has_all_three_hypotheses=len(valid) == 3,
        rough_range_not_fitted_or_used_as_precise_truth=data["user_distance_reference"]["used_to_fit_or_select_model"] is False and data["user_distance_reference"]["precise_measurement"] is False,
        no_physical_accuracy_or_live_approval=all(data[k] is False for k in ("physical_metric_verified", "independent_accuracy_validated", "live_integrated", "usable_for_ffb")))
    command = [sys.executable, "-m", "unittest", "discover", "-s", str(HERE), "-p", "test_same_session_range.py"]
    test = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=60)
    checks["eight_geometry_tests_passed"] = test.returncode == 0 and "Ran 8 tests" in test.stderr
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(9, 5))
    names = ["Paper-fit normal\nand inferred height + board", "External height 59cm\nand height-constrained normal", "External height 59cm only\nwith free-fit normal (control)"]
    values = [r["horizontal_camera_foot_range_m"] for r in valid]
    ax.bar(range(3), values, color=["tab:blue", "tab:orange", "tab:green"], width=.55)
    for i, row in enumerate(valid):
        lo, hi = row["numerical_1px_support_control_range_m"]
        ax.vlines(i, lo, hi, color="black")
        ax.hlines([lo, hi], i-.06, i+.06, color="black")
        ax.text(i, hi+.025, f"{values[i]:.3f}m", ha="center")
    ax.axhline(1.5, color="gray", linestyle="--", label="User's rough tile-based estimate: ~1.5m (NOT ground truth)")
    ax.set(xticks=range(3), xticklabels=names, ylim=(0, 1.85), ylabel="Horizontal range from camera floor foot (m)",
           title="Same-session frame 1655: offline conditional cone range, not validated distance")
    ax.legend(fontsize=8, loc="lower center")
    fig.text(.5, .02, "Black spans: +/-1 native-pixel support-position controls, NOT confidence intervals.\n"
             "Frame 1259 withheld; true floor contact/vehicle heading unverified. No live/FFB use.", ha="center", fontsize=9)
    fig.tight_layout(rect=(0, .10, 1, 1))
    fig.savefig(args.output_dir / "conditional_cone_ranges.png", dpi=150)
    plt.close(fig)
    result = dict(status="PASS" if all(checks.values()) else "FAIL", checks=checks,
        meaning="software and evidence consistency only; not distance accuracy validation",
        test_run=dict(command=command, returncode=test.returncode, stdout=test.stdout, stderr=test.stderr),
        source_sha256={str(p): digest(p) for p in (source, Path(__file__).resolve(), HERE / "test_same_session_range.py")})
    with (args.output_dir / "verification.json").open("x") as f:
        json.dump(result, f, indent=2, allow_nan=False)
        f.write("\n")
    print(json.dumps(dict(status=result["status"], checks=checks), indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
