"""One continuous real floor/cone sequence: safe native intake, no ROS/FFB."""
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
from analyze_field_recording import safe_extract_archive
from cone_dataset import read_csv,sha256,write_csv
from cone_observation import CAMERA_KEYS

ARCHIVE=Path('/home/robo25/Downloads/floor_cone_same_pose_r01_20261015_160621_378.tar.xz')
DESTINATION=ROOT/'recordings/2026-10-15_floor_cone_same_pose_intake_r01'


def main():
    if DESTINATION.exists() or (HERE/'intake_summary.json').exists():raise ValueError('new intake required; no overwrite')
    digest=sha256(ARCHIVE)
    safe_extract_archive(ARCHIVE,DESTINATION,3*1024**3)
    videos=list(DESTINATION.rglob('raw.avi'))
    if len(videos)!=1:raise ValueError('exactly one continuous raw session expected')
    session=videos[0].parent
    files={name:session/name for name in ('raw.avi','metadata.json','detections.csv')}
    if any(not f.is_file() or f.is_symlink() for f in files.values()):raise ValueError('complete regular session required')
    hashes={name:sha256(f) for name,f in files.items()}
    meta=json.loads(files['metadata.json'].read_text())
    p=meta['parameters']
    if str(meta.get('device'))!='0':raise ValueError('local real camera source 0 expected')
    if (int(meta['requested_camera_width']),int(meta['requested_camera_height']))!=(1280,720):raise ValueError('native1280x720 required')
    config_path=ROOT/'Experimental_results/2026-10-08/floor_reference_preparation/floor_reference_capture_config.json'
    config=json.loads(config_path.read_text())
    if any(p[k]!=config[k] for k in CAMERA_KEYS):raise ValueError('recorded geometry differs from fixed capture config')
    if any(p.get(k)!=0 for k in ('enable_ai','collision_ffb_publish_enabled','collision_ffb_relay_enabled')):raise ValueError('expected AI/FFB/relay disabled capture')
    rows=read_csv(files['detections.csv'])
    times=[float(r['time_sec']) for r in rows]
    if len(rows)<12 or [int(r['frame']) for r in rows]!=list(range(1,len(rows)+1)) or any(not math.isfinite(t) or t<0 for t in times) or any(b<=a for a,b in zip(times,times[1:])):
        raise ValueError('contiguous frames and finite increasing times required')
    sample_ids=set(np.linspace(1,len(rows),12,dtype=int).tolist())
    folder=HERE/'raw_samples';folder.mkdir(exist_ok=False)
    manifest=[]
    capture=cv2.VideoCapture(str(files['raw.avi']))
    if not capture.isOpened():raise ValueError('raw video not readable')
    try:
        for number in range(1,len(rows)+1):
            ok,pixels=capture.read()
            if not ok or pixels.shape!=(720,1280,3):raise ValueError('raw/CSV/native shape mismatch')
            if number in sample_ids:
                target=folder/f'same_pose_f{number:06d}.png'
                if not cv2.imwrite(str(target),pixels):raise ValueError('PNG export failed')
                pixel_digest=hashlib.sha256(pixels.tobytes()).hexdigest()
                if hashlib.sha256(cv2.imread(str(target)).tobytes()).hexdigest()!=pixel_digest:raise ValueError('raw PNG pixels changed')
                manifest.append(dict(file=str(target.relative_to(HERE)),session=session.name,frame=number,time_sec=times[number-1],
                    width=1280,height=720,png_sha256=sha256(target),decoded_bgr_sha256=pixel_digest,
                    source_raw_sha256=hashes['raw.avi'],reason='12 uniformly selected unedited native frames before phase assignment'))
        if capture.read()[0]:raise ValueError('raw has additional frames beyond CSV')
    finally:capture.release()
    odom=[r for r in rows if r.get('odom_available')=='1']
    velocities={}
    for key in ('odom_linear_mps','odom_angular_radps'):
        values=[float(r[key]) for r in odom if r.get(key) not in (None,'')]
        if any(not math.isfinite(v) for v in values):raise ValueError('nonfinite odom')
        velocities['max_abs_'+key]=max(map(abs,values),default=None)
    model=ROOT/'runs/cone/train_ab_augmented_v03_local_20261014_r01/yolov8n/weights/best.pt'
    expected_model_hash='3a6e124adb15c16efd7d22c853406066371f48873c82f1d3cfc445b22ae5997b'
    if sha256(model)!=expected_model_hash:raise ValueError('frozen model changed')
    if sha256(ARCHIVE)!=digest or any(sha256(files[k])!=v for k,v in hashes.items()):raise ValueError('source changed during intake')
    write_csv(HERE/'raw_sample_manifest.csv',manifest)
    write_csv(HERE/'video_plan.csv',[dict(session_dir=str(session),note='continuous floor-cone1.3-cone2.0-floor sequence; phase boundaries not yet assigned; no bbox GT')])
    result=dict(status='PASS_CONTINUOUS_SEQUENCE_INTAKE_NOT_POSITION_ACCURACY',archive=str(ARCHIVE),archive_sha256=digest,
        session=str(session),inputs=[dict(path=str(session),hashes=hashes,metadata=meta)],source_sha256=hashes,
        metadata=meta,total_frames=len(rows),last_time_sec=times[-1],sample_span_sec=times[-1]-times[0],
        sample_read_rate_fps=(len(rows)-1)/(times[-1]-times[0]),native_samples=len(manifest),all_raw_frames_decoded=True,
        odom_available_frames=len(odom),**velocities,
        model=dict(path=str(model),sha256=expected_model_hash,confidence=.5,imgsz=960,nms_iou=.7,max_det=300),
        protocol_reference='floor -> central front-edge z1.30 -> central front-edge z2.00 -> floor, per requested procedure; image review pending',
        reported_height_from_prior_user_confirmation_m=.59,height_unchanged_in_this_session_not_independently_measured=True,
        physical_output=False,production_settings_changed=False,script_sha256=sha256(Path(__file__)),capture_config_sha256=sha256(config_path))
    (HERE/'intake_summary.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:result[k] for k in ('status','total_frames','last_time_sec','sample_read_rate_fps','native_samples','odom_available_frames',*velocities.keys())},indent=2))


if __name__=='__main__':main()
