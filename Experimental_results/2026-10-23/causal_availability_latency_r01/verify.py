"""New scheduler/control regressions; no rerun or overwrite of frozen studies."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys

from replay_completion import HERE,ROOT,CAUSAL
from cone_dataset import sha256


def check(folder):
    d=json.loads((folder/'summary.json').read_text())
    for p,h in d['source_sha256'].items():assert sha256(Path(p))==h,p
    for name,h in d['output_sha256'].items():assert sha256(folder/name)==h,name
    return d


def main():
    output=HERE/'verification_r01'
    if output.exists():raise ValueError('completed verification is frozen')
    for folder in ('benchmark_r01','results_r01','pending_control_r01','report_r01'):check(HERE/folder)
    prior=check(CAUSAL/'verification_r01');assert prior['new_tests_passed'] and prior['newly_run_tests']==34
    check(CAUSAL/'results_r01')
    env=dict(os.environ,PYTHONPATH=str(ROOT/'src'),OPENBLAS_NUM_THREADS='1')
    process=subprocess.run([sys.executable,'-m','unittest','discover','-s',str(HERE),'-p','test_latency.py','-v'],
        cwd=ROOT,env=env,capture_output=True,text=True)
    log=process.stdout+process.stderr;match=re.search(r'Ran (\d+) tests? in ',log);passed=process.returncode==0 and match is not None
    output.mkdir();(output/'test_log.txt').write_text(log)
    paths=list(HERE.glob('*.py'))+[CAUSAL/'verification_r01/summary.json']
    record=dict(status='PASS_COMPLETION_AND_PENDING_HOLD_DIAGNOSTICS' if passed else 'FAIL',work_date='2026-10-23',
        newly_run_tests=int(match.group(1)) if match else 0,new_tests_passed=passed,
        prior_causal_tests_reused=34,prior_tests_rerun=False,prior_source_and_output_hashes_verified=True,
        source_sha256={str(p):sha256(p) for p in paths},output_sha256={'test_log.txt':sha256(output/'test_log.txt')},
        physical_output=False,usable_for_ffb=False)
    (output/'summary.json').write_text(json.dumps(record,indent=2)+'\n')
    print(json.dumps({k:v for k,v in record.items() if k not in ('source_sha256','output_sha256')},indent=2))
    if not passed:raise SystemExit(1)


if __name__=='__main__':main()
