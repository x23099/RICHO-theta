"""Assess copied pin integrity separately from known witness invalidation."""
import argparse
import importlib.util
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[3]
SPEC=importlib.util.spec_from_file_location('body_pin_assessment',
    ROOT/'Experimental_results/2026-11-13/body_display_reference_static_r01/intake.py')
intake=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(intake)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input-dir',type=Path,required=True)
    parser.add_argument('--output-dir',type=Path,required=True)
    args=parser.parse_args()
    payload={p.name:intake.pin.read_regular(p,4*1024*1024) for p in args.input_dir.iterdir()}
    result=intake.check(payload)
    result.update(state='requires_repin' if result['snapshot_requires_repin'] else 'pin_snapshot_eligible_NOT_current_remote_state',
        submitted_files_integrity_verified=True,reference_issued=False,
        supplied_files_sha256={name:intake.pin.sha(blob) for name,blob in payload.items()},
        source_sha256={str(p.relative_to(ROOT)):intake.pin.sha(p.read_bytes()) for p in
            (Path(__file__),Path(intake.__file__),Path(intake.pin.__file__))})
    args.output_dir.mkdir(parents=True,exist_ok=False)
    with (args.output_dir/'audit.json').open('x') as stream:json.dump(result,stream,indent=2);stream.write('\n')
    print(json.dumps({k:result[k] for k in ('state','session','source_frame','snapshot_latest_frame','snapshot_latest_reason','snapshot_requires_repin')},indent=2))


if __name__=='__main__':main()
