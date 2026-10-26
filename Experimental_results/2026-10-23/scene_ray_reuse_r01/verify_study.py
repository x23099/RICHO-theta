"""Record fresh tests and validate all immutable new-study evidence hashes."""
import json
import os
from pathlib import Path
import py_compile
import re
import subprocess
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from run_comparison import sha256


def main():
    output = HERE / 'verification_r01'
    if output.exists():
        raise ValueError('fresh verification output required')
    paths = sorted(HERE.glob('*.py')) + [HERE / 'method.md', HERE / 'README.md']
    sources = {str(p): sha256(p) for p in paths}
    checked = 0
    previous = HERE.parent / 'closeout_r01/results_r01/summary.json'
    previous_proof = json.loads(previous.read_text())
    assert previous_proof['status'] == 'PASS_DAY_CLOSEOUT'
    assert previous_proof['newly_rerun_tests'] == 125
    sources[str(previous)] = sha256(previous)
    reused_manifests = [previous] + [study_root / r['manifest']
        for study_root in [HERE.parents[2]] for r in previous_proof['manifest_checks']]
    for path in reused_manifests:
        proof = json.loads(path.read_text())
        if proof.get('status') != 'FAIL':
            for name, h in proof.get('source_sha256', {}).items():
                assert sha256(Path(name)) == h, name
                checked += 1
        for name, h in proof.get('output_sha256', {}).items():
            assert sha256(path.parent / name) == h, name
            checked += 1
    for folder in ('results_r01', 'replay_r01', 'report_r01'):
        p = HERE / folder / 'summary.json'
        sources[str(p)] = sha256(p)
        proof = json.loads(p.read_text())
        for name, h in proof['source_sha256'].items():
            assert sha256(Path(name)) == h, name
            checked += 1
        for name, h in proof['output_sha256'].items():
            assert sha256(HERE / folder / name) == h, name
            checked += 1
    for p in HERE.glob('*.py'):
        py_compile.compile(str(p), doraise=True)
    env = dict(os.environ, OPENBLAS_NUM_THREADS='1')
    process = subprocess.run([sys.executable, '-m', 'unittest', 'discover', '-s', str(HERE), '-p', 'test_*.py', '-v'],
                             env=env, capture_output=True, text=True)
    log = process.stdout + process.stderr
    tests = re.search(r'Ran (\d+) tests? in', log)
    passed = process.returncode == 0 and tests is not None
    assert all(sha256(Path(p)) == h for p, h in sources.items())
    output.mkdir()
    (output / 'test_log.txt').write_text(log)
    summary = dict(status='PASS' if passed else 'FAIL', fresh_tests=int(tests.group(1)) if tests else None,
                   source_sha256=sources, evidence_file_hash_checks=checked,
                   prior_tests_reused_not_rerun=125, previous_closeout_not_modified=True,
                   reused_manifest_count=len(reused_manifests),
                   physical_output=False, usable_for_ffb=False,
                   output_sha256={'test_log.txt': sha256(output / 'test_log.txt')})
    (output / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps({k: v for k, v in summary.items() if k != 'source_sha256'}, indent=2))
    if not passed:
        print(log)
        raise SystemExit(1)


if __name__ == '__main__':
    main()
