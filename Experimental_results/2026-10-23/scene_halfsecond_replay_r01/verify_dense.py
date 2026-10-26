"""Fresh local tests and evidence hash checks; no prior-output edits."""
import json
import os
from pathlib import Path
import py_compile
import re
import subprocess
import sys

from dense_common import HERE, REUSE, sha256, check_manifest, check_hashes


def main():
    output = HERE / 'verification_r01'
    if output.exists():
        raise ValueError('fresh verification output required')
    sources = {str(p): sha256(p) for p in sorted(HERE.glob('*.py')) + [HERE / 'method.md', HERE / 'README.md']}
    checked = 0
    for folder in ('intake_r01', 'scene_results_r01', 'replay_r01', 'report_r01'):
        path = HERE / folder / 'summary.json'
        proof = check_manifest(path)
        sources[str(path)] = sha256(path)
        checked += len(proof.get('source_sha256', {})) + len(proof.get('output_sha256', {}))
    # Reuse exactly the unchanged ray optimization's 37-test evidence.
    previous = REUSE / 'verification_r01/summary.json'
    prior = check_manifest(previous)
    assert prior['status'] == 'PASS' and prior['fresh_tests'] == 37
    sources[str(previous)] = sha256(previous)
    for p in HERE.glob('*.py'):
        py_compile.compile(str(p), doraise=True)
    process = subprocess.run([sys.executable, '-m', 'unittest', 'discover', '-s', str(HERE), '-p', 'test_*.py', '-v'],
                             env=dict(os.environ, OPENBLAS_NUM_THREADS='1'), capture_output=True, text=True)
    log = process.stdout + process.stderr
    match = re.search(r'Ran (\d+) tests? in', log)
    passed = process.returncode == 0 and match is not None
    check_hashes(sources)
    output.mkdir()
    (output / 'test_log.txt').write_text(log)
    summary = dict(status='PASS' if passed else 'FAIL', source_sha256=sources,
                   fresh_tests=int(match.group(1)) if match else None,
                   reused_ray_optimization_tests_not_rerun=37, evidence_file_hash_checks=checked,
                   source_images_edited=False, production_changed=False, physical_output=False, usable_for_ffb=False,
                   output_sha256={'test_log.txt': sha256(output / 'test_log.txt')})
    (output / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps({k: v for k, v in summary.items() if k != 'source_sha256'}, indent=2))
    if not passed:
        print(log)
        raise SystemExit(1)


if __name__ == '__main__':
    main()
