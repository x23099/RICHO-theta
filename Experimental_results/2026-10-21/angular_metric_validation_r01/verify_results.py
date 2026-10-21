"""Persist reproducible geometry/unit/result checks without hardware access."""
import io
import json
from pathlib import Path
import sys
import unittest

import cv2
import numpy as np
import scipy

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
sys.path.insert(0,str(ROOT/'src'))
sys.path.insert(0,str(HERE))
from cone_dataset import sha256


def main():
    output=HERE/'verification.json'
    if output.exists():raise ValueError('no verification overwrite')
    suite=unittest.TestSuite()
    suite.addTests(unittest.TestLoader().discover(str(ROOT/'tests'),pattern='test_*fisheye*.py'))
    suite.addTests(unittest.TestLoader().discover(str(HERE),pattern='test_*.py'))
    stream=io.StringIO()
    results=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
    log=HERE/'verification_tests.txt'
    log.write_text(stream.getvalue())
    paths=[Path(__file__),HERE/'test_results.py',HERE/'test_validation.py',log,
           ROOT/'tests/test_angular_fisheye_geometry.py',ROOT/'src/cone_dataset.py']
    record=dict(status='PASS_OFFLINE_TESTS_NOT_METRIC_OR_HARDWARE_APPROVAL' if results.wasSuccessful() else 'FAIL',
        tests_run=results.testsRun,failures=len(results.failures),errors=len(results.errors),
        skipped=len(results.skipped),python=sys.version,numpy=np.__version__,opencv=cv2.__version__,scipy=scipy.__version__,
        source_sha256={str(p):sha256(p) for p in paths},physical_output=False,usable_for_ffb=False)
    output.write_text(json.dumps(record,indent=2)+'\n')
    print(json.dumps(record,indent=2))
    if not results.wasSuccessful():raise SystemExit(1)


if __name__=='__main__':main()
