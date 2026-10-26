"""Apply paired timing costs to the unchanged completion/pending-hold controls."""
from collections import defaultdict
import json
from pathlib import Path
import sys

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import run_comparison as study
LATENCY = HERE.parent / 'causal_availability_latency_r01'
CAUSAL = HERE.parent / 'causal_pose_replay_r01'
sys.path[:0] = [str(LATENCY), str(CAUSAL)]
from replay_completion import replay
from pending_hold_control import hold_for_newer_input
from cone_dataset import read_csv, write_csv, sha256


def apply_pending(rows, jobs):
    result = []; cursor = 0; latest = 0
    for r in rows:
        while cursor < len(jobs) and jobs[cursor]['release_sec'] <= r['time_sec']:
            latest = jobs[cursor]['frame']; cursor += 1
        pending = hold_for_newer_input(latest, r['latest_completed_scene_frame'])
        available = r['diagnostic_available'] and not pending
        result.append(dict(r, latest_released_scene_frame=latest, newer_scene_input_pending=pending,
                           before_control_diagnostic_available=r['diagnostic_available'],
                           before_control_diagnostic_z_m=r['diagnostic_z_m'],
                           diagnostic_available=available,
                           diagnostic_z_m=r['diagnostic_z_m'] if available else None))
    return result


def main():
    output = HERE / 'replay_r01'
    if output.exists():
        raise ValueError('fresh output required')
    proof_path = HERE / 'results_r01/summary.json'
    proof = json.loads(proof_path.read_text())
    assert proof['all_curve_and_up_mismatches'] == 0 and proof['equivalence_images'] == 492
    for p, h in proof['source_sha256'].items():
        assert sha256(Path(p)) == h, p
    for p, h in proof['output_sha256'].items():
        assert sha256(HERE / 'results_r01' / p) == h, p
    paths = [Path(__file__), HERE / 'method.md', proof_path,
             HERE / 'results_r01/scene_stage_measurements.csv',
             LATENCY / 'replay_completion.py', LATENCY / 'finish_aware.py',
             LATENCY / 'pending_hold_control.py', CAUSAL / 'causal_pose.py', CAUSAL / 'replay_saved.py',
             study.UNIFORM / 'scene_results_r01/image_diagnostics.csv',
             study.UNIFORM / 'quality_results_r01/all_frame_quality.csv',
             study.ROOT / 'Experimental_results/2026-10-21/cone_known_height_pinhole_r01/results_r01/observed_pixels.csv',
             CAUSAL / 'results_r01/frame_metrics.csv', study.CAMERA, study.FLOOR]
    sources = {str(p): sha256(p) for p in paths}
    samples = [r for r in read_csv(paths[9]) if r['session'] == study.SESSION]
    quality = {int(r['frame']): r for r in read_csv(paths[10]) if r['session'] == study.SESSION}
    observations = [r for r in read_csv(paths[11]) if r['session'] == study.SESSION]
    previous = {int(r['frame']): r for r in read_csv(paths[12])
                if r['session'] == study.SESSION and r['mode'] == 'bounded_between_samples_1s'}
    costs = defaultdict(list)
    for r in read_csv(paths[3]):
        costs[r['variant'], int(r['frame'])].append(float(r['scene_service_ms']) / 1000.)
    assert len(costs) == 104 and all(len(v) == 3 for v in costs.values())
    camera = study.camera_from_candidate(json.loads(study.CAMERA.read_text()))
    T = np.array(json.loads(study.FLOOR.read_text())['transform_target_from_source'])
    all_rows = []; all_jobs = []; all_events = []; summaries = []; groups = []
    for variant in ('zero_service_reference', 'baseline', 'same_frame_reuse'):
        service = {int(r['frame']): 0. if variant == 'zero_service_reference'
                   else float(np.median(costs[variant, int(r['frame'])])) for r in samples}
        raw, jobs, events = replay(samples, observations, quality, service, camera, T)
        rows = apply_pending(raw, jobs)
        for r, ob in zip(rows, observations):
            if variant == 'zero_service_reference':
                old = previous[r['frame']]
                assert r['diagnostic_available'] == (old['diagnostic_available'] == 'True')
                assert r['diagnostic_z_m'] == (float(old['diagnostic_z_m']) if old['diagnostic_z_m'] else None)
            assert not (r['diagnostic_available'] and r['newer_scene_input_pending'])
            assert not (r['diagnostic_available'] and r['newer_unfinished_rejection_posthoc'])
            all_rows.append(dict(variant=variant, session=study.SESSION, **r,
                                 condition=ob['condition'], reference_z_m=ob['reference_z_m']))
        initial = [e for e in events if e['initialization_event']]
        summaries.append(dict(variant=variant, frames=len(rows),
                              before_pending_hold_frames=sum(r['diagnostic_available'] for r in raw),
                              after_pending_hold_frames=sum(r['diagnostic_available'] for r in rows),
                              pending_hold_removed_frames=sum(r['diagnostic_available'] for r in raw)
                              - sum(r['diagnostic_available'] for r in rows),
                              zero_service_frames=377,
                              lost_vs_zero_service=sum(previous[r['frame']]['diagnostic_available'] == 'True'
                                                       and not r['diagnostic_available'] for r in rows),
                              additional_vs_zero_service=sum(previous[r['frame']]['diagnostic_available'] == 'False'
                                                             and r['diagnostic_available'] for r in rows),
                              max_queue_wait_sec=max(j['queue_wait_sec'] for j in jobs),
                              initialization_source_time_sec=initial[0]['source_time_sec'] if initial else None,
                              initialization_completion_time_sec=initial[0]['completion_time_sec'] if initial else None,
                              physical_metric_verified=False, usable_for_ffb=False))
        for condition in sorted({ob['condition'] for ob in observations if ob['reference_z_m']}):
            selected = [(r, ob) for r, ob in zip(rows, observations) if ob['condition'] == condition]
            values = [r['diagnostic_z_m'] for r, _ in selected if r['diagnostic_available']]
            groups.append(dict(variant=variant, condition=condition, total_frames=len(selected),
                               diagnostic_frames=len(values), reference_z_m=float(selected[0][1]['reference_z_m']),
                               z_median_m=float(np.median(values)) if values else None,
                               physical_metric_verified=False, usable_for_ffb=False))
        all_jobs.extend(dict(variant=variant, **{k: v for k, v in j.items() if k != 'sample'}) for j in jobs)
        all_events.extend(dict(variant=variant, **e) for e in events)
    assert len(all_rows) == 3 * 1547
    assert summaries[0]['after_pending_hold_frames'] == 377
    assert all(sha256(Path(p)) == h for p, h in sources.items())
    output.mkdir()
    for name, data in [('frame_metrics.csv', all_rows), ('scene_job_schedule.csv', all_jobs),
                       ('scene_events.csv', all_events), ('replay_summary.csv', summaries), ('condition_summary.csv', groups)]:
        write_csv(output / name, data)
    summary = dict(status='COMPLETED_PAIRED_COST_COUNTERFACTUAL_WITH_UNCHANGED_PENDING_HOLD',
                   work_date='2026-10-23', source_sha256=sources, summaries=summaries,
                   zero_service_mismatches=0, source_ttl_sec=1., cone_compute_cost_included=False,
                   pending_future_acceptance_used=False, ground_truth_used_in_gate=False,
                   original_capture_delivery_latency_reproduced=False,
                   production_changed=False, physical_output=False, usable_for_ffb=False,
                   output_sha256={p.name: sha256(p) for p in output.iterdir() if p.is_file()})
    (output / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps(summaries, indent=2))


if __name__ == '__main__':
    main()
