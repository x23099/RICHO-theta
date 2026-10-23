"""Non-mutating closeout checks; preserve all frozen results and failed attempts."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[2]
DAYS=[ROOT/'Experimental_results/2026-10-22',ROOT/'Experimental_results/2026-10-23']


def main():
    output=HERE/'results_r01'
    if output.exists():raise ValueError('new closeout version required')
    cache={};manifest_checks=[];links=0;scripts=0
    def digest(p):
        p=Path(p).resolve()
        if p not in cache:cache[p]=hashlib.sha256(p.read_bytes()).hexdigest()
        return cache[p]
    for day in DAYS:
        for p in sorted(day.rglob('summary.json')):
            d=json.loads(p.read_text());failed=d.get('status')=='FAIL'
            source_count=0;output_count=0
            if not failed:
                for path,h in d.get('source_sha256',{}).items():assert digest(path)==h,path;source_count+=1
            for name,h in d.get('output_sha256',{}).items():assert digest(p.parent/name)==h,(p,name);output_count+=1
            manifest_checks.append(dict(manifest=str(p.relative_to(ROOT)),status=d.get('status'),
                source_check='archived_failed_attempt_source_checks_not_reused' if failed else 'verified',
                verified_source_files=source_count,verified_output_files=output_count))
    for day in DAYS:
        for path in day.rglob('*.py'):
            compile(path.read_text(),str(path),'exec');scripts+=1
    cases=[(ROOT/'Experimental_results/2026-10-23/metric_eligibility_contract_r01','test_eligibility.py'),
        (ROOT/'Experimental_results/2026-10-23/distance_comparison_evidence_r01','test_comparison.py'),
        (ROOT/'Experimental_results/2026-10-23/causal_pose_replay_r01','test_causal_pose.py'),
        (ROOT/'Experimental_results/2026-10-23/causal_availability_latency_r01','test_latency.py'),
        (ROOT/'Experimental_results/2026-10-23/cone_distance_visual_examples_r01','test_visualizations.py')]
    env=dict(os.environ,PYTHONPATH=str(ROOT/'src'),OPENBLAS_NUM_THREADS='1')
    logs=[];groups=[]
    for folder,pattern in cases:
        r=subprocess.run([sys.executable,'-m','unittest','discover','-s',str(folder),'-p',pattern,'-v'],
            capture_output=True,text=True,cwd=ROOT,env=env)
        log=r.stdout+r.stderr;match=re.search(r'Ran (\d+) tests? in ',log)
        groups.append(dict(folder=str(folder.relative_to(ROOT)),pattern=pattern,tests=int(match.group(1)) if match else 0,
            passed=r.returncode==0 and match is not None));logs.append(str(folder)+'\n'+log)
    old=ROOT/'Experimental_results/2026-10-23/contour_join_control_r01/verification_r01/summary.json'
    prior=json.loads(old.read_text());assert prior['all_groups_passed'] and prior['tests']==197
    # Its source/output manifest was checked above. These unchanged regressions are reused, not rerun.
    passed=all(r['passed'] for r in groups)
    output.mkdir();(output/'test_log.txt').write_text('\n\n'.join(logs))
    sources={str(Path(__file__)):digest(Path(__file__)),str(old):digest(old)}
    sources.update({str(p):digest(p) for folder,pattern in cases for p in folder.glob(pattern)})
    report=dict(status='PASS_DAY_CLOSEOUT' if passed else 'FAIL',work_date='2026-10-23',
        newly_rerun_tests=sum(r['tests'] for r in groups),new_test_groups=groups,
        reused_unchanged_regression_tests=197,regressions_rerun=False,
        distinct_tests_with_verified_success=197+sum(r['tests'] for r in groups),
        manifests_checked=len(manifest_checks),archived_failed_attempts=sum(r['status']=='FAIL' for r in manifest_checks),
        manifest_checks=manifest_checks,unique_hashed_files=len(cache),compiled_scripts=scripts,
        source_sha256=sources,output_sha256={'test_log.txt':digest(output/'test_log.txt')},
        source_images_edited=False,production_settings_changed=False,physical_output=False,usable_for_ffb=False)
    (output/'summary.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k not in ('source_sha256','output_sha256','manifest_checks','new_test_groups')},indent=2))
    if not passed:raise SystemExit(1)


if __name__=='__main__':main()
