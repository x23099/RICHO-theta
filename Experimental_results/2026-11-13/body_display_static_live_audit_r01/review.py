"""Closed static body-display run audit; no camera, CUDA, ROS or control."""
import argparse
from collections import Counter
import csv
import hashlib
import importlib.util
import json
from pathlib import Path, PurePosixPath
import struct
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'src'))
from driver_body_display_guard import checked_display_review, CLEAR
from cone_self_body_shadow import checked_reference, compare_self_body
from report_driver_motion_logs import FLAGS, distribution, read_jsonl, summarize
from verify_driver_withheld_evidence import parse_json, read_regular

spec = importlib.util.spec_from_file_location('static_audit_shared',
    ROOT / 'Experimental_results/2026-11-13/guarded_static_live_audit_r02/review.py')
shared = importlib.util.module_from_spec(spec)
spec.loader.exec_module(shared)
require, file_sha = shared.require, shared.file_sha
PIN = 'decoded_e011664e9b994ce1b070439efa875b6a_f000361'
PREFIXES = {'primary': 'Experimental_results/2026-11-13/driver_body_guard_static_r01',
            'comparison': 'recordings/2026-11-13/body_guard_static_r01'}
FILES = {'primary': (*shared.FILES['primary'], 'motion_display_reviews.jsonl'),
         'comparison': ('comparison_frames.jsonl', PIN + '.png', PIN + '.json',
                        'request.json', 'comparison_status.json', 'reference.json')}


def extract_archive(path, target):
    require(not target.exists() and path.stat().st_size <= 128*1024*1024,
            'new target and bounded archive required')
    allowed = {PREFIXES[role]+'/'+name: (role, name)
               for role, names in FILES.items() for name in names}
    directories = {*PREFIXES.values(), PREFIXES['primary']+'/ultralytics_config',
                   PREFIXES['primary']+'/ultralytics_config/matplotlib',
                   PREFIXES['primary']+'/ultralytics_config/Ultralytics'}
    with tarfile.open(path, 'r:xz') as archive:
        members = archive.getmembers()
        require(len(members) <= 40, 'too many archive entries')
        seen, regular, total = set(), {}, 0
        for item in members:
            name = item.name.rstrip('/')
            pure = PurePosixPath(name)
            require(name == str(pure) and not pure.is_absolute() and '..' not in pure.parts
                    and '\\' not in name, 'unsafe archive name')
            require(name not in seen, 'duplicate archive entry')
            seen.add(name)
            if item.isdir():
                require(name in directories, 'unexpected archive directory')
                continue
            require(item.isfile() and name in allowed, 'unexpected file, link or special entry')
            role, relative = allowed[name]
            limit = (128*1024*1024 if relative == 'motion_distance_frames.jsonl' else
                     64*1024*1024 if relative.endswith('.jsonl') else
                     4*1024*1024 if relative.endswith('.png') else 1024*1024)
            total += item.size
            require(0 <= item.size <= limit and total <= 256*1024*1024, 'archive size bound exceeded')
            regular[name] = item
        require(set(regular) == set(allowed), 'missing full-run file')
        target.mkdir(parents=True)
        hashes = {}
        for name, item in regular.items():
            role, relative = allowed[name]
            destination = target / role / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            digest, remaining = hashlib.sha256(), item.size
            with archive.extractfile(item) as source, destination.open('xb') as output:
                while remaining:
                    block = source.read(min(1024*1024, remaining))
                    require(block, 'incomplete archive file')
                    output.write(block)
                    digest.update(block)
                    remaining -= len(block)
            hashes[role+'/'+relative] = digest.hexdigest()
    return hashes


def matched_review(review, main, event, reference):
    checked_display_review(review, main)
    require(event.get('display_review') == review, 'bridge/display review mismatch')
    require(main['completed_time_sec'] <= review['completed_time_sec'], 'review precedes raw completion')
    age = 1000*(review['completed_time_sec']-review['source_time_sec'])
    require(not review['display_available'] or age <= 500.000001, 'stale numeric display permission')
    if review['reference_scope_verified']:
        require(review['reference_generation'] == 1
                and review['reference_frame'] == reference['source_frame']
                and review['reference_png_sha256'] == reference['source_png_sha256'],
                'wrong display reference binding')
    return age


def phase_rows(frames, first_active_frame):
    return {'all': frames,
            'pre_reference': [m for m in frames if m['frame'] < first_active_frame],
            'post_load': [m for m in frames if m['frame'] >= first_active_frame],
            'final_30_seconds': [m for m in frames if m['source_time_sec'] >= frames[-1]['source_time_sec']-30.]}


def phase_stats(frames, reviews, comparisons, accepted):
    pairs = [(m, reviews[(m['session'], m['frame'])]) for m in frames]
    comps = [comparisons[(m['session'], m['frame'])] for m in frames
             if (m['session'], m['frame']) in comparisons]
    span = frames[-1]['source_time_sec']-frames[0]['source_time_sec'] if frames else 0
    return dict(rows=len(frames), first_frame=frames[0]['frame'] if frames else None,
        last_frame=frames[-1]['frame'] if frames else None, source_span_sec=span,
        processed_interval_hz=(len(frames)-1)/span if span else None,
        original_numeric=sum(m['distance_available'] for m in frames),
        display_permitted=sum(r['display_available'] for m, r in pairs),
        permitted_and_bridge_accepted=sum(r['display_available'] and accepted[(m['session'], m['frame'])] for m, r in pairs),
        original_numeric_display_withheld=sum(m['distance_available'] and not r['display_available'] for m, r in pairs),
        original_withheld_display_numeric=sum(not m['distance_available'] and r['display_available'] for m, r in pairs),
        permitted_exact_original=sum(r['display_available'] and r['display_range_m'] == m['horizontal_camera_foot_range_m'] for m, r in pairs),
        original_reason_counts=dict(Counter(m['reason'] for m in frames)),
        display_reason_counts=dict(Counter(r['reason'] for m, r in pairs)),
        body_review_reason_counts=dict(Counter(r['body_review_reason'] for m, r in pairs)),
        reference_bound=sum(r['reference_scope_verified'] for m, r in pairs),
        main_age_ms=distribution([m['frame_age_ms'] for m in frames]),
        review_completion_age_ms=distribution([1000*(r['completed_time_sec']-m['source_time_sec']) for m, r in pairs]),
        raw_completion_to_review_completion_ms=distribution([1000*(r['completed_time_sec']-m['completed_time_sec']) for m, r in pairs]),
        review_age_over_33p33ms=sum(1000*(r['completed_time_sec']-m['source_time_sec']) > 1000/30 for m, r in pairs),
        review_age_over_500ms=sum(r['completed_time_sec']-m['source_time_sec'] > .5 for m, r in pairs),
        display_numeric_range_m=distribution([r['display_range_m'] for m, r in pairs if r['display_available']]),
        comparison_rows=len(comps), comparison_numeric=sum(r['comparison_distance_available'] for r in comps),
        comparison_reason_counts=dict(Counter(r['reason'] for r in comps)),
        comparison_service_ms=distribution([r['comparison_service_ms'] for r in comps]),
        comparison_age_ms=distribution([1000*(r['completed_time_sec']-r['source_time_sec']) for r in comps]))


def analyze(directory):
    import cv2
    import numpy as np
    primary, comparison = directory/'primary', directory/'comparison'
    j = lambda p: parse_json(read_regular(p, 1024*1024))
    status, engine, bridge = (j(comparison/'comparison_status.json'),
                              j(primary/'motion_engine_summary.json'), j(primary/'driver_motion_summary.json'))
    pin = status['pin']
    reference = checked_reference(j(comparison/'reference.json'))
    require(status['state'] == 'closed' and status['writer_done'] is True
            and status['shutdown_complete'] is True and status['error'] is None, 'comparison not normally closed')
    require(all(status[k] is False for k in (*FLAGS, 'main_display_modified')), 'status authority changed')
    require(pin == j(comparison/(PIN+'.json')) and pin['image_file'] == PIN+'.png'
            and pin['image_modified'] is False, 'pin metadata mismatch')
    require(pin['session'] == reference['session'] and pin['frame'] == reference['source_frame'], 'reference/pin mismatch')
    issued = ROOT/'Experimental_results/2026-11-13/body_display_reference_static_r01/reference.json'
    require(file_sha(comparison/'reference.json') == file_sha(issued), 'not analyst-issued reference bytes')
    prior = ROOT/'recordings/2026-11-13/body_display_pin_intake_r01'
    for name in (PIN+'.png', PIN+'.json'):
        require(file_sha(comparison/name) == file_sha(prior/name), 'pin differs from initial verified intake')
    require(file_sha(primary/'motion_engine_summary.json') == file_sha(prior/'motion_engine_summary.json'), 'engine differs from initial intake')
    png = read_regular(comparison/(PIN+'.png'), 4*1024*1024)
    require(hashlib.sha256(png).hexdigest() == pin['png_sha256'] == reference['source_png_sha256']
            and struct.unpack('>II', png[16:24]) == (1280, 720), 'PNG binding mismatch')
    image = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_COLOR)
    require(image is not None and image.shape == (720, 1280, 3)
            and hashlib.sha256(image.tobytes()).hexdigest() == pin['decoded_bgr_sha256'], 'native pixels mismatch')
    require(set(status['source_sha256']) == set(shared.SOURCES), 'unknown comparison dependency set')
    code = dict(status['source_sha256'])
    for name, digest in engine['body_display_guard']['code_sha256'].items():
        require(name not in code or code[name] == digest, 'conflicting recorded source hashes')
        code[name] = digest
    require(len(engine['body_display_guard']['code_sha256']) == 7 and len(code) == 12, 'display source set differs')
    for name, digest in code.items():
        require('/' not in name and file_sha(ROOT/'src'/name) == digest, 'source hash differs: '+name)
    guard = engine['body_display_guard']
    require(guard['enabled'] is True and guard['raw_main_result_modified'] is False
            and guard['display_rejection_only'] is True and guard['controlling_distance'] is False
            and guard['usable_for_ffb'] is False, 'body display mode mismatch')
    require(engine['guarded_comparison']['worker_started'] is True
            and engine['guarded_comparison']['main_display_modified'] is False, 'comparison mode mismatch')
    require(engine['profile_sha256'] == file_sha(primary/'motion_profile_used.json') == file_sha(
        ROOT/'Experimental_results/2026-11-09/cone_motion_evaluation_r01/prepared_r01/motion_profile_r01.json'), 'profile hash differs')
    require(engine['config_sha256'] == file_sha(ROOT/'src/cone_distance_diagnostic_config.json'), 'config differs')
    require(engine['weights_sha256'] == j(ROOT/'src/cone_distance_diagnostic_config.json')['weights_sha256'], 'recorded checkpoint hash differs')
    require(bridge['shutdown_complete'] is True and bridge['child_stopped'] is True and bridge['io_thread_stopped'] is True
            and bridge['worker_error'] is None and bridge['shutdown_error'] is None and bridge['forced_worker_kill'] is False,
            'primary/IO shutdown incomplete')
    require(all(bridge[k] is False for k in ('physical_metric_verified', 'usable_for_ffb', 'distance_published_to_ros', 'control_channel_modified')),
            'bridge authority changed')
    require(bridge['body_display_guard']['enabled'] is True and bridge['body_display_guard']['rejection_only'] is True
            and bridge['body_display_guard']['raw_main_measurement_modified'] is False, 'bridge guard mode mismatch')
    frames, pin_line = shared.read_main(primary/'motion_distance_frames.jsonl', pin['frame'])
    require(pin_line is not None and hashlib.sha256(pin_line).hexdigest() == pin['source_log_line_sha256'], 'pin exact primary line mismatch')
    events, _ = read_jsonl(primary/'motion_bridge_events.jsonl')
    report, accepted = summarize(frames, events)
    require(len(report['sessions']) == 1 and report['sessions'][0]['session'] == pin['session'], 'main session mismatch')
    reviews, _ = read_jsonl(primary/'motion_display_reviews.jsonl')
    require(len(frames) == len(reviews) == len(events) == bridge['returned'] == bridge['sent'], 'primary/review/bridge counts differ')
    require(sum(not a for a in accepted.values()) == bridge['retired_results'], 'bridge retirement differs')
    by_key = {(r['session'], r['frame']): r for r in frames}
    event_by_key = {(r['result']['session'], r['result']['frame']): r for r in events}
    review_by_key, timings = {}, []
    for r, m in zip(reviews, frames):
        key = r['session'], r['frame']
        require(key == (m['session'], m['frame']) and key not in review_by_key, 'display order/identity mismatch')
        age = matched_review(r, m, event_by_key[key], reference)
        review_by_key[key] = r
        timings.append(dict(session=m['session'], frame=m['frame'], source_time_sec=m['source_time_sec'],
            original_available=m['distance_available'], original_range_m=m['horizontal_camera_foot_range_m'],
            original_reason=m['reason'], support_pixel=json.dumps(m.get('support_pixel')),
            display_permitted=r['display_available'], display_range_m=r['display_range_m'], display_reason=r['reason'],
            body_review_reason=r['body_review_reason'], reference_generation=r['reference_generation'],
            bridge_accepted=accepted[key], raw_age_ms=m['frame_age_ms'], review_age_ms=age,
            raw_to_review_ms=1000*(r['completed_time_sec']-m['completed_time_sec'])))
    comparisons, _ = read_jsonl(comparison/'comparison_frames.jsonl')
    require(len(comparisons) == status['processed'] and (comparison/'comparison_frames.jsonl').stat().st_size == status['log_bytes'],
            'comparison log accounting mismatch')
    require(status['offered'] == len(frames), 'comparison offered count mismatch')
    comp_by_key, previous = {}, 0
    for r in comparisons:
        key = r['session'], r['frame']
        require(key in by_key and r['frame'] > previous, 'comparison identity/order mismatch')
        previous = r['frame']
        shared.matched_comparison(r, by_key[key], reference)
        comp_by_key[key] = r
    active = [r for r in comparisons if r['reference_scope_verified']]
    require(active, 'no active reference results')
    request = j(comparison/'request.json')
    require(request == dict(schema='driver_guarded_request_v1', request_id=status['request_id'], action='load')
            and status['request_count'] == 2 and status['request_action'] == 'load', 'request mismatch')
    # Independently re-evaluate logged current support against the issued local
    # body boundary. This does NOT rerun YOLO or verify unsaved frame pixels.
    geometry_count, geometry_reasons = 0, Counter()
    with (primary/'motion_distance_frames.jsonl').open('rb') as stream:
        for line in stream:
            raw = parse_json(line)
            r = review_by_key[(raw['session'], raw['frame'])]
            if not r['reference_scope_verified']:
                continue
            observation = raw.get('support_observation')
            require(isinstance(observation, dict) and observation.get('point') == raw.get('support_pixel'), 'raw support mismatch')
            geometry = compare_self_body(observation, reference, session=raw['session'], reference_matches=True, compact=True)
            require(geometry['reason'] == r['body_review_reason'], 'replayed body review reason mismatch')
            require(r['display_available'] == (not geometry['revoked'] and geometry['reference_usable'] and geometry['reason'] == CLEAR),
                    'replayed body numeric permission mismatch')
            geometry_count += 1
            geometry_reasons[geometry['reason']] += 1
    phases = phase_rows(frames, active[0]['frame'])
    result = dict(schema='body_display_static_full_audit_v1', state='pass', required_files_complete=True,
        session=pin['session'], pin_frame=pin['frame'], first_reference_frame=active[0]['frame'],
        main=report['sessions'][0], phases={label: phase_stats(items, review_by_key, comp_by_key, accepted) for label, items in phases.items()},
        display_reviews=len(reviews), exact_bridge_review_copies=len(reviews),
        geometry_replayed_from_logged_support=geometry_count, geometry_reason_counts=dict(geometry_reasons),
        first_bound_display_frame=next(r['frame'] for r in reviews if r['reference_scope_verified']),
        source_code_files_rehashed=len(code), source_code_sha256=code,
        issued_reference_sha256=file_sha(comparison/'reference.json'), pin_exact_primary_line_and_native_pixels_verified=True,
        checkpoint_file_supplied=False, engine_metadata=engine,
        shutdown=dict(primary=bridge, comparison={k: status[k] for k in ('state', 'writer_done', 'shutdown_complete', 'error',
            'offered', 'processed', 'latest_slot_overwrites', 'tap_busy_drops')},
            comparison_unprocessed= status['offered']-status['processed']),
        limits=dict(gui_draw_count_or_latency_verified=False, physical_metric_verified=False,
            floor_contact_verified=False, mount_repeatability_verified=False, actual_motion_verified=False,
            all_live_frame_pixels_independently_recomputed=False, supports_only_not_unsaved_images=True,
            local_camera_cuda_ros_or_vehicle_started=False))
    return result, timings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--intake-dir', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    require(not args.output_dir.exists(), 'new result directory required')
    hashes = extract_archive(args.archive, args.intake_dir)
    print('16 files safely preserved; auditing raw/review/bridge/comparison logs.', flush=True)
    result, timings = analyze(args.intake_dir)
    require(all(file_sha(args.intake_dir/name) == digest for name, digest in hashes.items()), 'submitted bytes changed')
    result.update(archive_sha256=file_sha(args.archive), supplied_files_sha256=hashes,
        audit_code_sha256={str(p.relative_to(ROOT)): file_sha(p) for p in (
            Path(__file__), Path(shared.__file__), ROOT/'src/report_driver_motion_logs.py', ROOT/'src/verify_driver_withheld_evidence.py')})
    args.output_dir.mkdir(parents=True)
    (args.output_dir/'audit.json').write_text(json.dumps(result, indent=2)+'\n')
    with (args.output_dir/'display_timing.csv').open('x', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=timings[0].keys())
        writer.writeheader()
        writer.writerows(timings)
    print(json.dumps(dict(state=result['state'], phases=result['phases'], shutdown=result['shutdown']), indent=2))


if __name__ == '__main__':
    main()
