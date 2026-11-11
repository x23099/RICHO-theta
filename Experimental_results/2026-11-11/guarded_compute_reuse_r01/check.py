"""Offline sharing candidate tests; runtime untouched, no CUDA/camera."""
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
    paths=[Path(__file__),Path(__file__).with_name('compute.py'),Path(__file__).with_name('profile_compute.py'),
        ROOT/'tests/test_guarded_compute_reuse.py']
    before={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    previous=ROOT/'Experimental_results/2026-11-11/guarded_async_comparison_r01/checks_r02/summary.json'
    old=json.loads(previous.read_text())
    reused=old['state']=='pass' and all(hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==digest
        for name,digest in old['source_sha256'].items())
    captured=io.StringIO()
    with redirect_stderr(captured),redirect_stdout(captured):
        suite=unittest.defaultTestLoader.loadTestsFromName('test_guarded_compute_reuse')
        result=unittest.TextTestRunner(stream=captured,verbosity=2).run(suite)
    unchanged=all(hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==digest for name,digest in before.items())
    passed=result.wasSuccessful() and reused and unchanged
    report=dict(state='pass' if passed else 'fail',tests_run=result.testsRun,failures=len(result.failures),
        errors=len(result.errors),skips=len(result.skipped),source_sha256=before,sources_unchanged=unchanged,
        reused_tests=old['tests_run'] if reused else 0,reused_source_sha256=old['source_sha256'],
        reused_summary_sha256=hashlib.sha256(previous.read_bytes()).hexdigest(),
        camera_started=False,cuda_started=False,runtime_modified=False)
    (args.output_dir/'summary.json').write_text(json.dumps(report,indent=2)+'\n')
    (args.output_dir/'tests.log').write_text(captured.getvalue())
    print(json.dumps({k:report[k] for k in ('state','tests_run','failures','errors','reused_tests')},indent=2))
    if not passed:print(captured.getvalue());raise SystemExit(1)


if __name__=='__main__':main()
