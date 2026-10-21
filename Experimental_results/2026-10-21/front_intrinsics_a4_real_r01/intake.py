"""Safe native capture intake. No calibration, detector, ROS, GPU, or hardware."""
import hashlib
import json
import math
from pathlib import Path
import sys
import cv2
import numpy as np

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
sys.path.insert(0,str(ROOT/'src'))
from analyze_field_recording import safe_extract_archive,summarize_session_integrity
from cone_dataset import read_csv,write_csv,sha256

ARCHIVE=Path('/home/robo25/Downloads/front_fisheye_intrinsic_a4_r01_20261021_170229_641.tar.xz')
DESTINATION=ROOT/'recordings/2026-10-21_front_intrinsic_a4_intake_r01'


def main():
    if DESTINATION.exists() or (HERE/'intake_summary.json').exists():
        raise ValueError('new intake required; no overwrite')
    digest=sha256(ARCHIVE)
    safe_extract_archive(ARCHIVE,DESTINATION,8*1024**3)
    videos=list(DESTINATION.rglob('raw.avi'))
    if len(videos)!=1:
        raise ValueError('one raw session required')
    session=videos[0].parent
    files=[session/n for n in ('raw.avi','metadata.json','detections.csv','bev.avi','detection.avi')]
    assert all(p.is_file() and not p.is_symlink() for p in files)
    hashes={str(p):sha256(p) for p in [ARCHIVE,*files]}
    rows=read_csv(session/'detections.csv')
    times=[float(r['time_sec']) for r in rows]
    assert rows and [int(r['frame']) for r in rows]==list(range(1,len(rows)+1))
    assert all(math.isfinite(t) and t>=0 for t in times) and all(b>a for a,b in zip(times,times[1:]))
    folder=HERE/'raw_samples'
    folder.mkdir()
    selected=set(np.linspace(1,len(rows),20,dtype=int))
    manifest=[]
    cap=cv2.VideoCapture(str(session/'raw.avi'))
    assert cap.isOpened()
    try:
        for number,r in enumerate(rows,1):
            ok,image=cap.read()
            assert ok and image.shape==(720,1280,3),'native raw/CSV mismatch'
            if number in selected:
                path=folder/f'raw_f{number:06d}.png'
                assert cv2.imwrite(str(path),image)
                pixel_hash=hashlib.sha256(image.tobytes()).hexdigest()
                assert hashlib.sha256(cv2.imread(str(path)).tobytes()).hexdigest()==pixel_hash
                manifest.append(dict(file=str(path.relative_to(HERE)),session=session.name,frame=number,
                    time_sec=times[number-1],width=1280,height=720,png_sha256=sha256(path),
                    decoded_bgr_sha256=pixel_hash,source_raw_sha256=hashes[str(session/'raw.avi')],
                    image_edited=False,reason='20 uniform native review frames, prior to target selection'))
        assert not cap.read()[0],'extra raw frames'
    finally:
        cap.release()
    assert all(sha256(Path(p))==h for p,h in hashes.items()) and sha256(ARCHIVE)==digest
    metadata=json.loads((session/'metadata.json').read_text())
    write_csv(HERE/'raw_sample_manifest.csv',manifest)
    summary=dict(status='COMPLETE_NATIVE_INTAKE_NOT_CALIBRATION_APPROVAL',archive=str(ARCHIVE),session=str(session),
        frames=len(rows),last_time_sec=times[-1],recording_rate_fps=(len(rows)-1)/(times[-1]-times[0]),
        integrity=summarize_session_integrity(session,str(ARCHIVE)),metadata=metadata,
        measured_square_mm=20.0,user_target='person-held moving paper board only; ignore stationary window checkerboard',
        detector_target_not_yet_selected=True,source_sha256=hashes,script_sha256=sha256(Path(__file__)),
        original_images_edited=False,physical_output=False,usable_for_ffb=False)
    (HERE/'intake_summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps({k:summary[k] for k in ('frames','last_time_sec','recording_rate_fps','session','integrity')},indent=2))


if __name__=='__main__':
    main()
