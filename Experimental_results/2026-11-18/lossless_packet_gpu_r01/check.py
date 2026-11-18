"""Prepare a pinned GPU manifest; CPU synthetic verification, NOT GPU results."""
import argparse
import ast
import copy
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]


def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


runner=load('lossless_GPU_preparation',HERE/'run.py')
probe=runner.probe


def run(output):
    output=Path(output).resolve()
    if output.exists() or HERE not in output.parents:raise ValueError('unused preparation output required')
    old_path=HERE.parent/'lossless_sender_load_r01/verification_r01/audit.json'
    old=json.loads(old_path.read_bytes())
    frozen={**old['source_code_sha256'],**old['unchanged_previous_source_sha256']}
    if any(probe.digest(ROOT/n)!=sha for n,sha in frozen.items()):
        raise ValueError('previous verified sources changed')
    packet_probe=load('GPU_prep_saved_sources',HERE.parent/'lossless_frame_packet_r01/run.py')
    cases,inputs=packet_probe.previous.load_cases()
    jobs=[c['job'] for c in cases]
    settings,camera,_,_=probe.load_config()
    profile,profile_sha=probe.load_motion_profile(probe.PROFILE,settings)
    expected={c['job']['pixel_sha256']:c['records']['original'] for c in cases}
    def factory(job):
        return probe.MotionRangeEngine(settings,camera,profile,profile_sha,acknowledged=True,
            target_roi=runner.ROIS[Path(job['path']).name],observer=probe.observe_upper_completion)
    def synthetic(frame):
        value=expected[probe.sha_bytes(frame.image.tobytes())]
        return [dict(copy.deepcopy(b),image=f'{frame.session}:{frame.sequence}') for b in value['raw_detector_boxes']]
    rows,pairs=runner.benchmark(jobs,synthetic,factory)
    if len(rows)!=80 or len(pairs)!=40 or any(r['exact_pixels'] is not True for r in rows):
        raise ValueError('full four-image synthetic verification required')
    values=runner.summarize(rows,pairs)
    if any(values['pair_counts'][k] for k in ('reason_changed','support_pixel_changed','detector_changed')):
        raise ValueError('deterministic synthetic GPU-input fixture changed after PNG')
    probe.assert_originals(jobs)
    if any(probe.digest(ROOT/n)!=sha for n,sha in {**frozen,**inputs}.items()):
        raise ValueError('previous sources/inputs changed')
    command=[sys.executable]+old['command'][1:]+['tests/test_lossless_packet_gpu.py']
    result=subprocess.run(command,cwd=ROOT,capture_output=True,text=True,timeout=60,
        env=dict(os.environ,PYTEST_DISABLE_PLUGIN_AUTOLOAD='1',OPENBLAS_NUM_THREADS='1'))
    log=result.stdout+result.stderr
    count=re.search(r'(\d+) passed in ([0-9.]+)s',log)
    if result.returncode or count is None or 'skipped' in log:raise ValueError('regression failed: '+log)
    paths=[HERE/'run.py',Path(__file__),ROOT/'tests/test_lossless_packet_gpu.py']
    for path in paths:ast.parse(path.read_bytes())
    manifest=runner.manifest_value()
    output.mkdir(parents=True,exist_ok=False)
    with (output/'tests.txt').open('x') as target:target.write(log)
    for name,value in (('run_manifest.json',manifest),('synthetic_summary.json',
        dict(schema='lossless_GPU_preparation_synthetic_v1',actual_CUDA_inference=False,
             measured_synthetic_samples=80,synthetic_pairs=40,warmup_calls_excluded=24,**values))):
        with (output/name).open('xb') as target:target.write(probe.json_bytes(value))
    for name,items in (('synthetic_samples.jsonl',rows),('synthetic_pairs.jsonl',pairs)):
        with (output/name).open('xb') as target:
            for row in items:target.write(probe.json_bytes(row))
    audit=dict(schema='lossless_GPU_preparation_audit_v1',state='pass',work_date='2026-11-18',
        source_code_sha256={str(p.relative_to(ROOT)):probe.digest(p) for p in paths},
        unchanged_previous_source_sha256=frozen,input_sha256=inputs,
        previous_verification_sha256=probe.digest(old_path),run_manifest_sha256=probe.digest(output/'run_manifest.json'),
        command=command,tests_passed=int(count[1]),elapsed_sec=float(count[2]),failed=0,skipped=0,
        real_saved_images=4,synthetic_measured_samples=80,synthetic_pairs=40,
        actual_CUDA_inference=False,actual_GPUPC_precision_or_load_verified=False,
        images_modified_or_derived_images_saved=False,camera_network_ROS_G923_started=False,
        source_freshness_verified=False,**probe.FLAGS)
    with (output/'audit.json').open('xb') as target:target.write(probe.json_bytes(audit))
    print(json.dumps({k:audit[k] for k in ('state','tests_passed','elapsed_sec',
        'real_saved_images','synthetic_measured_samples','actual_CUDA_inference')},indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path,required=True)
    run(parser.parse_args().output_dir)
