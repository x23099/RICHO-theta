"""Pre-fit dense audit near undersized high/low front grids, same detector/screen."""
import hashlib
import json
from pathlib import Path
import sys

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / 'src'))
from cone_dataset import read_csv, write_csv, sha256
from fisheye_intrinsic_calibration import Board, SCREEN, corner_rms
from extract import inspect
from recover_exports import union_fields, reference_match


def selected_frames(attempts, count):
    # Geometry-only selection, fixed before any intrinsic fit or residual exists.
    centres = [r['frame'] for r in attempts if r['reason'] == 'grid_too_small'
               and (r['centre_y'] < 240 or r['centre_y'] > 350)]
    return sorted({i for f in centres for i in range(max(1, f-20), min(count, f+20)+1)
                   if (i-1) % 5})


def main():
    output = HERE / 'dense_limits_audit_r01'
    if output.exists():
        raise ValueError('no dense audit overwrite')
    path = HERE / 'extraction_r01/observations.json'
    j = json.loads(path.read_text())
    sources = {str(p): sha256(p) for p in (path, Path(__file__), HERE/'extract.py', HERE/'recover_exports.py')}
    sources.update(j['source_sha256'])
    assert all(sha256(Path(p)) == value for p, value in sources.items())
    frames = set(selected_frames(j['attempts'], j['frames_decoded']))
    session = Path(json.loads((HERE/'intake_summary.json').read_text())['session'])
    original_rows = read_csv(session/'detections.csv')
    reference = cv2.imread(str(HERE/'raw_samples/raw_f000472.png'))
    board = Board(**j['board'])
    output.mkdir()
    (output/'raw_frames').mkdir()
    # Selection is frozen and written before running detection on any new frame.
    (output/'selection.json').write_text(json.dumps(dict(
        selected_frames=sorted(frames), margin_frames=20,
        rule='previous grid_too_small with centre_y<240 or >350; exclude primary sampled frames',
        detector_and_screens_unchanged=True, source_sha256=sources,
        intrinsic_solver_attempted=False), indent=2)+'\n')
    attempts, new_views = [], []
    old_points = [np.asarray(v['corners_native']) for v in j['retained_views']]
    cap = cv2.VideoCapture(str(session/'raw.avi'))
    cv2.setNumThreads(1)
    try:
        for i, row in enumerate(original_rows, 1):
            if i > max(frames):
                break
            ok, image = cap.read()
            assert ok
            if i not in frames:
                continue
            assert not reference_match(image, reference)[1]
            r = inspect(image, board)
            r.update(frame=i, time_sec=float(row['time_sec']), retained=False)
            if r['eligible']:
                points = np.asarray(r['corners_native'])
                minimum = min(corner_rms(points, old) for old in old_points)
                r['nearest_prior_pose_rms_px'] = minimum
                if minimum < SCREEN['duplicate_rms_px']:
                    r['reason'] = 'near_duplicate_pose'
                else:
                    file = output/'raw_frames'/f'raw_f{i:06d}.png'
                    assert cv2.imwrite(str(file), image)
                    assert np.array_equal(cv2.imread(str(file)), image)
                    r.update(retained=True, native_png=str(file.relative_to(HERE)), png_sha256=sha256(file),
                             decoded_bgr_sha256=hashlib.sha256(image.tobytes()).hexdigest())
                    new_views.append(r.copy())
                    old_points.append(points)
            attempts.append(r)
            if len(attempts) % 30 == 0:
                print('dense checked', len(attempts), '/', len(frames), 'new views', len(new_views), flush=True)
    finally:
        cap.release()
    assert len(attempts) == len(frames)
    assert all(sha256(Path(p)) == value for p, value in sources.items())
    csv_rows = [dict(r, corners_native=json.dumps(r['corners_native'])) for r in attempts]
    write_csv(output/'attempts.csv', csv_rows, fields=union_fields(csv_rows))
    from collections import Counter
    summary = dict(selected_frames=len(frames), attempted_frames=len(attempts),
                   new_eligible_distinct_views=len(new_views), retained_views=new_views,
                   counts=dict(Counter(r['reason'] for r in attempts)), source_sha256=sources,
                   intrinsic_solver_attempted=False, source_pixels_edited=False, usable_for_ffb=False)
    (output/'summary.json').write_text(json.dumps(summary, indent=2)+'\n')
    print(json.dumps({k:v for k,v in summary.items() if k not in ('source_sha256','retained_views')}, indent=2))


if __name__ == '__main__':
    main()
