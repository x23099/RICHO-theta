"""Verify height study and unchanged width study; collect one numeric daily asset."""
import importlib.util
import io
import json
from pathlib import Path
import shutil
import sys
import unittest

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
sys.path.insert(0,str(HERE))
import analyze_height as study


def main():
    output=HERE/'verification_r01'
    asset=HERE.parent/'report_assets/known_height_comparison.png'
    manifest=asset.parent/'known_height_manifest.json'
    if output.exists() or asset.exists() or manifest.exists():
        raise ValueError('no overwrite')
    suite=unittest.TestSuite()
    paths=[HERE/'test_known_height.py',study.WIDTH/'test_known_width.py',
           ROOT/'tests/test_fisheye_floor_geometry.py',ROOT/'tests/test_ground_contact.py']
    for i,path in enumerate(paths):
        spec=importlib.util.spec_from_file_location('height_verification_module_'+str(i),path)
        module=importlib.util.module_from_spec(spec)
        # Archived tests import a generic module called 'analyze'. Bind their
        # original study explicitly; other studies have the same filename.
        previous=sys.modules.get('analyze')
        if path==study.WIDTH/'test_known_width.py':
            sys.modules['analyze']=study.width
        try:
            spec.loader.exec_module(module)
        finally:
            if previous is None:
                sys.modules.pop('analyze',None)
            else:
                sys.modules['analyze']=previous
        suite.addTests(unittest.defaultTestLoader.loadTestsFromModule(module))
    log=io.StringIO()
    result=unittest.TextTestRunner(stream=log,verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise AssertionError(log.getvalue())
    output.mkdir()
    (output/'test_log.txt').write_text(log.getvalue())
    summary=dict(tests=result.testsRun,failures=len(result.failures),errors=len(result.errors),
                 height_tests=22,previous_width_tests=17,existing_geometry_tests=24,
                 input_output_hashes_verified=True,all_frames=6876,height_m=.73,
                 geometry_or_size_fit=False,production_settings_changed=False,physical_output=False,
                 usable_for_ffb=False,source_sha256={str(p):study.sha256(p) for p in paths+[Path(__file__)]})
    summary['test_log_sha256']=study.sha256(output/'test_log.txt')
    (output/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    source=HERE/'results_r01/height_comparison.png'
    shutil.copy2(source,asset)
    assert study.sha256(source)==study.sha256(asset)
    manifest.write_text(json.dumps(dict(kind='numeric_graph_not_camera_image',file=asset.name,
        source=str(source),sha256=study.sha256(asset),byte_identical_copy=True,
        data='../cone_known_height_pinhole_r01/results_r01/summary.csv',
        script='../cone_known_height_pinhole_r01/analyze_height.py'),indent=2)+'\n')
    print(json.dumps(summary,indent=2))


if __name__=='__main__':
    main()
