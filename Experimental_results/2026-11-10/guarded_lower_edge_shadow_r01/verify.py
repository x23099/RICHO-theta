"""元画像8枚と保存ログの条件を分離して統合候補を検証。live変更なし。"""
import argparse
from bisect import bisect_left
from collections import Counter
import copy
import csv
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))
import cv2
from angular_fisheye_geometry import unproject
from cone_distance_core import digest, load_config
from cone_guarded_lower_edge_shadow import compare_guarded_lower_edge, lower_half_pixel_only
from cone_motion_range import MotionRangeEngine, horizontal_range, load_motion_profile
from cone_self_body_shadow import checked_reference, compare_self_body
from report_driver_motion_logs import FLAGS, reject_constant, unique_object, validate_result
from theta_rtc_frames import NativeFrame


def load(path):
    return json.loads(path.read_bytes(), parse_constant=reject_constant, object_pairs_hook=unique_object)


def run(output):
    if output.exists():raise ValueError("new output required")
    previous = ROOT / "Experimental_results/2026-11-10/driver_motion_171250_review_r01"
    native_dir = previous / "evidence_replay_r01"
    old_summary = load(native_dir / "summary.json")
    cached = load(native_dir / "comparisons.json")
    body_dir = ROOT / "Experimental_results/2026-11-10/self_body_boundary_shadow_r01"
    reference = checked_reference(load(body_dir / "reference.json"))
    inputs = dict(old_summary["input_sha256"])
    inputs.update(old_summary["source_sha256"])
    # The native baseline predates the body veto. Bind that newer dependency
    # to its own successful verification rather than accepting a changed gate.
    inputs.update(load(body_dir / "results_r01/summary.json")["source_sha256"])
    inputs.update({str(p): digest(p) for p in (native_dir / "summary.json", native_dir / "comparisons.json",
                  body_dir / "reference.json", previous / "full_run_report/summary.json")})
    if any(digest(Path(p)) != sha for p, sha in inputs.items()):
        raise ValueError("cached native baseline input or implementation changed")
    reference_image = next(Path(r["image_file"]) for r in cached if r["frame"] == reference["source_frame"])
    if digest(reference_image) != reference["source_png_sha256"]:
        raise ValueError("reference PNG mismatch")
    source = ROOT / "recordings/2026-11-10/driver_motion_171250_intake_r01/driver_motion_live_20261110_171250"
    settings, camera, _, _ = load_config()
    profile, profile_sha = load_motion_profile(source / "motion_profile_used.json", settings)
    if profile_sha != old_summary["profile_sha256"]:
        raise ValueError("profile mismatch")
    model = next(m for m in profile["models"] if m["id"] == profile["primary_model"])
    native = []
    for saved in cached:
        path = Path(saved["image_file"])
        image = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if image is None or image.shape != (720, 1280, 3):
            raise ValueError("native image required")
        pixel_sha = hashlib.sha256(image.tobytes()).hexdigest()
        sidecar = load(path.with_suffix(".json"))
        if pixel_sha != sidecar["decoded_bgr_sha256"]:
            raise ValueError("native decoded pixel hash mismatch")
        image.flags.writeable = False
        old = sidecar["measurement"]
        boxes = old["selected_detector_boxes"]
        comparison = compare_guarded_lower_edge(image, boxes[0], camera, reference,
            session=old["session"], reference_matches=True)
        if comparison["baseline"] != saved["observation_comparison"]["baseline"]:
            raise ValueError("baseline observation changed")
        obs = comparison["proposed_observation"]
        engine = MotionRangeEngine(settings, camera, profile, profile_sha, acknowledged=True,
            target_roi=(270, 0, 350, 720), observer=lambda *a, v=obs: copy.deepcopy(v))
        result = engine.measure(NativeFrame(old["session"], old["frame"], 1., 1., image), boxes, 1.01)
        if any(result[k] is not False for k in FLAGS):
            raise ValueError("unexpected authority")
        if result["distance_available"]:
            former = saved["candidate_values_NOT_live_output_or_ground_truth"]["half_pixel_overlap"]
            if any(result[k] != former[k] for k in ("horizontal_camera_foot_range_m", "support_pixel", "models")):
                raise ValueError("point or metric changed instead of pure gating")
        if pixel_sha != hashlib.sha256(image.tobytes()).hexdigest():
            raise ValueError("pixels changed")
        native.append(dict(frame=old["frame"], original_available=old["distance_available"],
            proposed_available=result["distance_available"], proposed_range_m=result["horizontal_camera_foot_range_m"],
            native_pixels_rechecked=True, comparison=comparison, physical_accuracy_verified=False))
    spec = importlib.util.spec_from_file_location("saved_boundary_audit", ROOT /
        "Experimental_results/2026-11-10/support_boundary_audit_r01/audit.py")
    audit = importlib.util.module_from_spec(spec);spec.loader.exec_module(audit)
    inputs[str(Path(spec.origin))] = digest(Path(spec.origin))
    rows, positives, outcomes = [], [], Counter()
    with (source / "motion_distance_frames.jsonl").open("rb") as stream:
        for line in stream:
            r = json.loads(line, parse_constant=reject_constant, object_pairs_hook=unique_object)
            validate_result(r)
            if r["session"] != reference["session"]:
                raise ValueError("unexpected session")
            value = r["horizontal_camera_foot_range_m"]
            point = r["support_pixel"]
            new_point, new_value, lower, body_clear = point, value, False, False
            late = None
            if r["distance_available"]:
                body = compare_self_body(r["support_observation"], reference,
                    session=r["session"], reference_matches=True)
                body_clear = not body["revoked"]
                outcome = "existing_numeric_preserved" if body_clear else "existing_numeric_body_veto"
                if not body_clear:new_point, new_value = None, None
                positives.append(dict(frame=r["frame"], point=point, range_m=value))
            elif r["reason"] == "colour_contour_reaches_roi_edge":
                late = audit.candidate_audit(r)
                outcome = "existing_withheld_no_verified_late_candidate"
                if "relation" in late:
                    point = late["relation"]["point"]
                    box = r["selected_detector_boxes"][0]
                    lower = lower_half_pixel_only(box, point)
                    obs = dict(point=point, support=late["logged_candidate_support"],
                        reason="logged_candidate_NOT_image_recomputed", floor_contact_verified=False,
                        physical_metric_verified=False, controlling_distance=False, usable_for_ffb=False)
                    body = compare_self_body(obs, reference, session=r["session"], reference_matches=True)
                    body_clear = not body["revoked"]
                    outcome = "existing_withheld_lower_edge_rule_not_met"
                    if lower:
                        outcome = "existing_withheld_body_veto"
                        if body_clear:
                            ray, domain = unproject([point], camera, image_size=(1280, 720))
                            candidate_value = horizontal_range(ray[0], model) if domain[0] else None
                            low, high = settings["diagnostic_range_m"]
                            if candidate_value is not None and low <= candidate_value <= high:
                                new_point, new_value = point, candidate_value
                                outcome = "new_numeric_LOG_CONDITIONS_ONLY"
            else:
                outcome = "existing_withheld_other_reason"
            outcomes[outcome] += 1
            rows.append(dict(frame=r["frame"], source_time_sec=r["source_time_sec"],
                completed_time_sec=r["completed_time_sec"], original_available=r["distance_available"],
                original_range_m=value, proposed_available=new_value is not None,
                proposed_range_m=new_value, proposed_point=new_point, outcome=outcome,
                lower_half_pixel_eligible=lower, body_clear=body_clear,
                native_pixels_rechecked=False,
                lower_shortfall_px=late["relation"]["outside_bottom_px"] if late and "relation" in late else None))
    new = [r for r in rows if r["outcome"] == "new_numeric_LOG_CONDITIONS_ONLY"]
    keys = [r["frame"] for r in positives]
    for r in new:
        i = bisect_left(keys, r["frame"])
        neighbours = [positives[j] for j in (i-1, i) if 0 <= j < len(positives)]
        r["adjacent_original_numeric_NOT_ground_truth"] = neighbours
        r["same_point_as_both_neighbours"] = len(neighbours) == 2 and all(n["point"] == r["proposed_point"] for n in neighbours)
        r["max_neighbour_range_difference_m"] = max(abs(n["range_m"] - r["proposed_range_m"]) for n in neighbours)
        r["same_frame_native_replay_available"] = any(n["frame"] == r["frame"] for n in native)
    prior_report = load(previous / "full_run_report/summary.json")["sessions"][0]
    if len(rows) != prior_report["processed_frames"] or len(positives) != prior_report["numeric_results"]:
        raise ValueError("log audit incomplete")
    tests_log = io.StringIO()
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"), pattern="test_cone_guarded_lower_edge_shadow.py")
    tests = unittest.TextTestRunner(stream=tests_log, verbosity=2).run(suite)
    if not tests.wasSuccessful():raise ValueError(tests_log.getvalue())
    if any(digest(Path(p)) != sha for p, sha in inputs.items()):
        raise ValueError("inputs changed during analysis")
    summary = dict(schema="guarded_lower_edge_shadow_verification_v1", session=reference["session"],
        source_records=len(rows), original_numeric=len(positives),
        log_only_proposed_numeric=sum(r["proposed_available"] for r in rows), log_only_outcomes=dict(outcomes),
        saved_native_rechecked=len(native), saved_native_proposed_numeric=sum(r["proposed_available"] for r in native),
        added_numeric_log_conditions=len(new), added_same_frame_native_rechecked=sum(r["same_frame_native_replay_available"] for r in new),
        added_same_point_as_adjacent_numeric=sum(r["same_point_as_both_neighbours"] for r in new),
        added_max_range_difference_from_adjacent_numeric_m=max(r["max_neighbour_range_difference_m"] for r in new),
        added_lower_shortfall_min_px=min(r["lower_shortfall_px"] for r in new),
        added_lower_shortfall_max_px=max(r["lower_shortfall_px"] for r in new),
        native_frame_ids_with_new_point=[r["frame"] for r in native if r["proposed_available"] and not r["original_available"]],
        tests=dict(run=tests.testsRun, failures=len(tests.failures), errors=len(tests.errors), skipped=len(tests.skipped)),
        input_sha256=inputs, source_sha256={str(p): digest(p) for p in
            (Path(__file__), ROOT / "src/cone_guarded_lower_edge_shadow.py", ROOT / "tests/test_cone_guarded_lower_edge_shadow.py")},
        live_distance_policy_changed=False, images_modified=False, actual_new_yolo_inference=False,
        physical_accuracy_improvement_verified=False, ground_truth_from_neighbours=False,
        neighbours_used_by_candidate=False, body_reference_cross_session_verified=False)
    output.mkdir(parents=True, exist_ok=False)
    for name, payload in (("summary.json", summary), ("native_comparisons.json", native), ("added_log_candidates.json", new)):
        with (output / name).open("x") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2, allow_nan=False);stream.write("\n")
    fields = [k for k in rows[0] if k != "adjacent_original_numeric_NOT_ground_truth"]
    with (output / "log_impact.csv").open("x", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore");writer.writeheader();writer.writerows(rows)
    with (output / "tests.log").open("x") as stream:stream.write(tests_log.getvalue())
    print(json.dumps({k: summary[k] for k in ("source_records", "original_numeric", "log_only_proposed_numeric",
        "log_only_outcomes", "saved_native_proposed_numeric", "added_same_point_as_adjacent_numeric",
        "added_max_range_difference_from_adjacent_numeric_m", "tests")}, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    run(parser.parse_args().output_dir)
