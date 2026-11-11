"""Compact runtime regression, synthetic-only; no old test counts reused."""
import argparse
from contextlib import redirect_stderr,redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'tests'));sys.path.insert(0,str(ROOT/'src'))
sys.path.insert(0,str(ROOT/'Experimental_results/2026-11-11/guarded_compute_reuse_r01'))
from check_runtime import NAMES as PREVIOUS
NAMES=(*PREVIOUS,'test_guarded_compact_compute')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path,required=True)
    args=parser.parse_args();args.output_dir.mkdir(parents=True,exist_ok=False)
    previous=ROOT/'Experimental_results/2026-11-11/guarded_compute_reuse_r01/checks_runtime_r01/summary.json'
    files=set(json.loads(previous.read_bytes())['source_sha256'])
    files.update('tests/'+name+'.py' for name in NAMES)
    files.update(str(path.relative_to(ROOT)) for path in (Path(__file__),Path(__file__).with_name('bench.py')))
    before={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in sorted(files)}
    log=io.StringIO()
    with redirect_stderr(log),redirect_stdout(log):
        suite=unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromName(name) for name in NAMES)
        result=unittest.TextTestRunner(stream=log,verbosity=2).run(suite)
    unchanged=all(hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==digest for name,digest in before.items())
    passed=result.wasSuccessful() and unchanged
    report=dict(state='pass' if passed else 'fail',tests_run=result.testsRun,failures=len(result.failures),
        errors=len(result.errors),skips=len(result.skipped),sources_unchanged=unchanged,source_sha256=before,
        reused_tests=0,camera_started=False,cuda_started=False,ros_started=False,vehicle_operated=False)
    (args.output_dir/'summary.json').write_text(json.dumps(report,indent=2)+'\n')
    (args.output_dir/'tests.log').write_text(log.getvalue())
    print(json.dumps({k:report[k] for k in ('state','tests_run','failures','errors','skips')},indent=2))
    if not passed:print(log.getvalue());raise SystemExit(1)


if __name__=='__main__':main()
