"""Run isolated test modules to avoid frozen helper-name collisions."""
import json
import os
import re
import subprocess
import sys

from audit_metrics import HERE,ROOT,UNIFORM,OBJECT,JOIN
from cone_dataset import sha256


def main():
    output=HERE/'verification_r01'
    if output.exists():raise ValueError('completed verification is frozen')
    cases=[(HERE,'test_eligibility.py'),(JOIN,'test_join.py'),(OBJECT,'test_objects.py'),
        (HERE.parent/'lower_support_audit_r01','test_support.py'),(HERE.parent/'scene_separate_bands_r01','test_bands.py'),
        (ROOT/'Experimental_results/2026-10-22/scene_rejection_audit_r01','test_audit.py'),(UNIFORM,'test_pipeline.py'),
        (ROOT/'tests','test_angular_fisheye_geometry.py'),(ROOT/'tests','test_cone_support_quality*.py'),
        (ROOT/'Experimental_results/2026-10-21/scene_vertical_gravity_r01','test_scene_geometry.py')]
    test_env=dict(os.environ);test_env['PYTHONPATH']=str(ROOT/'src');test_env['OPENBLAS_NUM_THREADS']='1'
    logs=[];groups=[];tests=0
    for folder,pattern in cases:
        process=subprocess.run([sys.executable,'-m','unittest','discover','-s',str(folder),'-p',pattern,'-v'],
            capture_output=True,text=True,cwd=ROOT,env=test_env)
        log=process.stdout+process.stderr;match=re.search(r'Ran (\d+) tests? in ',log)
        count=int(match.group(1)) if match else 0;tests+=count
        groups.append(dict(folder=str(folder),pattern=pattern,tests=count,passed=process.returncode==0 and match is not None))
        logs.append(str(folder)+' / '+pattern+'\n'+log)
    passed=all(r['passed'] for r in groups);output.mkdir();(output/'test_log.txt').write_text('\n\n'.join(logs))
    files=[HERE/'verify.py',HERE/'eligibility.py',HERE/'audit_metrics.py']+[p for folder,pattern in cases for p in folder.glob(pattern)]
    report=dict(status='PASS_OFFLINE_EVIDENCE_TESTS_NOT_RUNTIME_APPROVAL' if passed else 'FAIL',work_date='2026-10-23',
        tests=tests,all_groups_passed=passed,groups=groups,source_sha256={str(p):sha256(p) for p in files},
        output_sha256={'test_log.txt':sha256(output/'test_log.txt')},source_images_edited=False,physical_output=False,usable_for_ffb=False)
    (output/'summary.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k not in ('source_sha256','output_sha256')},indent=2))
    if not passed:raise SystemExit(1)


if __name__=='__main__':main()
