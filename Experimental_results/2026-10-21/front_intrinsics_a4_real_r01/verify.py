"""New extraction + existing calibration/geometry regressions, no solver on real data."""
import importlib.util
import io
import json
from pathlib import Path
import sys
import unittest

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
sys.path.insert(0,str(HERE))
sys.path.insert(0,str(ROOT/'src'))
from cone_dataset import sha256


def main():
    output=HERE/'verification_r01'
    if output.exists():
        raise ValueError('no output overwrite')
    paths=[HERE/'test_real_extraction.py',ROOT/'tests/test_fisheye_intrinsic_calibration.py',
           ROOT/'tests/test_fisheye_floor_geometry.py',ROOT/'tests/test_ground_contact.py']
    suite=unittest.TestSuite()
    for i,p in enumerate(paths):
        spec=importlib.util.spec_from_file_location('real_intrinsic_tests_'+str(i),p)
        module=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        suite.addTests(unittest.defaultTestLoader.loadTestsFromModule(module))
    log=io.StringIO()
    result=unittest.TextTestRunner(stream=log,verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise AssertionError(log.getvalue())
    output.mkdir()
    (output/'test_log.txt').write_text(log.getvalue())
    summary=dict(tests=result.testsRun,failures=len(result.failures),errors=len(result.errors),
        real_extraction_tests=13,existing_intrinsic_tests=15,existing_geometry_tests=24,
        real_calibration_solver_not_called=True,source_hashes_and_native_pngs_verified=True,
        physical_output=False,usable_for_ffb=False,source_sha256={str(p):sha256(p) for p in paths+[Path(__file__)]},
        test_log_sha256=sha256(output/'test_log.txt'))
    (output/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps(summary,indent=2))


if __name__=='__main__':
    main()
