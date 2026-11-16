"""Save offline checks for user-designated 11/14 work; no hardware commands."""
import hashlib
import json
import os
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parents[3]
BASE=Path(__file__).resolve().parent


def main():
    out=BASE/'checks_r01';out.mkdir(exist_ok=False)
    command=['/home/robo25/theta-env/bin/python3','-m','pytest','-q','tests/test_guarded_display_submission_pack.py']
    env=os.environ.copy();env['PYTEST_DISABLE_PLUGIN_AUTOLOAD']='1'
    result=subprocess.run(command,cwd=ROOT,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
    (out/'tests.log').write_text(result.stdout)
    files=(BASE/'pack_submission.py',BASE/'README.md',Path(__file__),ROOT/'tests/test_guarded_display_submission_pack.py')
    summary=dict(state='pass' if result.returncode==0 else 'fail',work_date='2026-11-14',
        work_date_explicitly_designated_by_user=True,calendar_or_20261113_experiment_timestamps_changed=False,
        basis_head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        preceding_20261113_push_verified_commit='0ecfad2540c955ace62dd6b368971ecde6f86b08',
        command=command,pytest_disable_plugin_autoload=True,returncode=result.returncode,
        source_sha256={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files},
        test_log_sha256=hashlib.sha256((out/'tests.log').read_bytes()).hexdigest(),
        camera_cuda_ros_gpu_pc_or_sender_used=False,live_pin_load_or_control_request_sent=False,
        runtime_or_calibration_changed=False,new_20261114_commit_or_push_performed=False)
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(result.stdout);print(json.dumps(summary,indent=2))
    if result.returncode:raise SystemExit(result.returncode)


if __name__=='__main__':main()
