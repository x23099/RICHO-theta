"""Run new bearing and geometry tests; reuse unchanged prior regression record."""
import importlib.util
import io
import json
from pathlib import Path
import sys
import unittest

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import analyze_bearing as study


def main():
    output=HERE/'verification_r01'
    if output.exists():
        raise ValueError('no verification overwrite')
    suite=unittest.TestSuite()
    paths=[HERE/'test_bearing.py',study.ROOT/'tests/test_fisheye_floor_geometry.py',study.ROOT/'tests/test_ground_contact.py']
    for i,p in enumerate(paths):
        spec=importlib.util.spec_from_file_location('bearing_tests_'+str(i),p)
        module=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        suite.addTests(unittest.defaultTestLoader.loadTestsFromModule(module))
    prior=HERE.parent/'cone_plumb_support_r01/verification_r01'
    record=json.loads((prior/'summary.json').read_text())
    assert record['tests']==85 and record['failures']==record['errors']==0
    for path,digest in record['source_sha256'].items():
        assert study.sha256(Path(path))==digest,path
    assert study.sha256(prior/'test_log.txt')==record['test_log_sha256']
    log=io.StringIO()
    result=unittest.TextTestRunner(stream=log,verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise AssertionError(log.getvalue())
    output.mkdir()
    (output/'test_log.txt').write_text(log.getvalue())
    summary=dict(tests_executed=result.testsRun,new_bearing_tests=16,existing_geometry_tests_executed=24,
        failures=len(result.failures),errors=len(result.errors),
        prior_85_tests_reused_not_reexecuted=True,prior_record=str(prior/'summary.json'),
        prior_record_sha256=study.sha256(prior/'summary.json'),new_calibration_fit=False,
        usable_for_ffb=False,source_sha256={str(p):study.sha256(p) for p in paths+[Path(__file__)]},
        test_log_sha256=study.sha256(output/'test_log.txt'))
    (output/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps(summary,indent=2))


if __name__=='__main__':
    main()
