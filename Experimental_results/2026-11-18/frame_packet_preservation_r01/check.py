"""Recompute comparison totals, verify frozen runtime, run CPU-only tests."""
import argparse
import ast
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
SPEC=importlib.util.spec_from_file_location('preservation_check',HERE/'compare.py')
comparison=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(comparison)
probe=comparison.probe


def run(results,output):
    results,output=Path(results).resolve(),Path(output).resolve()
    if output.exists() or HERE not in output.parents:
        raise ValueError('unused verification output required')
    audit=json.loads((results/'audit.json').read_bytes())
    rows=[comparison.prior.parse(l) for l in (results/'trials.jsonl').read_bytes().splitlines()]
    if len(rows)!=80 or not comparison.prior.equivalent(audit['groups'],comparison.summarize(rows)):
        raise ValueError('all comparison totals must reproduce')
    if any(probe.digest(ROOT/name)!=sha for name,sha in audit['source_code_sha256'].items()):
        raise ValueError('comparison code version changed')
    for kind in comparison.KINDS[1:]:
        group=audit['groups'][kind]
        if group['pixels_preserved_trials']!=20 or group['decisions_preserved_trials']!=20:
            raise ValueError('lossless input/decision preservation failed')
    old_path=ROOT/'Experimental_results/2026-11-18/frame_packet_saved_suite_r01/verification_r03/audit.json'
    old=json.loads(old_path.read_bytes())
    unchanged=old['unchanged_previous_runtime_source_sha256']
    if any(probe.digest(ROOT/name)!=sha for name,sha in unchanged.items()):
        raise ValueError('previous runtime changed')
    command=[sys.executable]+old['command'][1:]+['tests/test_frame_packet_preservation.py']
    output.mkdir(parents=True,exist_ok=False)
    result=subprocess.run(command,cwd=ROOT,capture_output=True,text=True,timeout=60,
        env=dict(os.environ,OPENBLAS_NUM_THREADS='1',PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'))
    log=result.stdout+result.stderr
    with (output/'tests.txt').open('x') as target:target.write(log)
    count=re.search(r'(\d+) passed in ([0-9.]+)s',log)
    if result.returncode or count is None or 'skipped' in log:
        raise ValueError('all tests must pass: '+log)
    paths=[HERE/'compare.py',Path(__file__),ROOT/'tests/test_frame_packet_preservation.py']
    for path in paths:ast.parse(path.read_bytes())
    value=dict(schema='pixel_preservation_verification_v1',state='pass',
        comparison_audit_sha256=probe.digest(results/'audit.json'),comparison_totals_reproduced=True,
        source_code_sha256={str(p.relative_to(ROOT)):probe.digest(p) for p in paths},
        unchanged_runtime_source_sha256=unchanged,command=command,
        tests_passed=int(count[1]),elapsed_sec=float(count[2]),failed=0,skipped=0,
        actual_new_GPU_inference=False,network_or_hardware_started=False,
        source_images_modified=False,**probe.FLAGS)
    with (output/'audit.json').open('xb') as target:target.write(probe.json_bytes(value))
    print(json.dumps({k:value[k] for k in ('state','tests_passed','elapsed_sec')},indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--results',type=Path,required=True)
    parser.add_argument('--output-dir',type=Path,required=True)
    args=parser.parse_args();run(args.results,args.output_dir)
