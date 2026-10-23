"""Persist tests for new orchestration plus reused geometry and causal gate."""
import io
import json
from pathlib import Path
import sys
import unittest

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
OLD=ROOT/'Experimental_results/2026-10-21/scene_vertical_gravity_r01'
sys.path[:0]=[str(HERE),str(ROOT/'src'),str(OLD)]
from cone_dataset import sha256


def main():
    output=HERE/'verification_r01'
    if output.exists():raise ValueError('new verification output required')
    suite=unittest.TestSuite()
    suite.addTests(unittest.TestLoader().discover(str(HERE),pattern='test_pipeline.py'))
    suite.addTests(unittest.TestLoader().discover(str(ROOT/'tests'),pattern='test_angular_fisheye_geometry.py'))
    suite.addTests(unittest.TestLoader().discover(str(ROOT/'tests'),pattern='test_cone_support_quality*.py'))
    suite.addTests(unittest.TestLoader().discover(str(OLD),pattern='test_scene_geometry.py'))
    stream=io.StringIO();results=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
    # New plot/copy checks are separate from the numerical tests.
    asset_path=HERE.parent/'report_assets/manifest.json';assets=json.loads(asset_path.read_text())
    for r in assets['assets']:
        assert sha256(HERE.parent/'report_assets'/r['file'])==sha256(Path(r['source']))==r['sha256']
    for name,h in assets['output_sha256'].items():assert sha256(HERE/'plots_r01'/name)==h
    output.mkdir();(output/'test_log.txt').write_text(stream.getvalue())
    files=[Path(__file__),HERE/'test_pipeline.py',ROOT/'tests/test_angular_fisheye_geometry.py',
        ROOT/'tests/test_cone_support_quality.py',ROOT/'tests/test_cone_support_quality_limits.py',OLD/'test_scene_geometry.py',asset_path]
    record=dict(status='PASS_OFFLINE_UNIFORM_REPLAY_TESTS_NOT_HARDWARE_APPROVAL' if results.wasSuccessful() else 'FAIL',
        work_date='2026-10-22',tests=results.testsRun,failures=len(results.failures),errors=len(results.errors),skipped=len(results.skipped),
        source_sha256={str(p):sha256(p) for p in files},source_images_edited=False,physical_output=False,usable_for_ffb=False,
        output_sha256={'test_log.txt':sha256(output/'test_log.txt')})
    (output/'summary.json').write_text(json.dumps(record,indent=2)+'\n')
    print(json.dumps({k:v for k,v in record.items() if k not in ('source_sha256','output_sha256')},indent=2))
    if not results.wasSuccessful():raise SystemExit(1)


if __name__=='__main__':main()
