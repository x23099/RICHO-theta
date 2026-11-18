"""Offline regression and frozen-source checks; never starts a network test."""
import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
BASELINE = ROOT / 'Experimental_results/2026-11-18/lossless_packet_gpu_r01/submission_verification_r01/audit.json'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', required=True, type=Path)
    args = parser.parse_args()
    output = args.output_dir.resolve()
    if output.exists() or not output.is_relative_to(HERE):
        parser.error('unused verification directory under this experiment required')
    previous = json.loads(BASELINE.read_bytes())
    frozen = {**previous['source_code_sha256'], **previous['unchanged_previous_source_sha256']}
    if previous['state'] != 'pass' or any(sha(ROOT / name) != digest for name, digest in frozen.items()):
        raise ValueError('successful previous evidence/source must remain unchanged')
    sources = [HERE / 'collect.py', Path(__file__), ROOT / 'tests/test_network_coexistence_collect.py']
    for source in sources:
        ast.parse(source.read_bytes())
    command = [sys.executable, *previous['command'][1:], 'tests/test_network_coexistence_collect.py']
    output.mkdir(parents=True, exist_ok=False)
    process = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=60,
                             env=dict(os.environ, PYTEST_DISABLE_PLUGIN_AUTOLOAD='1', OPENBLAS_NUM_THREADS='1'))
    log = process.stdout + process.stderr
    with (output / 'tests.txt').open('x') as target:
        target.write(log)
    passed = re.search(r'(\d+) passed in ([0-9.]+)s', log)
    if process.returncode or passed is None or 'skipped' in log:
        raise ValueError('all regressions required: ' + log)
    result = dict(schema='network_coexistence_preparation_verification_v1', state='pass',
                  tests_passed=int(passed[1]), failed=0, skipped=0, elapsed_sec=float(passed[2]),
                  command=command, source_sha256={str(p.relative_to(ROOT)): sha(p) for p in sources},
                  unchanged_previous_source_sha256=frozen,
                  baseline_verification_sha256=sha(BASELINE), active_network_test_started=False,
                  video_or_control_modified=False, new_gpu_inference=False, usable_for_ffb=False)
    with (output / 'audit.json').open('x') as target:
        json.dump(result, target, indent=2, allow_nan=False)
        target.write('\n')
    print(json.dumps({key: result[key] for key in ('state', 'tests_passed', 'elapsed_sec')}, indent=2))


if __name__ == '__main__':
    main()
