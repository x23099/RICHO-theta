"""Reuse reviewed safe intake with r02 input and new output paths only."""
import importlib.util
import json
from pathlib import Path
import sys

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
sys.path.insert(0,str(ROOT/'src'))
from cone_dataset import sha256


def main():
    helper=HERE.parent/'front_intrinsics_a4_real_r01/intake.py'
    spec=importlib.util.spec_from_file_location('native_intrinsic_intake_r01',helper)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.HERE=HERE
    module.ARCHIVE=Path('/home/robo25/Downloads/front_fisheye_intrinsic_a4_r02_20261021_173517_156.tar.xz')
    module.DESTINATION=ROOT/'recordings/2026-10-21_front_intrinsic_a4_intake_r02'
    module.main()
    (HERE/'intake_wrapper_provenance.json').write_text(json.dumps(dict(
        entrypoint=str(Path(__file__)),entrypoint_sha256=sha256(Path(__file__)),
        helper=str(helper),helper_sha256=sha256(helper),
        differences_from_helper='archive, destination and result directory only',
        original_images_edited=False,usable_for_ffb=False),indent=2)+'\n')


if __name__=='__main__':
    main()
