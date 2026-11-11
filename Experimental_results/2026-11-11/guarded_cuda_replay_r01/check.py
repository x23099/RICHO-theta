"""New saved-image benchmark tests plus hash-based reuse of unchanged regression."""
import argparse
from contextlib import redirect_stderr,redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import unittest

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'tests'))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path,required=True)
    args=parser.parse_args();args.output_dir.mkdir(parents=True,exist_ok=False)
    previous=ROOT/'Experimental_results/2026-11-11/guarded_async_comparison_r01/checks_r02/summary.json'
    old=json.loads(previous.read_text())
    reused=old['state']=='pass' and old['tests_run']==198 and all(
        hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==sha for name,sha in old['source_sha256'].items())
    paths=[Path(__file__),Path(__file__).parent/'cuda_replay.py',ROOT/'tests/test_guarded_cuda_replay.py']
    before={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    captured=io.StringIO()
    with redirect_stdout(captured),redirect_stderr(captured):
        suite=unittest.defaultTestLoader.loadTestsFromName('test_guarded_cuda_replay')
        result=unittest.TextTestRunner(stream=captured,verbosity=2).run(suite)
    (args.output_dir/'tests.log').write_text(captured.getvalue())
    help_run=subprocess.run([sys.executable,str(Path(__file__).parent/'cuda_replay.py'),'--help'],
        cwd=ROOT,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=30)
    (args.output_dir/'cli_help.txt').write_text(help_run.stdout)
    unchanged=all(hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==sha for name,sha in before.items())
    passed=result.wasSuccessful() and reused and unchanged and help_run.returncode==0
    summary=dict(state='pass' if passed else 'fail',tests_run=result.testsRun,
        failures=len(result.failures),errors=len(result.errors),skips=len(result.skipped),
        reused_regression_tests=198 if reused else 0,reused_summary=str(previous.relative_to(ROOT)),
        reused_summary_sha256=hashlib.sha256(previous.read_bytes()).hexdigest(),
        reused_source_sha256=old['source_sha256'],source_sha256=before,
        sources_unchanged=unchanged,cli_help_exit=help_run.returncode,
        actual_cuda_inference=False,actual_camera=False,vehicle_operated=False)
    (args.output_dir/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps({k:summary[k] for k in ('state','tests_run','failures','errors','reused_regression_tests')},indent=2))
    if not passed:print(captured.getvalue());raise SystemExit(1)


if __name__=='__main__':main()
