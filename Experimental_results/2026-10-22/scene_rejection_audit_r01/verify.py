"""Save this batch's tests together with the unchanged previous 81 tests."""
import io
import json
from pathlib import Path
import unittest

from audit import HERE, ROOT, PREVIOUS, OLD
from cone_dataset import sha256


def main():
    output=HERE/'verification_r01'
    if output.exists():raise ValueError('completed verification is preserved')
    suite=unittest.TestSuite()
    for folder,pattern in [(HERE,'test_audit.py'),(PREVIOUS,'test_pipeline.py'),
        (ROOT/'tests','test_angular_fisheye_geometry.py'),(ROOT/'tests','test_cone_support_quality*.py'),
        (OLD,'test_scene_geometry.py')]:
        suite.addTests(unittest.TestLoader().discover(str(folder),pattern=pattern))
    stream=io.StringIO();result=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
    output.mkdir();(output/'test_log.txt').write_text(stream.getvalue())
    files=[Path(__file__),HERE/'test_audit.py',PREVIOUS/'test_pipeline.py',
        ROOT/'tests/test_angular_fisheye_geometry.py',ROOT/'tests/test_cone_support_quality.py',
        ROOT/'tests/test_cone_support_quality_limits.py',OLD/'test_scene_geometry.py']
    record=dict(status='PASS_OFFLINE_REJECTION_AUDIT_AND_ROI_CONTROL' if result.wasSuccessful() else 'FAIL',
        work_date='2026-10-22',tests=result.testsRun,failures=len(result.failures),errors=len(result.errors),skipped=len(result.skipped),
        source_sha256={str(p):sha256(p) for p in files},
        output_sha256={'test_log.txt':sha256(output/'test_log.txt')},
        source_images_edited=False,physical_output=False,usable_for_ffb=False)
    (output/'summary.json').write_text(json.dumps(record,indent=2)+'\n')
    print(json.dumps({k:v for k,v in record.items() if k not in ('source_sha256','output_sha256')},indent=2))
    if not result.wasSuccessful():
        print(stream.getvalue());raise SystemExit(1)


if __name__=='__main__':main()
