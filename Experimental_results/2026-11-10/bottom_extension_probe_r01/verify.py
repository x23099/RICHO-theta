"""既存10画像と下側拡張の合成反例を評価。実機／モデルは起動しない。"""
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
from cone_distance_core import digest, load_config
from cone_motion_range import MotionRangeEngine, load_motion_profile
from theta_rtc_frames import NativeFrame
from probe import probe_bottom_extension


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    output = args.output_dir.resolve()
    if output.exists():
        raise ValueError("new output directory required")
    prior_dir = ROOT/"Experimental_results/2026-11-10/bbox_boundary_native_comparison_r01/results_r02"
    records_path = prior_dir/"observations.json"
    records = json.loads(records_path.read_text())
    previous_summary = json.loads((prior_dir/"summary.json").read_text())
    inputs = dict(previous_summary["input_sha256"])
    inputs[str(records_path)] = digest(records_path)
    for name, sha in inputs.items():
        if digest(Path(name)) != sha:
            raise ValueError("changed historical input: " + name)
    provenance = json.loads((ROOT/"Experimental_results/2026-11-09/cone_motion_evaluation_r01/verification_r02/input_provenance.json").read_text())
    for name in ("cone_distance_core.py", "cone_motion_range.py", "cone_upper_support_candidate.py",
                 "cone_support_completion_candidate.py", "angular_fisheye_geometry.py"):
        path = ROOT/"src"/name
        if digest(path) != provenance[str(path)]:
            raise ValueError("existing baseline source changed")
        inputs[str(path)] = digest(path)
    settings, camera, _, _ = load_config()
    profile, profile_sha = load_motion_profile(
        ROOT/"Experimental_results/2026-11-09/cone_motion_evaluation_r01/prepared_r01/motion_profile_r01.json", settings)
    metrics, probes = [], []
    for record in records:
        path = Path(record["image_file"])
        pixels = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if pixels is None or pixels.shape != (720, 1280, 3):
            raise ValueError("original native pixels required")
        pixel_sha = hashlib.sha256(pixels.tobytes()).hexdigest()
        if pixel_sha != record["decoded_pixel_sha256"]:
            raise ValueError("decoded pixels differ from previous verification")
        pixels.flags.writeable = False
        old = record["range_comparisons"]["baseline"]
        boxes = old["selected_detector_boxes"]
        result = probe_bottom_extension(pixels, boxes[0], camera)
        computed = {}
        for name in ("baseline", "guarded_observation"):
            observation = result[name]
            engine = MotionRangeEngine(settings, camera, profile, profile_sha, acknowledged=True,
                target_roi=(270, 0, 350, 720), observer=lambda *a, value=observation: copy.deepcopy(value))
            computed[name] = engine.measure(NativeFrame(old["session"], old["frame"], 1., 1., pixels), boxes, 1.01)
        for key in ("distance_available", "reason", "horizontal_camera_foot_range_m"):
            if computed["baseline"][key] != old[key]:
                raise ValueError("baseline mismatch")
        if old["distance_available"] and any(computed["guarded_observation"][key] != old[key]
                for key in ("distance_available", "reason", "horizontal_camera_foot_range_m", "support_pixel", "models")):
            raise ValueError("existing numeric result changed")
        metrics.append(dict(session=old["session"], frame=old["frame"],
            baseline_available=old["distance_available"], guarded_available=computed["guarded_observation"]["distance_available"],
            baseline_m=old["horizontal_camera_foot_range_m"], guarded_m=computed["guarded_observation"]["horizontal_camera_foot_range_m"],
            closure_only_point_NOT_safe=result["closure_only_point_NOT_safe"],
            guarded_candidate=result["guarded_candidate"], probe_reason=result["reason"]))
        probes.append(dict(image_file=str(path), probe=result))
        if hashlib.sha256(pixels.tobytes()).hexdigest() != pixel_sha:
            raise ValueError("pixels modified")

    synthetic = []
    for label in ("clipped_triangle", "finite_connected_tail", "peripheral_tail", "long_connected_tail"):
        image = np.zeros((720, 1280, 3), np.uint8)
        cv2.fillPoly(image, [np.array([[320, 310], [295, 400], [345, 400]], np.int32)], (0, 0, 255))
        box = dict(x1=290., y1=305., x2=350., y2=395., confidence=.95, class_id=0)
        if label == "finite_connected_tail":
            cv2.rectangle(image, (310, 397), (330, 408), (0, 0, 255), -1)
        elif label == "peripheral_tail":
            cv2.rectangle(image, (296, 398), (298, 414), (0, 0, 255), -1)
            box["y2"] = 405.
        elif label == "long_connected_tail":
            cv2.rectangle(image, (310, 397), (330, 480), (0, 0, 255), -1)
        result = probe_bottom_extension(image, box, camera)
        synthetic.append(dict(case=label, drawn_triangle_base_y_NOT_real_ground_truth=400,
            closure_only_point_NOT_safe=result["closure_only_point_NOT_safe"],
            guarded_candidate=result["guarded_candidate"], reason=result["reason"], synthetic=True))
    expected = {"clipped_triangle": ([320, 400], False), "finite_connected_tail": ([320, 408], False),
                "peripheral_tail": ([320, 400], True), "long_connected_tail": (None, False)}
    for row in synthetic:
        if (row["closure_only_point_NOT_safe"], row["guarded_candidate"]) != expected[row["case"]]:
            raise ValueError("synthetic counterexample result changed")

    for path, sha in inputs.items():
        if digest(Path(path)) != sha:
            raise ValueError("input changed during analysis")
    output.mkdir(parents=True, exist_ok=False)
    summary = dict(schema="bottom_extension_probe_verification_v1", native_images=len(records),
        baseline_numeric=sum(r["baseline_available"] for r in metrics),
        guarded_numeric=sum(r["guarded_available"] for r in metrics),
        native_new_guarded_candidates=sum(r["guarded_candidate"] for r in metrics),
        native_closure_only_candidates=sum(r["closure_only_point_NOT_safe"] is not None for r in metrics),
        synthetic_counterexamples=synthetic, existing_positive_values_preserved=True,
        all_input_images_unchanged=True, current_motion_pixels_available=False,
        actual_negative_image_labels_available=False, physical_accuracy_improvement_verified=False,
        live_policy_changed=False, input_sha256=inputs,
        source_sha256={str(p): digest(p) for p in (Path(__file__), Path(__file__).with_name("probe.py"),
            ROOT/"tests/test_bottom_extension_probe.py")})
    for name, value in (("summary.json", summary), ("observations.json", probes)):
        with (output/name).open("x") as stream:
            json.dump(value, stream, indent=2, allow_nan=False)
            stream.write("\n")
    with (output/"metrics.csv").open("x", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(metrics[0]))
        writer.writeheader()
        writer.writerows(metrics)
    print(json.dumps({k: v for k, v in summary.items() if not k.endswith("sha256")}, indent=2))


if __name__ == "__main__":
    main()
