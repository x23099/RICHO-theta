"""Fresh guarded-bin tests; preserve and validate both r01 and r02 evidence."""
import json
import os
import py_compile
import re
import subprocess
import sys

from run_fast import HERE, PROFILE, p


def main():
    output = HERE / 'verification_r01'
    if output.exists():
        raise ValueError('fresh verification output required')
    sources = {str(x): p.sha256(x) for x in sorted(HERE.glob('*.py'))
               + [HERE / 'method.md', HERE / 'guard_r02_method.md', HERE / 'README.md']}
    for folder in ('results_r01', 'results_guard_r02', 'replay_r01', 'report_r01'):
        path = HERE / folder / 'summary.json'
        p.check_manifest(path)
        sources[str(path)] = p.sha256(path)
    prior_path = PROFILE / 'verification_r01/summary.json'
    prior = p.check_manifest(prior_path)
    assert prior['status'] == 'PASS' and prior['fresh_tests'] == 20
    sources[str(prior_path)] = p.sha256(prior_path)
    for x in HERE.glob('*.py'):
        py_compile.compile(str(x), doraise=True)
    proc = subprocess.run([sys.executable, '-m', 'unittest', 'discover', '-s', str(HERE), '-p', 'test_*.py', '-v'],
                          env=dict(os.environ, OPENBLAS_NUM_THREADS='1'), capture_output=True, text=True)
    log = proc.stdout + proc.stderr
    match = re.search(r'Ran (\d+) tests? in', log)
    passed = proc.returncode == 0 and match is not None
    p.check_hashes(sources)
    output.mkdir()
    (output / 'test_log.txt').write_text(log)
    report = dict(status='PASS' if passed else 'FAIL', source_sha256=sources,
                  fresh_tests=int(match.group(1)) if match else None, profile_tests_reused_not_rerun=20,
                  r01_sources_preserved=True, guarded_r02_is_selected_candidate=True,
                  source_images_edited=False, production_changed=False, physical_output=False, usable_for_ffb=False,
                  output_sha256={'test_log.txt': p.sha256(output / 'test_log.txt')})
    (output / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({k: v for k, v in report.items() if k != 'source_sha256'}, indent=2))
    if not passed:
        print(log)
        raise SystemExit(1)


if __name__ == '__main__':
    main()
