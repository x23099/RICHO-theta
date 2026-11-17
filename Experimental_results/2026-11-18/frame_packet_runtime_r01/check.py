"""Source-delta audit + fake bindings/real local inference-pipe regression."""
import argparse
import ast
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[3]
CHANGED=('src/driver_motion_bridge.py','src/driver_motion_camera.py','src/driver_motion_process.py',
         'src/webrtc_stream.py','src/webrtc_receive_ui.py')


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def run(output):
    output=output.resolve()
    if ROOT/'Experimental_results/2026-11-18/frame_packet_runtime_r01' not in output.parents or output.exists():
        raise ValueError('unused runtime experiment result directory required')
    previous_path=ROOT/'Experimental_results/2026-11-18/frame_packet_channel_r01/results_r01/audit.json'
    previous=json.loads(previous_path.read_bytes())
    unchanged={}
    changed={}
    for name,digest in (previous['source_code_sha256']|previous['unchanged_runtime_source_sha256']).items():
        current=sha(ROOT/name)
        if name in CHANGED:
            if current==digest:raise ValueError('expected explicit opt-in delta missing: '+name)
            changed[name]=dict(before=digest,after=current)
        elif current!=digest:raise ValueError('unplanned previous component change: '+name)
        else:unchanged[name]=digest
    distance_path=ROOT/'Experimental_results/2026-11-16/body_display_range_audit_r01/results_r01/audit.json'
    distance=json.loads(distance_path.read_bytes())
    distance_unchanged=[]
    for name,digest in distance['source_code_sha256'].items():
        path='src/'+name
        current=sha(ROOT/path)
        if path in CHANGED:changed[path]=dict(before=digest,after=current)
        elif current!=digest:raise ValueError('range/geometry component changed: '+name)
        else:distance_unchanged.append(name)
    # The former camera wrapper is intentionally changed as well, against HEAD.
    camera_before=subprocess.check_output(['git','show','HEAD:src/driver_motion_camera.py'],cwd=ROOT)
    changed['src/driver_motion_camera.py']=dict(before=hashlib.sha256(camera_before).hexdigest(),
                                              after=sha(ROOT/'src/driver_motion_camera.py'))
    old=json.loads((ROOT/'Experimental_results/2026-11-18/frame_packet_load_r01/verification_r01/audit.json').read_bytes())
    tests=['tests/test_driver_frame_packet_runtime.py']+old['command'][4:]+[
        'tests/test_driver_motion_camera.py','tests/test_driver_motion_bridge.py',
        'tests/test_driver_motion_presentation.py','tests/test_driver_body_display_guard.py',
        'tests/test_driver_motion_shutdown.py','tests/test_cone_motion_range.py']
    tests=list(dict.fromkeys(tests))
    command=[sys.executable,'-m','pytest','-q']+tests
    output.mkdir(parents=True,exist_ok=False)
    result=subprocess.run(command,cwd=ROOT,capture_output=True,text=True,timeout=60,
        env=dict(os.environ,OPENBLAS_NUM_THREADS='1',PYTEST_DISABLE_PLUGIN_AUTOLOAD='1',
                 THETA_PACKET_RUNTIME_AUDIT_DIR=str(output)))
    log=result.stdout+result.stderr
    with (output/'tests.txt').open('x') as stream:stream.write(log)
    count=re.search(r'(\d+) passed in ([0-9.]+)s',log)
    if result.returncode or count is None or 'skipped' in log:
        raise ValueError('all default and opt-in tests must pass: '+log)
    event=json.loads((output/'representative_bridge_event.json').read_bytes())
    raw=json.loads((output/'representative_measurement.json').read_bytes())
    if (event['result']['frame']!=723 or event['source_candidate']['capture_sequence']!=723
            or event['result']['session']!=event['source_candidate']['stream_id']
            or raw['frame']!=723 or event['usable_for_ffb'] is not False
            or event['accepted_current_session_and_age'] is not True):
        raise ValueError('representative exact source binding failed')
    sources={name:sha(ROOT/name) for name in CHANGED}
    for name in ('src/driver_frame_packet_runtime.py','tests/test_driver_frame_packet_runtime.py',
                 str(Path(__file__).resolve().relative_to(ROOT))):sources[name]=sha(ROOT/name)
    syntax=[]
    for name in sources:
        ast.parse((ROOT/name).read_bytes());syntax.append(name)
    audit=dict(schema='frame_motion_packet_runtime_fake_audit_v1',state='pass',work_date='2026-11-18',
        executed_utc=datetime.now(timezone.utc).isoformat(),tests_passed=int(count[1]),
        failed=0,skipped=0,elapsed_sec=float(count[2]),command=command,
        intentional_default_off_deltas=changed,unchanged_previous_source_sha256=unchanged,
        unchanged_old_distance_geometry_components=distance_unchanged,
        previous_channel_audit_sha256=sha(previous_path),source_code_sha256=sources,syntax_checked=syntax,
        sample_capture_sequence=723,inference_frame_identity_verified_in_synthetic_test=True,
        real_codec_and_local_inference_pipe=True,detector_and_support_are_synthetic=True,
        representative_files_sha256={name:sha(output/name) for name in
            ('representative_bridge_event.json','representative_measurement.json')},
        normal_driver_control_AST_tests_passed=True,normal_RTP_mode_default_unchanged=True,
        old_CaptureFrames_and_native_track_unchanged=True,IPC_old_schema_unchanged=True,
        extra_inference_model_created=False,live_transport_adopted=False,
        real_network_camera_ROS_CUDA_or_G923_started=False,source_images_modified=False,
        source_freshness_verified=False,physical_metric_verified=False,usable_for_ffb=False,
        published_to_ros=False,git_write_performed=False)
    with (output/'audit.json').open('x') as stream:
        json.dump(audit,stream,indent=2,allow_nan=False);stream.write('\n')
    print(json.dumps(dict(state='pass',tests_passed=int(count[1]),elapsed_sec=float(count[2]),
                         sample_capture_sequence=723),indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path,required=True)
    run(parser.parse_args().output_dir)
