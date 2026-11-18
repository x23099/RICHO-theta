"""Verify inventory intake and mocked finite-trial regressions; no live network."""
import argparse
import ast
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SPEC = importlib.util.spec_from_file_location('network_trial_intake_verification', HERE / 'intake.py')
intake = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(intake)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    output = args.output_dir.resolve()
    if output.exists() or not output.is_relative_to(HERE):
        parser.error('unused local verification directory required')
    baseline = HERE / 'verification_r01/audit.json'
    previous = json.loads(baseline.read_bytes())
    frozen = {**previous['source_sha256'], **previous['unchanged_previous_source_sha256']}
    if previous['state'] != 'pass' or any(sha(ROOT / name) != digest for name, digest in frozen.items()):
        raise ValueError('frozen previous source differs')
    audit_path = HERE / 'inventory_audit_r01/audit.json'
    audit = json.loads(audit_path.read_bytes())
    if audit['script_sha256'] != sha(HERE / 'intake.py'):
        raise ValueError('intake code differs')
    raw = ROOT / 'recordings/2026-11-18/network_inventory_intake_r01'
    for role in ('camera', 'gpu'):
        original, report, _, chosen = intake.read(raw / (role + '.tar.xz'), role)
        if (hashlib.sha256(original).hexdigest() != audit['roles'][role]['archive_sha256']
                or hashlib.sha256(report).hexdigest() != audit['roles'][role]['report_sha256']
                or (raw / (role + '_report.json')).read_bytes() != report
                or any(audit['roles'][role][key] != value for key, value in chosen.items())):
            raise ValueError('preserved submitted inventory differs')
    sources = [HERE / name for name in ('intake.py', 'probe.py', 'verify_trial.py')]
    sources.append(ROOT / 'tests/test_network_coexistence_trial.py')
    for path in sources:
        ast.parse(path.read_bytes())
    command = [sys.executable, *previous['command'][1:], 'tests/test_network_coexistence_trial.py']
    output.mkdir(parents=True, exist_ok=False)
    process = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=60,
                             env=dict(os.environ, PYTEST_DISABLE_PLUGIN_AUTOLOAD='1', OPENBLAS_NUM_THREADS='1'))
    log = process.stdout + process.stderr
    with (output / 'tests.txt').open('x') as target:
        target.write(log)
    count = re.search(r'(\d+) passed in ([0-9.]+)s', log)
    if process.returncode or count is None or 'skipped' in log:
        raise ValueError('all regressions required: ' + log)
    result = dict(schema='network_bounded_trial_preparation_verification_v1', state='pass',
                  tests_passed=int(count[1]), failed=0, skipped=0, elapsed_sec=float(count[2]), command=command,
                  source_sha256={str(path.relative_to(ROOT)): sha(path) for path in sources},
                  unchanged_previous_source_sha256=frozen, baseline_verification_sha256=sha(baseline),
                  inventory_audit_sha256=sha(audit_path), active_probe_started=False,
                  iperf_installed_by_agent=False, live_control_or_video_modified=False, usable_for_ffb=False)
    with (output / 'audit.json').open('x') as target:
        json.dump(result, target, indent=2, allow_nan=False)
        target.write('\n')
    print(json.dumps({key: result[key] for key in ('state', 'tests_passed', 'elapsed_sec')}, indent=2))


if __name__ == '__main__':
    main()
