"""Scoped synthetic/regression verification. No device, ROS, CUDA or RTC."""
import argparse
from contextlib import redirect_stderr, redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT/'src'))
sys.path.insert(0, str(ROOT/'tests'))
NAMES = ('test_driver_guarded_comparison', 'test_cone_guarded_stream_comparison',
    'test_driver_motion_bridge', 'test_driver_motion_camera', 'test_driver_motion_integration',
    'test_driver_motion_shutdown', 'test_driver_withheld_evidence',
    'test_cone_guarded_lower_edge_shadow', 'test_cone_bbox_boundary_shadow',
    'test_cone_self_body_shadow', 'test_guarded_recording_comparison')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path,required=True)
    args=parser.parse_args()
    args.output_dir.mkdir(parents=True,exist_ok=False)
    files=[ROOT/'tests'/(name+'.py') for name in NAMES]
    files += [ROOT/'src'/name for name in ('driver_guarded_comparison.py',
        'manage_guarded_comparison.py','cone_guarded_stream_comparison.py',
        'driver_motion_bridge.py','driver_motion_process.py','driver_motion_protocol.py',
        'driver_withheld_evidence.py','webrtc_receive_ui.py','webrtc_stream.py')]
    files.append(Path(__file__))
    before={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    suite=unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromName(name) for name in NAMES)
    output=io.StringIO()
    with redirect_stdout(output),redirect_stderr(output):
        result=unittest.TextTestRunner(stream=output,verbosity=2).run(suite)
    (args.output_dir/'tests.log').write_text(output.getvalue())
    commands=[([sys.executable,'src/driver_motion_process.py','--help'],'worker_help.txt'),
              ([sys.executable,'src/manage_guarded_comparison.py','--help'],'manage_help.txt'),
              (['bash','-n','src/start_theta_receive_rtc.sh'],'receiver_shell.txt')]
    checks=[]
    for command,name in commands:
        run=subprocess.run(command,cwd=ROOT,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=30)
        (args.output_dir/name).write_text(run.stdout)
        checks.append(dict(command=command,exit_code=run.returncode))
    unchanged=all(hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==sha for name,sha in before.items())
    passed=result.wasSuccessful() and unchanged and all(item['exit_code']==0 for item in checks)
    summary=dict(schema='guarded_async_checks_v1',state='pass' if passed else 'fail',
        tests_run=result.testsRun,failures=len(result.failures),errors=len(result.errors),skips=len(result.skipped),
        sources_unchanged=unchanged,source_sha256=before,cli_checks=checks,
        camera_started=False,cuda_inference_started=False,ros_started=False,vehicle_operated=False)
    (args.output_dir/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps({key:summary[key] for key in ('state','tests_run','failures','errors','skips','cli_checks')},indent=2))
    if not passed:
        print(output.getvalue());raise SystemExit(1)


if __name__=='__main__':
    main()
