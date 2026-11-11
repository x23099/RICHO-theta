"""Verify unchanged successful domain/runtime checks by SHA, not a test rerun."""
import argparse
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[3]


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path,required=True)
    args=parser.parse_args();args.output_dir.mkdir(parents=True,exist_ok=False)
    base=ROOT/'Experimental_results/2026-11-11/guarded_domain_only_r01'
    paths=[base/'checks_r01/summary.json',base/'checks_metadata_r01/summary.json']
    previous,metadata=[json.loads(path.read_bytes()) for path in paths]
    if previous['state']!='pass' or previous['tests_run']!=404 or metadata['state']!='pass' or metadata['tests_run']!=22:
        raise ValueError('expected prior successful checks required')
    changed=[name for name,digest in previous['source_sha256'].items() if sha(ROOT/name)!=digest]
    expected='Experimental_results/2026-11-11/guarded_cuda_replay_r01/cuda_replay.py'
    if changed!=[expected]:raise ValueError('unexpected change since domain regression')
    for name,digest in metadata['source_sha256'].items():
        if sha(ROOT/name)!=digest:raise ValueError('metadata followup tested source changed')
    hashes={name:sha(ROOT/name) for name in previous['source_sha256']}
    hashes.update(metadata['source_sha256']);hashes[str(Path(__file__).relative_to(ROOT))]=sha(Path(__file__))
    report=dict(state='pass',prior_regression_count=404,prior_affected_metadata_rerun_count=22,
        tests_executed_this_check=0,counts_overlap_NOT_426_unique=True,
        expected_change_covered_by_metadata_rerun=changed,
        consumed_summaries_sha256={str(path.relative_to(ROOT)):sha(path) for path in paths},
        verified_source_sha256=hashes,cuda_started=False,camera_started=False,vehicle_operated=False)
    (args.output_dir/'summary.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({k:report[k] for k in ('state','prior_regression_count','prior_affected_metadata_rerun_count',
        'tests_executed_this_check')},indent=2))


if __name__=='__main__':main()
