"""Identical one-second inputs, different paired measured service costs only."""
from collections import defaultdict
import json
from pathlib import Path

import numpy as np

from run_fast import HERE, ROOT, p
from replay_completion import replay
from replay_paired_costs import apply_pending


def main():
    output = HERE / 'replay_r01'
    if output.exists():
        raise ValueError('fresh replay output required')
    p.check_manifest(HERE / 'results_guard_r02/summary.json')
    causal = HERE.parent / 'causal_pose_replay_r01'
    latency = HERE.parent / 'causal_availability_latency_r01'
    observation = ROOT / 'Experimental_results/2026-10-21/cone_known_height_pinhole_r01/results_r01/observed_pixels.csv'
    uniform = ROOT / 'Experimental_results/2026-10-22/scene_uniform_validation_r01'
    paths = [Path(__file__), HERE / 'method.md', HERE / 'run_fast_guarded.py', HERE / 'results_guard_r02/summary.json',
             HERE / 'results_guard_r02/scene_stage_measurements.csv', p.DENSE / 'scene_results_r01/image_diagnostics.csv',
             uniform / 'quality_results_r01/all_frame_quality.csv', observation,
             causal / 'results_r01/frame_metrics.csv', latency / 'replay_completion.py', latency / 'finish_aware.py',
             latency / 'pending_hold_control.py', p.REUSE / 'replay_paired_costs.py', causal / 'causal_pose.py',
             causal / 'replay_saved.py', p.GEO / 'scene_geometry.py', ROOT / 'src/angular_fisheye_geometry.py', p.CAMERA, p.FLOOR]
    sources = {str(x): p.sha256(x) for x in paths}
    samples = [r for r in p.read_csv(paths[5]) if r['session'] == p.SESSION and r['sparse_1s_member'] == 'True']
    quality = {int(r['frame']): r for r in p.read_csv(paths[6]) if r['session'] == p.SESSION}
    obs = [r for r in p.read_csv(observation) if r['session'] == p.SESSION]
    previous = {int(r['frame']): r for r in p.read_csv(paths[8]) if r['session'] == p.SESSION and r['mode'] == 'bounded_between_samples_1s'}
    costs = defaultdict(list)
    for r in p.read_csv(paths[4]):
        costs[r['variant'], int(r['frame'])].append(float(r['scene_service_ms']) / 1000.)
    assert len(costs) == 104 and all(len(v) == 3 for v in costs.values())
    camera = p.camera_from_candidate(json.loads(p.CAMERA.read_text()))
    T = np.array(json.loads(p.FLOOR.read_text())['transform_target_from_source'])
    rows = []; summaries = []; schedules = []; events = []
    for variant in ('zero_service_reference', 'ray_reuse_control', 'bin_reduction'):
        service = {int(r['frame']): 0. if variant == 'zero_service_reference' else float(np.median(costs[variant, int(r['frame'])])) for r in samples}
        raw, jobs, applied = replay(samples, obs, quality, service, camera, T)
        current = apply_pending(raw, jobs)
        for r, ob in zip(current, obs):
            if variant == 'zero_service_reference':
                old = previous[r['frame']]
                assert r['diagnostic_available'] == (old['diagnostic_available'] == 'True')
                assert r['diagnostic_z_m'] == (float(old['diagnostic_z_m']) if old['diagnostic_z_m'] else None)
            rows.append(dict(variant=variant, session=p.SESSION, **r, condition=ob['condition'], reference_z_m=ob['reference_z_m']))
        summaries.append(dict(variant=variant, frames=len(current), before_pending_hold_frames=sum(r['diagnostic_available'] for r in raw),
                              diagnostic_frames=sum(r['diagnostic_available'] for r in current),
                              max_queue_wait_sec=max(j['queue_wait_sec'] for j in jobs),
                              outputs_during_pending=sum(r['diagnostic_available'] and r['newer_scene_input_pending'] for r in current),
                              physical_metric_verified=False, usable_for_ffb=False))
        schedules.extend(dict(variant=variant, **{k: v for k, v in j.items() if k != 'sample'}) for j in jobs)
        events.extend(dict(variant=variant, **e) for e in applied)
    assert len(rows) == 4641 and summaries[0]['diagnostic_frames'] == 377
    assert all(r['outputs_during_pending'] == 0 for r in summaries)
    p.check_hashes(sources)
    output.mkdir()
    for name, data in [('frame_metrics.csv', rows), ('replay_summary.csv', summaries), ('scene_job_schedule.csv', schedules), ('scene_events.csv', events)]:
        p.write_csv(output / name, data)
    summary = dict(status='COMPLETED_ONE_SECOND_BIN_REDUCTION_COST_COUNTERFACTUAL', source_sha256=sources,
                   zero_cost_mismatches=0, summaries=summaries, source_ttl_sec=1., source_images_edited=False,
                   current_cone_compute_cost_included=False, physical_output=False, usable_for_ffb=False,
                   output_sha256={x.name: p.sha256(x) for x in output.iterdir() if x.is_file()})
    (output / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps(summaries, indent=2))


if __name__ == '__main__':
    main()
