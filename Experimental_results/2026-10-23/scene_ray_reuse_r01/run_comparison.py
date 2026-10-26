"""All 492 equivalence checks before alternating-order paired timing."""
from collections import Counter
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
GEO = ROOT / 'Experimental_results/2026-10-21/scene_vertical_gravity_r01'
UNIFORM = ROOT / 'Experimental_results/2026-10-22/scene_uniform_validation_r01'
SESSION = 'floor_cone_same_pose_r01_20261015_160621_378'
CAMERA = ROOT / 'Experimental_results/2026-10-21/front_fisheye_solver_audit_r01/angular_results_r01/angular_diagnostic_candidate.json'
FLOOR = ROOT / 'Experimental_results/2026-10-21/angular_metric_validation_r01/results_r01/floor_transform_candidate.json'
sys.path[:0] = [str(ROOT / 'src'), str(GEO), str(HERE)]
from cone_dataset import read_csv, write_csv, sha256
from angular_fisheye_geometry import camera_from_candidate
from curve_geometry import extract_curve_planes
from scene_geometry import infer_up, angle_degrees
from cached_curve_geometry import extract_cached_curve_planes


def canonical(value):
    def convert(v):
        if isinstance(v, np.generic):
            return v.item()
        raise TypeError(type(v))
    return json.dumps(value, sort_keys=True, allow_nan=False, default=convert)


def compute(image, camera, prior, candidate):
    lines = (extract_cached_curve_planes if candidate else extract_curve_planes)(image, camera)
    normals = np.array([r['normal'] for r in lines if r['accepted']]).reshape(-1, 3)
    return lines, infer_up(normals, prior)


def main():
    output = HERE / 'results_r01'
    if output.exists():
        raise ValueError('fresh output required')
    if os.environ.get('OPENBLAS_NUM_THREADS') != '1':
        raise ValueError('OPENBLAS_NUM_THREADS=1 required before Python starts')
    cv2.setNumThreads(1)
    paths = [Path(__file__), HERE / 'method.md', HERE / 'cached_curve_geometry.py',
             GEO / 'curve_geometry.py', GEO / 'scene_geometry.py', ROOT / 'src/angular_fisheye_geometry.py',
             ROOT / 'src/cone_dataset.py', CAMERA, FLOOR,
             UNIFORM / 'scene_results_r01/image_diagnostics.csv']
    sources = {str(p): sha256(p) for p in paths}
    camera = camera_from_candidate(json.loads(CAMERA.read_text()))
    prior = np.array(json.loads(FLOOR.read_text())['nominal_transform'])[:3, :3].T @ [0., 0., 1.]
    frames = read_csv(paths[-1])
    assert len(frames) == 492 and len({r['session'] for r in frames}) == 9
    checks = []
    benchmark_images = []
    for i, r in enumerate(frames):
        p = Path(r['source_native_png'])
        assert sha256(p) == r['png_sha256']
        sources[str(p)] = r['png_sha256']
        image = cv2.imread(str(p))
        assert image.shape == (720, 1280, 3) and image.dtype == np.uint8
        baseline = compute(image, camera, prior, False)
        candidate = compute(image, camera, prior, True)
        assert canonical(baseline) == canonical(candidate), (r['session'], r['frame'])
        up = baseline[1]
        assert bool(up['accepted']) == (r['accepted'] == 'True') and up['reason'] == r['reason']
        if up['accepted']:
            assert angle_degrees(up['up'], json.loads(r['up_optical_json'])) < 1e-5
        checks.append(dict(session=r['session'], frame=int(r['frame']), time_sec=float(r['time_sec']),
                           curves=len(baseline[0]), repeated_unprojections_avoided=len(baseline[0]),
                           repeated_ray_points_avoided=sum(len(x['actual_edge_pixels_json']) for x in baseline[0]),
                           all_curve_fields_exact=True, up_fields_exact=True,
                           frozen_single_image_decision_matches=True, up_accepted=bool(up['accepted']),
                           up_reason=up['reason'], physical_metric_verified=False, usable_for_ffb=False))
        if r['session'] == SESSION:
            benchmark_images.append((r, image))
        if (i + 1) % 50 == 0:
            print('equivalence', i + 1, '/ 492', flush=True)
    assert len(benchmark_images) == 52
    output.mkdir()
    write_csv(output / 'equivalence.csv', checks)
    # Save the passed precondition before timing; failure/interrupt remains visible.
    (output / 'equivalence_precondition.json').write_text(json.dumps(dict(
        status='PASS_EXACT_ALL_CURVES_AND_UP', images=len(checks), sessions=9,
        source_sha256=sources), indent=2) + '\n')
    for mode in (False, True):
        compute(benchmark_images[0][1], camera, prior, mode)
    measured = []
    pairs = []
    for run in range(1, 4):
        for index, (r, image) in enumerate(benchmark_images):
            order = (False, True) if (index + run) % 2 else (True, False)
            pair = {}
            results = {}
            for position, mode in enumerate(order):
                start = time.perf_counter_ns()
                result = compute(image, camera, prior, mode)
                elapsed = (time.perf_counter_ns() - start) / 1e6
                variant = 'same_frame_reuse' if mode else 'baseline'
                pair[variant] = elapsed
                results[mode] = result
                measured.append(dict(session=SESSION, frame=int(r['frame']), time_sec=float(r['time_sec']),
                                     run=run, variant=variant, position_in_pair=position,
                                     scene_service_ms=elapsed, image_read_in_timing=False,
                                     physical_output=False, usable_for_ffb=False))
            assert canonical(results[False]) == canonical(results[True])
            pairs.append(dict(frame=int(r['frame']), run=run,
                              first='candidate' if order[0] else 'baseline',
                              baseline_ms=pair['baseline'], candidate_ms=pair['same_frame_reuse'],
                              paired_speedup=pair['baseline'] / pair['same_frame_reuse']))
        print('paired benchmark', run, '/ 3 complete', flush=True)
    assert all(sha256(Path(p)) == h for p, h in sources.items())
    write_csv(output / 'scene_stage_measurements.csv', measured)
    write_csv(output / 'paired_measurements.csv', pairs)
    stats = {}
    for variant in ('baseline', 'same_frame_reuse'):
        values = [r['scene_service_ms'] for r in measured if r['variant'] == variant]
        stats[variant] = dict(measurements=len(values), mean_ms=float(np.mean(values)),
                              median_ms=float(np.median(values)), p95_ms=float(np.percentile(values, 95)),
                              observed_max_ms=float(max(values)))
    summary = dict(status='PASS_EXACT_EQUIVALENCE_AND_COMPLETED_LOCAL_PAIRED_BENCHMARK',
                   work_date='2026-10-23', source_sha256=sources,
                   equivalence_images=492, equivalence_sessions=9,
                   all_curve_and_up_mismatches=0, accepted_images=sum(r['up_accepted'] for r in checks),
                   curve_rows=sum(r['curves'] for r in checks),
                   avoided_subset_unprojections=sum(r['repeated_unprojections_avoided'] for r in checks),
                   avoided_subset_ray_points=sum(r['repeated_ray_points_avoided'] for r in checks),
                   benchmark_session=SESSION, benchmark_unique_images=52, passes=3,
                   measurement_count=len(measured), pair_count=len(pairs),
                   order_counts=dict(Counter(r['first'] for r in pairs)),
                   paired_speedup_median=float(np.median([r['paired_speedup'] for r in pairs])),
                   timings=stats, warmup_each_variant=1, image_decode_in_timing=False,
                   environment=dict(host=platform.node(), python=sys.version.split()[0],
                                    numpy=np.__version__, opencv=cv2.__version__,
                                    opencv_threads=cv2.getNumThreads(), openblas_threads=os.environ['OPENBLAS_NUM_THREADS']),
                   source_images_edited=False, original_geometry_edited=False,
                   production_changed=False, physical_metric_verified=False,
                   end_to_end_latency_measured=False, physical_output=False, usable_for_ffb=False,
                   output_sha256={p.name: sha256(p) for p in output.iterdir() if p.is_file()})
    (output / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps({k: v for k, v in summary.items() if k not in ('source_sha256', 'output_sha256')}, indent=2))


if __name__ == '__main__':
    main()
