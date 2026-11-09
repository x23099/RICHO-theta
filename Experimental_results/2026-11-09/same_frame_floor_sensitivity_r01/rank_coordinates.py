"""保存済み画素摂動から、Eを動かさない床4点の座標別感度を整理する。"""
import argparse
import csv
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
from cone_distance_core import digest

LABELS = ("near_image_left", "near_image_right", "far_image_left", "far_image_right")


def pair_sensitivity(baseline, minus, plus, amplitude):
    """中央差分の局所感度。座標の基準はX右/Z前。距離真値は使わない。"""
    if not math.isfinite(amplitude) or amplitude <= 0:
        raise ValueError("positive finite pixel amplitude required")
    if any(row.get("predicted_X_m") in (None, "") or row.get("predicted_Z_m") in (None, "")
           for row in (baseline, minus, plus)):
        return dict(available=False, dX_m_per_px=None, dZ_m_per_px=None,
                    max_center_shift_m=None, max_height_shift_m=None)
    bx, bz = float(baseline["predicted_X_m"]), float(baseline["predicted_Z_m"])
    mx, mz = float(minus["predicted_X_m"]), float(minus["predicted_Z_m"])
    px, pz = float(plus["predicted_X_m"]), float(plus["predicted_Z_m"])
    bh, mh, ph = (float(row["height_m"]) for row in (baseline, minus, plus))
    if not all(math.isfinite(v) for v in (bx, bz, mx, mz, px, pz, bh, mh, ph)):
        raise ValueError("finite saved prediction and height required")
    return dict(available=True, dX_m_per_px=(px-mx)/(2*amplitude),
        dZ_m_per_px=(pz-mz)/(2*amplitude),
        max_center_shift_m=max(math.hypot(px-bx, pz-bz), math.hypot(mx-bx, mz-bz)),
        max_height_shift_m=max(abs(ph-bh), abs(mh-bh)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.output_dir.exists():
        raise ValueError("new output directory required")
    folder = Path(__file__).parent
    verification = folder / "verification_r01/verification.json"
    checked = json.loads(verification.read_text())
    inputs = dict(checked["results_sha256"])
    inputs.update(checked["source_sha256"])
    for name, sha in inputs.items():
        if digest(name) != sha:
            raise ValueError("fixed sensitivity record/source changed: " + name)
    inputs.update({str(p): digest(p) for p in (Path(__file__), verification,
                   ROOT / "tests/test_same_frame_floor_coordinate_ranking.py")})
    with (folder / "results_r01/pixel_stress.csv").open() as stream:
        rows = list(csv.DictReader(stream))
    baseline = {(r["frame"], r["hypothesis"], r["matched_reference_branch"]): r
                for r in rows if r["case"] == "baseline"}
    singles = {(r["frame"], r["hypothesis"], r["matched_reference_branch"], float(r["amplitude_px"]),
                 r["variant_id"]): r for r in rows if r["case"] == "single_coordinate"}
    sensitivity = []
    for key, b in baseline.items():
        for amp in (.5, 1.):
            for axis in range(8):
                m = singles[(*key, amp, f"{axis}:-1")]
                p = singles[(*key, amp, f"{axis}:+1")]
                sensitivity.append(dict(frame=int(b["frame"]), group=b["group"], hypothesis=b["hypothesis"],
                    branch=int(b["matched_reference_branch"]), point=LABELS[axis//2], axis="xy"[axis % 2],
                    amplitude_px=amp, **pair_sensitivity(b, m, p, amp),
                    E_pixel_perturbed=False, E_target_used=False, physical_metric_verified=False, usable_for_ffb=False))
    grouped = []
    groups = sorted({(r["group"], r["hypothesis"], r["branch"], r["amplitude_px"]) for r in sensitivity})
    for group, h, branch, amp in groups:
        out = []
        for point, axis in ((p, a) for p in LABELS for a in "xy"):
            subset = [r for r in sensitivity if (r["group"], r["hypothesis"], r["branch"], r["amplitude_px"],
                       r["point"], r["axis"]) == (group, h, branch, amp, point, axis)]
            valid = [r for r in subset if r["available"]]
            out.append(dict(group=group, hypothesis=h, branch=branch, amplitude_px=amp,
                point=point, axis=axis, available_frames=len(valid), total_frames=len(subset),
                max_center_shift_m=max(r["max_center_shift_m"] for r in valid) if valid else None,
                dZ_min_m_per_px=min(r["dZ_m_per_px"] for r in valid) if valid else None,
                dZ_max_m_per_px=max(r["dZ_m_per_px"] for r in valid) if valid else None,
                physical_metric_verified=False, usable_for_ffb=False))
        out.sort(key=lambda r: -(r["max_center_shift_m"] if r["max_center_shift_m"] is not None else -1.))
        grouped.extend(dict(r, diagnostic_rank=i+1 if r["available_frames"] else None) for i, r in enumerate(out))
    args.output_dir.mkdir(parents=True)
    for filename, content in (("input_provenance.json", inputs), ("summary.json", dict(
        status="FIXED_CORNER_LOCAL_SENSITIVITY_ONLY", per_frame_rows=len(sensitivity), group_rows=len(grouped),
        E_pixel_perturbed=False, E_target_used=False, selected_model=None, runtime_changed=False,
        physical_metric_verified=False, usable_for_ffb=False, camera_images_edited_or_exported=False))):
        (args.output_dir / filename).write_text(json.dumps(content, indent=2)+"\n")
    for filename, content in (("coordinate_sensitivity.csv", sensitivity), ("group_ranking.csv", grouped)):
        with (args.output_dir / filename).open("x", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(content[0]), lineterminator="\n")
            writer.writeheader()
            writer.writerows(content)
    for r in grouped:
        if r["group"] == "P2" and r["hypothesis"].endswith("reflected_ray_x_control") and r["branch"] == 0 and r["amplitude_px"] == 1.:
            print(r)


if __name__ == "__main__":
    main()
