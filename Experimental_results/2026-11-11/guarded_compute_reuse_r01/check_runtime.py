"""Re-run changed runtime's scoped regression; no CUDA/camera/ROS/network."""
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
sys.path.insert(0,str(ROOT/'tests'));sys.path.insert(0,str(ROOT/'src'))
NAMES=('test_driver_guarded_comparison','test_cone_guarded_stream_comparison',
    'test_driver_motion_bridge','test_driver_motion_camera','test_driver_motion_integration',
    'test_driver_motion_shutdown','test_driver_withheld_evidence','test_cone_guarded_lower_edge_shadow',
    'test_cone_bbox_boundary_shadow','test_cone_self_body_shadow','test_guarded_recording_comparison',
    'test_cone_motion_range','test_cone_motion_worker','test_guarded_cuda_replay',
    'test_guarded_compute_reuse','test_guarded_observation_reuse_runtime')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path,required=True)
    args=parser.parse_args();args.output_dir.mkdir(parents=True,exist_ok=False)
    audit=ROOT/'Experimental_results/2026-11-11/guarded_cuda_gpu_audit_r01/results_r01/audit.json'
    # The submitted benchmark records dependencies. Use names, never remote paths.
    intake=ROOT/'recordings/2026-11-11/guarded_cuda_gpu_intake_r01/summary.json'
    sources=json.loads(intake.read_bytes())['source_sha256']
    names=set(sources)|{'src/driver_motion_process.py','src/driver_motion_bridge.py','src/cone_motion_worker.py'}
    names.update('tests/'+name+'.py' for name in NAMES)
    paths=[ROOT/name for name in sorted(names)]+[Path(__file__),Path(__file__).with_name('compute.py')]
    before={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    captured=io.StringIO()
    with redirect_stdout(captured),redirect_stderr(captured):
        suite=unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromName(name) for name in NAMES)
        result=unittest.TextTestRunner(stream=captured,verbosity=2).run(suite)
    unchanged=all(hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==digest for name,digest in before.items())
    passed=result.wasSuccessful() and unchanged
    report=dict(state='pass' if passed else 'fail',tests_run=result.testsRun,failures=len(result.failures),
        errors=len(result.errors),skips=len(result.skipped),source_sha256=before,sources_unchanged=unchanged,
        reused_tests=0,camera_started=False,cuda_started=False,ros_started=False,vehicle_operated=False)
    (args.output_dir/'summary.json').write_text(json.dumps(report,indent=2)+'\n')
    (args.output_dir/'tests.log').write_text(captured.getvalue())
    print(json.dumps({k:report[k] for k in ('state','tests_run','failures','errors','skips')},indent=2))
    if not passed:print(captured.getvalue());raise SystemExit(1)


if __name__=='__main__':main()
