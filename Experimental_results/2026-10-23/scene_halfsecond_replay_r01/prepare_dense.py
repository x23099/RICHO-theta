"""Predeclare denser nested time samples and preserve native decoded pixels."""
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np

from dense_common import HERE, ROOT, UNIFORM, read_csv, write_csv, sha256, time_grid, check_manifest, check_hashes


def main():
    output = HERE / 'intake_r01'
    local = ROOT / 'recordings/2026-10-23_scene_halfsecond_r01'
    if output.exists() or local.exists():
        raise ValueError('fresh intake and native image destination required')
    old_plan = UNIFORM / 'intake_r01/sampling_plan.json'
    old_images = UNIFORM / 'intake_r01/native_sample_manifest.csv'
    old_proof = UNIFORM / 'intake_r01/summary.json'
    check_manifest(old_proof)
    paths = [Path(__file__), HERE / 'dense_common.py', HERE / 'method.md',
             UNIFORM / 'prepare.py', old_plan, old_images, old_proof]
    sources = {str(p): sha256(p) for p in paths}
    old = {(r['session'], int(r['frame'])): r for r in read_csv(old_images)}
    entries = json.loads(old_plan.read_text())['sessions']
    plan = []
    for entry in entries:
        folder = Path(entry['session_path'])
        for name in ('raw.avi', 'detections.csv', 'metadata.json'):
            sources[str(folder / name)] = sha256(folder / name)
        rows = read_csv(folder / 'detections.csv')
        selected, duplicates = time_grid(rows, .5)
        sparse, _ = time_grid(rows, 1.)
        expected = {r['frame'] for r in sparse}
        assert sparse == entry['selected']
        assert expected <= {r['frame'] for r in selected}
        assert expected == {f for s, f in old if s == entry['session']}
        plan.append(dict(session=entry['session'], session_path=str(folder), raw_frames=len(rows),
                         interval_sec=.5, duplicate_target_frames_skipped=duplicates,
                         first_time_sec=entry['first_time_sec'], last_time_sec=entry['last_time_sec'],
                         selected=[dict(r, sparse_1s_member=r['frame'] in expected) for r in selected]))
    assert len(plan) == 9 and sum(p['raw_frames'] for p in plan) == 14526
    output.mkdir()
    local.mkdir(parents=True)
    fixed = dict(work_date='2026-10-23', source_sha256=sources, sessions=plan,
                 selection_precedes_decode_and_scene_results=True, metric_labels_used=False)
    (output / 'sampling_plan.json').write_text(json.dumps(fixed, indent=2) + '\n')
    manifest = []; session_rows = []
    for entry in plan:
        folder = Path(entry['session_path']); session = entry['session']
        targets = {r['frame']: r for r in entry['selected']}
        destination = local / session
        destination.mkdir()
        cap = cv2.VideoCapture(str(folder / 'raw.avi'))
        assert cap.isOpened()
        count = 0; reused = 0
        try:
            while True:
                ok, image = cap.read()
                if not ok:
                    break
                count += 1
                assert image.shape == (720, 1280, 3) and image.dtype == np.uint8
                if count not in targets:
                    continue
                decoded = hashlib.sha256(image.tobytes()).hexdigest()
                original = old.get((session, count))
                if original:
                    p = Path(original['source_native_png'])
                    assert sha256(p) == original['png_sha256']
                    assert decoded == original['decoded_bgr_sha256']
                    assert np.array_equal(cv2.imread(str(p)), image)
                    reused += 1
                else:
                    p = destination / f'raw_f{count:06d}.png'
                    assert cv2.imwrite(str(p), image)
                    assert np.array_equal(cv2.imread(str(p)), image)
                r = targets[count]
                manifest.append(dict(session=session, source_session_path=str(folder), frame=count,
                                     target_time_sec=r['target_time_sec'], time_sec=r['time_sec'],
                                     sparse_1s_member=r['sparse_1s_member'], source_native_png=str(p),
                                     png_sha256=sha256(p), decoded_bgr_sha256=decoded,
                                     source_raw_sha256=sources[str(folder / 'raw.avi')],
                                     width=1280, height=720, reused_original_png=bool(original),
                                     image_edited=False, usable_for_ffb=False))
        finally:
            cap.release()
        assert count == entry['raw_frames']
        session_rows.append(dict(session=session, decoded_frames=count, sampled_frames=len(targets),
                                 reused_1s_images=reused, additional_images=len(targets) - reused))
        print('sampled', session, len(targets), 'reused', reused, flush=True)
    check_hashes(sources)
    assert sum(r['reused_1s_images'] for r in session_rows) == 492
    write_csv(output / 'native_sample_manifest.csv', manifest)
    write_csv(output / 'sessions.csv', session_rows)
    summary = dict(status='PASS_NESTED_HALFSECOND_NATIVE_SAMPLING', work_date='2026-10-23',
                   source_sha256=sources, sessions=9, decoded_frames=14526,
                   sampled_images=len(manifest), reused_1s_images=492,
                   additional_images=len(manifest) - 492, source_images_edited=False,
                   physical_output=False, usable_for_ffb=False,
                   output_sha256={p.name: sha256(p) for p in output.iterdir() if p.is_file()})
    (output / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps({k: v for k, v in summary.items() if k not in ('source_sha256', 'output_sha256')}, indent=2))


if __name__ == '__main__':
    main()
