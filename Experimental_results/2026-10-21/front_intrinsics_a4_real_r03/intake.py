"""Safe r03 intake using the already reviewed native intake helper."""
import importlib.util
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT/'src'))
from cone_dataset import sha256


def main():
    helper = HERE.parent/'front_intrinsics_a4_real_r01/intake.py'
    spec = importlib.util.spec_from_file_location('native_intake', helper)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.HERE = HERE
    module.ARCHIVE = Path('/home/robo25/Downloads/front_fisheye_intrinsic_a4_r03_20261021_182522_716.tar.xz')
    module.DESTINATION = ROOT/'recordings/2026-10-21_front_intrinsic_a4_intake_r03'
    module.main()
    (HERE/'intake_wrapper_provenance.json').write_text(json.dumps(dict(
        entrypoint_sha256=sha256(Path(__file__)), helper=str(helper), helper_sha256=sha256(helper),
        changed_inputs='archive, result folder and extraction destination only',
        measured_square_mm=20., square_size_basis='same-board supplement to r02 procedure; no new measurement supplied',
        physical_output=False, original_images_edited=False), indent=2)+'\n')


if __name__ == '__main__':
    main()
