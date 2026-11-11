"""Run new audit parser tests only; no model or device initialization."""
import argparse
from contextlib import redirect_stderr,redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'tests'))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path,required=True)
    args=parser.parse_args();args.output_dir.mkdir(parents=True,exist_ok=False)
    files=[Path(__file__),Path(__file__).with_name('audit.py'),ROOT/'tests/test_guarded_cuda_gpu_audit.py']
    before={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    log=io.StringIO()
    with redirect_stderr(log),redirect_stdout(log):
        suite=unittest.defaultTestLoader.loadTestsFromName('test_guarded_cuda_gpu_audit')
        result=unittest.TextTestRunner(stream=log,verbosity=2).run(suite)
    unchanged=all(hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==digest for name,digest in before.items())
    passed=result.wasSuccessful() and unchanged
    report=dict(state='pass' if passed else 'fail',tests_run=result.testsRun,failures=len(result.failures),
        errors=len(result.errors),skips=len(result.skipped),source_sha256=before,sources_unchanged=unchanged,
        cuda_started=False,camera_started=False,vehicle_operated=False)
    (args.output_dir/'tests.log').write_text(log.getvalue())
    (args.output_dir/'summary.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))
    if not passed:print(log.getvalue());raise SystemExit(1)


if __name__=='__main__':main()
