import json
import os
import re
import subprocess
import sys

from render_examples import HERE,ROOT
from cone_dataset import sha256


def main():
    output=HERE/'verification_r01'
    if output.exists():raise ValueError('completed verification is frozen')
    env=dict(os.environ,PYTHONPATH=str(ROOT/'src'),OPENBLAS_NUM_THREADS='1')
    p=subprocess.run([sys.executable,'-m','unittest','discover','-s',str(HERE),'-p','test_visualizations.py','-v'],
        capture_output=True,text=True,cwd=ROOT,env=env)
    log=p.stdout+p.stderr;match=re.search(r'Ran (\d+) tests? in ',log);passed=p.returncode==0 and match is not None
    output.mkdir();(output/'test_log.txt').write_text(log)
    record=dict(status='PASS_DETERMINISTIC_VISUALIZATION_BINDING' if passed else 'FAIL',work_date='2026-10-23',
        tests=int(match.group(1)) if match else 0,passed=passed,original_images_edited=False,physical_output=False,
        source_sha256={str(path):sha256(path) for path in HERE.glob('*.py')},output_sha256={'test_log.txt':sha256(output/'test_log.txt')})
    (output/'summary.json').write_text(json.dumps(record,indent=2)+'\n')
    print(json.dumps({k:v for k,v in record.items() if k not in ('source_sha256','output_sha256')},indent=2))
    if not passed:raise SystemExit(1)


if __name__=='__main__':main()
