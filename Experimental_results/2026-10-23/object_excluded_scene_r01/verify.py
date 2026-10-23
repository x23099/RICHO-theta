import json
import os
import re
import subprocess
import sys

from analyze import HERE,ROOT,BANDS,SUPPORT,UNIFORM,OLD
from cone_dataset import sha256


def main():
    output=HERE/'verification_r01'
    if output.exists():raise ValueError('completed verification is frozen')
    audit=ROOT/'Experimental_results/2026-10-22/scene_rejection_audit_r01'
    cases=[(HERE,'test_objects.py'),(SUPPORT,'test_support.py'),(BANDS,'test_bands.py'),(audit,'test_audit.py'),
        (UNIFORM,'test_pipeline.py'),(ROOT/'tests','test_angular_fisheye_geometry.py'),
        (ROOT/'tests','test_cone_support_quality*.py'),(OLD,'test_scene_geometry.py')]
    test_env=dict(os.environ);test_env['PYTHONPATH']=str(ROOT/'src')
    logs=[];groups=[];tests=0
    for folder,pattern in cases:
        process=subprocess.run([sys.executable,'-m','unittest','discover','-s',str(folder),'-p',pattern,'-v'],
            capture_output=True,text=True,cwd=ROOT,env=test_env)
        log=process.stdout+process.stderr;match=re.search(r'Ran (\d+) tests? in ',log)
        count=int(match.group(1)) if match else 0;tests+=count
        groups.append(dict(folder=str(folder),pattern=pattern,tests=count,passed=process.returncode==0 and match is not None))
        logs.append(str(folder)+' / '+pattern+'\n'+log)
    passed=all(r['passed'] for r in groups);output.mkdir()
    (output/'test_log.txt').write_text('\n\n'.join(logs))
    files=[HERE/'verify.py']+[p for folder,pattern in cases for p in folder.glob(pattern)]
    summary=dict(status='PASS_OFFLINE_OBJECT_SUPPORT_SCREEN_TESTS_NOT_HARDWARE_APPROVAL' if passed else 'FAIL',
        work_date='2026-10-23',tests=tests,all_groups_passed=passed,groups=groups,
        source_sha256={str(p):sha256(p) for p in files},output_sha256={'test_log.txt':sha256(output/'test_log.txt')},
        source_images_edited=False,physical_output=False,usable_for_ffb=False)
    (output/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps({k:v for k,v in summary.items() if k not in ('source_sha256','output_sha256')},indent=2))
    if not passed:raise SystemExit(1)


if __name__=='__main__':main()
