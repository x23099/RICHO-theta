"""Check finite load evidence, frozen inputs and focused regression suite."""
import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]


def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def run(results,output):
    results,output=Path(results).resolve(),Path(output).resolve()
    if output.exists() or HERE not in output.parents:raise ValueError('unused verification output required')
    audit=json.loads((results/'audit.json').read_bytes())
    summaries=[json.loads(l) for l in (results/'scenarios.jsonl').read_bytes().splitlines()]
    trace=[json.loads(l) for l in (results/'consumed.jsonl').read_bytes().splitlines()]
    if audit['state']!='pass' or len(summaries)!=11 or len(trace)!=audit['consumed_total']:
        raise ValueError('complete eleven-scenario evidence required')
    hashes={**audit['source_code_sha256'],**audit['input_sha256'],**audit['unchanged_previous_source_sha256']}
    if any(digest(ROOT/n)!=sha for n,sha in hashes.items()):raise ValueError('frozen input/code changed')
    if any(digest(results/n)!=sha for n,sha in audit['artifact_sha256'].items()):
        raise ValueError('result artifact changed')
    for summary in summaries:
        rows=[r for r in trace if r['scenario']==summary['name']]
        if (summary['counts']['captured']!=int(4*summary['hz'])
                or len(rows)!=summary['counts']['consumed']
                or summary['consumed_fraction']!=len(rows)/summary['counts']['captured']
                or len({r['sequence'] for r in rows})!=len(rows)
                or [r['sequence'] for r in rows]!=sorted(r['sequence'] for r in rows)
                or summary['oracle_over_200ms_consumed']!=sum(r['oracle_capture_to_take_ms']>200 for r in rows)
                or summary['peaks']['sender_slots']>2 or summary['peaks']['raw_slots']>2
                or summary['peaks']['decode_slots']>2 or summary['peaks']['channel_buffer_bytes']>32768
                or summary['max_sender_capture_age_at_handoff_ms']>200.000001):
            raise ValueError('count, ordering or bounded sender evidence differs')
        for row in rows:
            if (row['exact_pixels'] is not True or row['receiver_local_first_to_take_ms']>200.000001
                    or abs(row['oracle_capture_to_take_ms']-(row['take_oracle_sec']-row['capture_oracle_sec'])*1000)>1e-8
                    or any(row[k] is not False for k in ('source_freshness_verified','usable_for_ffb','controlling_distance','published_to_ros'))):
                raise ValueError('trace identity, local deadline or authority evidence differs')
    delayed=next(s for s in summaries if s['name']=='delayed_first_100Mbps_10Hz')
    if delayed['counts']['consumed']==0 or delayed['oracle_max_capture_to_take_ms']<=500:
        raise ValueError('delayed-first-arrival limitation must be exercised, not hidden')
    old=json.loads((HERE.parent/'lossless_frame_packet_r01/verification_r01/audit.json').read_bytes())
    command=[sys.executable]+old['command'][1:]+[
        'tests/test_driver_lossless_frame_sender.py','tests/test_lossless_sender_load_model.py',
        'tests/test_driver_frame_packet_flow.py']
    output.mkdir(parents=True,exist_ok=False)
    result=subprocess.run(command,cwd=ROOT,capture_output=True,text=True,timeout=60,
        env=dict(os.environ,PYTEST_DISABLE_PLUGIN_AUTOLOAD='1',OPENBLAS_NUM_THREADS='1'))
    log=result.stdout+result.stderr
    with (output/'tests.txt').open('x') as target:target.write(log)
    count=re.search(r'(\d+) passed in ([0-9.]+)s',log)
    if result.returncode or count is None or 'skipped' in log:raise ValueError('regression failed: '+log)
    paths=[Path(__file__),HERE/'run.py',HERE/'model.py',ROOT/'src/driver_lossless_frame_sender.py',
           ROOT/'tests/test_driver_lossless_frame_sender.py',ROOT/'tests/test_lossless_sender_load_model.py']
    for path in paths:ast.parse(path.read_bytes())
    value=dict(schema='offline_lossless_sender_load_verification_v1',state='pass',
        result_audit_sha256=digest(results/'audit.json'),all_scenario_totals_checked=True,
        source_code_sha256={str(p.relative_to(ROOT)):digest(p) for p in paths},
        unchanged_previous_source_sha256=audit['unchanged_previous_source_sha256'],
        command=command,tests_passed=int(count[1]),elapsed_sec=float(count[2]),failed=0,skipped=0,
        network_or_hardware_started=False,source_freshness_verified=False,
        physical_metric_verified=False,controlling_distance=False,usable_for_ffb=False,published_to_ros=False)
    with (output/'audit.json').open('x') as target:json.dump(value,target,ensure_ascii=False,indent=2)
    print(json.dumps({k:value[k] for k in ('state','tests_passed','elapsed_sec')},indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--results',type=Path,required=True)
    parser.add_argument('--output-dir',type=Path,required=True)
    args=parser.parse_args();run(args.results,args.output_dir)
