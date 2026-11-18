"""Reproduce a saved paired UDP audit (audit_udp_v2) and run offline regressions."""
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
SCRIPT = HERE / 'audit_udp_v2.py'
SPEC = importlib.util.spec_from_file_location('verified_saved_udp_audit_v2', SCRIPT)
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--results', type=Path, required=True)
    parser.add_argument('--raw-dir', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    output, raw = args.output_dir.resolve(), args.raw_dir.resolve()
    if output.exists() or not output.is_relative_to(HERE) or not raw.is_relative_to(ROOT / 'recordings'):
        parser.error('unused local verification output and raw recordings required')
    value = audit.parse((args.results / 'audit.json').read_bytes())
    loaded = {role: audit.archive(raw / role / 'original.tar.xz') for role in ('client', 'server')}
    reproduced = audit.paired(loaded['client'][2], loaded['server'][2],
                              value['condition_operator_reported_NOT_verified'], value['target_mbps'])
    for key, expected in reproduced.items():
        audit.require(value[key] == expected, 'saved UDP aggregate differs: ' + key)
    audit.require(value['audit_script_sha256'] == digest(SCRIPT), 'audit source differs')
    audit.require(value['base_audit_sha256'] == digest(HERE / 'audit_udp.py'), 'base audit source differs')
    for role, (original, files, _) in loaded.items():
        audit.require(value['archives'][role]['sha256'] == audit.sha(original), 'source archive SHA differs')
        for name, data in files.items():
            audit.require((raw / role / name).read_bytes() == data
                          and value['archives'][role]['files_sha256'][name] == audit.sha(data), 'raw trial differs')
    baseline = HERE / 'trial_verification_r01/audit.json'
    previous = audit.parse(baseline.read_bytes())
    frozen = {**previous['source_sha256'], **previous['unchanged_previous_source_sha256']}
    audit.require(previous['state'] == 'pass' and all(digest(ROOT / name) == sha for name, sha in frozen.items()),
                  'previous frozen source differs')
    sources = [SCRIPT, HERE / 'audit_udp.py', Path(__file__), ROOT / 'tests/test_network_udp_audit_v2.py']
    for path in sources:
        ast.parse(path.read_bytes())
    command = [sys.executable, *previous['command'][1:], 'tests/test_network_udp_audit.py',
               'tests/test_network_udp_audit_v2.py']
    output.mkdir(parents=True, exist_ok=False)
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=60,
                            env=dict(os.environ, PYTEST_DISABLE_PLUGIN_AUTOLOAD='1', OPENBLAS_NUM_THREADS='1'))
    log = result.stdout + result.stderr
    with (output / 'tests.txt').open('x') as target:
        target.write(log)
    count = re.search(r'(\d+) passed in ([0-9.]+)s', log)
    audit.require(result.returncode == 0 and count is not None and 'skipped' not in log, 'regression failure: ' + log)
    result = dict(schema='saved_udp_submission_verification_v1', state='pass', tests_passed=int(count[1]),
                  failed=0, skipped=0, elapsed_sec=float(count[2]), command=command,
                  source_sha256={str(path.relative_to(ROOT)): digest(path) for path in sources},
                  unchanged_previous_source_sha256=frozen, baseline_verification_sha256=digest(baseline),
                  submission_audit_sha256=digest(args.results / 'audit.json'),
                  received_aggregates_and_raw_hashes_reproduced=True, new_network_test_started=False,
                  video_or_control_modified=False, usable_for_ffb=False)
    with (output / 'audit.json').open('x') as target:
        json.dump(result, target, indent=2, allow_nan=False)
        target.write('\n')
    print(json.dumps({key: result[key] for key in ('state', 'tests_passed', 'elapsed_sec')}, indent=2))


if __name__ == '__main__':
    main()
