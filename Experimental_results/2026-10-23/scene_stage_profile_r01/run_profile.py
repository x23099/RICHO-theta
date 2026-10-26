"""All-image exact result checks, then alternating paired instrumentation audit."""
from collections import Counter, defaultdict
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
DENSE = HERE.parent / 'scene_halfsecond_replay_r01'
REUSE = HERE.parent / 'scene_ray_reuse_r01'
GEO = ROOT / 'Experimental_results/2026-10-21/scene_vertical_gravity_r01'
sys.path[:0] = [str(ROOT / 'src'), str(REUSE), str(GEO), str(DENSE), str(HERE)]
from dense_common import CAMERA, FLOOR, check_manifest, check_hashes
from run_comparison import canonical, compute, SESSION
from cone_dataset import read_csv, write_csv, sha256
from angular_fisheye_geometry import camera_from_candidate
from profile_curve import compute_profiled, STAGES


def stage_summary(rows, population):
    wall = float(np.mean([r['wall_ns'] for r in rows]))
    result = []
    for stage in (*STAGES, 'other_and_instrumentation'):
        values = np.array([r[stage + '_ns'] for r in rows], float) / 1e6
        result.append(dict(population=population, stage=stage, measurements=len(rows),
                           mean_ms=float(values.mean()), median_ms=float(np.median(values)),
                           p95_ms=float(np.percentile(values, 95)),
                           share_of_mean_wall_percent=float(values.mean() * 1e6 / wall * 100),
                           total_wall_mean_ms=wall / 1e6, physical_output=False, usable_for_ffb=False))
    return result


def main():
    output = HERE / 'results_r01'
    if output.exists():
        raise ValueError('fresh profiling output required')
    if os.environ.get('OPENBLAS_NUM_THREADS') != '1':
        raise ValueError('OPENBLAS_NUM_THREADS=1 required before start')
    cv2.setNumThreads(1)
    check_manifest(DENSE / 'scene_results_r01/summary.json')
    check_manifest(DENSE / 'verification_r01/summary.json')
    paths = [Path(__file__), HERE / 'profile_curve.py', HERE / 'method.md',
             DENSE / 'dense_common.py', DENSE / 'scene_results_r01/summary.json',
             DENSE / 'scene_results_r01/image_diagnostics.csv', DENSE / 'verification_r01/summary.json',
             REUSE / 'cached_curve_geometry.py', REUSE / 'run_comparison.py',
             GEO / 'scene_geometry.py', ROOT / 'src/angular_fisheye_geometry.py',
             ROOT / 'src/fisheye_floor_geometry.py', CAMERA, FLOOR]
    sources = {str(p): sha256(p) for p in paths}
    camera = camera_from_candidate(json.loads(CAMERA.read_text()))
    prior = np.array(json.loads(FLOOR.read_text())['nominal_transform'])[:3, :3].T @ [0., 0., 1.]
    images = read_csv(paths[5])
    assert len(images) == 978
    profiled = []; benchmark = []
    compute_profiled(cv2.imread(images[0]['source_native_png']), camera, prior)
    for index, r in enumerate(images):
        p = Path(r['source_native_png']); assert sha256(p) == r['png_sha256']
        sources[str(p)] = r['png_sha256']
        image = cv2.imread(str(p))
        curves, up, record = compute_profiled(image, camera, prior)
        signature = hashlib.sha256(canonical((curves, up)).encode()).hexdigest()
        assert signature == r['candidate_and_up_sha256'], (r['session'], r['frame'])
        profiled.append(dict(session=r['session'], frame=int(r['frame']), time_sec=float(r['time_sec']),
                             accepted=bool(up['accepted']), reason=up['reason'], **record,
                             all_candidate_and_up_fields_exact=True, image_decode_in_timing=False,
                             physical_output=False, usable_for_ffb=False))
        if r['session'] == SESSION and r['sparse_1s_member'] == 'True':
            benchmark.append((r, image))
        if (index + 1) % 50 == 0:
            print('profile equivalence', index + 1, '/ 978', flush=True)
    assert len(benchmark) == 52
    output.mkdir()
    write_csv(output / 'all_image_profile.csv', profiled)
    (output / 'equivalence_precondition.json').write_text(json.dumps(dict(
        status='PASS_EXACT_978_ALL_CANDIDATES_AND_UP', source_sha256=sources), indent=2) + '\n')
    compute(benchmark[0][1], camera, prior, True)
    compute_profiled(benchmark[0][1], camera, prior)
    pairs = []; detailed = []
    for run in range(1, 4):
        for index, (r, image) in enumerate(benchmark):
            order = (False, True) if (index + run) % 2 else (True, False)
            results = {}; elapsed = {}
            for position, instrumented in enumerate(order):
                start = time.perf_counter_ns()
                if instrumented:
                    curves, up, record = compute_profiled(image, camera, prior)
                else:
                    curves, up = compute(image, camera, prior, True)
                wall = time.perf_counter_ns() - start
                results[instrumented] = (curves, up)
                elapsed[instrumented] = wall / 1e6
                if instrumented:
                    detailed.append(dict(session=SESSION, frame=int(r['frame']), run=run,
                                         position_in_pair=position, **record, outer_call_wall_ns=wall,
                                         image_decode_in_timing=False, physical_output=False, usable_for_ffb=False))
            assert canonical(results[False]) == canonical(results[True])
            pairs.append(dict(session=SESSION, frame=int(r['frame']), run=run,
                              first='profiled' if order[0] else 'plain',
                              plain_wall_ms=elapsed[False], profiled_wall_ms=elapsed[True],
                              profile_minus_plain_ms=elapsed[True] - elapsed[False],
                              profiled_over_plain_ratio=elapsed[True] / elapsed[False],
                              all_candidate_and_up_fields_exact=True))
        print('paired instrumentation pass', run, '/ 3 complete', flush=True)
    check_hashes(sources)
    aggregates = stage_summary(profiled, 'all_978_images_one_pass')
    groups = defaultdict(list)
    for r in profiled:
        groups[r['session']].append(r)
    for session, rows in sorted(groups.items()):
        aggregates.extend(stage_summary(rows, 'session_one_pass:' + session))
    aggregates.extend(stage_summary(detailed, 'fixed_52_images_three_pass'))
    for name, rows in [('paired_measurements.csv', pairs), ('paired_stage_measurements.csv', detailed),
                       ('stage_summary.csv', aggregates)]:
        write_csv(output / name, rows)
    focus = [r for r in aggregates if r['population'] == 'fixed_52_images_three_pass']
    profile_stats = dict(plain_median_ms=float(np.median([r['plain_wall_ms'] for r in pairs])),
                         profiled_median_ms=float(np.median([r['profiled_wall_ms'] for r in pairs])),
                         paired_delta_median_ms=float(np.median([r['profile_minus_plain_ms'] for r in pairs])),
                         paired_ratio_median=float(np.median([r['profiled_over_plain_ratio'] for r in pairs])))
    summary = dict(status='PASS_EXACT_EQUIVALENCE_AND_COMPLETED_EXCLUSIVE_SCENE_PROFILE',
                   work_date='2026-10-23', source_sha256=sources, images=978, recordings=9,
                   result_mismatches=0, fixed_benchmark_images=52, fixed_passes=3, paired_measurements=156,
                   order_counts=dict(Counter(r['first'] for r in pairs)),
                   instrumentation_comparison=profile_stats,
                   stage_budget_sorted=sorted(focus, key=lambda r: -r['mean_ms']),
                   environment=dict(host=platform.node(), python=sys.version.split()[0], numpy=np.__version__,
                                    opencv=cv2.__version__, opencv_threads=cv2.getNumThreads(),
                                    openblas_threads=os.environ['OPENBLAS_NUM_THREADS']),
                   optimization_implemented=False, image_decode_in_timing=False,
                   end_to_end_latency_measured=False, source_images_edited=False,
                   production_changed=False, physical_output=False, usable_for_ffb=False,
                   output_sha256={p.name: sha256(p) for p in output.iterdir() if p.is_file()})
    (output / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps({k: v for k, v in summary.items() if k not in ('source_sha256', 'output_sha256')}, indent=2))


if __name__ == '__main__':
    main()
