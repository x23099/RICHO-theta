"""Native occlusion example + common-valid secondary bookkeeping, no filtering."""
import hashlib
import json
from pathlib import Path
import sys

import cv2
import numpy as np

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parents[2]/'src'))
from cone_dataset import read_csv,sha256,write_csv
from evaluate_floor_reference import load_raw_frames


def main():
    output=HERE/'occlusion_diagnosis_r01'
    if output.exists():raise ValueError('new diagnostic required; no overwrite')
    intake=json.loads((HERE/'intake_summary.json').read_text())
    source=HERE/'analysis_r01/observations.csv'
    rows=read_csv(source)
    names=('recorded58','measured59','frozen_centre2')
    paired=[]
    for phase in ('cone_130','cone_200'):
        common=None
        for name in names:
            used={int(r['frame']) for r in rows if r['phase']==phase and r['model']==name and r['target_hypothesis_used']=='True'}
            common=used if common is None else common&used
        for name in names:
            selected=[r for r in rows if r['phase']==phase and r['model']==name and int(r['frame']) in common]
            paired.append(dict(phase=phase,model=name,common_valid_frames=len(selected),
                z_median_m=float(np.median([float(r['z_m']) for r in selected])),
                z_std_m=float(np.std([float(r['z_m']) for r in selected])),
                z_error_median_m=float(np.median([float(r['error_z_m']) for r in selected])),
                scope='secondary common-range-valid subset; primary data including rejected/outlier frames remains intact'))
    failures=[r for r in rows if r['phase']=='cone_200' and (r['target_hypothesis_used']!='True' or (r['z_m'] and float(r['z_m'])>3))]
    session=Path(intake['session'])
    selected,timestamps=load_raw_frames(session,{1133,1134})
    output.mkdir(exist_ok=False)
    manifest=[]
    for number,pixels in selected.items():
        target=output/f'occlusion_raw_f{number:06d}.png'
        if not cv2.imwrite(str(target),pixels):raise ValueError('native PNG failed')
        digest=hashlib.sha256(pixels.tobytes()).hexdigest()
        if hashlib.sha256(cv2.imread(str(target)).tobytes()).hexdigest()!=digest:raise ValueError('saved pixels changed')
        manifest.append(dict(file=target.name,frame=number,time_sec=timestamps[number-1]['time_sec'],session=session.name,
            width=1280,height=720,png_sha256=sha256(target),decoded_bgr_sha256=digest,
            source_raw_sha256=intake['source_sha256']['raw.avi'],reason='targeted failure review, not random accuracy sample; no image edits'))
    write_csv(output/'raw_manifest.csv',manifest)
    write_csv(output/'all_failure_rows.csv',failures)
    write_csv(output/'common_valid_summary.csv',paired)
    (output/'provenance.json').write_text(json.dumps(dict(
        status='COMPLETED_RETAINED_OCCLUSION_DIAGNOSTIC_NO_GATE_OR_MODEL_CHANGE',
        source_sha256={str(p):sha256(p) for p in (source,Path(__file__),session/'raw.avi')},
        physical_output=False,primary_rows_removed=0,fitted_parameters=False,
        output_sha256={p.name:sha256(p) for p in output.iterdir() if p.is_file()}),indent=2)+'\n')
    print(json.dumps(paired,indent=2))


if __name__=='__main__':main()
