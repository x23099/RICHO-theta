"""Expanded domain-only regression. Synthetic/no camera/CUDA/ROS/control."""
import argparse
from contextlib import redirect_stderr,redirect_stdout
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'tests'));sys.path.insert(0,str(ROOT/'src'))
SPEC=importlib.util.spec_from_file_location('previous_compact_checks',
    ROOT/'Experimental_results/2026-11-11/guarded_compact_compute_r01/check.py')
PREVIOUS=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(PREVIOUS)
NAMES=(*PREVIOUS.NAMES,'test_angular_fisheye_geometry','test_angular_domain_only',
    'test_guarded_cadence_selection','test_cone_colour_support_candidate','test_cone_support_completion_candidate',
    'test_cone_upper_support_candidate','test_cone_distance_diagnostic','test_cone_distance_worker_lifecycle')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path,required=True)
    args=parser.parse_args();args.output_dir.mkdir(parents=True,exist_ok=False)
    previous=ROOT/'Experimental_results/2026-11-11/guarded_compact_compute_r01/checks_r01/summary.json'
    files=set(json.loads(previous.read_bytes())['source_sha256'])
    files.update('tests/'+name+'.py' for name in NAMES)
    files.update(('src/angular_fisheye_geometry.py','src/cone_colour_support_candidate.py',
        'Experimental_results/2026-11-11/guarded_cadence_r01/simulate.py',str(Path(__file__).relative_to(ROOT))))
    hashes={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in sorted(files)}
    log=io.StringIO()
    with redirect_stderr(log),redirect_stdout(log):
        suite=unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromName(name) for name in NAMES)
        result=unittest.TextTestRunner(stream=log,verbosity=2).run(suite)
    unchanged=all(hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==digest for name,digest in hashes.items())
    report=dict(state='pass' if result.wasSuccessful() and unchanged else 'fail',tests_run=result.testsRun,
        failures=len(result.failures),errors=len(result.errors),skips=len(result.skipped),source_sha256=hashes,
        sources_unchanged=unchanged,reused_tests=0,camera_started=False,cuda_started=False,vehicle_operated=False)
    (args.output_dir/'tests.log').write_text(log.getvalue())
    (args.output_dir/'summary.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:report[k] for k in ('state','tests_run','failures','errors','skips')},indent=2))
    if report['state']!='pass':print(log.getvalue());raise SystemExit(1)


if __name__=='__main__':main()
