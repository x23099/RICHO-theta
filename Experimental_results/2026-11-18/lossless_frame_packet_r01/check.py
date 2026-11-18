"""Verify PNG packet evidence and frozen old runtime, then run regression tests."""
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
    if output.exists() or HERE not in output.parents:
        raise ValueError('unused verification output required')
    audit=json.loads((results/'audit.json').read_bytes())
    rows=[json.loads(line) for line in (results/'trials.jsonl').read_bytes().splitlines()]
    if (audit['state']!='pass' or len(rows)!=20 or audit['trials_sha256']!=digest(results/'trials.jsonl')
            or len({r['image'] for r in rows})!=4
            or any(not all(r[k] is True for k in ('exact_pixels','exact_candidate','original_full_measurement_reproduced')) for r in rows)):
        raise ValueError('exact four-image/20-trial evidence required')
    frozen=audit['unchanged_runtime_source_sha256']
    hashes={**audit['source_code_sha256'],**audit['input_sha256'],**frozen}
    if any(digest(ROOT/n)!=sha for n,sha in hashes.items()):
        raise ValueError('frozen code/input evidence changed')
    sys.path.insert(0,str(HERE))
    import run as experiment
    keys=tuple(audit['statistics'])
    if audit['statistics']!={key:experiment.probe.describe([r[key] for r in rows]) for key in keys}:
        raise ValueError('all timing/size totals must reproduce')
    for index,rate in enumerate((15,30,100)):
        expected=dict(assembly=sum(r['ideal_models'][index]['assembly_within_first_200ms'] for r in rows),
            postdecode=sum(r['ideal_models'][index]['after_receiver_work_within_first_200ms'] for r in rows))
        if audit['ideal_model_pass_counts'][str(rate)]!=expected:
            raise ValueError('model totals differ')
        for row in rows:
            # Independently check the ideal serialization and unchanged deadline.
            model=row['ideal_models'][index]
            wire_ms=row['fragmented_bytes']*8/(rate*1000)
            first_message_ms=min(16384,row['fragmented_bytes'])*8/(rate*1000)
            total_ms=wire_ms-first_message_ms+row['local_first_fragment_to_take_ms']
            if (abs(model['wire_serialization_ms']-wire_ms)>1e-8
                    or abs(model['first_message_to_postdecode_ms']-total_ms)>1e-8
                    or model['assembly_within_first_200ms']!=(wire_ms-first_message_ms<=200)
                    or model['after_receiver_work_within_first_200ms']!=(total_ms<=200)):
                raise ValueError('ideal model arithmetic differs')
    previous=json.loads((HERE.parent/'frame_packet_preservation_r01/verification_r01/audit.json').read_bytes())
    command=[sys.executable]+previous['command'][1:]+['tests/test_driver_lossless_frame_packet.py']
    output.mkdir(parents=True,exist_ok=False)
    result=subprocess.run(command,cwd=ROOT,capture_output=True,text=True,timeout=60,
        env=dict(os.environ,PYTEST_DISABLE_PLUGIN_AUTOLOAD='1',OPENBLAS_NUM_THREADS='1'))
    log=result.stdout+result.stderr
    with (output/'tests.txt').open('x') as target:target.write(log)
    count=re.search(r'(\d+) passed in ([0-9.]+)s',log)
    if result.returncode or count is None or 'skipped' in log:raise ValueError('regression failed: '+log)
    paths=[HERE/'run.py',Path(__file__),ROOT/'src/driver_lossless_frame_packet.py',
        ROOT/'src/driver_lossless_frame_fragments.py',ROOT/'tests/test_driver_lossless_frame_packet.py']
    for path in paths:ast.parse(path.read_bytes())
    value=dict(schema='offline_lossless_atomic_packet_verification_v1',state='pass',
        result_audit_sha256=digest(results/'audit.json'),all_statistics_reproduced=True,
        source_code_sha256={str(p.relative_to(ROOT)):digest(p) for p in paths},
        unchanged_runtime_source_sha256=frozen,command=command,tests_passed=int(count[1]),
        elapsed_sec=float(count[2]),failed=0,skipped=0,network_or_hardware_started=False,
        **experiment.probe.FLAGS)
    with (output/'audit.json').open('x') as target:json.dump(value,target,ensure_ascii=False,indent=2)
    print(json.dumps({k:value[k] for k in ('state','tests_passed','elapsed_sec')},indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--results',type=Path,required=True)
    parser.add_argument('--output-dir',type=Path,required=True)
    args=parser.parse_args();run(args.results,args.output_dir)
