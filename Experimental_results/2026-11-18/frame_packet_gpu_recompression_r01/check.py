"""Local preparation audit: real saved-image VP8, synthetic tests, NOT CUDA."""
import argparse
import ast
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SPEC = importlib.util.spec_from_file_location('recompression_probe_audit', HERE/'run.py')
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)


def run(output):
    output = output.resolve()
    if output.exists() or HERE not in output.parents:
        raise ValueError('unused result directory under this experiment required')
    previous_path = ROOT/'Experimental_results/2026-11-18/frame_packet_runtime_r01/results_r02/audit.json'
    previous = json.loads(previous_path.read_bytes())
    unchanged = previous['source_code_sha256'] | previous['unchanged_previous_source_sha256']
    for name, expected in unchanged.items():
        if probe.digest(ROOT/name) != expected:
            raise ValueError('runtime/baseline changed: '+name)
    sources = [ROOT/'recordings/2026-11-16/body_display_full_intake_r02/comparison'/
               'decoded_e52bb32f03d6488ebf37d769f46ec37a_f005186.png']
    evidence = ROOT/'recordings/2026-11-13/guarded_motion_full_intake_r02/logs/evidence'
    sources.extend(evidence/name for name in probe.KNOWN_IMAGES if name.startswith('decoded_24aad'))
    jobs = probe.load_images(sources)
    cases = []
    for sequence, job in enumerate(jobs, 1):
        image, value = probe.packet_roundtrip(job['image'], sequence)
        if image.shape != (720, 1280, 3) or image.flags.writeable:
            raise ValueError('native immutable decoded image required')
        cases.append(dict(source_path=job['path'], png_sha256=job['png_sha256'],
            original_pixel_sha256=job['pixel_sha256'], decoded_pixel_sha256=probe.sha_bytes(image.tobytes()),
            shape=list(image.shape), packet_bytes=value['packet_bytes'],
            packet_sha256=value['packet_sha256'], packet_candidate=value['packet_candidate']))
    probe.assert_originals(jobs)
    tests = ['tests/test_frame_packet_gpu_recompression.py', 'tests/test_driver_frame_packet.py',
        'tests/test_driver_frame_motion.py', 'tests/test_cone_motion_range.py',
        'tests/test_driver_frame_packet_runtime.py', 'tests/test_driver_frame_packet_channel.py']
    command = [sys.executable, '-m', 'pytest', '-q'] + tests
    output.mkdir(parents=True, exist_ok=False)
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=60,
        env=dict(os.environ, OPENBLAS_NUM_THREADS='1', PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'))
    log = result.stdout + result.stderr
    with (output/'tests.txt').open('x') as stream:
        stream.write(log)
    match = re.search(r'(\d+) passed in ([0-9.]+)s', log)
    if result.returncode or match is None or 'skipped' in log:
        raise ValueError('all preparation tests must pass: '+log)
    code = [HERE/'run.py', Path(__file__), ROOT/'tests/test_frame_packet_gpu_recompression.py']
    for path in code:
        ast.parse(path.read_bytes())
    probe.assert_originals(jobs)
    if any(probe.digest(ROOT/name) != expected for name, expected in unchanged.items()):
        raise ValueError('runtime changed during audit')
    audit = dict(schema='packet_GPU_recompression_preparation_audit_v1', state='pass',
        executed_utc=datetime.now(timezone.utc).isoformat(), work_date='2026-11-18',
        command=command, tests_passed=int(match[1]), failed=0, skipped=0, elapsed_sec=float(match[2]),
        source_code_sha256={str(p.relative_to(ROOT)):probe.digest(p) for p in code},
        runtime_source_unchanged_sha256=unchanged, previous_runtime_audit_sha256=probe.digest(previous_path),
        saved_image_real_VP8_codec_cases=cases, saved_images_modified=False, images_written=False,
        detector_in_tests='synthetic_NOT_YOLO_or_CUDA', actual_CUDA_inference=False,
        GPU_accuracy_or_load_verified=False, camera_ROS_network_or_G923_started=False,
        source_freshness_verified=False, physical_metric_verified=False,
        controlling_distance=False, usable_for_ffb=False, published_to_ros=False,
        git_write_performed=False)
    with (output/'audit.json').open('xb') as stream:
        stream.write(probe.json_bytes(audit))
    print(json.dumps(dict(state='pass', tests_passed=int(match[1]), elapsed_sec=float(match[2]),
        real_saved_image_codec_cases=len(cases), actual_CUDA_inference=False), indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    run(parser.parse_args().output_dir)
