"""Independent r02 full-equivalence and paired timing; preserve r01 evidence."""
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import time

import cv2
import numpy as np

from run_fast import HERE, ROOT, PROFILE, p
from guarded_curve_geometry import extract_guarded_curve_planes
from scene_geometry import infer_up


def compute_guarded(image, camera, prior):
    curves = extract_guarded_curve_planes(image, camera)
    normals = np.array([r['normal'] for r in curves if r['accepted']]).reshape(-1, 3)
    return curves, infer_up(normals, prior)


def main():
    output = HERE / 'results_guard_r02'
    if output.exists():
        raise ValueError('fresh guarded output required')
    assert os.environ.get('OPENBLAS_NUM_THREADS') == '1'
    cv2.setNumThreads(1)
    p.check_manifest(HERE / 'results_r01/summary.json')
    paths = [Path(__file__), HERE / 'guarded_curve_geometry.py', HERE / 'method.md', HERE / 'guard_r02_method.md',
             HERE / 'run_fast.py', HERE / 'results_r01/summary.json',
             p.DENSE / 'scene_results_r01/image_diagnostics.csv', p.REUSE / 'cached_curve_geometry.py',
             p.REUSE / 'run_comparison.py', PROFILE / 'run_profile.py', p.GEO / 'scene_geometry.py',
             ROOT / 'src/angular_fisheye_geometry.py', ROOT / 'src/fisheye_floor_geometry.py', p.CAMERA, p.FLOOR]
    sources = {str(x): p.sha256(x) for x in paths}
    camera = p.camera_from_candidate(json.loads(p.CAMERA.read_text()))
    prior = np.array(json.loads(p.FLOOR.read_text())['nominal_transform'])[:3, :3].T @ [0., 0., 1.]
    checkpoint = HERE / 'guard_equivalence_checkpoints_r02'
    spec = dict(source_sha256=sources, batch_size=100)
    spec_path = checkpoint / 'run_spec.json'
    if checkpoint.exists():
        assert json.loads(spec_path.read_text()) == spec
    else:
        checkpoint.mkdir()
        spec_path.write_text(json.dumps(spec, indent=2) + '\n')
    cached = {}
    for path in sorted(checkpoint.glob('batch_*.json')):
        record = json.loads(path.read_text())
        assert record['run_spec_sha256'] == p.sha256(spec_path)
        assert hashlib.sha256(p.canonical(record['checks']).encode()).hexdigest() == record['checks_sha256']
        for row in record['checks']:
            key = (row['session'], row['frame'])
            assert key not in cached
            cached[key] = row
    checks = []; benchmark = []; pending = []
    images = p.read_csv(paths[6])
    for index, r in enumerate(images):
        path = Path(r['source_native_png']); assert p.sha256(path) == r['png_sha256']
        sources[str(path)] = r['png_sha256']
        image = cv2.imread(str(path))
        key = (r['session'], int(r['frame']))
        if key in cached:
            row = cached[key]
            assert row['png_sha256'] == r['png_sha256']
        else:
            result = compute_guarded(image, camera, prior)
            assert hashlib.sha256(p.canonical(result).encode()).hexdigest() == r['candidate_and_up_sha256']
            row = dict(session=r['session'], frame=int(r['frame']), accepted=bool(result[1]['accepted']),
                       png_sha256=r['png_sha256'], all_candidate_and_up_fields_exact=True,
                       physical_output=False, usable_for_ffb=False)
            pending.append(row)
        checks.append(row)
        if r['session'] == p.SESSION and r['sparse_1s_member'] == 'True':
            benchmark.append((r, image))
        if (index + 1) % 100 == 0:
            print('guarded-bin equivalence', index + 1, '/ 978', flush=True)
        if pending and ((index + 1) % 100 == 0 or index + 1 == len(images)):
            path = checkpoint / f'batch_{index + 1:06d}.json'
            assert not path.exists()
            path.write_text(json.dumps(dict(run_spec_sha256=p.sha256(spec_path), checks=pending,
                checks_sha256=hashlib.sha256(p.canonical(pending).encode()).hexdigest()), indent=2) + '\n')
            pending = []
    assert len(checks) == 978 and len(benchmark) == 52
    sources.update({str(x): p.sha256(x) for x in checkpoint.glob('*.json')})
    output.mkdir()
    p.write_csv(output / 'equivalence.csv', checks)
    compute_guarded(benchmark[0][1], camera, prior); p.compute(benchmark[0][1], camera, prior, True)
    measured = []; pairs = []
    for run in range(1, 4):
        for index, (r, image) in enumerate(benchmark):
            order = (False, True) if (index + run) % 2 else (True, False)
            costs = {}; results = {}
            for position, fast in enumerate(order):
                start = time.perf_counter_ns()
                results[fast] = compute_guarded(image, camera, prior) if fast else p.compute(image, camera, prior, True)
                costs[fast] = (time.perf_counter_ns() - start) / 1e6
                measured.append(dict(session=p.SESSION, frame=int(r['frame']), time_sec=float(r['time_sec']), run=run,
                                     variant='bin_reduction' if fast else 'ray_reuse_control', position_in_pair=position,
                                     scene_service_ms=costs[fast], image_decode_in_timing=False,
                                     physical_output=False, usable_for_ffb=False))
            assert p.canonical(results[False]) == p.canonical(results[True])
            pairs.append(dict(frame=int(r['frame']), run=run, first='fast' if order[0] else 'control',
                              control_ms=costs[False], fast_ms=costs[True], paired_speedup=costs[False] / costs[True]))
        print('guarded-bin paired pass', run, '/ 3 complete', flush=True)
    p.check_hashes(sources)
    p.write_csv(output / 'scene_stage_measurements.csv', measured)
    p.write_csv(output / 'paired_measurements.csv', pairs)
    timings = {}
    for variant in ('ray_reuse_control', 'bin_reduction'):
        values = [r['scene_service_ms'] for r in measured if r['variant'] == variant]
        timings[variant] = dict(median_ms=float(np.median(values)), mean_ms=float(np.mean(values)),
                               p95_ms=float(np.percentile(values, 95)), observed_max_ms=max(values))
    summary = dict(status='PASS_EXACT_OVERFLOW_SAFE_BIN_REDUCTION_AND_PAIRED_BENCHMARK',
                   source_sha256=sources, images=978, recordings=9, result_mismatches=0,
                   benchmark_images=52, passes=3, pairs=156, timings=timings,
                   order_counts=dict(Counter(r['first'] for r in pairs)),
                   paired_speedup_median=float(np.median([r['paired_speedup'] for r in pairs])),
                   overflow_safe_order_checks=True, tie_rule_changed=False, approximate_minimum_used=False,
                   production_changed=False, end_to_end_latency_measured=False, source_images_edited=False,
                   physical_output=False, usable_for_ffb=False,
                   output_sha256={x.name: p.sha256(x) for x in output.iterdir() if x.is_file()})
    (output / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps({k: v for k, v in summary.items() if k not in ('source_sha256', 'output_sha256')}, indent=2))


if __name__ == '__main__':
    main()
