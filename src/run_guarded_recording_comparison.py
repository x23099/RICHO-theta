"""Post-recording comparison ONLY. No UI, IPC, camera, ROS, model or control.

Can wait for an existing evidence writer to finish, but never compares live
frames. Reads committed native evidence and writes a separate bounded JSONL.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import stat
import time

from verify_driver_withheld_evidence import parse_json, read_regular, verify

MAX_SOURCE = 512 * 1024 * 1024
MAX_OUTPUT = 2 * 1024 * 1024
FALSE_FLAGS = dict(physical_metric_verified=False, floor_contact_verified=False,
                   controlling_distance=False, usable_for_ffb=False, published_to_ros=False)


def hash_regular(path, maximum):
    """Bounded streaming hash; reject replacement/truncation and special files."""
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or not 0 <= before.st_size <= maximum:
            raise ValueError("bounded regular input required")
        h, count = hashlib.sha256(), 0
        while True:
            chunk = stream.read(64 * 1024)
            if not chunk:break
            count += len(chunk)
            if count > maximum:raise ValueError("input exceeded size limit")
            h.update(chunk)
        after = os.fstat(stream.fileno())
    current = os.stat(path, follow_symlinks=False)
    identity = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns)
    if identity(before) != identity(after) or identity(after) != identity(current) or count != before.st_size:
        raise ValueError("input changed while reading")
    return h.hexdigest()


def wait_for_writer(evidence_dir, timeout_sec, poll_sec, *, stop=None, clock=time.monotonic):
    if (type(timeout_sec) not in (int, float) or not math.isfinite(timeout_sec) or not 0 <= timeout_sec <= 3600
            or type(poll_sec) not in (int, float) or not math.isfinite(poll_sec) or not .1 <= poll_sec <= 5):
        raise ValueError("wait must be 0..3600 sec and poll .1..5 sec")
    deadline = clock() + timeout_sec
    while True:
        if stop is not None and stop.is_set():raise InterruptedError("comparison wait cancelled")
        try:
            status = parse_json(read_regular(Path(evidence_dir) / "evidence_status.json", 16384))
        except FileNotFoundError:
            status = None
        if status is not None and status.get("writer_done") is True:
            if status.get("shutdown_complete") is not True:
                raise ValueError("evidence writer finished incompletely")
            return
        remaining = deadline - clock()
        if remaining <= 0:raise TimeoutError("evidence writer not complete; stop recording first or use --wait-sec")
        delay = min(poll_sec, remaining)
        if stop is None:time.sleep(delay)
        else:stop.wait(delay)


def _status(directory, payload):
    data = (json.dumps(payload, indent=2, allow_nan=False) + "\n").encode()
    temporary = directory / "comparison_summary.json.part"
    with temporary.open("xb") as stream:stream.write(data)
    os.replace(temporary, directory / "comparison_summary.json")


def compare_recording(input_dir, evidence_dir, reference_path, output_dir, *, config=None,
                      wait_sec=0., poll_sec=.25, stop=None):
    source, evidence, output = (Path(p).resolve() for p in (input_dir, evidence_dir, output_dir))
    reference_path = Path(reference_path).absolute()  # Keep final symlink visible to O_NOFOLLOW.
    if output.exists() or any(output == p or p in output.parents for p in (source, evidence)):
        raise ValueError("new output outside source/evidence directories required")
    output.mkdir(parents=True, exist_ok=False)
    info = dict(schema="guarded_recording_comparison_job_v1", state="waiting_for_closed_evidence",
        result_kind="post_recording_recalculation_NOT_live_display", rows_committed=0,
        inputs_modified=False, main_display_modified=False, camera_or_model_started=False,
        input_dir=str(source), evidence_dir=str(evidence), **FALSE_FLAGS)
    try:
        _status(output, info)
        wait_for_writer(evidence, wait_sec, poll_sec, stop=stop)
        from cone_distance_core import DEFAULT_CONFIG, load_config
        from cone_guarded_lower_edge_shadow import compare_guarded_lower_edge
        from cone_motion_range import MotionRangeEngine, load_motion_profile
        from cone_self_body_shadow import checked_reference
        from theta_rtc_frames import NativeFrame
        import cv2
        import numpy as np
        config = Path(DEFAULT_CONFIG if config is None else config).absolute()
        paths = {source / "motion_distance_frames.jsonl": MAX_SOURCE,
            source / "motion_profile_used.json": 256 * 1024,
            source / "motion_engine_summary.json": 256 * 1024,
            evidence / "evidence_index.jsonl": 256 * 1024,
            evidence / "evidence_status.json": 16384, reference_path: 32768, config: 512 * 1024}
        hashes = {str(p): hash_regular(p, cap) for p, cap in paths.items()}
        validation = verify(evidence, source / "motion_distance_frames.jsonl")
        if not validation["capture_shutdown_complete"] or validation["verified_pairs"] == 0:
            raise ValueError("nonempty complete verified evidence required")
        index = [parse_json(line) for line in read_regular(evidence / "evidence_index.jsonl", 256 * 1024).splitlines()]
        ref = checked_reference(parse_json(read_regular(reference_path, 32768)))
        matches = [r for r in index if r["session"] == ref["session"] and r["frame"] == ref["source_frame"]
                   and r["png_sha256"] == ref["source_png_sha256"]]
        if len(matches) != 1:
            raise ValueError("reference must match an indexed source-verified PNG in this recording; no rebinding")
        settings, camera, _, _ = load_config(config)
        profile, profile_sha = load_motion_profile(source / "motion_profile_used.json", settings)
        engine_meta = parse_json(read_regular(source / "motion_engine_summary.json", 256 * 1024))
        if (engine_meta.get("profile_sha256") != profile_sha
                or engine_meta.get("config_sha256") != hashes[str(config)]
                or engine_meta.get("metric") != "horizontal_camera_foot_range_m_NOT_base_link_or_contact"
                or any(engine_meta.get(k) is not False for k in ("physical_metric_verified", "usable_for_ffb", "published_to_ros"))):
            raise ValueError("source engine profile/config/metric mismatch")
        info.update(state="validating_and_comparing", reference_scope_verified=True,
                    profile_sha256=profile_sha, reference_session=ref["session"], reference_frame=ref["source_frame"])
        _status(output, info)
        records = []
        for item in index:
            png_path, meta_path = evidence / item["image_file"], evidence / item["sidecar_file"]
            paths[png_path] = 1280 * 720 * 3 + 65536
            paths[meta_path] = 1024 * 1024 + 16384
            png = read_regular(png_path, paths[png_path]);meta_bytes = read_regular(meta_path, paths[meta_path])
            if hashlib.sha256(png).hexdigest() != item["png_sha256"] or hashlib.sha256(meta_bytes).hexdigest() != item["sidecar_sha256"]:
                raise ValueError("verified evidence changed before comparison")
            hashes[str(png_path)] = item["png_sha256"];hashes[str(meta_path)] = item["sidecar_sha256"]
            meta = parse_json(meta_bytes);old = meta["measurement"]
            if old.get("profile_sha256") != profile_sha:
                raise ValueError("frame profile differs from source engine")
            row = dict(schema="guarded_recording_comparison_frame_v1", session=old["session"], frame=old["frame"],
                source_time_sec=old["source_time_sec"], source_log_line_sha256=item["source_log_line_sha256"],
                png_sha256=item["png_sha256"], decoded_bgr_sha256=meta["decoded_bgr_sha256"],
                original_distance_available=old["distance_available"], original_range_m=old["horizontal_camera_foot_range_m"],
                original_reason=old["reason"], comparison_distance_available=False, comparison_range_m=None,
                comparison_support_pixel=None, baseline_reproduced=False, reference_scope_verified=False,
                reference_frame=ref["source_frame"], reference_used_posthoc=old["frame"] < ref["source_frame"],
                result_kind=info["result_kind"], source_log_verified=True, **FALSE_FLAGS)
            if old["session"] != ref["session"]:
                row["reason"] = "withheld_reference_session_mismatch"
            else:
                image = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_COLOR)
                if image is None or image.shape != (720, 1280, 3) or hashlib.sha256(image.tobytes()).hexdigest() != meta["decoded_bgr_sha256"]:
                    raise ValueError("native pixel mismatch")
                image.flags.writeable = False
                boxes = old["selected_detector_boxes"]
                if len(boxes) != 1:raise ValueError("one saved selected detector box required")
                comparison = compare_guarded_lower_edge(image, boxes[0], camera, ref,
                    session=old["session"], reference_matches=True)
                if comparison["baseline"] != old.get("support_observation"):
                    raise ValueError("source baseline observation cannot be reproduced")
                values = {}
                for name, obs in (("baseline", comparison["baseline"]), ("proposal", comparison["proposed_observation"])):
                    engine = MotionRangeEngine(settings, camera, profile, profile_sha, acknowledged=True,
                        target_roi=old.get("target_roi_native_xyxy"), observer=lambda *a, v=obs: v)
                    # Explicit synthetic freshness for post-recording geometry only.
                    values[name] = engine.measure(NativeFrame(old["session"], old["frame"], meta["media_time_sec"], 1., image), boxes, 1.01)
                if any(values["baseline"][k] != old[k] for k in ("distance_available", "reason",
                        "horizontal_camera_foot_range_m", "support_pixel", "models")):
                    raise ValueError("source baseline metric cannot be reproduced")
                value = values["proposal"]
                row.update(baseline_reproduced=True, reference_scope_verified=True,
                    comparison_distance_available=value["distance_available"],
                    comparison_range_m=value["horizontal_camera_foot_range_m"],
                    comparison_support_pixel=value["support_pixel"], reason=value["reason"],
                    body_review_reason=comparison["proposed_body_review"]["reason"],
                    lower_half_pixel_eligible=comparison["lower_half_pixel_eligible"])
                if any(value[k] is not False for k in FALSE_FLAGS):raise ValueError("unexpected authority")
                if hashlib.sha256(image.tobytes()).hexdigest() != meta["decoded_bgr_sha256"]:
                    raise ValueError("comparison modified input pixels")
            records.append(row)
        if any(hash_regular(p, cap) != hashes[str(p)] for p, cap in paths.items()):
            raise ValueError("input changed during comparison")
        lines = []
        for row in records:
            line = json.dumps(row, allow_nan=False) + "\n"
            if len(line.encode()) > 16384:raise ValueError("comparison row exceeds limit")
            lines.append(line)
        data = "".join(lines).encode()
        if len(data) > MAX_OUTPUT:raise ValueError("comparison log exceeds limit")
        temporary, final = output / "comparison_frames.jsonl.part", output / "comparison_frames.jsonl"
        with temporary.open("xb") as stream:stream.write(data)
        os.link(temporary, final);temporary.unlink()  # Only our new temporary hardlink.
        info.update(state="complete", rows_committed=len(records),
            numeric_comparison_rows=sum(r["comparison_distance_available"] for r in records),
            baseline_reproduced_rows=sum(r["baseline_reproduced"] for r in records),
            comparison_log_sha256=hashlib.sha256(data).hexdigest(), input_sha256=hashes,
            source_sha256={str(p): hash_regular(p, 128 * 1024) for p in
                [Path(__file__).resolve(), *[Path(__file__).with_name(name) for name in (
                    "cone_guarded_lower_edge_shadow.py", "cone_bbox_boundary_shadow.py", "cone_self_body_shadow.py",
                    "cone_motion_range.py", "cone_upper_support_candidate.py", "cone_support_completion_candidate.py",
                    "verify_driver_withheld_evidence.py")]]},
            evidence_verification=validation, images_written=False)
        _status(output, info)
        return info
    except BaseException as error:
        info.update(state="failed", rows_committed=0, error=f"{type(error).__name__}: {error}"[:1000])
        try:_status(output, info)
        except Exception:pass  # Keep the original exception; never touch acquisition.
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--wait-sec", type=float, default=0., help="wait up to 3600 seconds for writer completion, NOT live comparison")
    parser.add_argument("--poll-sec", type=float, default=.25)
    args = parser.parse_args(argv)
    try:
        result = compare_recording(args.input_dir, args.evidence_dir, args.reference, args.output_dir,
            config=args.config, wait_sec=args.wait_sec, poll_sec=args.poll_sec)
    except (Exception, KeyboardInterrupt) as error:
        print(f"[ERROR] comparison not complete: {type(error).__name__}: {error}")
        return 1
    print(f"Comparison ONLY: {result['rows_committed']} rows, {result['numeric_comparison_rows']} numeric; main display unchanged.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
