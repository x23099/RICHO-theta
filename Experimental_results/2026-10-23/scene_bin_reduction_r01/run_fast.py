"""Frozen full-result equality before paired exact-bin benchmark."""
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import platform
import sys
import time

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PROFILE = HERE.parent / 'scene_stage_profile_r01'
sys.path.insert(0, str(PROFILE))
import run_profile as p
from fast_curve_geometry import extract_fast_curve_planes
from scene_geometry import infer_up


def compute_fast(image, camera, prior):
    curves = extract_fast_curve_planes(image, camera)
    normals = np.array([r['normal'] for r in curves if r['accepted']]).reshape(-1, 3)
    return curves, infer_up(normals, prior)


def main():
    output = HERE / 'results_r01'
    if output.exists():
        raise ValueError('fresh fast-bin output required')
    if os.environ.get('OPENBLAS_NUM_THREADS') != '1':
        raise ValueError('OPENBLAS_NUM_THREADS=1 required')
    cv2.setNumThreads(1)
    p.check_manifest(PROFILE / 'results_r01/summary.json')
    paths = [Path(__file__), HERE / 'fast_curve_geometry.py', HERE / 'method.md',
             PROFILE / 'run_profile.py', PROFILE / 'results_r01/summary.json',
             p.DENSE / 'scene_results_r01/image_diagnostics.csv', p.DENSE / 'scene_results_r01/summary.json',
             p.REUSE / 'cached_curve_geometry.py', p.REUSE / 'run_comparison.py',
             p.GEO / 'scene_geometry.py', ROOT / 'src/angular_fisheye_geometry.py',
             ROOT / 'src/fisheye_floor_geometry.py', p.CAMERA, p.FLOOR]
    sources = {str(x): p.sha256(x) for x in paths}
    camera = p.camera_from_candidate(json.loads(p.CAMERA.read_text()))
    prior = np.array(json.loads(p.FLOOR.read_text())['nominal_transform'])[:3, :3].T @ [0., 0., 1.]
    images = p.read_csv(paths[5]); assert len(images) == 978
    checks = []; benchmark = []
    for index, r in enumerate(images):
        image_path = Path(r['source_native_png'])
        assert p.sha256(image_path) == r['png_sha256']
        sources[str(image_path)] = r['png_sha256']
        image = cv2.imread(str(image_path))
        result = compute_fast(image, camera, prior)
        signature = hashlib.sha256(p.canonical(result).encode()).hexdigest()
        assert signature == r['candidate_and_up_sha256'], (r['session'], r['frame'])
        checks.append(dict(session=r['session'], frame=int(r['frame']), accepted=bool(result[1]['accepted']),
                           all_candidate_and_up_fields_exact=True, physical_output=False, usable_for_ffb=False))
        if r['session'] == p.SESSION and r['sparse_1s_member'] == 'True':
            benchmark.append((r, image))
        if (index + 1) % 100 == 0:
            print('fast-bin equivalence', index + 1, '/ 978', flush=True)
    assert len(benchmark) == 52
    output.mkdir()
    p.write_csv(output / 'equivalence.csv', checks)
    (output / 'equivalence_precondition.json').write_text(json.dumps(dict(status='PASS_EXACT_978_IMAGES', source_sha256=sources), indent=2) + '\n')
    p.compute(benchmark[0][1], camera, prior, True)
    compute_fast(benchmark[0][1], camera, prior)
    measured = []; pairs = []
    for run in range(1, 4):
        for index, (r, image) in enumerate(benchmark):
            order = (False, True) if (index + run) % 2 else (True, False)
            results = {}; costs = {}
            for position, fast in enumerate(order):
                start = time.perf_counter_ns()
                result = compute_fast(image, camera, prior) if fast else p.compute(image, camera, prior, True)
                elapsed = (time.perf_counter_ns() - start) / 1e6
                variant = 'bin_reduction' if fast else 'ray_reuse_control'
                costs[fast] = elapsed; results[fast] = result
                measured.append(dict(session=p.SESSION, frame=int(r['frame']), time_sec=float(r['time_sec']), run=run,
                                     variant=variant, position_in_pair=position, scene_service_ms=elapsed,
                                     image_decode_in_timing=False, physical_output=False, usable_for_ffb=False))
            assert p.canonical(results[False]) == p.canonical(results[True])
            pairs.append(dict(frame=int(r['frame']), run=run, first='fast' if order[0] else 'control',
                              control_ms=costs[False], fast_ms=costs[True], paired_speedup=costs[False] / costs[True]))
        print('fast-bin paired pass', run, '/ 3 complete', flush=True)
    p.check_hashes(sources)
    p.write_csv(output / 'scene_stage_measurements.csv', measured)
    p.write_csv(output / 'paired_measurements.csv', pairs)
    timings = {}
    for variant in ('ray_reuse_control', 'bin_reduction'):
        values = [r['scene_service_ms'] for r in measured if r['variant'] == variant]
        timings[variant] = dict(median_ms=float(np.median(values)), mean_ms=float(np.mean(values)),
                               p95_ms=float(np.percentile(values, 95)), observed_max_ms=max(values))
    summary = dict(status='PASS_EXACT_BIN_REDUCTION_AND_PAIRED_LOCAL_BENCHMARK', work_date='2026-10-23',
                   source_sha256=sources, images=978, recordings=9, result_mismatches=0,
                   benchmark_images=52, passes=3, measurements=312, pairs=156,
                   order_counts=dict(Counter(r['first'] for r in pairs)), timings=timings,
                   paired_speedup_median=float(np.median([r['paired_speedup'] for r in pairs])),
                   environment=dict(host=platform.node(), python=sys.version.split()[0], numpy=np.__version__,
                                    opencv=cv2.__version__, opencv_threads=cv2.getNumThreads(),
                                    openblas_threads=os.environ['OPENBLAS_NUM_THREADS']),
                   approximate_minimum_used=False, tie_rule_changed=False, source_images_edited=False,
                   production_changed=False, end_to_end_latency_measured=False, physical_output=False, usable_for_ffb=False,
                   output_sha256={x.name: p.sha256(x) for x in output.iterdir() if x.is_file()})
    (output / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps({k: v for k, v in summary.items() if k not in ('source_sha256', 'output_sha256')}, indent=2))


if __name__ == '__main__':
    main()
