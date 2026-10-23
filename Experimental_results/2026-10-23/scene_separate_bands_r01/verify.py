"""Persist new band tests and the unchanged previous 113 regression tests."""
import io
import json
import unittest

from run import HERE,ROOT,PREVIOUS,AUDIT,OLD
from cone_dataset import sha256


def main():
    output=HERE/'verification_r01'
    if output.exists():raise ValueError('new verification output required')
    cases=[(HERE,'test_bands.py'),(AUDIT,'test_audit.py'),(PREVIOUS,'test_pipeline.py'),
        (ROOT/'tests','test_angular_fisheye_geometry.py'),(ROOT/'tests','test_cone_support_quality*.py'),
        (OLD,'test_scene_geometry.py')]
    suite=unittest.TestSuite()
    for folder,pattern in cases:suite.addTests(unittest.TestLoader().discover(str(folder),pattern=pattern))
    stream=io.StringIO();results=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
    output.mkdir();(output/'test_log.txt').write_text(stream.getvalue())
    files=[HERE/'verify.py',HERE/'test_bands.py',AUDIT/'test_audit.py',PREVIOUS/'test_pipeline.py',
        ROOT/'tests/test_angular_fisheye_geometry.py',ROOT/'tests/test_cone_support_quality.py',
        ROOT/'tests/test_cone_support_quality_limits.py',OLD/'test_scene_geometry.py']
    summary=dict(status='PASS_OFFLINE_BAND_COMPARISON_NOT_HARDWARE_APPROVAL' if results.wasSuccessful() else 'FAIL',
        work_date='2026-10-23',tests=results.testsRun,failures=len(results.failures),errors=len(results.errors),skipped=len(results.skipped),
        source_sha256={str(p):sha256(p) for p in files},output_sha256={'test_log.txt':sha256(output/'test_log.txt')},
        source_images_edited=False,physical_output=False,usable_for_ffb=False)
    (output/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps({k:v for k,v in summary.items() if k not in ('source_sha256','output_sha256')},indent=2))
    if not results.wasSuccessful():print(stream.getvalue());raise SystemExit(1)


if __name__=='__main__':main()
