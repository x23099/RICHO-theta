"""Full static-run audit helper and existing log-parser checks, no hardware."""
import argparse
from contextlib import redirect_stderr,redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'tests'))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path,required=True)
    args=parser.parse_args();args.output_dir.mkdir(parents=True,exist_ok=False)
    paths=[Path(__file__),Path(__file__).with_name('review.py'),ROOT/'src/report_driver_motion_logs.py',
        ROOT/'tests/test_guarded_static_full_audit.py',ROOT/'tests/test_report_driver_motion_logs.py']
    hashes={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    log=io.StringIO()
    with redirect_stdout(log),redirect_stderr(log):
        suite=unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromName(n)
            for n in ('test_guarded_static_full_audit','test_report_driver_motion_logs'))
        result=unittest.TextTestRunner(stream=log,verbosity=2).run(suite)
    unchanged=all(hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==sha for name,sha in hashes.items())
    report=dict(state='pass' if result.wasSuccessful() and unchanged else 'fail',tests_run=result.testsRun,
        failures=len(result.failures),errors=len(result.errors),skips=len(result.skipped),source_sha256=hashes,
        local_camera_started=False,local_cuda_started=False,local_vehicle_operation=False)
    (args.output_dir/'tests.log').write_text(log.getvalue());(args.output_dir/'summary.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:report[k] for k in ('state','tests_run','failures','errors','skips')},indent=2))
    if report['state']!='pass':print(log.getvalue());raise SystemExit(1)


if __name__=='__main__':main()
