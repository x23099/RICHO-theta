"""Training-only diagnosis: initial poses vs first OpenCV update, not usable K/D."""
import json
import math
from pathlib import Path
import sys

import cv2
import numpy as np

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
sys.path.insert(0,str(ROOT/'src'))
from cone_dataset import sha256,write_csv
from fisheye_intrinsic_calibration import Board


def main():
    output=HERE/'iteration_step_audit_r01'
    if output.exists():
        raise ValueError('no diagnostic overwrite')
    path=HERE/'combined_candidate_r01/merged_observations.json'
    data=json.loads(path.read_text())
    sources={str(p):sha256(p) for p in (path,Path(__file__),HERE/'initialization_diagnosis_method.md')}
    sources.update(data['source_sha256'])
    assert all(sha256(Path(p))==v for p,v in sources.items())
    board=Board(**data['board'])
    points=[np.array(data['selected_views'][i]['corners_native']).reshape(1,-1,2) for i in data['train_indices']]
    f=640/math.pi
    output.mkdir()
    specification=dict(steps=[0,1,2],fx=f,fy=f,cx=319.5,cy=300.,D=[0.]*4,flags=15,
        fixed_train_indices=data['train_indices'],validation_not_used=True,
        purpose='distinguish initial pose failure from update failure; do not approve early-terminated solution',
        source_sha256=sources,usable_for_ffb=False)
    (output/'specification.json').write_text(json.dumps(specification,indent=2)+'\n')
    rows=[]
    for steps in specification['steps']:
        K=np.array([[f,0.,319.5],[0.,f,300.],[0.,0.,1.]])
        row=dict(steps=steps,completed=False,training_rms_px=None,error=None)
        try:
            rms,_,_,_,_=cv2.fisheye.calibrate([board.object_points.copy() for _ in points],points,(1280,720),K,
                np.zeros((4,1)),flags=15,criteria=(3,steps,1e-9))
            row.update(completed=True,training_rms_px=float(rms))
        except cv2.error as error:
            row['error']=str(error)
        rows.append(row)
    assert all(sha256(Path(p))==v for p,v in sources.items())
    write_csv(output/'step_results.csv',rows)
    summary=dict(rows=rows,source_sha256=sources,
        conclusion='initial poses can be computed with cy=300; first intrinsic update still rejected',
        early_terminated_K_not_calibrated=True,usable_for_ffb=False,physical_output=False)
    (output/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps(rows,indent=2))


if __name__=='__main__':
    main()
