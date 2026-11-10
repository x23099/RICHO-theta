"""同session元画像・既存再計算とログで自己領域の棄却候補を検証。"""
import argparse
from collections import Counter, defaultdict
import copy
import csv
import io
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))
from cone_distance_core import digest, load_config
from cone_motion_range import MotionRangeEngine, load_motion_profile
from cone_self_body_shadow import checked_reference, compare_self_body
from report_driver_motion_logs import distribution, reject_constant, unique_object
from theta_rtc_frames import NativeFrame
import cv2


def load(path):
    return json.loads(path.read_bytes(), parse_constant=reject_constant, object_pairs_hook=unique_object)


def run(output):
    output = output.resolve()
    if output.exists():
        raise ValueError("new output required")
    prior = ROOT / "Experimental_results/2026-11-10/driver_motion_171250_review_r01"
    cached_path = prior / "evidence_replay_r01/comparisons.json"
    cached_summary_path = prior / "evidence_replay_r01/summary.json"
    cached = load(cached_path)
    cached_summary = load(cached_summary_path)
    inputs = dict(cached_summary["input_sha256"])
    inputs.update(cached_summary["source_sha256"])
    inputs.update({str(p): digest(p) for p in (cached_path, cached_summary_path,
                  HERE / "reference.json", HERE / "visual_review.json", prior / "audit_r02.json")})
    if any(digest(Path(p)) != sha for p, sha in inputs.items()):
        raise ValueError("cached baseline inputs or implementation changed")
    ref = checked_reference(load(HERE / "reference.json"))
    labels = load(HERE / "visual_review.json")
    if labels["session"] != ref["session"] or labels["physical_contact_labels"] is not False:
        raise ValueError("qualitative same-session review required")
    reviews = {r["frame"]: r["review"] for r in labels["frames"]}
    if len(reviews) != len(labels["frames"]) or set(reviews) != {r["frame"] for r in cached}:
        raise ValueError("all and only saved frames must have a qualitative review")
    reference_record = next(r for r in cached if r["frame"] == ref["source_frame"])
    if digest(Path(reference_record["image_file"])) != ref["source_png_sha256"]:
        raise ValueError("reference native PNG SHA mismatch")
    source = ROOT / "recordings/2026-11-10/driver_motion_171250_intake_r01/driver_motion_live_20261110_171250"
    settings, camera, _, _ = load_config()
    profile, profile_sha = load_motion_profile(source / "motion_profile_used.json", settings)
    if profile_sha != cached_summary["profile_sha256"]:
        raise ValueError("profile mismatch")
    rows, counts = [], defaultdict(Counter)
    for saved in cached:
        image = cv2.imread(saved["image_file"], cv2.IMREAD_COLOR)
        if image is None or image.shape != (720, 1280, 3):
            raise ValueError("native image required")
        image.flags.writeable = False
        comparison = saved["observation_comparison"]
        choices = dict(baseline=comparison["baseline"], **{p: v["observation"]
            for p, v in comparison["comparisons"].items()})
        boxes = load(Path(saved["image_file"]).with_suffix(".json"))["measurement"]["selected_detector_boxes"]
        for margin in (0, 1, 2, 4, 8):
            for policy, obs in choices.items():
                checked = compare_self_body(obs, ref, session=saved["session"],
                    margin_px=margin, reference_matches=True)
                engine = MotionRangeEngine(settings, camera, profile, profile_sha, acknowledged=True,
                    target_roi=(270, 0, 350, 720),
                    observer=lambda *a, v=checked["observation"]: copy.deepcopy(v))
                result = engine.measure(NativeFrame(saved["session"], saved["frame"], 1., 1., image), boxes, 1.01)
                before = saved["candidate_values_NOT_live_output_or_ground_truth"][policy]
                if result["distance_available"] and (not before["distance_available"] or any(
                    result[k] != before[k] for k in ("horizontal_camera_foot_range_m", "support_pixel", "models"))):
                    raise ValueError("rejection-only comparator created or changed a numeric value")
                key = f"{policy}:margin={margin}"
                counts[key]["numeric_before"] += before["distance_available"]
                counts[key]["numeric_after"] += result["distance_available"]
                counts[key]["newly_revoked"] += checked["revoked"]
                rows.append(dict(session=saved["session"], frame=saved["frame"], policy=policy,
                    margin_px=margin, qualitative_review=reviews[saved["frame"]],
                    before_available=before["distance_available"], after_available=result["distance_available"],
                    before_m=before["horizontal_camera_foot_range_m"],
                    after_m=result["horizontal_camera_foot_range_m"],
                    support_pixel=result["support_pixel"], review_reason=checked["reason"],
                    min_clearance_px=checked["min_clearance_px"],
                    point_clearance_px=checked["point_clearance_px"],
                    affected_columns=checked["affected_columns"],
                    floor_contact_verified=False, real_accuracy_verified=False))
    # Reuse real measured supports in ALL numeric records. No original image
    # exists for most of these, so boundary conflict is NOT an occlusion label.
    numeric, full_counts = [], Counter()
    log_path = source / "motion_distance_frames.jsonl"
    total = 0
    with log_path.open("rb") as stream:
        for line in stream:
            total += 1
            r = json.loads(line, parse_constant=reject_constant, object_pairs_hook=unique_object)
            if not r["distance_available"]:
                continue
            if r["session"] != ref["session"]:
                raise ValueError("unexpected session in numeric audit")
            obs = r["support_observation"]
            if obs["point"] != r["support_pixel"]:
                raise ValueError("logged point mismatch")
            review = compare_self_body(obs, ref, session=r["session"], reference_matches=True)
            full_counts[review["reason"]] += 1
            numeric.append(dict(session=r["session"], frame=r["frame"],
                range_m=r["horizontal_camera_foot_range_m"], point_x=r["support_pixel"][0],
                point_y=r["support_pixel"][1], proposed_revoke=review["revoked"],
                reason=review["reason"], min_clearance_px=review["min_clearance_px"],
                point_clearance_px=review["point_clearance_px"],
                native_image_available=r["frame"] in reviews,
                floor_contact_or_occlusion_ground_truth=False))
    old = load(prior / "full_run_report/summary.json")["sessions"][0]
    if total != old["processed_frames"] or len(numeric) != old["numeric_results"]:
        raise ValueError("numeric audit incomplete")
    if any(digest(Path(p)) != sha for p, sha in inputs.items()):
        raise ValueError("inputs changed")
    test_log = io.StringIO()
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"), pattern="test_cone_self_body_shadow.py")
    tests = unittest.TextTestRunner(stream=test_log, verbosity=2).run(suite)
    if not tests.wasSuccessful():
        raise ValueError(test_log.getvalue())
    summary = dict(schema="self_body_rejection_shadow_verification_v1",
        session=ref["session"], saved_native_frames=len(cached),
        independent_native_frames=len(cached) - 1, reference_frame=ref["source_frame"],
        comparisons=len(rows), saved_frame_policy_counts={k: dict(v) for k, v in counts.items()},
        existing_numeric_records=len(numeric), existing_numeric_shadow_reasons=dict(full_counts),
        numeric_boundary_conflict_range_m=distribution([r["range_m"] for r in numeric
            if r["reason"] == "possible_self_body_occlusion"]),
        tests=dict(run=tests.testsRun, failures=len(tests.failures), errors=len(tests.errors),
                   skipped=len(tests.skipped)), input_sha256=inputs,
        source_sha256={str(p): digest(p) for p in (Path(__file__), ROOT / "src/cone_self_body_shadow.py",
                          ROOT / "tests/test_cone_self_body_shadow.py")},
        original_png_files_unchanged=True, original_numeric_values_changed=False,
        boundary_reference_analyst_estimate=True, current_same_session_body_edge_stability_verified=False,
        occlusion_labels_independently_validated=False, physical_accuracy_verified=False,
        live_entry_points_modified=False, real_camera_gpu_or_vehicle_started=False)
    output.mkdir(parents=True, exist_ok=False)
    for name, payload in (("summary.json", summary), ("frame_comparisons.json", rows)):
        with (output / name).open("x") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
    with (output / "numeric_log_shadow.csv").open("x", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(numeric[0]))
        writer.writeheader();writer.writerows(numeric)
    with (output / "tests.log").open("x") as stream:
        stream.write(test_log.getvalue())
    print(json.dumps({k: summary[k] for k in ("saved_native_frames", "comparisons",
        "saved_frame_policy_counts", "existing_numeric_records", "existing_numeric_shadow_reasons", "tests")}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    run(args.output_dir)
