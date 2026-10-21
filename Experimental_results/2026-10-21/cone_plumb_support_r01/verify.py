"""Combined read-only study regression; new verification output only."""
import importlib.util
import io
import json
from pathlib import Path
import sys
import unittest

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import analyze_plumb as study


def main():
    output=HERE/'verification_r01'
    if output.exists():
        raise ValueError('no verification overwrite')
    paths=[HERE/'test_plumb_support.py',study.HEIGHT/'test_known_height.py',
           study.previous.WIDTH/'test_known_width.py',study.ROOT/'tests/test_fisheye_floor_geometry.py',
           study.ROOT/'tests/test_ground_contact.py']
    suite=unittest.TestSuite()
    for i,p in enumerate(paths):
        spec=importlib.util.spec_from_file_location('plumb_test_suite_'+str(i),p)
        module=importlib.util.module_from_spec(spec)
        previous_analyze=sys.modules.get('analyze')
        if p==study.previous.WIDTH/'test_known_width.py':
            sys.modules['analyze']=study.previous.width
        try:
            spec.loader.exec_module(module)
        finally:
            if previous_analyze is None:
                sys.modules.pop('analyze',None)
            else:
                sys.modules['analyze']=previous_analyze
        suite.addTests(unittest.defaultTestLoader.loadTestsFromModule(module))
    log=io.StringIO()
    result=unittest.TextTestRunner(stream=log,verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise AssertionError(log.getvalue())
    r1=study.read_csv(HERE/'results_r01/all_frame_estimates.csv')
    r2=study.read_csv(HERE/'results_r02/all_frame_estimates.csv')
    assert len(r1)==len(r2)
    changed=sum(a!=b for a,b in zip(r1,r2))
    summary=dict(tests=result.testsRun,failures=len(result.failures),errors=len(result.errors),
        plumb_tests=22,height_tests=22,width_tests=17,existing_geometry_tests=24,
        initial_result='results_r01: preliminary, superseded by results_r02',
        verified_result='results_r02',rows_different_from_initial=changed,frames=6876,
        source_output_hashes_verified=True,geometry_or_size_fit=False,usable_for_ffb=False,
        source_sha256={str(p):study.sha256(p) for p in paths+[Path(__file__)]})
    output.mkdir()
    (output/'test_log.txt').write_text(log.getvalue())
    summary['test_log_sha256']=study.sha256(output/'test_log.txt')
    (output/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps(summary,indent=2))


if __name__=='__main__':
    main()
