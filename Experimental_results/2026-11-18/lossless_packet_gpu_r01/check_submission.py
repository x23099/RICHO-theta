"""Recheck formal PNG submission evidence and run all focused regressions."""
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
SPEC=importlib.util.spec_from_file_location('verified_png_GPU_submission',HERE/'audit_submission.py')
audit=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(audit)
probe=audit.probe


def run(results,output):
    results,output=Path(results).resolve(),Path(output).resolve()
    if output.exists() or not output.is_relative_to(HERE):raise ValueError('unused local verification output required')
    value=audit.prior.parse((results/'audit.json').read_bytes())
    intake=Path(value['raw_intake'])
    if (value['state']!='pass' or not intake.is_relative_to(ROOT/'recordings')
            or value['audit_script_sha256']!=probe.digest(HERE/'audit_submission.py')):
        raise ValueError('audited code/intake evidence differs')
    archives=list(intake.glob('lossless_packet_gpu_20261118_r01.tar.xz'))
    if len(archives)!=1:raise ValueError('one preserved source archive required')
    wire,files,values=audit.read_archive(archives[0])
    aggregate,images=audit.checked_results(values)
    if (probe.sha_bytes(wire)!=value['archive_sha256']
            or any(probe.bounded_regular_bytes(intake/n,probe.MAX_LOG)!=data for n,data in files.items())
            or not audit.prior.equivalent(audit.prior.parse((results/'aggregate.json').read_bytes()),aggregate)
            or not audit.prior.equivalent(audit.prior.parse((results/'per_image_summary.json').read_bytes()),images)
            or not audit.prior.equivalent(value['groups'],aggregate['groups'])
            or value['pair_counts']!=aggregate['pair_counts']):
        raise ValueError('preserved source/pair/statistics differ')
    rows=[audit.prior.parse(l) for l in (results/'reproduced_measurements.jsonl').read_bytes().splitlines()]
    if (len(rows)!=80 or sum(r['packet_wire_reproduced'] for r in rows)!=40
            or any(not r['inference_pixels_reproduced'] or not r['measurement_reproduced'] for r in rows)):
        raise ValueError('all replay results required')
    old_path=HERE/'verification_r01/audit.json';old=audit.prior.parse(old_path.read_bytes())
    frozen={**old['source_code_sha256'],**old['unchanged_previous_source_sha256']}
    if any(probe.digest(ROOT/n)!=sha for n,sha in frozen.items()):raise ValueError('frozen previous source changed')
    command=[sys.executable]+old['command'][1:]+['tests/test_lossless_packet_gpu_submission.py']
    output.mkdir(parents=True,exist_ok=False)
    result=subprocess.run(command,cwd=ROOT,capture_output=True,text=True,timeout=60,
        env=dict(os.environ,PYTEST_DISABLE_PLUGIN_AUTOLOAD='1',OPENBLAS_NUM_THREADS='1'))
    log=result.stdout+result.stderr
    with (output/'tests.txt').open('x') as target:target.write(log)
    count=re.search(r'(\d+) passed in ([0-9.]+)s',log)
    if result.returncode or count is None or 'skipped' in log:raise ValueError('all regressions required: '+log)
    paths=[Path(__file__),HERE/'audit_submission.py',ROOT/'tests/test_lossless_packet_gpu_submission.py']
    for path in paths:ast.parse(path.read_bytes())
    result=dict(schema='lossless_GPU_submission_verification_v1',state='pass',
        source_code_sha256={str(p.relative_to(ROOT)):probe.digest(p) for p in paths},
        unchanged_previous_source_sha256=frozen,submission_archive_sha256=probe.sha_bytes(wire),
        submission_audit_sha256=probe.digest(results/'audit.json'),all_submitted_statistics_reproduced=True,
        command=command,tests_passed=int(count[1]),elapsed_sec=float(count[2]),failed=0,skipped=0,
        new_GPU_inference_performed=False,network_or_hardware_started=False,
        source_freshness_verified=False,**probe.FLAGS)
    with (output/'audit.json').open('xb') as target:target.write(probe.json_bytes(result))
    print(json.dumps({k:result[k] for k in ('state','tests_passed','elapsed_sec')},indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--results',type=Path,required=True)
    parser.add_argument('--output-dir',type=Path,required=True)
    args=parser.parse_args();run(args.results,args.output_dir)
