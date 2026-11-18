"""Local fixed-suite packaging/regression audit; synthetic predictor, NOT GPU."""
import argparse
import ast
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SPEC = importlib.util.spec_from_file_location('saved_suite_preparation',HERE/'run_suite.py')
suite = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(suite)


def run(output,input_pack):
    output = output.resolve()
    if output.exists() or HERE not in output.parents:
        raise ValueError('unused suite verification output required')
    previous = ROOT/'Experimental_results/2026-11-18/frame_packet_gpu_recompression_r01/verification_r03/audit.json'
    old = json.loads(previous.read_bytes())
    for name,sha in old['runtime_source_unchanged_sha256'].items():
        if suite.probe.digest(ROOT/name) != sha:
            raise ValueError('previous runtime changed: '+name)
    if suite.probe.digest(suite.LEGACY) != suite.LEGACY_SHA:
        raise ValueError('old GPU runner changed')
    output.mkdir(parents=True,exist_ok=False)
    with tempfile.TemporaryDirectory(prefix='theta-suite-codec-check-') as temporary:
        paths = suite.unpack_inputs(input_pack,temporary)
        jobs = suite.probe.load_images(paths)
        pixel_hashes = [j['pixel_sha256'] for j in jobs]
        settings,camera,_,_ = suite.probe.load_config()
        profile,sha = suite.probe.load_motion_profile(suite.probe.PROFILE,settings)
        synthetic = output/'synthetic_predictor_only'
        synthetic.mkdir()
        def factory():
            return suite.probe.MotionRangeEngine(settings,camera,profile,sha,acknowledged=True,
                target_roi=suite.ROI,observer=suite.probe.observe_upper_completion)
        def predict(frame):
            # Test-only fixed box, NOT actual saved-image YOLO inference.
            return [dict(x1=285.,y1=295.,x2=345.,y2=420.,class_id=0,confidence=.95)]
        rows,pairs,summary = suite.probe.benchmark(jobs,predict,factory,output=synthetic)
        with (synthetic/'pairs.jsonl').open('xb') as target:
            for pair in pairs:target.write(suite.probe.json_bytes(pair))
        values = suite.summarize_by_image(synthetic)
        suite.probe.assert_originals(jobs)
        if len(rows) != 60 or len(pairs) != 30 or len(values) != 3:
            raise ValueError('complete synthetic batch required')
        with (output/'synthetic_per_image_summary.json').open('xb') as target:
            target.write(suite.probe.json_bytes(dict(result_kind='synthetic_predictor_NOT_actual_GPU_result',cases=values)))
    command = old['command'] + ['tests/test_frame_packet_saved_suite.py','tests/test_frame_packet_saved_suite_audit.py']
    command[0] = sys.executable
    result = subprocess.run(command,cwd=ROOT,capture_output=True,text=True,timeout=60,
        env=dict(os.environ,OPENBLAS_NUM_THREADS='1',PYTEST_DISABLE_PLUGIN_AUTOLOAD='1'))
    log = result.stdout+result.stderr
    with (output/'tests.txt').open('x') as target:target.write(log)
    match = re.search(r'(\d+) passed in ([0-9.]+)s',log)
    if result.returncode or match is None or 'skipped' in log:
        raise ValueError('all suite/regression tests required: '+log)
    files = [HERE/'run_suite.py',HERE/'audit_submission.py',Path(__file__),
             ROOT/'tests/test_frame_packet_saved_suite.py',ROOT/'tests/test_frame_packet_saved_suite_audit.py']
    for path in files:ast.parse(path.read_bytes())
    audit = dict(schema='saved_packet_suite_preparation_audit_v1',state='pass',work_date='2026-11-18',
        input_pack_sha256=suite.probe.digest(input_pack),input_manifest=suite.manifest(),
        original_pixel_sha256=pixel_hashes,previous_verification_sha256=suite.probe.digest(previous),
        source_code_sha256={str(p.relative_to(ROOT)):suite.probe.digest(p) for p in files},
        unchanged_previous_runtime_source_sha256=old['runtime_source_unchanged_sha256'],
        unchanged_old_GPU_runner_sha256=suite.LEGACY_SHA,
        command=command,tests_passed=int(match[1]),elapsed_sec=float(match[2]),failed=0,skipped=0,
        real_saved_images=3,synthetic_predictor_measured_samples=60,synthetic_predictor_pairs=30,
        real_VP8_and_geometry_used=True,actual_CUDA_inference=False,
        new_actual_GPU_precision_or_load_verified=False,images_modified_or_derived_images_saved=False,
        camera_ROS_network_G923_started=False,source_freshness_verified=False,**suite.probe.FLAGS)
    with (output/'audit.json').open('xb') as target:target.write(suite.probe.json_bytes(audit))
    print(json.dumps({k:audit[k] for k in ('state','tests_passed','elapsed_sec',
        'real_saved_images','synthetic_predictor_measured_samples','actual_CUDA_inference')},indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input-pack',type=Path,required=True)
    parser.add_argument('--output-dir',type=Path,required=True)
    args = parser.parse_args()
    run(args.output_dir,args.input_pack)
