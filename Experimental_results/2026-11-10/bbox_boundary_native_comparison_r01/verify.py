"""過去10枚の元画素と保存YOLO枠によるオフライン境界候補比較。"""
import argparse
import copy
import csv
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT/"src"))
import cv2
import numpy as np
from cone_bbox_boundary_shadow import POLICIES, compare_boundary_observations
from cone_distance_core import DEFAULT_CONFIG, digest, load_config
from cone_motion_range import MotionRangeEngine, load_motion_profile
from theta_rtc_frames import NativeFrame


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    output = args.output_dir.resolve()
    if output.exists():
        raise ValueError("new output required")
    prior = ROOT/"Experimental_results/2026-11-09/cone_motion_evaluation_r01"
    provenance_path = prior/"verification_r02/input_provenance.json"
    provenance = json.loads(provenance_path.read_text())
    replay_path = prior/"verification_r02/cached_replay.jsonl"
    originals = [json.loads(line) for line in replay_path.read_text().splitlines()]
    paths = {Path(p).name: Path(p) for p in provenance if p.endswith(".png")}
    profile_path = prior/"prepared_r01/motion_profile_r01.json"
    settings, camera, _, _ = load_config()
    profile, profile_sha = load_motion_profile(profile_path, settings)
    inputs = {str(p): digest(p) for p in (provenance_path, replay_path, DEFAULT_CONFIG, profile_path)}
    for name in ("cone_distance_core.py", "cone_motion_range.py", "cone_upper_support_candidate.py",
                 "cone_support_completion_candidate.py", "angular_fisheye_geometry.py"):
        path = ROOT/"src"/name
        if digest(path) != provenance[str(path)]:
            raise ValueError("baseline source changed: " + name)
    metrics, observations, jitter = [], [], []
    for old in originals:
        name = f"decoded_{old['session']}_f{old['frame']:06d}.png"
        path = paths[name]
        inputs[str(path)] = digest(path)
        if inputs[str(path)] != provenance[str(path)]:
            raise ValueError("historical PNG bytes changed")
        pixels = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if pixels is None or pixels.shape != (720, 1280, 3):
            raise ValueError("original native image required")
        pixel_sha = hashlib.sha256(pixels.tobytes()).hexdigest()
        pixels.flags.writeable = False
        boxes = copy.deepcopy(old["selected_detector_boxes"])
        if len(boxes) != 1:
            raise ValueError("expected one cached detector box")
        comparison = compare_boundary_observations(pixels, boxes[0], camera)
        choices = {"baseline": comparison["baseline"],
                   **{p: comparison["comparisons"][p]["observation"] for p in POLICIES}}
        result_rows = {}
        for policy, observation in choices.items():
            engine = MotionRangeEngine(settings, camera, profile, profile_sha, acknowledged=True,
                target_roi=(270, 0, 350, 720),
                observer=lambda *args, value=observation: copy.deepcopy(value))
            # Explicit synthetic timing: not evidence of inference speed.
            frame = NativeFrame(old["session"], old["frame"], 1., 1., pixels)
            row = engine.measure(frame, boxes, 1.01)
            row["offline_policy"] = policy
            result_rows[policy] = row
        baseline = result_rows["baseline"]
        for key in ("distance_available", "reason", "horizontal_camera_foot_range_m"):
            if baseline[key] != old[key]:
                raise ValueError("baseline no longer matches prior saved result: " + key)
        for policy in POLICIES:
            row = result_rows[policy]
            if baseline["distance_available"] and any(row[k] != baseline[k] for k in
                    ("distance_available", "reason", "horizontal_camera_foot_range_m", "support_pixel", "models")):
                raise ValueError("existing positive distance changed")
            metrics.append(dict(session=old["session"], frame=old["frame"], policy=policy,
                baseline_available=baseline["distance_available"], candidate_available=row["distance_available"],
                baseline_range_m=baseline["horizontal_camera_foot_range_m"],
                candidate_range_m=row["horizontal_camera_foot_range_m"], reason=row["reason"],
                observation_changed=comparison["comparisons"][policy]["changed"],
                baseline_completion_reason=comparison["baseline"].get("completion_reason"),
                baseline_upper_reason=comparison["baseline"].get("upper_completion_reason"),
                diagnostic_only=True, physical_metric_verified=False))
        observations.append(dict(image_file=str(path), image_sha256=inputs[str(path)],
                                 decoded_pixel_sha256=pixel_sha, comparison=comparison,
                                 range_comparisons=result_rows))
        # Controlled bbox sensitivity, NOT new YOLO detections or motion images.
        base_obs = comparison["baseline"]
        if base_obs.get("completion_reason") == "completed_point_outside_original_bbox":
            anchor = base_obs["contexts"][-1]["observation"]["point"]
            if anchor is not None:
                for offset in (-1.1, -.75, -.5, -.25, 0., .25):
                    jitter_box = dict(boxes[0], y2=anchor[1]+offset)
                    simulated = compare_boundary_observations(pixels, jitter_box, camera)
                    for policy in POLICIES:
                        item = simulated["comparisons"][policy]
                        point = item["observation"]["point"]
                        jitter.append(dict(session=old["session"], frame=old["frame"], policy=policy,
                            synthetic_bbox_y2_offset_from_observed_point_px=offset,
                            synthetic_bbox_y2=jitter_box["y2"], baseline_point_available=simulated["baseline"]["point"] is not None,
                            policy_point_available=point is not None, changed=item["changed"],
                            observed_point_preserved=point == anchor if point is not None else None,
                            new_yolo_prediction=False, original_image_pixels_unchanged=True))
        if digest(path) != inputs[str(path)] or hashlib.sha256(pixels.tobytes()).hexdigest() != pixel_sha:
            raise ValueError("input file or decoded pixels changed")
    for path, sha in inputs.items():
        if digest(Path(path)) != sha:
            raise ValueError("input changed during comparison")
    source_paths = [Path(__file__), ROOT/"src/cone_bbox_boundary_shadow.py",
                    ROOT/"tests/test_cone_bbox_boundary_shadow.py"]
    summary = dict(schema="native_bbox_boundary_comparison_v1", native_images=len(originals),
        input_sha256=inputs, source_sha256={str(p): digest(p) for p in source_paths},
        opencv_version=cv2.__version__, numpy_version=np.__version__,
        baseline_numeric_images=sum(row["distance_available"] for row in originals),
        policies={p: dict(numeric_images=sum(r["candidate_available"] for r in metrics if r["policy"] == p),
                          changed_observations=sum(r["observation_changed"] for r in metrics if r["policy"] == p))
                  for p in POLICIES},
        controlled_bbox_jitter=dict(native_source_images=len({(r["session"], r["frame"]) for r in jitter}),
            synthetic_bbox_variants=len(jitter)//len(POLICIES),
            policies={p: dict(baseline_points=sum(r["baseline_point_available"] for r in jitter if r["policy"] == p),
                policy_points=sum(r["policy_point_available"] for r in jitter if r["policy"] == p),
                added_points=sum(r["changed"] for r in jitter if r["policy"] == p),
                changed_observed_point_count=sum(r["observed_point_preserved"] is False for r in jitter if r["policy"] == p))
                for p in POLICIES}, actual_new_detections=False),
        baseline_reproduced_images=len(originals), existing_positive_ranges_preserved=True,
        all_input_pixels_unchanged=True, current_motion_pixels_available=False,
        actual_new_yolo_inference=False, actual_vehicle_motion_trial=False,
        actual_negative_image_labels_available=False, physical_accuracy_improvement_verified=False,
        live_policy_changed=False, tests_reexecuted_by_this_script=False)
    output.mkdir(parents=True, exist_ok=False)
    for name, value in (("summary.json", summary), ("observations.json", observations)):
        with (output/name).open("x") as stream:
            json.dump(value, stream, indent=2, allow_nan=False)
            stream.write("\n")
    with (output/"metrics.csv").open("x", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(metrics[0]))
        writer.writeheader()
        writer.writerows(metrics)
    if jitter:
        with (output/"controlled_bbox_jitter.csv").open("x", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(jitter[0]))
            writer.writeheader()
            writer.writerows(jitter)
    print(json.dumps({k: v for k, v in summary.items() if not k.endswith("sha256")}, indent=2))


if __name__ == "__main__":
    main()
