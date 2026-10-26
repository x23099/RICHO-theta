"""Nested input grids with identical geometry, initialization, TTL and pending hold."""
from collections import Counter, defaultdict
import json
from pathlib import Path

import numpy as np

from dense_common import HERE, ROOT, UNIFORM, REUSE, LATENCY, CAUSAL, GEO, CAMERA, FLOOR
from dense_common import read_csv, write_csv, sha256, check_manifest, check_hashes
from dense_common import replay, apply_pending, schedule, FinishAwarePose
from angular_fisheye_geometry import camera_from_candidate
from causal_pose import PastOnlyPose


def private_samples(samples):
    """Labels/roles/references never enter the state machine."""
    return [{k: r[k] for k in ('frame', 'time_sec', 'accepted', 'up_optical_json')} for r in samples]


def private_observations(rows):
    return [{k: r[k] for k in ('frame', 'time_sec', 'native_colour_pair_json')} for r in rows]


def audit_initializations(samples, jobs, events):
    """Post-replay source span audit only; never feeds the distance gate."""
    state = PastOnlyPose()
    times = {int(r['frame']): float(r['time_sec']) for r in samples}
    initial_events = {e['scene_frame']: e for e in events if e['initialization_event']}
    completed_frames = {e['scene_frame'] for e in events}
    rows = []
    for j in jobs:
        # A recording can end before its last queued input completes. Do not
        # retroactively count that unobserved future completion as evidence.
        if j['frame'] not in completed_frames:
            break
        sample = j['sample']; frame = j['frame']; was_ready = state.ready
        accepted = sample['accepted'] == 'True'
        assert sample['accepted'] in ('True', 'False')
        state.ingest(frame, j['release_sec'], accepted,
                     json.loads(sample['up_optical_json']) if accepted else None)
        if state.ready and not was_ready:
            evidence = [f for f, _ in state.train] + state.validation
            assert len(evidence) == 4 and frame in initial_events
            event = initial_events[frame]
            rows.append(dict(scene_frame=frame, source_time_sec=j['release_sec'],
                             completion_time_sec=j['finish_sec'], first_query_time_sec=event['first_query_time_sec'],
                             training_frames_json=json.dumps(evidence[:2]), validation_frames_json=json.dumps(evidence[2:]),
                             four_source_times_json=json.dumps([times[f] for f in evidence]),
                             four_evidence_span_sec=times[evidence[-1]] - times[evidence[0]],
                             min_evidence_gap_sec=float(np.min(np.diff([times[f] for f in evidence]))),
                             first_source_time_sec=times[evidence[0]], physically_independent_observations_verified=False,
                             usable_for_ffb=False))
    assert len(rows) == len(initial_events)
    return rows, state.restarts


def paper_pose_only(samples, timeline, service):
    jobs = schedule(private_samples(samples), service)
    worker = FinishAwarePose(jobs)
    for ob in timeline:
        worker.query(int(ob['frame']), float(ob['time_sec']))
    return jobs, worker.events


def reason(row):
    if row['diagnostic_available']:
        return 'diagnostic_available'
    if row['newer_scene_input_pending']:
        return 'newer_scene_input_not_finished'
    if not row['initialized']:
        return 'not_initialized'
    if not row['pose_available']:
        return row['pose_reason']
    if not row['quality_accepted']:
        return 'current_image_quality_withheld'
    return 'current_colour_or_floor_intersection_unavailable'


def main():
    output = HERE / 'replay_r01'
    if output.exists():
        raise ValueError('fresh replay output required')
    check_manifest(HERE / 'scene_results_r01/summary.json')
    check_manifest(REUSE / 'verification_r01/summary.json')
    observations_path = ROOT / 'Experimental_results/2026-10-21/cone_known_height_pinhole_r01/results_r01/observed_pixels.csv'
    paths = [Path(__file__), HERE / 'dense_common.py', HERE / 'method.md',
             HERE / 'scene_results_r01/summary.json', HERE / 'scene_results_r01/image_diagnostics.csv',
             HERE / 'scene_results_r01/scene_stage_measurements.csv', HERE / 'intake_r01/sampling_plan.json',
             LATENCY / 'replay_completion.py', LATENCY / 'finish_aware.py', LATENCY / 'pending_hold_control.py',
             REUSE / 'replay_paired_costs.py', CAUSAL / 'causal_pose.py', CAUSAL / 'replay_saved.py',
             GEO / 'scene_geometry.py', ROOT / 'src/angular_fisheye_geometry.py',
             UNIFORM / 'quality_results_r01/all_frame_quality.csv', observations_path,
             CAUSAL / 'results_r01/frame_metrics.csv', REUSE / 'verification_r01/summary.json', CAMERA, FLOOR]
    sources = {str(p): sha256(p) for p in paths}
    grouped = defaultdict(list); obs_groups = defaultdict(list); old = {}
    for r in read_csv(paths[4]):
        grouped[r['session']].append(r)
    for r in read_csv(observations_path):
        obs_groups[r['session']].append(r)
    quality = {(r['session'], int(r['frame'])): r for r in read_csv(paths[15])}
    for r in read_csv(paths[17]):
        if r['mode'] == 'bounded_between_samples_1s':
            old[r['session'], int(r['frame'])] = r
    costs = defaultdict(list)
    for r in read_csv(paths[5]):
        costs[r['session'], int(r['frame'])].append(float(r['scene_service_ms']) / 1000.)
    assert all(len(v) == 3 for v in costs.values())
    plan = json.loads(paths[6].read_text())['sessions']
    timelines = {}
    for p in plan:
        path = Path(p['session_path']) / 'detections.csv'
        sources[str(path)] = sha256(path)
        timelines[p['session']] = read_csv(path)
    camera = camera_from_candidate(json.loads(CAMERA.read_text()))
    T = np.array(json.loads(FLOOR.read_text())['transform_target_from_source'])
    frames = []; job_rows = []; event_rows = []; sessions = []; conditions = []; init_rows = []; reasons = []
    reference_mismatches = 0
    for interval in ('sparse_1s', 'dense_0p5s'):
        for cost_mode in ('zero_service', 'three_pass_median'):
            scenario = interval + '__' + cost_mode
            for session, group in sorted(grouped.items()):
                samples = [r for r in group if interval == 'dense_0p5s' or r['sparse_1s_member'] == 'True']
                service = {int(r['frame']): 0. if cost_mode == 'zero_service'
                           else float(np.median(costs[session, int(r['frame'])])) for r in samples}
                obs = obs_groups[session]
                if obs:
                    q = {int(r['frame']): {k: quality[session, int(r['frame'])][k]
                         for k in ('time_sec', 'quality_accepted')} for r in obs}
                    raw, jobs, events = replay(private_samples(samples), private_observations(obs), q, service, camera, T)
                    rows = apply_pending(raw, jobs)
                else:
                    jobs, events = paper_pose_only(samples, timelines[session], service)
                    rows = []; raw = []
                audit, restarts = audit_initializations(samples, jobs, events)
                for row, ob in zip(rows, obs):
                    if scenario == 'sparse_1s__zero_service':
                        previous = old[session, row['frame']]
                        matches = row['diagnostic_available'] == (previous['diagnostic_available'] == 'True')
                        matches &= row['diagnostic_z_m'] == (float(previous['diagnostic_z_m']) if previous['diagnostic_z_m'] else None)
                        reference_mismatches += not matches
                    assert not (row['diagnostic_available'] and row['newer_scene_input_pending'])
                    assert not (row['diagnostic_available'] and row['newer_unfinished_rejection_posthoc'])
                    frames.append(dict(scenario=scenario, session=session, **row,
                                       condition=ob['condition'], reference_z_m=ob['reference_z_m']))
                first = audit[0] if audit else None
                sessions.append(dict(scenario=scenario, session=session, sampled_images=len(samples),
                                     accepted_images=sum(r['accepted'] == 'True' for r in samples),
                                     raw_frames=len(timelines[session]), cone_query_frames=len(obs),
                                     initialization_events=len(audit), direction_restarts=restarts,
                                     first_initialization_source_sec=first['source_time_sec'] if first else None,
                                     first_initialization_elapsed_sec=first['source_time_sec'] - float(timelines[session][0]['time_sec']) if first else None,
                                     first_initialization_completion_sec=first['completion_time_sec'] if first else None,
                                     first_initialization_evidence_span_sec=first['four_evidence_span_sec'] if first else None,
                                     before_pending_hold_frames=sum(r['diagnostic_available'] for r in raw),
                                     diagnostic_frames=sum(r['diagnostic_available'] for r in rows),
                                     max_queue_wait_sec=max(j['queue_wait_sec'] for j in jobs),
                                     pending_input_query_frames=sum(r['newer_scene_input_pending'] for r in rows),
                                     physical_metric_verified=False, usable_for_ffb=False))
                for condition in sorted({ob['condition'] for ob in obs}):
                    selected = [(r, ob) for r, ob in zip(rows, obs) if ob['condition'] == condition]
                    used = [r['diagnostic_z_m'] for r, _ in selected if r['diagnostic_available']]
                    ref = selected[0][1]['reference_z_m']
                    errors = np.array(used) - float(ref) if ref and used else np.array([])
                    conditions.append(dict(scenario=scenario, session=session, condition=condition,
                                           all_frames=len(selected), diagnostic_frames=len(used), reference_z_m=ref,
                                           z_median_m=float(np.median(used)) if used else None,
                                           absolute_error_max_m=float(max(abs(errors))) if len(errors) else None,
                                           physical_metric_verified=False, usable_for_ffb=False))
                counts = Counter(reason(r) for r in rows)
                reasons.extend(dict(scenario=scenario, session=session, reason=k, frames=n) for k, n in sorted(counts.items()))
                init_rows.extend(dict(scenario=scenario, session=session, **r) for r in audit)
                event_rows.extend(dict(scenario=scenario, session=session, **r) for r in events)
                job_rows.extend(dict(scenario=scenario, session=session, **{k: v for k, v in j.items() if k != 'sample'}) for j in jobs)
            print('replay complete', scenario, flush=True)
    assert reference_mismatches == 0 and len(frames) == 4 * 6876 and len(sessions) == 36
    # Compare exact same query frames; references are deliberately not used here.
    matched = []; frame_index = {(r['scenario'], r['session'], r['frame']): r for r in frames}
    for cost_mode in ('zero_service', 'three_pass_median'):
        for session, obs in sorted(obs_groups.items()):
            if not obs:
                continue
            sparse = [frame_index['sparse_1s__' + cost_mode, session, int(ob['frame'])] for ob in obs]
            dense = [frame_index['dense_0p5s__' + cost_mode, session, int(ob['frame'])] for ob in obs]
            both = [(a, b) for a, b in zip(sparse, dense) if a['diagnostic_available'] and b['diagnostic_available']]
            differences = np.array([b['diagnostic_z_m'] - a['diagnostic_z_m'] for a, b in both])
            matched.append(dict(cost_mode=cost_mode, session=session, cone_query_frames=len(obs),
                                sparse_available=sum(r['diagnostic_available'] for r in sparse),
                                dense_available=sum(r['diagnostic_available'] for r in dense), common_available=len(both),
                                dense_only=sum(b['diagnostic_available'] and not a['diagnostic_available'] for a, b in zip(sparse, dense)),
                                sparse_only=sum(a['diagnostic_available'] and not b['diagnostic_available'] for a, b in zip(sparse, dense)),
                                matched_z_difference_median_m=float(np.median(differences)) if len(differences) else None,
                                matched_z_difference_max_abs_m=float(max(abs(differences))) if len(differences) else None,
                                physical_metric_verified=False, usable_for_ffb=False))
    check_hashes(sources)
    output.mkdir()
    for name, data in [('frame_metrics.csv', frames), ('session_summary.csv', sessions), ('condition_summary.csv', conditions),
                       ('initialization_evidence.csv', init_rows), ('scene_job_schedule.csv', job_rows),
                       ('scene_events.csv', event_rows), ('hold_reasons.csv', reasons), ('matched_frame_comparison.csv', matched)]:
        write_csv(output / name, data)
    totals = []
    for scenario in sorted({r['scenario'] for r in sessions}):
        selected = [r for r in sessions if r['scenario'] == scenario]
        totals.append(dict(scenario=scenario, initialized_recordings=sum(r['initialization_events'] > 0 for r in selected),
                           diagnostic_frames=sum(r['diagnostic_frames'] for r in selected),
                           max_queue_wait_sec=max(r['max_queue_wait_sec'] for r in selected)))
    summary = dict(status='COMPLETED_NESTED_HALFSECOND_COMPLETION_REPLAY_NOT_PHYSICAL_VALIDATION',
                   work_date='2026-10-23', source_sha256=sources, scenarios=4, recordings=9,
                   unique_cone_frames=6876, scenario_frame_rows=len(frames), reference_1s_zero_mismatches=0,
                   source_ttl_sec=1., prior_thresholds_unchanged=True, current_cone_compute_cost_included=False,
                   initial_four_images_not_asserted_independent=True, totals=totals,
                   source_images_edited=False, production_changed=False, physical_output=False, usable_for_ffb=False,
                   output_sha256={p.name: sha256(p) for p in output.iterdir() if p.is_file()})
    (output / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps(totals, indent=2))


if __name__ == '__main__':
    main()
