"""Select exact saved metric rows, then extract native unannotated raw frames."""
import csv
import hashlib
import json
from pathlib import Path
import sys

import cv2

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
sys.path.insert(0,str(ROOT/'src'))
from cone_dataset import read_csv,write_csv,sha256


def row_sha(row):return hashlib.sha256(json.dumps(row,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def main():
    output=HERE/'originals_r01'
    if output.exists():raise ValueError('new output required; do not overwrite original samples')
    control=HERE.parent/'causal_availability_latency_r01/pending_control_r01'
    data_path=control/'pending_control_frame_metrics.csv';proof_path=control/'summary.json'
    proof=json.loads(proof_path.read_text())
    for name,h in proof['output_sha256'].items():assert sha256(control/name)==h
    sample_path=ROOT/'Experimental_results/2026-10-22/scene_uniform_validation_r01/intake_r01/native_sample_manifest.csv'
    ob_path=ROOT/'Experimental_results/2026-10-21/cone_known_height_pinhole_r01/results_r01/observed_pixels.csv'
    sources={str(p):sha256(p) for p in (Path(__file__),data_path,proof_path,sample_path,ob_path)}
    rows=[r for r in read_csv(data_path) if r['scenario']=='local_three_pass_median'];selected=[]
    for condition in ('cone_130','cone_200'):
        available=sorted([r for r in rows if r['condition']==condition and r['diagnostic_available']=='True'],key=lambda r:int(r['frame']))
        r=available[len(available)//2]
        selected.append((condition,r,'middle_available_frame_by_time_not_smallest_error'))
    selected.append(('occlusion_hold',next(r for r in rows if r['frame']=='1134'),'previously_audited_occlusion_frame_1134'))
    assert len({r['session'] for _,r,_ in selected})==1
    session=selected[0][1]['session']
    sample=next(r for r in read_csv(sample_path) if r['session']==session)
    raw=Path(sample['source_session_path'])/'raw.avi';expected=sample['source_raw_sha256']
    assert sha256(raw)==expected;sources[str(raw)]=expected
    observations={(r['session'],r['frame']):r for r in read_csv(ob_path)}
    wanted={int(r['frame']):(label,r,policy) for label,r,policy in selected}
    output.mkdir();cap=cv2.VideoCapture(str(raw));assert cap.isOpened();manifest=[]
    for frame in range(1,max(wanted)+1):
        ok,image=cap.read();assert ok and image.shape==(720,1280,3)
        if frame not in wanted:continue
        label,r,policy=wanted[frame];ob=observations[session,str(frame)]
        assert float(r['time_sec'])==float(ob['time_sec']) and r['reference_z_m']==ob['reference_z_m']
        name=f'{label}_raw_f{frame:06d}.png';path=output/name
        assert cv2.imwrite(str(path),image)
        decoded=cv2.imread(str(path));assert (decoded==image).all()
        manifest.append(dict(label=label,session=session,frame=frame,time_sec=r['time_sec'],condition=r['condition'],
            source_raw_path=str(raw),source_raw_sha256=expected,original_png=name,original_png_sha256=sha256(path),
            decoded_bgr_sha256=hashlib.sha256(image.tobytes()).hexdigest(),width=1280,height=720,original_image_edited=False,
            scenario=r['scenario'],diagnostic_available=r['diagnostic_available'],diagnostic_z_m=r['diagnostic_z_m'],reference_z_m=r['reference_z_m'],
            latest_completed_scene_frame=r['latest_completed_scene_frame'],quality_accepted=r['quality_accepted'],pose_available=r['pose_available'],
            pose_reason=r['pose_reason'],newer_scene_input_pending=r['newer_scene_input_pending'],physical_metric_verified=r['physical_metric_verified'],
            source_metric_csv=str(data_path),source_metric_row_sha256=row_sha(r),source_observed_csv=str(ob_path),source_observed_row_sha256=row_sha(ob),
            native_colour_pair_json=ob['native_colour_pair_json'],selection_policy=policy))
    cap.release();assert len(manifest)==3 and sha256(raw)==expected
    write_csv(output/'frame_manifest.csv',manifest)
    record=dict(status='EXTRACTED_THREE_UNEDITED_NATIVE_ORIGINALS_FOR_SEPARATE_VISUALIZATION',work_date='2026-10-23',
        source_sha256=sources,source_images_edited=False,post_recording_visualization=True,physical_output=False,
        output_sha256={p.name:sha256(p) for p in output.iterdir() if p.is_file()})
    (output/'summary.json').write_text(json.dumps(record,indent=2)+'\n')
    print(json.dumps([dict(label=r['label'],frame=r['frame'],diagnostic_z_m=r['diagnostic_z_m']) for r in manifest],indent=2))


if __name__=='__main__':main()
