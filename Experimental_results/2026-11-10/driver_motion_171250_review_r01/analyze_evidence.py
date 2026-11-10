"""提出された保留元画像8枚を同frameの保存枠で再計算。live変更なし。"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
import cv2
from cone_bbox_boundary_shadow import POLICIES, compare_boundary_observations
from cone_distance_core import DEFAULT_CONFIG, digest, load_config
from cone_motion_range import MotionRangeEngine, load_motion_profile
from report_driver_motion_logs import reject_constant, unique_object
from theta_rtc_frames import NativeFrame
from verify_driver_withheld_evidence import verify


def load(path):
    return json.loads(path.read_bytes(), parse_constant=reject_constant,
                      object_pairs_hook=unique_object)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    source, evidence = args.input_dir.resolve(), args.evidence_dir.resolve()
    output = args.output_dir.resolve()
    if output.exists() or any(p == output or p in output.parents for p in (source, evidence)):
        raise ValueError("new output outside raw input required")
    validation = verify(evidence, source / "motion_distance_frames.jsonl")
    if validation["verified_pairs"] == 0:
        raise ValueError("no evidence collected")
    settings, camera, _, _ = load_config()
    profile, profile_sha = load_motion_profile(source / "motion_profile_used.json", settings)
    metadata = load(source / "motion_engine_summary.json")
    if digest(DEFAULT_CONFIG) != metadata["config_sha256"] or profile_sha != metadata["profile_sha256"]:
        raise ValueError("original profile/config required")
    inputs = {str(p): digest(p) for p in (source / "motion_profile_used.json",
              source / "motion_engine_summary.json", DEFAULT_CONFIG, evidence / "evidence_index.jsonl",
              evidence / "evidence_status.json", source / "motion_distance_frames.jsonl")}
    rows = []
    for line in (evidence / "evidence_index.jsonl").read_bytes().splitlines():
        indexed = json.loads(line)
        meta = load(evidence / indexed["sidecar_file"])
        old = meta["measurement"]
        path = evidence / indexed["image_file"]
        inputs[str(path)] = digest(path)
        inputs[str(evidence / indexed["sidecar_file"])] = digest(evidence / indexed["sidecar_file"])
        pixels = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if pixels is None or pixels.shape != (720, 1280, 3):
            raise ValueError("native frame required")
        pixel_sha = hashlib.sha256(pixels.tobytes()).hexdigest()
        if pixel_sha != meta["decoded_bgr_sha256"]:
            raise ValueError("pixel hash mismatch")
        pixels.flags.writeable = False
        boxes = copy.deepcopy(old["selected_detector_boxes"])
        if len(boxes) != 1:
            raise ValueError("one historical detector box required")
        comparison = compare_boundary_observations(pixels, boxes[0], camera)
        if comparison["baseline"] != old["support_observation"]:
            raise ValueError("baseline observation differs from live log")
        choices = dict(baseline=comparison["baseline"], **{p: comparison["comparisons"][p]["observation"]
                                                         for p in POLICIES})
        results = {}
        for policy, obs in choices.items():
            engine = MotionRangeEngine(settings, camera, profile, profile_sha, acknowledged=True,
                target_roi=(270, 0, 350, 720), observer=lambda *a, value=obs: copy.deepcopy(value))
            frame = NativeFrame(old["session"], old["frame"], old["media_time_sec"], 1., pixels)
            result = engine.measure(frame, boxes, 1.01)
            results[policy] = {k: result[k] for k in ("distance_available", "reason",
                "horizontal_camera_foot_range_m", "support_pixel", "models")}
        if any(results["baseline"][k] != old[k] for k in ("distance_available", "reason",
                  "horizontal_camera_foot_range_m", "support_pixel", "models")):
            raise ValueError("baseline metric differs")
        if hashlib.sha256(pixels.tobytes()).hexdigest() != pixel_sha:
            raise ValueError("pixels changed")
        rows.append(dict(session=old["session"], frame=old["frame"], image_file=str(path),
            candidate_values_NOT_live_output_or_ground_truth=results,
            observation_comparison=comparison, native_pixels_unchanged=True))
    if any(digest(Path(p)) != sha for p, sha in inputs.items()):
        raise ValueError("input changed during analysis")
    summary = dict(schema="actual_withheld_native_replay_v1", verified_pairs=validation["verified_pairs"],
        baseline_reproduced_frames=len(rows),
        policies={policy: dict(numeric_results=sum(r["candidate_values_NOT_live_output_or_ground_truth"][policy]
                    ["distance_available"] for r in rows)) for policy in ("baseline", *POLICIES)},
        original_pixels_unchanged=True, exact_saved_detector_boxes=True,
        actual_new_yolo_inference=False, timing_synthetic_NOT_performance_measurement=True,
        frame_motion_or_static_labels_available=False, physical_error_measured=False,
        all_candidates_require_occlusion_review=True, live_policy_changed=False,
        profile_sha256=profile_sha, input_sha256=inputs,
        source_sha256={str(p): digest(p) for p in (Path(__file__), ROOT / "src/cone_bbox_boundary_shadow.py",
            ROOT / "src/cone_motion_range.py", ROOT / "src/cone_upper_support_candidate.py",
            ROOT / "src/cone_support_completion_candidate.py", ROOT / "src/verify_driver_withheld_evidence.py")})
    output.mkdir(parents=True, exist_ok=False)
    for name, value in (("verification.json", validation), ("summary.json", summary), ("comparisons.json", rows)):
        with (output / name).open("x") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
    print(json.dumps({k: summary[k] for k in ("verified_pairs", "baseline_reproduced_frames", "policies")}, indent=2))


if __name__ == "__main__":
    main()
