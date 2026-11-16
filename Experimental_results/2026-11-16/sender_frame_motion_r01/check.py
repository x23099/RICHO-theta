"""Reproducible sender-local candidate and RTP-identity tests; no live IO."""
import argparse
import hashlib
import importlib.metadata
import io
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT/'src'))
sys.path.insert(0, str(ROOT/'tests'))
from test_driver_frame_motion import associator, observation, associate
import test_driver_frame_motion


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(output_dir):
    output_dir = output_dir.resolve()
    if ROOT/'Experimental_results' not in output_dir.parents or output_dir.exists():
        raise ValueError('new result directory under Experimental_results required')
    captured = io.StringIO()
    suite = unittest.defaultTestLoader.loadTestsFromModule(test_driver_frame_motion)
    test = unittest.TextTestRunner(stream=captured, verbosity=2).run(suite)
    if not test.wasSuccessful() or test.skipped:
        raise ValueError('all candidate and actual codec tests must pass: '+captured.getvalue())
    cases = []
    for name, v, w in (('received_stop', 0., 0.), ('forward', .2, -.1), ('reverse', -.2, .1)):
        source = associator()
        observed = observation(10., v=v, w=w)
        source.offer(observed)
        value = associate(source)
        if not value['local_pair_available'] or value['odometry_observation'] != observed:
            raise ValueError('candidate differs from actual input observation')
        cases.append(dict(case=name, synthetic=True, candidate=value))
    future = associator()
    future.offer(observation(10.1))
    value = associate(future, 10.05, now=10.11)
    if value['local_pair_available'] or value['reason'] != 'no_observed_past_callback':
        raise ValueError('future sample adopted')
    cases.append(dict(case='future_only_withheld', synthetic=True, candidate=value))

    from aiortc.rtcrtpreceiver import TimestampMapper
    import aiortc.rtcrtpreceiver as receiver
    import aiortc.rtcrtpsender as sender
    from aiortc.codecs import vpx
    origin = 2**32-1000
    media = [0, 3000, 6000]
    rtp = [(origin+p) % 2**32 for p in media]
    normal, lost = TimestampMapper(), TimestampMapper()
    mapped, lost_mapped = [normal.map(p) for p in rtp], [lost.map(p) for p in rtp[1:]]
    if mapped != media or lost_mapped != [0, 3000]:
        raise ValueError('installed transport rebasing behaviour changed')
    previous = json.loads((ROOT/'Experimental_results/2026-11-16/body_display_range_audit_r01/results_r01/audit.json').read_bytes())
    if not all(sha(ROOT/'src'/name) == digest for name, digest in previous['source_code_sha256'].items()):
        raise ValueError('existing distance/display source changed')
    files = ['src/driver_frame_motion.py', 'src/driver_odometry_observation.py',
        'src/theta_rtc_diagnostic.py', 'src/webrtc_stream.py', 'src/webrtc_receive_ui.py',
        'src/collision_ffb_relay.py', 'src/collision_ffb_publisher.py',
        'tests/test_driver_frame_motion.py', 'tests/test_driver_motion_integration.py',
        str(Path(__file__).resolve().relative_to(ROOT))]
    audit = dict(schema='sender_frame_motion_local_audit_v1', state='pass', synthetic_only=True,
        test_count=test.testsRun, failed=0, skipped=0, example_cases=len(cases),
        old_distance_display_sources_unchanged=len(previous['source_code_sha256']),
        source_sha256={name:sha(ROOT/name) for name in files},
        library_versions={name:importlib.metadata.version(name) for name in ('aiortc', 'av', 'numpy')},
        library_source_sha256={name:sha(Path(module.__file__)) for name, module in
            (('aiortc.rtcrtpreceiver', receiver), ('aiortc.rtcrtpsender', sender), ('aiortc.codecs.vpx', vpx))},
        rtp_rebasing=dict(sender_media_pts=media, synthetic_rtp_origin=origin,
            synthetic_rtp_timestamps=rtp, normal_receiver_pts=mapped,
            first_capture_lost_receiver_pts=lost_mapped,
            first_receiver_pts_zero_does_not_identify_first_sender_capture=True),
        runtime_wiring_changed=False, live_camera_or_ROS_started=False,
        network_started=False, operating_system_clock_changed=False,
        receiver_frame_identity_verified=False, exposure_time_verified=False,
        header_clock_relation_verified=False, source_freshness_verified=False,
        physical_metric_verified=False, usable_for_ffb=False, published_to_ros=False)
    output_dir.mkdir(parents=True, exist_ok=False)
    for name, value in (('audit.json', audit), ('synthetic_candidates.json', cases)):
        with (output_dir/name).open('x') as stream:
            json.dump(value, stream, indent=2, allow_nan=False, ensure_ascii=False)
            stream.write('\n')
    with (output_dir/'tests.txt').open('x') as stream:
        stream.write(captured.getvalue())
    return audit


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    result = run(args.output_dir)
    print(json.dumps(dict(state=result['state'], tests=result['test_count'],
                          output_dir=str(args.output_dir)), ensure_ascii=False))
