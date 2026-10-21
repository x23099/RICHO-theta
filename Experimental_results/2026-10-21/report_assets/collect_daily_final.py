"""Copy four final daily-report assets byte-for-byte; never edit camera pixels."""
import json
from pathlib import Path
import shutil
import sys

import cv2

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
sys.path.insert(0,str(ROOT/'src'))
from cone_dataset import sha256


def main():
    manifest=HERE/'daily_final_manifest.json'
    if manifest.exists():raise ValueError('final report assets already collected; no overwrite')
    pairs=[
        (HERE.parent/'front_intrinsics_a4_real_r03/extraction_r01/raw_frames/raw_f002771.png',
         'daily_final_raw_intrinsic_r03_f002771.png','native_camera',
         'front_fisheye_intrinsic_a4_r03_20261021_182522_716',2771),
        (HERE.parent/'front_fisheye_solver_audit_r01/plots_r01/solver_domain_comparison.png',
         'daily_final_intrinsic_solver.png','numerical_plot',None,None),
        (HERE.parent/'angular_metric_validation_r01/plots_r01/floor_metric_validation.png',
         'daily_final_floor_validation.png','numerical_plot',None,None),
        (HERE.parent/'scene_vertical_gravity_r01/plots_and_verification_r01/sequence_metric_crosscheck.png',
         'daily_final_scene_metric.png','numerical_plot',None,None)]
    records=[]
    for source,name,kind,session,frame in pairs:
        target=HERE/name
        if target.exists():raise ValueError('no report asset overwrite')
        digest=sha256(source)
        if kind=='native_camera':assert cv2.imread(str(source)).shape==(720,1280,3)
        shutil.copy2(source,target)
        assert sha256(target)==digest==sha256(source)
        records.append(dict(file=name,source=str(source),sha256=digest,kind=kind,session=session,frame=frame,
            source_byte_identical=True,camera_image_edited=False))
    manifest.write_text(json.dumps(dict(assets=records,collector_sha256=sha256(Path(__file__)),
        physical_output=False),indent=2)+'\n')
    print('Four final daily-report assets copied with identical SHA-256')


if __name__=='__main__':main()
