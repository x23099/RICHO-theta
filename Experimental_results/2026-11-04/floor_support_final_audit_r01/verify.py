"""Record offline analysis tests and immutable-input checks."""
import argparse
import json
from pathlib import Path
import sys
import unittest

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
sys.path.insert(0,str(ROOT/'src'))
from cone_distance_core import digest


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--results-dir',required=True,type=Path)
    p.add_argument('--output-dir',required=True,type=Path)
    args=p.parse_args();args.output_dir.mkdir(parents=True,exist_ok=False)
    summary=json.loads((args.results_dir/'summary.json').read_text())
    bad=[name for name,sha in summary['source_sha256'].items() if digest(ROOT/name)!=sha]
    suite=unittest.TestSuite()
    suite.addTests(unittest.defaultTestLoader.discover(str(HERE),pattern='test_audit.py'))
    prior=ROOT/'Experimental_results/2026-11-04/floor_df33e833_diagnosis_r01'
    # A fresh loader avoids discover top-level state leaking between unrelated folders.
    suite.addTests(unittest.TestLoader().discover(str(prior),pattern='test_diagnose.py',top_level_dir=str(prior)))
    with (args.output_dir/'tests.log').open('x') as stream:
        result=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
    reuse_path=ROOT/'Experimental_results/2026-11-04/upper_support_live_r01/verification_r01/verification.json'
    reuse=json.loads(reuse_path.read_text())
    changed=[name for name,sha in reuse['source_sha256'].items() if digest(ROOT/name)!=sha]
    checks=dict(local_tests_pass=result.wasSuccessful() and not result.skipped,
        source_images_and_inputs_unchanged=not bad,prior_435_runtime_hashes_unchanged=not changed,
        floor_solutions_reproduced=summary['pose_solutions_reproduced']==32,
        original_distance_rows_revalidated=summary['distance_rows_revalidated']==1800,
        saved_images_reproduced=summary['native_saved_frames_reproduced']==8,
        all_models_including_withheld_retained=summary['distance_comparison_rows']==40,
        no_model_selected=summary['selected_model'] is None,
        no_runtime_changes=summary['runtime_changed'] is False,
        no_mixed_session_calibration=summary['mixed_session_calibration'] is False)
    sources=[Path(__file__),HERE/'audit.py',HERE/'test_audit.py',args.results_dir/'summary.json',reuse_path]
    report=dict(status='PASS_OFFLINE_AUDIT_CHECKS_NOT_PHYSICAL_APPROVAL' if all(checks.values()) else 'FAIL',
        checks=checks,tests=result.testsRun,failures=len(result.failures),errors=len(result.errors),skipped=len(result.skipped),
        prior_software_tests_reused=reuse['tests'],source_hash_mismatches=bad,prior_source_mismatches=changed,
        source_sha256={str(s.resolve().relative_to(ROOT)):digest(s) for s in sources},
        physical_metric_verified=False,usable_for_ffb=False,hardware_started=False)
    (args.output_dir/'verification.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2));return 0 if all(checks.values()) else 1


if __name__=='__main__':raise SystemExit(main())
