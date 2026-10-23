"""New integration tests plus provenance-checked reuse of unchanged regressions."""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from compare_saved import HERE,ROOT,CONTRACT
from cone_dataset import sha256


def main():
    output=HERE/'verification_r01'
    if output.exists():raise ValueError('completed verification is frozen')
    prior_path=CONTRACT/'verification_r01/summary.json';prior=json.loads(prior_path.read_text())
    assert prior['all_groups_passed'] and prior['tests']==225
    for p,h in prior['source_sha256'].items():assert sha256(Path(p))==h,p
    for name,h in prior['output_sha256'].items():assert sha256(prior_path.parent/name)==h,name
    for folder in (CONTRACT/'results_r01',HERE/'results_r01',HERE/'plots_r01'):
        data=json.loads((folder/'summary.json').read_text())
        for p,h in data['source_sha256'].items():assert sha256(Path(p))==h,p
        for name,h in data['output_sha256'].items():assert sha256(folder/name)==h,name
    env=dict(os.environ,PYTHONPATH=str(ROOT/'src'),OPENBLAS_NUM_THREADS='1')
    p=subprocess.run([sys.executable,'-m','unittest','discover','-s',str(HERE),'-p','test_comparison.py','-v'],
        cwd=ROOT,env=env,capture_output=True,text=True)
    log=p.stdout+p.stderr;match=re.search(r'Ran (\d+) tests? in ',log);passed=p.returncode==0 and match is not None
    output.mkdir();(output/'test_log.txt').write_text(log)
    sources=[HERE/'compare_saved.py',HERE/'test_comparison.py',HERE/'plot_comparison.py',HERE/'verify_comparison.py',prior_path]
    summary=dict(status='PASS_EVIDENCE_STRATIFIED_COMPARISON' if passed else 'FAIL',work_date='2026-10-23',
        newly_run_tests=int(match.group(1)) if match else 0,new_tests_passed=passed,
        reused_unchanged_regression_tests=225,prior_tests_rerun=False,prior_source_and_result_hashes_verified=True,
        source_sha256={str(path):sha256(path) for path in sources},
        output_sha256={'test_log.txt':sha256(output/'test_log.txt')},physical_output=False,usable_for_ffb=False)
    (output/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps({k:v for k,v in summary.items() if k not in ('source_sha256','output_sha256')},indent=2))
    if not passed:raise SystemExit(1)


if __name__=='__main__':main()
