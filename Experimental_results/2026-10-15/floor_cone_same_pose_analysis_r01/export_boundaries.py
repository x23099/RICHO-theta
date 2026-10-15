"""Additional native boundary frames, no edits, fitting or inference."""
import hashlib
import json
from pathlib import Path
import sys

import cv2

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parents[2]/'src'))
from cone_dataset import sha256,write_csv
from evaluate_floor_reference import load_raw_frames


def main():
    target=HERE/'raw_boundary_manifest.csv'
    if target.exists():raise ValueError('new export required; no overwrite')
    intake=json.loads((HERE/'intake_summary.json').read_text())
    session=Path(intake['session'])
    frames,timestamps=load_raw_frames(session,{480,780,1000})
    rows=[]
    for number,pixels in frames.items():
        path=HERE/'raw_samples'/f'same_pose_f{number:06d}.png'
        if path.exists() or pixels.shape!=(720,1280,3):raise ValueError('new native output required')
        if not cv2.imwrite(str(path),pixels):raise ValueError('PNG export failed')
        digest=hashlib.sha256(pixels.tobytes()).hexdigest()
        if hashlib.sha256(cv2.imread(str(path)).tobytes()).hexdigest()!=digest:raise ValueError('saved pixels differ')
        rows.append(dict(file=str(path.relative_to(HERE)),session=session.name,frame=number,
            time_sec=timestamps[number-1]['time_sec'],width=1280,height=720,png_sha256=sha256(path),
            decoded_bgr_sha256=digest,source_raw_sha256=intake['source_sha256']['raw.avi'],
            reason='native boundary review for predeclared static intervals; no image edits'))
    write_csv(target,rows)


if __name__=='__main__':main()
