"""Record tests and input hashes without opening the real review queue UI."""
import argparse
import json
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'src'))
import review_physical_reference as review


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output-dir',type=Path,required=True);args=p.parse_args()
    args.output_dir.mkdir(parents=True,exist_ok=False)
    base=Path(__file__).resolve().parent;queue_path=base/'prepared_r01/queue.json'
    queue=review.validate_queue(review.read_json(queue_path));hashed=review.digest(queue_path)
    initial={i['image']:review.digest(ROOT/i['image']) for i in queue['items']}
    patterns=['test_review_physical_reference.py','test_derive_fixed_floor_live_bundle.py','test_floor_reference_pose.py']
    suite=unittest.TestSuite()
    for pattern in patterns:suite.addTests(unittest.defaultTestLoader.discover(str(ROOT/'tests'),pattern=pattern))
    with (args.output_dir/'tests.log').open('x') as stream:
        result=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
    decisions=review.load_decisions(base/'prepared_r01/decisions',queue,hashed)
    prior=ROOT/'Experimental_results/2026-11-04/upper_support_live_r01/verification_r01/verification.json'
    previous=review.read_json(prior)
    changed=[name for name,sha in previous['source_sha256'].items() if review.digest(ROOT/name)!=sha]
    checks=dict(tests_pass=result.wasSuccessful() and not result.skipped,native_images_checked=len(initial)==6,
        image_bytes_unchanged=all(review.digest(ROOT/name)==sha for name,sha in initial.items()),
        queue_bytes_unchanged=review.digest(queue_path)==hashed,real_human_decisions_not_invented=not decisions,
        prior_runtime_hashes_unchanged=not changed)
    sources=[Path(__file__),base/'gui_smoke.py',ROOT/'src/review_physical_reference.py',ROOT/'tests/test_review_physical_reference.py',base/'spec.json',queue_path]
    output=dict(status='PASS_REVIEW_PREPARATION_SOFTWARE_ONLY' if all(checks.values()) else 'FAIL',checks=checks,
        tests=result.testsRun,failures=len(result.failures),errors=len(result.errors),skipped=len(result.skipped),patterns=patterns,
        source_sha256={str(s.relative_to(ROOT)):review.digest(s) for s in sources},
        image_sha256=initial,prior_software_tests_reused=previous['tests'],prior_runtime_mismatches=changed,
        real_human_reviews_performed=0,physical_metric_verified=False,usable_for_ffb=False)
    review.dump_new(args.output_dir/'verification.json',output)
    print(json.dumps({k:v for k,v in output.items() if k not in ('source_sha256','image_sha256')},indent=2))
    return 0 if all(checks.values()) else 1


if __name__=='__main__':raise SystemExit(main())
