"""Finite regression checks for the saved-image benchmark and prior transport."""
import argparse
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys

from bench import ROOT,sha


def run(output):
    output=output.resolve()
    if ROOT/'Experimental_results/2026-11-18/frame_packet_load_r01' not in output.parents or output.exists():
        raise ValueError('unused verification directory required')
    previous=json.loads((ROOT/'Experimental_results/2026-11-18/frame_packet_channel_r01/results_r01/audit.json').read_bytes())
    frozen=previous['source_code_sha256'] | previous['unchanged_runtime_source_sha256']
    if any(sha(ROOT/name)!=digest for name,digest in frozen.items()):
        raise ValueError('prior source or runtime changed')
    tests=['tests/test_frame_packet_load_report.py']+previous['pytest_command'][4:]
    command=[sys.executable,'-m','pytest','-q']+tests
    result=subprocess.run(command,cwd=ROOT,capture_output=True,text=True,timeout=60,
        env=dict(os.environ,OPENBLAS_NUM_THREADS='1',PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'))
    log=result.stdout+result.stderr
    count=re.search(r'(\d+) passed in ([0-9.]+)s',log)
    if result.returncode or count is None or 'skipped' in log:
        raise ValueError('all local regressions must pass: '+log)
    files=['bench.py','report.py','check.py']
    sources={str((Path(__file__).resolve().parent/name).relative_to(ROOT)):
             sha(Path(__file__).resolve().parent/name) for name in files}
    sources['tests/test_frame_packet_load_report.py']=sha(ROOT/'tests/test_frame_packet_load_report.py')
    audit=dict(schema='frame_packet_load_regression_v1',state='pass',
        executed_utc=datetime.now(timezone.utc).isoformat(),tests_passed=int(count[1]),
        failed=0,skipped=0,elapsed_sec=float(count[2]),command=command,
        source_code_sha256=sources,prior_sources_unchanged=frozen,
        real_network_or_camera_or_ROS_or_G923_started=False,git_write_performed=False,
        physical_metric_verified=False,usable_for_ffb=False,published_to_ros=False)
    output.mkdir(parents=True,exist_ok=False)
    with (output/'tests.txt').open('x') as stream:
        stream.write(log)
    with (output/'audit.json').open('x') as stream:
        json.dump(audit,stream,indent=2,allow_nan=False);stream.write('\n')
    print(json.dumps(dict(state='pass',tests_passed=int(count[1]),elapsed_sec=float(count[2])),indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path,required=True)
    run(parser.parse_args().output_dir)
