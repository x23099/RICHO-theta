"""Rerun affected saved-CUDA tests after adding a dependency SHA to metadata."""
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
    sources=[Path(__file__),ROOT/'tests/test_guarded_cuda_replay.py',
        ROOT/'Experimental_results/2026-11-11/guarded_cuda_replay_r01/cuda_replay.py']
    hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    log=io.StringIO()
    with redirect_stderr(log),redirect_stdout(log):
        suite=unittest.defaultTestLoader.loadTestsFromName('test_guarded_cuda_replay')
        result=unittest.TextTestRunner(stream=log,verbosity=2).run(suite)
    unchanged=all(hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==digest for name,digest in hashes.items())
    report=dict(state='pass' if result.wasSuccessful() and unchanged else 'fail',tests_run=result.testsRun,
        failures=len(result.failures),errors=len(result.errors),skips=len(result.skipped),source_sha256=hashes,
        sources_unchanged=unchanged,cuda_started=False,camera_started=False)
    (args.output_dir/'tests.log').write_text(log.getvalue())
    (args.output_dir/'summary.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:report[k] for k in ('state','tests_run','failures','errors','skips')},indent=2))
    if report['state']!='pass':print(log.getvalue());raise SystemExit(1)


if __name__=='__main__':main()
