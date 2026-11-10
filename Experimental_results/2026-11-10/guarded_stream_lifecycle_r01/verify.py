"""Run lifecycle tests and replay saved samples in their ORIGINAL log order.

The replay clock uses original receiver/completion times, not today's clock.
Only eight frames have pixels; other records admit identity/time ONLY.
No new inference, actual realtime scheduling, device or control operation.
"""
import argparse
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import unittest

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'src'))
from cone_distance_core import load_config
from cone_guarded_stream_comparison import GuardedStreamComparison
from cone_motion_range import load_motion_profile
from run_guarded_recording_comparison import hash_regular
from theta_rtc_frames import NativeFrame
from verify_driver_withheld_evidence import verify, read_regular, parse_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    if args.output_dir.exists():
        raise ValueError('new output directory required')
    expected = json.loads((ROOT / ('Experimental_results/2026-11-10/'
        'guarded_comparison_log_r01/recorded_run_r01/comparison_summary.json')).read_bytes())
    before = {}
    for name, digest in {**expected['input_sha256'], **expected['source_sha256']}.items():
        path = Path(name)
        if not path.resolve().is_relative_to(ROOT):
            raise ValueError('expected local repository input only')
        actual = hash_regular(path, 512*1024*1024)
        if actual != digest:
            raise ValueError('previously verified dependency/input changed: ' + name)
        before[name] = actual
    test_names = ['test_cone_guarded_stream_comparison', 'test_cone_guarded_lower_edge_shadow',
                  'test_cone_self_body_shadow', 'test_guarded_recording_comparison']
    suite = unittest.TestSuite()
    test_sources = []
    new_test_count = 0
    for name in test_names:
        path = ROOT / 'tests' / (name+'.py')
        spec = importlib.util.spec_from_file_location(name, path)
        module = importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        loaded = unittest.defaultTestLoader.loadTestsFromModule(module)
        if name == 'test_cone_guarded_stream_comparison':
            new_test_count = loaded.countTestCases()
        suite.addTests(loaded)
        test_sources.append(path)
    log = io.StringIO()
    result = unittest.TextTestRunner(stream=log, verbosity=2).run(suite)
    if not result.wasSuccessful():
        print(log.getvalue());raise RuntimeError('lifecycle/related tests failed')
    base = ROOT / 'recordings/2026-11-10/driver_motion_171250_intake_r01'
    source = base / 'driver_motion_live_20261110_171250'
    evidence = base / 'motion_withheld_20261110_171250'
    checked = verify(evidence, source / 'motion_distance_frames.jsonl')
    assert checked['verified_pairs'] == 8 and checked['capture_shutdown_complete']
    index = [parse_json(line) for line in read_regular(evidence/'evidence_index.jsonl', 256*1024).splitlines()]
    samples = {item['frame']: item for item in index}
    ref_path = ROOT / 'Experimental_results/2026-11-10/self_body_boundary_shadow_r01/reference.json'
    ref = parse_json(read_regular(ref_path, 32768))
    settings, camera, _, _ = load_config()
    profile, sha = load_motion_profile(source/'motion_profile_used.json', settings)
    clock = [0.]
    stream = GuardedStreamComparison(settings, camera, profile, sha,
        target_roi=[270, 0, 350, 720], acknowledged=True, clock=lambda: clock[0])
    rows, admissions, rejected = [], 0, []
    with (source/'motion_distance_frames.jsonl').open() as input_log:
        for line in input_log:
            original = json.loads(line)
            clock[0] = original['completed_time_sec']
            try:
                stream.admit(original['session'], original['frame'], original['source_time_sec'])
                admissions += 1
            except ValueError as error:
                rejected.append(dict(frame=original['frame'], reason=str(error)))
                continue
            item = samples.get(original['frame'])
            if item is None:
                continue  # Identity/time only; no invented pixels or distance.
            assert item['session'] == original['session'] == ref['session']
            png = read_regular(evidence/item['image_file'], 3*1280*720+65536)
            assert hashlib.sha256(png).hexdigest() == item['png_sha256']
            image = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_COLOR)
            image.flags.writeable = False
            frame = NativeFrame(original['session'], original['frame'], original['media_time_sec'],
                                original['source_time_sec'], image)
            if frame.sequence == ref['source_frame']:
                stream.pin_reference_frame(frame)
                stream.activate(ref, png)
            original_bytes = json.dumps(original, sort_keys=True)
            row = stream.compare(frame, original['selected_detector_boxes'], original)
            assert original_bytes == json.dumps(original, sort_keys=True)
            assert hashlib.sha256(image.tobytes()).hexdigest() == json.loads(
                read_regular(evidence/item['sidecar_file'], 1024*1024+16384))['decoded_bgr_sha256']
            rows.append(row)
    assert len(rows) == 8
    assert all(not row['comparison_distance_available'] for row in rows[:-1])
    assert rows[-1]['frame'] == 14922 and rows[-1]['baseline_reproduced']
    assert rows[-1]['comparison_range_m'] == 1.142471541888944
    assert rows[-1]['comparison_support_pixel'] == [312, 407]
    assert all(row['reference_used_posthoc'] is False for row in rows)
    stream.close()
    assert stream.poll(ref['session']) is None
    for name, digest in before.items():
        assert hash_regular(Path(name), 512*1024*1024) == digest, name
    relevant = [Path(__file__), ROOT/'src/cone_guarded_stream_comparison.py', *test_sources]
    report = dict(schema='guarded_stream_lifecycle_verification_v1', state='pass',
        new_stream_tests=new_test_count,
        tests_run=result.testsRun, failures=len(result.failures), errors=len(result.errors),
        skipped=len(result.skipped), replay_kind='original_log_order_with_recorded_logical_clock_NOT_live',
        admitted_identity_time_records=admissions, rejected_identity_time_records=rejected,
        image_comparison_rows=len(rows), future_reference_rows_used=0,
        numeric_rows=1, baseline_reproduced_rows=sum(r['baseline_reproduced'] for r in rows),
        unsaved_frames_recomputed=False, realtime_throughput_verified=False,
        gpu_or_device_started=False, live_entry_points_modified=False,
        inputs_modified=False, main_display_modified=False,
        physical_metric_verified=False, usable_for_ffb=False, published_to_ros=False,
        prior_inputs_and_sources_rehashed=before,
        verification_source_sha256={str(path.relative_to(ROOT)): hash_regular(path, 128*1024) for path in relevant})
    args.output_dir.mkdir(parents=True)
    (args.output_dir/'summary.json').write_text(json.dumps(report, indent=2)+'\n')
    (args.output_dir/'tests.log').write_text(log.getvalue())
    (args.output_dir/'sample_comparisons.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))
    print(json.dumps({key: report[key] for key in ('state', 'tests_run', 'image_comparison_rows',
        'admitted_identity_time_records', 'rejected_identity_time_records', 'numeric_rows')}, indent=2))


if __name__ == '__main__':
    main()
