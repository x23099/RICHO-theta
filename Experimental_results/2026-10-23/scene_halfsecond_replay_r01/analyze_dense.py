"""Fixed cached geometry, three timing passes, immutable per-session checkpoints."""
from collections import defaultdict
import hashlib
import json
import os
from pathlib import Path
import platform
import sys
import time

import cv2
import numpy as np

from dense_common import HERE, ROOT, UNIFORM, REUSE, GEO, CAMERA, FLOOR, canonical, compute
from dense_common import read_csv, write_csv, sha256, check_manifest, check_hashes
from angular_fisheye_geometry import camera_from_candidate


def common_matches(pose, normals, old):
    assert bool(pose['accepted']) == (old['accepted'] == 'True')
    assert pose['reason'] == old['reason']
    assert len(normals) == int(old['distinct_ray_planes'])
    assert pose['inliers'] == int(old['inliers'])
    assert pose['up'] == (json.loads(old['up_optical_json']) if old['up_optical_json'] else None)
    for field in ('median_residual_deg', 'normal_span_deg', 'rank_gap_ratio'):
        assert pose[field] == (float(old[field]) if old[field] else None)


def main():
    output = HERE / 'scene_results_r01'
    if (output / 'summary.json').exists():
        raise ValueError('completed output is frozen')
    if os.environ.get('OPENBLAS_NUM_THREADS') != '1':
        raise ValueError('OPENBLAS_NUM_THREADS=1 required before start')
    cv2.setNumThreads(1)
    intake = HERE / 'intake_r01'
    check_manifest(intake / 'summary.json')
    check_manifest(REUSE / 'results_r01/summary.json')
    paths = [Path(__file__), HERE / 'dense_common.py', HERE / 'method.md',
             intake / 'summary.json', intake / 'sampling_plan.json', intake / 'native_sample_manifest.csv',
             REUSE / 'cached_curve_geometry.py', REUSE / 'run_comparison.py', REUSE / 'results_r01/summary.json',
             GEO / 'scene_geometry.py', ROOT / 'src/angular_fisheye_geometry.py',
             ROOT / 'src/fisheye_floor_geometry.py', CAMERA, FLOOR,
             UNIFORM / 'scene_results_r01/image_diagnostics.csv']
    sources = {str(p): sha256(p) for p in paths}
    run_spec = dict(work_date='2026-10-23', source_sha256=sources, passes=3,
                    warmup_each_session=1, image_decode_in_timing=False)
    if output.exists():
        assert json.loads((output / 'run_spec.json').read_text()) == run_spec
    else:
        output.mkdir()
        (output / 'run_spec.json').write_text(json.dumps(run_spec, indent=2) + '\n')
    camera = camera_from_candidate(json.loads(CAMERA.read_text()))
    prior = np.array(json.loads(FLOOR.read_text())['nominal_transform'])[:3, :3].T @ [0., 0., 1.]
    old = {(r['session'], int(r['frame'])): r for r in read_csv(paths[-1])}
    grouped = defaultdict(list)
    for r in read_csv(intake / 'native_sample_manifest.csv'):
        grouped[r['session']].append(r)
    all_features = []; all_timings = []; all_sessions = []
    checkpoint = output / 'sessions'
    checkpoint.mkdir(exist_ok=True)
    for session, group in sorted(grouped.items()):
        folder = checkpoint / session
        if (folder / 'complete.json').exists():
            proof = json.loads((folder / 'complete.json').read_text())
            assert proof['run_spec_sha256'] == sha256(output / 'run_spec.json')
            assert sha256(folder / 'data.json') == proof['output_sha256']['data.json']
            data = json.loads((folder / 'data.json').read_text())
            for r in group:
                assert sha256(Path(r['source_native_png'])) == r['png_sha256']
            all_features.extend(data['features']); all_timings.extend(data['timings']); all_sessions.append(data['session'])
            print('resumed', session, flush=True)
            continue
        if folder.exists():
            raise ValueError('partial session preserved; new output version required')
        # Decode one native image at a time; do not retain all recordings in RAM.
        compute(cv2.imread(group[0]['source_native_png']), camera, prior, True)
        features = []; timings = []; expected = {}
        for run in range(1, 4):
            for i, r in enumerate(group):
                p = Path(r['source_native_png'])
                assert sha256(p) == r['png_sha256']
                image = cv2.imread(str(p))
                assert image.shape == (720, 1280, 3) and image.dtype == np.uint8
                start = time.perf_counter_ns()
                curves, pose = compute(image, camera, prior, True)
                elapsed = (time.perf_counter_ns() - start) / 1e6
                encoded = canonical((curves, pose))
                signature = hashlib.sha256(encoded.encode()).hexdigest()
                frame = int(r['frame'])
                if run == 1:
                    expected[frame] = signature
                    normals = [c['normal'] for c in curves if c['accepted']]
                    common = r['sparse_1s_member'] == 'True'
                    if common:
                        common_matches(pose, normals, old[session, frame])
                    features.append(dict(session=session, frame=frame, time_sec=float(r['time_sec']),
                                         sparse_1s_member=common, accepted=bool(pose['accepted']), reason=pose['reason'],
                                         up_optical_json=json.dumps(pose['up']) if pose['up'] is not None else '',
                                         distinct_ray_planes=len(normals), inliers=pose['inliers'],
                                         curve_rows=len(curves), candidate_and_up_sha256=signature,
                                         full_pose_json=canonical(pose), common_1s_result_matches=common,
                                         source_native_png=str(p), png_sha256=r['png_sha256'],
                                         physical_metric_verified=False, usable_for_ffb=False))
                else:
                    assert expected[frame] == signature, (session, frame, run)
                timings.append(dict(session=session, frame=frame, time_sec=float(r['time_sec']), run=run,
                                    scene_service_ms=elapsed, image_decode_in_timing=False,
                                    physical_output=False, usable_for_ffb=False))
                if (i + 1) % 50 == 0:
                    print('scene', session, 'pass', run, i + 1, '/', len(group), flush=True)
            print('pass complete', session, run, '/ 3', flush=True)
        stats = dict(session=session, images=len(group),
                     sparse_images=sum(r['sparse_1s_member'] for r in features),
                     accepted_images=sum(r['accepted'] for r in features),
                     accepted_sparse_images=sum(r['accepted'] and r['sparse_1s_member'] for r in features),
                     scene_median_ms=float(np.median([r['scene_service_ms'] for r in timings])),
                     scene_p95_ms=float(np.percentile([r['scene_service_ms'] for r in timings], 95)),
                     scene_max_ms=max(r['scene_service_ms'] for r in timings), physical_metric_verified=False, usable_for_ffb=False)
        folder.mkdir()
        (folder / 'data.json').write_text(json.dumps(dict(features=features, timings=timings, session=stats), indent=2) + '\n')
        (folder / 'complete.json').write_text(json.dumps(dict(run_spec_sha256=sha256(output / 'run_spec.json'),
                    output_sha256={'data.json': sha256(folder / 'data.json')}), indent=2) + '\n')
        all_features.extend(features); all_timings.extend(timings); all_sessions.append(stats)
        print('session complete', session, 'accepted', stats['accepted_images'], '/', len(group), flush=True)
    check_hashes(sources)
    assert sum(r['sparse_1s_member'] for r in all_features) == 492
    assert sum(r['accepted'] and r['sparse_1s_member'] for r in all_features) == 27
    for name, data in [('image_diagnostics.csv', all_features), ('scene_stage_measurements.csv', all_timings),
                       ('session_summary.csv', all_sessions)]:
        write_csv(output / name, data)
    summary = dict(status='COMPLETED_FIXED_HALFSECOND_SCENE_AND_THREE_PASS_COST', work_date='2026-10-23',
                   source_sha256=sources, sessions=9, sampled_images=len(all_features),
                   common_1s_images=492, common_1s_mismatches=0,
                   accepted_images=sum(r['accepted'] for r in all_features),
                   measurements=len(all_timings), passes=3, all_pass_results_exact=True,
                   environment=dict(host=platform.node(), python=sys.version.split()[0], numpy=np.__version__,
                                    opencv=cv2.__version__, opencv_threads=cv2.getNumThreads(),
                                    openblas_threads=os.environ['OPENBLAS_NUM_THREADS']),
                   metric_labels_used_for_pose=False, original_images_edited=False,
                   physical_output=False, usable_for_ffb=False,
                   output_sha256={p.name: sha256(p) for p in output.iterdir() if p.is_file()})
    (output / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps({k: v for k, v in summary.items() if k not in ('source_sha256', 'output_sha256')}, indent=2))


if __name__ == '__main__':
    main()
