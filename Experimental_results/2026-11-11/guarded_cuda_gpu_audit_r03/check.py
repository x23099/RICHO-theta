"""Cross-run audit helper tests only; no model or hardware initialization."""
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
    paths=[Path(__file__),Path(__file__).with_name('review.py'),ROOT/'tests/test_guarded_cuda_cross_run.py',
        ROOT/'Experimental_results/2026-11-11/guarded_cuda_gpu_audit_r02/review.py']
    hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    log=io.StringIO()
    with redirect_stdout(log),redirect_stderr(log):
        suite=unittest.defaultTestLoader.loadTestsFromName('test_guarded_cuda_cross_run')
        result=unittest.TextTestRunner(stream=log,verbosity=2).run(suite)
    unchanged=all(hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==digest for name,digest in hashes.items())
    report=dict(state='pass' if result.wasSuccessful() and unchanged else 'fail',tests_run=result.testsRun,
        failures=len(result.failures),errors=len(result.errors),skips=len(result.skipped),source_sha256=hashes,
        sources_unchanged=unchanged,cuda_started=False,camera_started=False,vehicle_operated=False)
    (args.output_dir/'tests.log').write_text(log.getvalue())
    (args.output_dir/'summary.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))
    if report['state']!='pass':print(log.getvalue());raise SystemExit(1)


if __name__=='__main__':main()
