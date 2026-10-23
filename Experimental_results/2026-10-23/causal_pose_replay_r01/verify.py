"""New causal replay tests and hash-verified reuse of prior successful tests."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys

from replay_saved import HERE,ROOT,CONTRACT
from cone_dataset import sha256


def check_manifest(folder):
    data=json.loads((folder/'summary.json').read_text())
    for p,h in data['source_sha256'].items():assert sha256(Path(p))==h,p
    for name,h in data['output_sha256'].items():assert sha256(folder/name)==h,name
    return data


def main():
    output=HERE/'verification_r01'
    if output.exists():raise ValueError('completed verification is frozen')
    priors=[CONTRACT/'verification_r01',HERE.parent/'distance_comparison_evidence_r01/verification_r01']
    previous=[check_manifest(p) for p in priors]
    assert previous[0]['all_groups_passed'] and previous[1]['new_tests_passed']
    for p in (HERE/'results_r01',HERE/'report_r01'):check_manifest(p)
    env=dict(os.environ,PYTHONPATH=str(ROOT/'src'),OPENBLAS_NUM_THREADS='1')
    p=subprocess.run([sys.executable,'-m','unittest','discover','-s',str(HERE),'-p','test_causal_pose.py','-v'],
        cwd=ROOT,env=env,capture_output=True,text=True)
    log=p.stdout+p.stderr;match=re.search(r'Ran (\d+) tests? in ',log);passed=p.returncode==0 and match is not None
    output.mkdir();(output/'test_log.txt').write_text(log)
    paths=[HERE/name for name in ('causal_pose.py','replay_saved.py','test_causal_pose.py','report.py','verify.py')]+[p/'summary.json' for p in priors]
    report=dict(status='PASS_CAUSAL_RECORDING_REPLAY_NOT_HARDWARE_APPROVAL' if passed else 'FAIL',work_date='2026-10-23',
        newly_run_tests=int(match.group(1)) if match else 0,new_tests_passed=passed,
        reused_prior_tests=[dict(folder=str(priors[0]),tests=previous[0]['tests']),dict(folder=str(priors[1]),tests=previous[1]['newly_run_tests'])],
        prior_tests_rerun=False,prior_source_and_output_hashes_verified=True,source_sha256={str(p):sha256(p) for p in paths},
        output_sha256={'test_log.txt':sha256(output/'test_log.txt')},physical_output=False,usable_for_ffb=False)
    (output/'summary.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k not in ('source_sha256','output_sha256')},indent=2))
    if not passed:raise SystemExit(1)


if __name__=='__main__':main()
