"""Offline saved-image original/packet ABBA probe. No camera, ROS or FFB."""
import argparse
from collections import Counter
import copy
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import math
from pathlib import Path
import platform
import resource
import sys
import tarfile
import time

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'src'))

import cv2
import numpy as np
from cone_distance_core import DEFAULT_CONFIG, checked_target_roi, digest, load_config
from cone_fixed_floor_live_load import bounded_regular_bytes
from cone_motion_range import FLAGS, MotionRangeEngine, load_motion_profile
from cone_upper_support_candidate import observe_upper_completion
from driver_frame_motion import SenderFrameMotion
from driver_frame_packet import encode_packet, FramePacketReceiver
from theta_rtc_frames import NativeFrame, native_frame

PROFILE = ROOT / 'Experimental_results/2026-11-09/cone_motion_evaluation_r01/prepared_r01/motion_profile_r01.json'
KNOWN_IMAGES = {
    'decoded_e52bb32f03d6488ebf37d769f46ec37a_f005186.png':
        '7b6e0361b53e52b5e6337f07d0c46719d421b79edb013f43e65d22e25fc0fc89',
    'decoded_24aad0a8d31d46eeb33ef252b0d18475_f028980.png':
        '1d6aae33fefd99a58ddbe6c01d6b2fe02cb37f8961317b0d9a897cb6c6aac74f',
    'decoded_24aad0a8d31d46eeb33ef252b0d18475_f037696.png':
        '17ae1e55225ca083bd58bcac9097f19211fd0abfe52c0163a411f2f51088ae1d',
    'decoded_24aad0a8d31d46eeb33ef252b0d18475_f044793.png':
        'bd6ebf33da1ac1e849a5bb3c277dd2ebc44ec23e8a69e0c0009e10d25d291230',
}
CODE = ('driver_frame_packet.py', 'driver_frame_motion.py', 'driver_odometry_observation.py',
        'driver_motion_handoff.py', 'theta_rtc_frames.py', 'cone_distance_core.py',
        'cone_distance_worker.py', 'run_cone_yolo.py', 'cone_detection_diagnostics.py',
        'cone_motion_range.py', 'cone_upper_support_candidate.py',
        'cone_support_completion_candidate.py', 'cone_support_quality.py',
        'angular_fisheye_geometry.py')
MAX_LOG = 32 * 1024 * 1024


def sha_bytes(data):
    return hashlib.sha256(data).hexdigest()


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True) + '\n').encode()


def describe(values):
    if not values:
        return dict(count=0, minimum=None, median=None, p95=None, maximum=None)
    a = np.asarray(values, dtype=float)
    if not np.isfinite(a).all():
        raise ValueError('nonfinite measurement')
    return dict(count=len(values), minimum=float(a.min()), median=float(np.median(a)),
                p95=float(np.percentile(a, 95)), maximum=float(a.max()))


def load_images(paths):
    if not 1 <= len(paths) <= 4:
        raise ValueError('1..4 explicit previously audited saved images required')
    jobs, seen = [], set()
    for value in paths:
        path = Path(value).absolute()  # Do not hide a final symlink from bounded read.
        expected = KNOWN_IMAGES.get(path.name)
        data = bounded_regular_bytes(path, 4 * 1024 * 1024)
        if expected is None or sha_bytes(data) != expected or expected in seen:
            raise ValueError('unknown/changed/duplicate saved PNG: ' + str(path))
        image = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
        native_frame(image)
        image.flags.writeable = False
        jobs.append(dict(path=str(path), png_sha256=expected, image=image,
                         pixel_sha256=sha_bytes(image.tobytes())))
        seen.add(expected)
    return jobs


def assert_originals(jobs):
    for job in jobs:
        if (sha_bytes(bounded_regular_bytes(job['path'], 4 * 1024 * 1024)) != job['png_sha256']
                or sha_bytes(job['image'].tobytes()) != job['pixel_sha256']
                or job['image'].flags.writeable):
            raise ValueError('original PNG/pixels modified: ' + job['path'])


def packet_roundtrip(image, sequence):
    # This identity/time is an OFFLINE admission fixture, NOT the saved capture.
    # No odometry is offered; local_pair_available stays false.
    source = SenderFrameMotion(sender_id='a' * 32, stream_id='b' * 32, capacity=4,
        max_callback_lag_sec=.1, max_progress_lag_sec=.1, max_capture_wait_sec=.2,
        motion_frame_id='base_footprint')
    candidate = source.associate(capture_sequence=sequence, captured_at_sec=float(sequence),
        associated_at_sec=float(sequence), media_pts=(sequence - 1) * 3000)
    start, cpu = time.perf_counter(), time.process_time()
    wire = encode_packet(image, candidate)
    encoded, encoded_cpu = time.perf_counter(), time.process_time()
    receiver = FramePacketReceiver(sender_id=candidate['sender_id'], stream_id=candidate['stream_id'],
                                  max_receive_age_sec=.2)
    try:
        decoded = receiver.accept(wire, received_at_sec=1.)
    finally:
        receiver.close()
    end, end_cpu = time.perf_counter(), time.process_time()
    if decoded.candidate != candidate or decoded.candidate['local_pair_available']:
        raise ValueError('offline candidate identity changed or motion invented')
    return decoded.image, dict(encode_ms=(encoded-start)*1000, encode_cpu_ms=(encoded_cpu-cpu)*1000,
        decode_validate_copy_ms=(end-encoded)*1000, decode_cpu_ms=(end_cpu-encoded_cpu)*1000,
        packet_bytes=len(wire), packet_sha256=decoded.packet_sha256,
        packet_candidate=decoded.candidate)


def detector_signature(boxes):
    # Keep coordinates/confidence/class/all other fields, omit only replay label.
    return sha_bytes(json_bytes([{k: v for k, v in b.items() if k != 'image'} for b in boxes]))


def measure(job, variant, sequence, engine, predictor, sync=lambda: None, memory=None):
    if variant not in ('original', 'packet'):
        raise ValueError('explicit original or packet required')
    original = job['image']
    if sha_bytes(original.tobytes()) != job['pixel_sha256'] or original.flags.writeable:
        raise ValueError('modified source pixels')
    image, codec = original, dict(encode_ms=0., encode_cpu_ms=0., decode_validate_copy_ms=0.,
                                decode_cpu_ms=0., packet_bytes=None, packet_sha256=None,
                                packet_candidate=None)
    if variant == 'packet':
        image, codec = packet_roundtrip(original, sequence)
    pixel_sha = sha_bytes(image.tobytes())
    # One deliberate synthetic zero-age geometry calculation per offline input.
    # Actual service durations are recorded separately, never certified freshness.
    frame = NativeFrame('c' * 32, sequence, (sequence-1)/30., float(sequence), image)
    sync()
    if memory is not None:
        memory('reset')
    start, cpu = time.perf_counter(), time.process_time()
    boxes = predictor(frame)
    sync()
    inferred, inferred_cpu = time.perf_counter(), time.process_time()
    result = engine.measure(frame, boxes, float(sequence))
    done, done_cpu = time.perf_counter(), time.process_time()
    if any(result.get(k) is not False for k in FLAGS):
        raise ValueError('unexpected authority in offline measurement')
    if sha_bytes(image.tobytes()) != pixel_sha or image.flags.writeable:
        raise ValueError('predictor modified inference pixels')
    if sha_bytes(original.tobytes()) != job['pixel_sha256'] or original.flags.writeable:
        raise ValueError('predictor modified source pixels')
    # Pixel diagnostics excluded from stage timings; decoded image is never saved.
    difference = image.astype(np.int16) - original.astype(np.int16)
    mse = float(np.mean(difference.astype(np.float64) ** 2))
    receiver_ms = codec['decode_validate_copy_ms'] + (done-start)*1000
    return dict(schema='offline_packet_recompression_sample_v1', variant=variant, sequence=sequence,
        source_path=job['path'], source_png_sha256=job['png_sha256'],
        source_pixel_sha256=job['pixel_sha256'], inference_pixel_sha256=pixel_sha,
        geometry_age_basis='synthetic_zero_age_OFFLINE_NOT_live_freshness',
        packet_identity_basis='synthetic_replay_admission_NOT_original_capture',
        saved_image_is_already_received_video=True, raw_detector_boxes=copy.deepcopy(boxes),
        detector_signature=detector_signature(boxes), measurement=result,
        mean_absolute_pixel_difference=float(np.abs(difference).mean()), pixel_mse=mse,
        psnr_db=None if mse == 0 else float(10*math.log10(255**2/mse)),
        predict_sync_ms=(inferred-start)*1000, predict_cpu_ms=(inferred_cpu-cpu)*1000,
        support_geometry_ms=(done-inferred)*1000, support_cpu_ms=(done_cpu-inferred_cpu)*1000,
        receiver_stage_ms=receiver_ms, sender_encode_plus_receiver_stage_ms=codec['encode_ms']+receiver_ms,
        pytorch_memory_bytes=None if memory is None else memory('read'), **codec,
        source_freshness_verified=False, **FLAGS)


def compare_pair(original, packet):
    if (original['variant'] != 'original' or packet['variant'] != 'packet'
            or original['source_png_sha256'] != packet['source_png_sha256']):
        raise ValueError('same original image with exact variants required')
    a, b = original['measurement'], packet['measurement']
    both = a['distance_available'] and b['distance_available']
    delta = b['horizontal_camera_foot_range_m'] - a['horizontal_camera_foot_range_m'] if both else None
    return dict(original_sequence=original['sequence'], packet_sequence=packet['sequence'],
        source_png_sha256=original['source_png_sha256'], both_numeric=both,
        range_delta_m=delta, absolute_range_delta_m=None if delta is None else abs(delta),
        original_numeric_packet_withheld=a['distance_available'] and not b['distance_available'],
        original_withheld_packet_numeric=not a['distance_available'] and b['distance_available'],
        reason_changed=a['reason'] != b['reason'], detector_changed=original['detector_signature'] != packet['detector_signature'],
        support_pixel_changed=a.get('support_pixel') != b.get('support_pixel'),
        support_observation_changed=a.get('support_observation') != b.get('support_observation'),
        original_reason=a['reason'], packet_reason=b['reason'])


def summarize(rows, pairs):
    if not rows or len(rows) != 2*len(pairs):
        raise ValueError('complete measured pairs required')
    groups = {}
    for variant in ('original', 'packet'):
        selected = [r for r in rows if r['variant'] == variant]
        groups[variant] = dict(samples=len(selected), numeric=sum(r['measurement']['distance_available'] for r in selected),
            reasons=dict(Counter(r['measurement']['reason'] for r in selected)),
            receiver_stage_over_100ms=sum(r['receiver_stage_ms'] > 100 for r in selected),
            receiver_stage_over_200ms=sum(r['receiver_stage_ms'] > 200 for r in selected))
        for key in ('encode_ms', 'encode_cpu_ms', 'decode_validate_copy_ms', 'decode_cpu_ms',
                    'predict_sync_ms', 'predict_cpu_ms', 'support_geometry_ms', 'support_cpu_ms',
                    'receiver_stage_ms', 'sender_encode_plus_receiver_stage_ms', 'mean_absolute_pixel_difference'):
            groups[variant][key] = describe([r[key] for r in selected])
        groups[variant]['packet_bytes'] = describe([r['packet_bytes'] for r in selected if r['packet_bytes'] is not None])
        groups[variant]['pytorch_memory_bytes'] = {
            key: describe([r['pytorch_memory_bytes'][key] for r in selected if r['pytorch_memory_bytes'] is not None])
            for key in ('peak_allocated', 'peak_reserved')}
    stability = []
    for source in sorted({r['source_png_sha256'] for r in rows}):
        item = dict(source_png_sha256=source)
        for variant in ('original', 'packet'):
            subset = [r for r in rows if r['variant'] == variant and r['source_png_sha256'] == source]
            item[variant] = dict(detector_signatures=len({r['detector_signature'] for r in subset}),
                metric_signatures=len({json_bytes({key: r['measurement'].get(key) for key in
                    ('distance_available', 'reason', 'support_pixel', 'horizontal_camera_foot_range_m')}) for r in subset}))
        stability.append(item)
    counts = {key: sum(p[key] for p in pairs) for key in ('both_numeric',
        'original_numeric_packet_withheld', 'original_withheld_packet_numeric', 'reason_changed',
        'detector_changed', 'support_pixel_changed', 'support_observation_changed')}
    return dict(groups=groups, paired_samples=len(pairs), pair_counts=counts,
        absolute_range_delta_m=describe([p['absolute_range_delta_m'] for p in pairs if p['both_numeric']]),
        range_delta_m=describe([p['range_delta_m'] for p in pairs if p['both_numeric']]),
        repeat_stability=stability, live_rate_or_deadline_verified=False,
        absolute_ground_truth_accuracy_verified=False, body_display_guard_tested=False,
        actual_network_or_sender_CPU_load_measured=False, GPU_utilization_percent_measured=False,
        GPU_memory_scope='PyTorch allocator peaks, NOT whole GPU memory/utilization',
        **FLAGS)


def benchmark(jobs, predictor, engine_factory, *, repetitions=5, warmup=3,
              sync=lambda: None, memory=None, output=None, timeout_sec=180.):
    if (type(repetitions) is not int or not 1 <= repetitions <= 20
            or type(warmup) is not int or not 1 <= warmup <= 10
            or not 1 <= len(jobs) <= 4 or not 0 < timeout_sec <= 180):
        raise ValueError('bounded jobs/repetitions/warmup/duration required')
    rows, pairs, sequence, used = [], [], 0, 0
    deadline = time.monotonic() + timeout_sec
    stream = None
    if output is not None:
        stream = (Path(output) / 'samples.jsonl').open('xb')
    try:
        for job in jobs:
            engines = {v: engine_factory() for v in ('original', 'packet')}
            for n in range(warmup*2 + repetitions*4):
                if time.monotonic() > deadline:
                    raise TimeoutError('offline benchmark wall-time budget exceeded')
                measured = n >= warmup*2
                position = (n-warmup*2) % 4
                variant = ('original', 'packet', 'packet', 'original')[position] if measured else ('original', 'packet')[n % 2]
                sequence += 1
                row = measure(job, variant, sequence, engines[variant], predictor, sync, memory)
                if not measured:
                    continue
                row.update(cycle=(n-warmup*2)//4, abba_position=position)
                line = json_bytes(row)
                used += len(line)
                if used > MAX_LOG:
                    raise ValueError('sample log exceeds byte limit')
                if stream is not None:
                    stream.write(line)
                    stream.flush()
                rows.append(row)
                if position == 3:
                    a, b, c, d = rows[-4:]
                    pairs.extend((compare_pair(a, b), compare_pair(d, c)))
            assert_originals([job])
    finally:
        if stream is not None:
            stream.close()
    assert_originals(jobs)
    return rows, pairs, summarize(rows, pairs)


def save_summary(output, summary):
    temporary = output / 'summary.json.part'
    with temporary.open('xb') as stream:
        stream.write(json_bytes(summary))
    temporary.replace(output / 'summary.json')  # Only our own new run's status.


def pack_result(output, archive):
    output, archive = Path(output).resolve(), Path(archive).absolute()
    if output == archive or output in archive.parents:
        raise ValueError('archive must be outside result directory')
    if json.loads((output/'summary.json').read_bytes()).get('state') != 'complete':
        raise ValueError('only complete result may be submitted')
    files = sorted(output.rglob('*'))
    if (any(p.is_symlink() for p in files) or sum(p.stat().st_size for p in files if p.is_file()) > 64*1024*1024
            or any(p.suffix.lower() in ('.png', '.jpg', '.pt') for p in files)):
        raise ValueError('bounded results only; images/checkpoints may not be archived')
    with archive.open('xb') as target:
        with tarfile.open(fileobj=target, mode='w:xz') as bundle:
            bundle.add(output, arcname=output.name)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', type=Path, action='append', required=True)
    parser.add_argument('--weights', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--archive', type=Path)
    parser.add_argument('--config', type=Path, default=DEFAULT_CONFIG)
    parser.add_argument('--profile', type=Path, default=PROFILE)
    parser.add_argument('--target-roi', type=int, nargs=4, default=[270, 0, 350, 720])
    parser.add_argument('--device', type=int, default=0)
    parser.add_argument('--repetitions', type=int, default=5)
    parser.add_argument('--warmup', type=int, default=3)
    parser.add_argument('--experimental-rigid-mount', action='store_true')
    args = parser.parse_args(argv)
    output, created = args.output_dir.resolve(), False
    summary = dict(schema='offline_packet_recompression_GPU_audit_v1', state='initializing',
        executed_utc=datetime.now(timezone.utc).isoformat(), work_date='2026-11-18',
        actual_cuda_inference=False, source_images_modified=False, images_written=False,
        source_freshness_verified=False, live_transport_adopted=False, **FLAGS)
    try:
        if not args.experimental_rigid_mount:
            raise ValueError('--experimental-rigid-mount acknowledgement required')
        if (not 1 <= args.repetitions <= 20 or not 1 <= args.warmup <= 10 or args.device < 0):
            raise ValueError('bounded repetitions/warmup and CUDA device required')
        checked_target_roi(args.target_roi)
        jobs = load_images(args.image)
        settings, camera, _, _ = load_config(args.config)
        profile, profile_sha = load_motion_profile(args.profile, settings)
        weights = args.weights.resolve()
        if not weights.is_file() or digest(weights) != settings['weights_sha256']:
            raise ValueError('trusted local checkpoint SHA mismatch')
        input_paths = [Path(j['path']) for j in jobs] + [args.config, args.profile, weights]
        if output.exists() or any(output == p.resolve() or output in p.resolve().parents for p in input_paths):
            raise ValueError('unused output, outside all input paths, required')
        if args.archive is not None and (args.archive.exists() or not args.archive.parent.is_dir()
                or output in args.archive.resolve().parents):
            raise ValueError('unused archive outside output with existing parent required')
        import av
        import torch
        from run_cone_yolo import check_cuda
        gpu = check_cuda(torch, args.device)  # No CPU fallback, no model yet.
        code = {str(Path(__file__).resolve().relative_to(ROOT)): digest(__file__)}
        code.update({'src/'+name: digest(ROOT/'src'/name) for name in CODE})
        inputs = {str(p.resolve()): digest(p) for p in input_paths}
        output.mkdir(parents=True, exist_ok=False)
        created = True
        summary.update(gpu=gpu, runtime=dict(python=sys.version, platform=platform.platform(),
            PyAV=av.__version__, OpenCV=cv2.__version__, torch=str(torch.__version__),
            ultralytics=importlib.metadata.version('ultralytics')),
            source_code_sha256=code, input_sha256=inputs, target_roi_native_xyxy=args.target_roi,
            profile_sha256=profile_sha, config_sha256=digest(args.config),
            original_pngs=[{k:v for k,v in j.items() if k != 'image'} for j in jobs],
            image_count=len(jobs), single_image_preliminary=len(jobs) == 1,
            repetitions=args.repetitions, warmup_calls_excluded=2*args.warmup*len(jobs),
            order='original/packet/packet/original per ABBA cycle',
            original_capture_or_odometry_metadata_reconstructed=False)
        save_summary(output, summary)
        from cone_distance_worker import YoloConePredictor
        predictor = YoloConePredictor(weights, settings, output, args.device)
        def factory():
            return MotionRangeEngine(settings, camera, profile, profile_sha, acknowledged=True,
                target_roi=args.target_roi, observer=observe_upper_completion)
        def sync():
            torch.cuda.synchronize(args.device)
        def memory(action):
            if action == 'reset':
                torch.cuda.reset_peak_memory_stats(args.device)
                return None
            return dict(peak_allocated=torch.cuda.max_memory_allocated(args.device),
                        peak_reserved=torch.cuda.max_memory_reserved(args.device))
        start, cpu = time.perf_counter(), time.process_time()
        rows, pairs, values = benchmark(jobs, predictor, factory, repetitions=args.repetitions,
            warmup=args.warmup, sync=sync, memory=memory, output=output)
        wall, process_cpu = time.perf_counter()-start, time.process_time()-cpu
        if any(digest(p) != sha for p, sha in inputs.items()) or any(digest(ROOT/p) != sha for p, sha in code.items()):
            raise ValueError('input/code changed during probe')
        with (output/'pairs.jsonl').open('xb') as stream:
            for pair in pairs:
                stream.write(json_bytes(pair))
        summary.update(values, state='complete', actual_cuda_inference=True, measured_samples=len(rows),
            probe_wall_sec_including_warmup=wall, probe_process_CPU_sec_including_warmup=process_cpu,
            probe_CPU_core_equivalent_including_warmup=process_cpu/wall,
            process_max_RSS_KiB=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            result_sha256={name: digest(output/name) for name in ('samples.jsonl', 'pairs.jsonl')})
        save_summary(output, summary)
        if args.archive is not None:
            pack_result(output, args.archive)
        print(json.dumps(dict(state='complete', image_count=len(jobs), measured_samples=len(rows),
            paired_samples=len(pairs), absolute_range_delta_m=values['absolute_range_delta_m'],
            pair_counts=values['pair_counts'], output_dir=str(output), archive=str(args.archive) if args.archive else None),
            ensure_ascii=False, indent=2))
        return 0
    except (Exception, KeyboardInterrupt) as error:
        if created:
            summary.update(state='failed', error=f'{type(error).__name__}: {error}'[:2000])
            save_summary(output, summary)
        print(f'[ERROR] offline GPU comparison incomplete: {type(error).__name__}: {error}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
