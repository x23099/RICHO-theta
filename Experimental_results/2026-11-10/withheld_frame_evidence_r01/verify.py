"""実ローカルpipe＋保存枠で保存ONを検証。CUDA/カメラ/ROS/RTCは未起動。"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT/"src"))


def cached_worker(manifest):
    import cone_distance_worker
    from driver_motion_process import main
    spec = json.loads(manifest.read_text())
    class CachedPredictor:
        inference_source = "cached_YOLO_boxes_NOT_new_inference_NOT_live_GPU"
        def __init__(self, *args):
            self.weights_sha256 = "synthetic_cached_NOT_live_weights"
            self.gpu = dict(name="cached predictor NOT CUDA")
        def __call__(self, frame):
            sha = hashlib.sha256(frame.image.tobytes()).hexdigest()
            return spec["boxes_by_pixel_sha"][sha]
    # Only this explicit verifier mode substitutes the predictor. The actual
    # worker main, signal handler, recorder, pipe and geometry remain in use.
    cone_distance_worker.YoloConePredictor = CachedPredictor
    return main(["--weights", str(manifest), "--profile", spec["profile"],
        "--output-dir", spec["output_dir"], "--experimental-rigid-mount", "--target-roi", "270", "0", "350", "720",
        "--withheld-evidence-dir", spec["evidence_dir"], "--withheld-evidence-max-frames", "10",
        "--withheld-evidence-max-mib", "32", "--withheld-evidence-interval-sec", ".1"])


def wait_for(predicate, bridge, timeout=5.):
    deadline = time.monotonic()+timeout
    while not predicate():
        if bridge.error:
            raise RuntimeError(bridge.error)
        if time.monotonic() >= deadline:
            raise RuntimeError("bounded offline verifier wait expired")
        time.sleep(.005)


def verify(output, evidence_dir):
    import cv2
    from cone_distance_core import digest
    from driver_motion_bridge import DriverMotionBridge
    from driver_motion_protocol import PROFILE
    from driver_withheld_evidence import evidence_path
    from verify_driver_withheld_evidence import verify as verify_pairs
    if output.exists():
        raise ValueError("new output required")
    evidence_dir = evidence_path(evidence_dir)
    prior = ROOT/"Experimental_results/2026-11-09/cone_motion_evaluation_r01"
    provenance_path = prior/"verification_r02/input_provenance.json"
    source_path = prior/"verification_r02/cached_replay.jsonl"
    profile = prior/"prepared_r01/motion_profile_r01.json"
    provenance = json.loads(provenance_path.read_text())
    paths = {Path(p).name: Path(p) for p in provenance if p.endswith(".png")}
    old_rows = [json.loads(line) for line in source_path.read_text().splitlines()]
    inputs = {str(p): digest(p) for p in (provenance_path, source_path, profile)}
    boxes_by_sha, jobs = {}, []
    for old in old_rows:
        path = paths[f"decoded_{old['session']}_f{old['frame']:06d}.png"]
        inputs[str(path)] = digest(path)
        if inputs[str(path)] != provenance[str(path)]:
            raise ValueError("historical PNG changed")
        pixels = cv2.imread(str(path))
        if pixels is None or pixels.shape != (720, 1280, 3):
            raise ValueError("native original PNG required")
        boxes_by_sha[hashlib.sha256(pixels.tobytes()).hexdigest()] = old["selected_detector_boxes"]
        jobs.append((path, old))
    output.mkdir(parents=True, exist_ok=False)
    manifest = output/"cached_predictor_manifest.json"
    manifest.write_text(json.dumps(dict(profile=str(profile), output_dir=str(output/"pipe_replay"),
        evidence_dir=str(evidence_dir), boxes_by_pixel_sha=boxes_by_sha), indent=2)+"\n")
    bridge = DriverMotionBridge([sys.executable, "-u", str(Path(__file__).resolve()),
        "--cached-worker", "--manifest", str(manifest)], output/"pipe_replay", evidence_dir=evidence_dir)
    results = []
    try:
        bridge.start()
        wait_for(lambda: bridge.ready.is_set(), bridge)
        previous, sequence, last_source = None, 0, 0.
        for path, old in jobs:
            if old["session"] != previous:
                bridge.begin(uuid.uuid4().hex, dict(PROFILE))
                previous, sequence = old["session"], 0
            sequence += 1
            pixels = cv2.imread(str(path))
            before = hashlib.sha256(pixels.tobytes()).hexdigest()
            pixels.flags.writeable = False
            wait_for(lambda: time.monotonic()-last_source >= .12, bridge)
            last_source = time.monotonic()
            count = bridge.returned
            if not bridge.publish(bridge.session, pixels, sequence/30., last_source):
                raise ValueError("offline publish failed")
            wait_for(lambda: bridge.returned > count, bridge)
            snapshot = bridge.snapshot()
            value = snapshot.get("result")
            if value is None or any(value[k] != old[k] for k in ("distance_available", "horizontal_camera_foot_range_m", "reason")):
                raise ValueError("evidence option changed baseline result")
            if hashlib.sha256(pixels.tobytes()).hexdigest() != before:
                raise ValueError("source pixels changed")
            results.append(dict(original_session=old["session"], original_frame=old["frame"],
                offline_session=value["session"], offline_frame=value["frame"], baseline_equal=True,
                distance_available=value["distance_available"], reason=value["reason"]))
            if value["reason"] == "colour_contour_reaches_roi_edge":
                expected = f"decoded_{value['session']}_f{value['frame']:06d}.json"
                wait_for(lambda: (evidence_dir/expected).is_file(), bridge)
    finally:
        shutdown = bridge.close()
    if shutdown["worker_error"] or not shutdown["child_stopped"] or not shutdown["io_thread_stopped"]:
        raise ValueError("child or pipe failed to close")
    pairs = verify_pairs(evidence_dir, output/"pipe_replay/motion_distance_frames.jsonl")
    expected_count = sum(r["reason"] == "colour_contour_reaches_roi_edge" for r in results)
    if pairs["verified_pairs"] != expected_count or not pairs["capture_shutdown_complete"]:
        raise ValueError("expected evidence pairs or graceful shutdown incomplete")
    for path, sha in inputs.items():
        if digest(Path(path)) != sha:
            raise ValueError("original input changed")
    sources = [Path(__file__), *[ROOT/"src"/name for name in ("driver_withheld_evidence.py",
        "driver_motion_process.py", "driver_motion_bridge.py", "verify_driver_withheld_evidence.py")]]
    summary = dict(schema="withheld_evidence_offline_verification_v1", baseline_equal_images=len(results),
        numeric_images=sum(r["distance_available"] for r in results), evidence_pair_verification=pairs,
        bridge_shutdown=shutdown, input_sha256=inputs, source_sha256={str(p): digest(p) for p in sources},
        actual_camera=False, actual_cuda_inference=False, actual_vehicle_motion_trial=False,
        actual_live_latency_measured=False, physical_metric_verified=False,
        evidence_images_are_historical_decoded_frames_NOT_new_capture=True)
    (output/"summary.json").write_text(json.dumps(summary, indent=2)+"\n")
    (output/"replay_identity.json").write_text(json.dumps(results, indent=2)+"\n")
    print(json.dumps({k: v for k, v in summary.items() if not k.endswith("sha256")}, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--evidence-dir", type=Path)
    parser.add_argument("--cached-worker", action="store_true")
    parser.add_argument("--manifest", type=Path)
    args = parser.parse_args()
    if args.cached_worker:
        if args.manifest is None:
            raise ValueError("explicit cached manifest required")
        return cached_worker(args.manifest)
    if args.output_dir is None or args.evidence_dir is None:
        raise ValueError("explicit new output/evidence directories required")
    verify(args.output_dir.resolve(), args.evidence_dir)


if __name__ == "__main__":
    raise SystemExit(main())
