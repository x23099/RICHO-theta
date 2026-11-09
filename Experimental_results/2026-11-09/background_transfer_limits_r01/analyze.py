"""背景回転検査の限界を、合成対照と保存追跡点の除外試験で調べる。

既存のゲートを固定して試す。距離誤差を用いた閾値調整・runtime変更なし。
合成背景の奥行き、並進、誤対応は実機の測定値ではない。
"""
import argparse
import csv
import importlib.util
import json
from pathlib import Path
import sys

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
PRIOR = ROOT / "Experimental_results/2026-11-09/background_rotation_transfer_r01"
SPEC = importlib.util.spec_from_file_location("limits_transfer", PRIOR / "analyze.py")
transfer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(transfer)
from angular_fisheye_geometry import floor_from_rays, project, unproject
from cone_distance_core import digest, load_config

# 全ケースで同じ、重複なしの35点。床点・距離の正解とは独立。
SOURCE_PIXELS = np.array([[x, y] for x in np.linspace(170, 470, 7)
                          for y in (90, 120, 150, 180, 210)], float)
FLOOR_TARGETS = np.array([[1., 0., 0.], [1.4, 0., 0.], [2., 0., 0.],
                          [1.4, .2, 0.], [1.4, -.2, 0.]])
# 合成対照専用。物理測量や実画像への採用ではない。
REFERENCE_T = np.array([[0., 0., 1., .02], [-1., 0., 0., -.03],
                        [0., -1., 0., .59], [0., 0., 0., 1.]])
FALSE_FLAGS = dict(physical_metric_verified=False, usable_for_ffb=False,
                   model_selected=False, runtime_changed=False)


def rotation_error_deg(a, b):
    relative = transfer.checked_rotation(a) @ transfer.checked_rotation(b).T
    return float(np.degrees(np.arccos(np.clip((np.trace(relative)-1)/2, -1, 1))))


def project_checked(points, camera):
    pixels, valid = project(points, camera)
    if not valid.all():
        raise ValueError("synthetic rays left the declared calibration domain")
    return pixels


def target_error(camera, model, true_shift, true_rotation):
    """固定した床真値は推定後の評価のみ。拒否時に数値を出さない。"""
    if not model["accepted_for_offline_diagnostic"]:
        return dict(max_planar_error_m=None, target_results=[], distance_withheld=True)
    reference_optical = (FLOOR_TARGETS - REFERENCE_T[:3, 3]) @ REFERENCE_T[:3, :3]
    current_optical = (reference_optical - true_shift) @ true_rotation.T
    pixels = project_checked(current_optical, camera)
    rays, valid = unproject(pixels, camera, image_size=(1280, 720))
    candidate = transfer.transfer_floor_pose(dict(
        transform_floor_from_optical=REFERENCE_T.tolist(), geometry_consistent=True),
        model["rotation_current_from_reference"])
    points, accepted = floor_from_rays(rays, valid, candidate["transform_floor_from_optical"])
    if not accepted.all():
        raise ValueError("synthetic floor evaluation unexpectedly unavailable")
    errors = np.linalg.norm(points[:, :2] - FLOOR_TARGETS[:, :2], axis=1)
    records = [dict(target_forward_m=float(t[0]), target_left_m=float(t[1]),
                    predicted_forward_m=float(p[0]), predicted_left_m=float(p[1]),
                    planar_error_m=float(e)) for t, p, e in zip(FLOOR_TARGETS, points, errors)]
    # distance_withheld refers to this diagnostic calculation only, never live approval.
    return dict(max_planar_error_m=float(max(errors)), target_results=records,
                distance_withheld=False)


def motion_case(camera, depth, shift, rotation_vector):
    shift = np.asarray(shift, float)
    rotation = cv2.Rodrigues(np.asarray(rotation_vector, float))[0]
    rays, valid = unproject(SOURCE_PIXELS, camera, image_size=(1280, 720))
    if not valid.all() or np.any(rays[:, 2] <= 0):
        raise ValueError("positive optical Z and valid synthetic source required")
    if depth == "mixed_3_10":
        # 混合奥行きの配置は固定。正解距離による並べ替えなし。
        depths = np.where(np.arange(len(rays)) % 2 == 0, 3., 10.)
    else:
        depths = np.full(len(rays), float(depth))
    cloud = rays * (depths / rays[:, 2])[:, None]
    current = project_checked((cloud-shift) @ rotation.T, camera)
    model = transfer.estimate_background_rotation(SOURCE_PIXELS, current, camera)
    return dict(synthetic=True, physical_trial=False, background_optical_z=str(depth),
                true_shift_optical_m=shift.tolist(), true_rotation_vector_rad=list(rotation_vector),
                model=model, **target_error(camera, model, shift, rotation), **FALSE_FLAGS)


def tracking_cases(camera):
    """追跡点だけを壊した対照。実画像で同じ異常が起きたとの主張ではない。"""
    p = SOURCE_PIXELS.copy()
    split = transfer.spatial_train_mask(p)
    q_test, q_train, q_sparse = p.copy(), p.copy(), p.copy()
    q_test[~split, 0] += 8.
    q_train[split, 0] += 8.
    q_sparse[::5, 0] += 8.
    rays, _ = unproject(p, camera, image_size=(1280, 720))
    false_r = cv2.Rodrigues(np.array([np.deg2rad(.8), 0., 0.]))[0]
    coherent_wrong = project_checked(rays @ false_r.T, camera)
    large_r = cv2.Rodrigues(np.array([0., np.deg2rad(6.), 0.]))[0]
    large_q = project_checked(rays @ large_r.T, camera)
    concentrated = np.array([[x, y] for x in (300, 310, 320, 330, 340)
                              for y in (100, 120, 140, 160, 180, 200)], float)
    fixtures = [
        ("correct_identity", p, p, np.eye(3)),
        ("heldout_only_wrong_8px", p, q_test, np.eye(3)),
        ("training_only_wrong_8px", p, q_train, np.eye(3)),
        ("every_fifth_wrong_8px", p, q_sparse, np.eye(3)),
        ("coherent_wrong_rotation_0p8deg", p, coherent_wrong, np.eye(3)),
        ("insufficient_10_matches", p[:10], p[:10], np.eye(3)),
        ("narrow_40px_coverage", concentrated, concentrated, np.eye(3)),
        ("true_rotation_6deg", p, large_q, large_r)]
    results = []
    for name, source, target, true_r in fixtures:
        model = transfer.estimate_background_rotation(source, target, camera)
        results.append(dict(case=name, synthetic=True, physical_trial=False, model=model,
            **target_error(camera, model, np.zeros(3), true_r), **FALSE_FLAGS))
    return results


def flatten(record, **labels):
    m = record["model"]
    return dict(**labels, background_pass=m["accepted_for_offline_diagnostic"],
        reason=m["reason"], matches=m["matches"], training=m["train_count"], heldout=m["test_count"],
        heldout_median_px=m["test_median_px"], heldout_p90_px=m["test_p90_px"],
        apparent_rotation_deg=m["rotation_deg"], max_planar_error_m=record["max_planar_error_m"],
        distance_withheld=record["distance_withheld"], **FALSE_FLAGS)


def real_track_jackknife(camera, tracks):
    """推定用48pxセルを1つずつ除く。元の検査点は全て固定して保持。"""
    output = []
    frames = sorted({int(r["frame"]) for r in tracks} - {20063, 20493})
    for frame in frames:
        rows = [r for r in tracks if int(r["frame"]) == frame]
        p = np.array([[float(r["source_x"]), float(r["source_y"])] for r in rows])
        q = np.array([[float(r["target_x"]), float(r["target_y"])] for r in rows])
        baseline = transfer.estimate_background_rotation(p, q, camera)
        split = transfer.spatial_train_mask(p)
        cells = np.floor(p / transfer.SCREENS["spatial_cell_px"]).astype(int)
        for cell in sorted(set(map(tuple, cells[split]))):
            omitted = split & (cells == cell).all(axis=1)
            keep = ~omitted
            # Check that we have not removed or reassigned any held-out correspondence.
            np.testing.assert_array_equal(p[keep][~transfer.spatial_train_mask(p[keep])], p[~split])
            model = transfer.estimate_background_rotation(p[keep], q[keep], camera)
            delta = None
            if model["rotation_current_from_reference"] is not None:
                delta = rotation_error_deg(model["rotation_current_from_reference"],
                                           baseline["rotation_current_from_reference"])
            output.append(dict(frame=frame, omitted_cell=[int(v) for v in cell], removed_training=int(omitted.sum()),
                original_test_count=int((~split).sum()), rotation_change_deg=delta, model=model))
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.output_dir.exists():
        raise ValueError("new output directory required")
    manifest = PRIOR / "results_r01/input_provenance.json"
    source_hashes = json.loads(manifest.read_text())
    # Close the inherited provenance chain to the original PNG/candidate sources.
    inherited = transfer.GEOMETRY / "same_frame_pose_r01/input_provenance.json"
    source_hashes.update(json.loads(inherited.read_text()))
    for name, expected in source_hashes.items():
        if digest(name) != expected:
            raise ValueError("prior source/input changed: " + name)
    track_path = transfer.GEOMETRY / "same_frame_pose_r01/background_tracks.csv"
    source_hashes.update({str(p): digest(p) for p in (
        Path(__file__), manifest, inherited, track_path, PRIOR / "analyze.py")})
    camera = load_config()[1]
    motion, motion_rows = [], []
    # 5奥行き × 3方向 × 4移動量 × 2回転 = 120ケース。通過率は実機確率ではない。
    for depth in (3., 5., 10., 20., "mixed_3_10"):
        for axis, label in enumerate(("lateral_x", "vertical_y", "forward_z")):
            for amount in (.01, .03, .05, .10):
                for deg in (0., .8):
                    shift = np.eye(3)[axis] * amount
                    case = motion_case(camera, depth, shift, [0., np.deg2rad(deg), 0.])
                    motion.append(case)
                    motion_rows.append(flatten(case, depth=str(depth), axis=label,
                                               shift_m=amount, true_yaw_deg=deg))
    # 静止/正しい回転の陽性対照を並進ケースと混ぜない。
    positive = [motion_case(camera, 5., [0., 0., 0.], vector) for vector in (
        [0., 0., 0.], [np.deg2rad(.8), 0., 0.], [0., np.deg2rad(.8), 0.])]
    tracking = tracking_cases(camera)
    with track_path.open() as stream:
        jackknife = real_track_jackknife(camera, list(csv.DictReader(stream)))
    per_frame = []
    for frame in sorted({r["frame"] for r in jackknife}):
        rows = [r for r in jackknife if r["frame"] == frame]
        delta = [r["rotation_change_deg"] for r in rows if r["rotation_change_deg"] is not None]
        per_frame.append(dict(frame=frame, omitted_cells=len(rows), passed=sum(
            r["model"]["accepted_for_offline_diagnostic"] for r in rows),
            max_rotation_change_deg=max(delta) if delta else None,
            max_heldout_p90_px=max(r["model"]["test_p90_px"] for r in rows
                                  if r["model"]["test_p90_px"] is not None)))
    passed = [r for r in motion_rows if r["background_pass"]]
    summary = dict(status="BACKGROUND_GATE_CANNOT_APPROVE_STATIC_CENTRE_OR_METRIC_RANGE",
        synthetic_motion_cases=len(motion), synthetic_motion_passed=len(passed),
        synthetic_passed_max_error_m=max(r["max_planar_error_m"] for r in passed),
        synthetic_positive_control_max_error_m=max(r["max_planar_error_m"] for r in positive),
        tracking_controls=[flatten(r, case=r["case"]) for r in tracking],
        real_jackknife=per_frame, screens_changed=False, thresholds_fitted_to_E=False,
        actual_camera_translation_measured=False, mirror_verified=False,
        camera_images_edited_or_exported=False, published_to_ros=False, **FALSE_FLAGS)
    args.output_dir.mkdir(parents=True)
    transfer.original.dump(args.output_dir / "input_provenance.json", source_hashes)
    transfer.original.dump(args.output_dir / "summary.json", summary)
    transfer.original.dump(args.output_dir / "synthetic_motion_cases.json", motion)
    transfer.original.dump(args.output_dir / "positive_controls.json", positive)
    transfer.original.dump(args.output_dir / "tracking_controls.json", tracking)
    transfer.original.dump(args.output_dir / "real_jackknife.json", jackknife)
    transfer.original.table(args.output_dir / "synthetic_motion_metrics.csv", motion_rows)
    transfer.original.table(args.output_dir / "tracking_metrics.csv", summary["tracking_controls"])
    transfer.original.table(args.output_dir / "real_jackknife_summary.csv", per_frame)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
