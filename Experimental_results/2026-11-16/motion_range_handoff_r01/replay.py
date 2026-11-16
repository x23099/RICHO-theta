"""Verify offline range transport over the SHA-bound closed run; no ROS/FFB."""
import argparse
from collections import Counter
import csv
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT/'src'))
from driver_motion_handoff import OfflineRangeReceiver, make_range_sample

SOURCE_PLAN = Path('/home/robo25/FFB_feedback_control/FFB_feedback_control/docs/2026-10-21_risk_gradient_ffb_plan.md')
PLAN_SHA = '331dbab8c3879f443f49202334de5517df204820f113f8fab5cb8cfd175088ab'


def sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            digest.update(block)
    return digest.hexdigest()


def require(value, message):
    if not value:
        raise ValueError(message)


def run(args):
    audit_path, intake = args.audit.resolve(), args.intake_dir.resolve()
    raw_output, output = args.raw_output_dir.resolve(), args.output_dir.resolve()
    require(not raw_output.exists() and not output.exists(), 'new raw/output directories required')
    require(ROOT/'recordings' in raw_output.parents, 'handoff samples belong under recordings/')
    audit = json.loads(audit_path.read_bytes())
    require(audit['schema'] == 'body_display_three_distance_closed_audit_v1' and audit['state'] == 'pass',
            'completed closed-run audit required')
    require(sha(SOURCE_PLAN) == PLAN_SHA, 'goal source changed; review updated plan first')
    for name, digest in audit['source_code_sha256'].items():
        require(sha(ROOT/'src'/name) == digest, 'previous live computation source changed: '+name)
    reference_path = intake/'comparison/reference.json'
    require(sha(reference_path) == audit['supplied_files_sha256']['comparison/reference.json']
            == audit['issued_reference_sha256'], 'reference binding mismatch')
    reference = json.loads(reference_path.read_bytes())
    session = audit['session']
    inbox_args = dict(reference_frame=reference['source_frame'],
                      reference_png_sha256=reference['source_png_sha256'], reference_generation=1)
    inbox = OfflineRangeReceiver(session, **inbox_args)
    delays = (.1, .4, .501)
    delayed = {delay: OfflineRangeReceiver(session, **inbox_args) for delay in delays}
    delayed_numeric = Counter()
    reasons, source_reasons = Counter(), Counter()
    totals = Counter()
    points = {p['frame']: p for p in audit['reported_points']}
    matched = []
    raw_output.mkdir(parents=True)
    temporary = raw_output/'handoff_samples.jsonl.part'
    target = raw_output/'handoff_samples.jsonl'
    source_digest = hashlib.sha256()
    with (intake/'primary/motion_bridge_events.jsonl').open('rb') as source, temporary.open('xb') as sink:
        while True:
            line = source.readline(16*1024+1)
            if not line:
                break
            require(len(line) <= 16*1024 and line.endswith(b'\n'), 'bounded complete bridge line required')
            source_digest.update(line)
            event = json.loads(line)
            review = event['display_review']
            now = review['completed_time_sec']
            sample = make_range_sample(event, session=session, now_source_clock_sec=now)
            wire = (json.dumps(sample, allow_nan=False, separators=(',', ':'))+'\n').encode()
            require(len(wire) <= 16*1024, 'bounded wire sample required')
            sink.write(wire)
            restored = json.loads(wire)
            require(restored == sample, 'JSON roundtrip changed source sample')
            decision = inbox.receive(restored, now_source_clock_sec=now)
            expected = event['accepted_current_session_and_age'] and review['display_available']
            require(decision['range_available'] == expected, 'handoff availability differs from accepted display review')
            require(decision['distance_m'] == (review['display_range_m'] if expected else None),
                    'handoff changed number, held an old number or zero-filled withheld')
            if expected:
                require(decision['frame'] == sample['frame'] and decision['source_time_sec'] == sample['source_time_sec'],
                        'consumer lost numeric sample identity/time')
            require(decision['vehicle_xy_m'] is None and decision['object_id'] is None
                    and decision['steering_gradient_available'] is False and decision['usable_for_ffb'] is False,
                    'scalar distance acquired unsupported spatial/FFB authority')
            totals['samples'] += 1
            totals['input_verified'] += sample['input_verified']
            totals['numeric'] += decision['range_available']
            totals['withheld'] += not decision['range_available']
            reasons[decision['reason']] += 1
            source_reasons[review['reason']] += 1
            for delay, delayed_inbox in delayed.items():
                late = delayed_inbox.receive(restored, now_source_clock_sec=now+delay)
                require(not late['range_available'] or decision['range_available'], 'delay rescued an unavailable sample')
                delayed_numeric[delay] += late['range_available']
            if sample['frame'] in points:
                point = points[sample['frame']]
                require(decision['range_available'] and decision['distance_m'] == point['logged_display_range_m'],
                        'known screenshot frame changed across handoff')
                matched.append(dict(frame=sample['frame'], reported_measured_m=point['reported_measured_m'],
                    screenshot_range_m=point['screenshot_range_m'], before_m=review['display_range_m'],
                    after_m=decision['distance_m'], same_value=True, distance_clock='recorded_receiver_monotonic'))
    require(source_digest.hexdigest() == audit['supplied_files_sha256']['primary/motion_bridge_events.jsonl'],
            'bridge source SHA mismatch')
    require(totals['samples'] == audit['display_reviews'] and totals['numeric'] == audit['phases']['all']['display_permitted'],
            'closed-run sample count mismatch')
    require(len(matched) == 3 and delayed_numeric[.501] == 0, 'point coverage or stale suppression failed')
    final = inbox.snapshot(now_source_clock_sec=now+.501)
    require(final['range_available'] is False and final['distance_m'] is None, 'last distance survives timeout')
    os.link(temporary, target)
    temporary.unlink()  # only this run's unpublished output; no original evidence is removed
    result = dict(schema='offline_motion_range_handoff_audit_v1', state='pass', session=session,
        counts=dict(totals), received_reason_counts=dict(reasons), source_display_reason_counts=dict(source_reasons),
        matched_screenshot_points=matched,
        delivery_delay_stress=[dict(additional_delay_sec=delay, numeric=delayed_numeric[delay],
            withheld=totals['samples']-delayed_numeric[delay]) for delay in delays],
        final_snapshot_after_timeout=final,
        samples=dict(path=str(target.relative_to(ROOT)), sha256=sha(target)),
        source_bridge_sha256=source_digest.hexdigest(),
        input_and_code_sha256={str(p.relative_to(ROOT)): sha(p) for p in
            (Path(__file__), ROOT/'src/driver_motion_handoff.py', ROOT/'src/driver_motion_protocol.py',
             ROOT/'src/driver_body_display_guard.py', ROOT/'RESEARCH_GOAL.md', audit_path)},
        goal_source=dict(path=str(SOURCE_PLAN), sha256=PLAN_SHA),
        evaluation_clock='recorded review completion; NOT current wall/ROS time',
        current_live_delivery_or_ROS_verified=False, vehicle_coordinates_available=False,
        temporal_target_association_verified=False, steering_gradient_computed=False,
        source_profiles_or_measurements_modified=False, physical_metric_verified=False,
        usable_for_ffb=False, published_to_ros=False, g923_or_vehicle_started=False)
    output.mkdir(parents=True)
    with (output/'audit.json').open('x') as stream:
        json.dump(result, stream, indent=2)
        stream.write('\n')
    with (output/'point_handoff.csv').open('x', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=matched[0])
        writer.writeheader()
        writer.writerows(matched)
    print(json.dumps(dict(state='pass', counts=result['counts'], delay_stress=result['delivery_delay_stress'], points=matched), indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--audit', type=Path, required=True)
    parser.add_argument('--intake-dir', type=Path, required=True)
    parser.add_argument('--raw-output-dir', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    run(parser.parse_args())


if __name__ == '__main__':
    main()
