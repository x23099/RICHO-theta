"""Four-file current pin + display-gate metadata audit; no live/GPU/control."""
import argparse
import importlib.util
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[3]
SPEC=importlib.util.spec_from_file_location('current_pin',ROOT/'Experimental_results/2026-11-13/guarded_static_reference_r02/intake.py')
pin=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(pin)
GUARD_SOURCES=('driver_body_display_guard.py','cone_self_body_shadow.py','driver_motion_process.py',
    'driver_motion_bridge.py','driver_motion_protocol.py','driver_guarded_comparison.py','cone_guarded_stream_comparison.py')


def check(payload):
    pin.require('motion_engine_summary.json' in payload,'engine summary required')
    pin_payload={name:blob for name,blob in payload.items() if name!='motion_engine_summary.json'}
    report=pin.check(pin_payload)
    engine=pin.parse_json(payload['motion_engine_summary.json']);gate=engine.get('body_display_guard',{})
    pin.require(engine.get('schema')=='driver_motion_engine_v1' and gate.get('enabled') is True
        and gate.get('raw_main_result_modified') is False and gate.get('display_rejection_only') is True
        and gate.get('reference_source')=='same_stream_explicit_pin_load'
        and gate.get('controlling_distance') is False and gate.get('usable_for_ffb') is False,'explicit rejection-only display gate required')
    pin.require(all(engine.get(k) is False for k in ('physical_metric_verified','usable_for_ffb','published_to_ros','mount_or_floor_tilt_compensated')),
        'engine authority changed')
    comparison=engine.get('guarded_comparison',{})
    pin.require(comparison.get('requested') is True and comparison.get('worker_started') is True
        and comparison.get('main_display_modified') is False and comparison.get('controlling_distance') is False,'comparison not started/isolated')
    hashes=gate.get('code_sha256',{})
    pin.require(set(hashes)==set(GUARD_SOURCES),'display code manifest differs')
    for name,digest in hashes.items():
        pin.require(pin.sha(pin.read_regular(ROOT/'src'/name,256*1024))==digest,'display code SHA mismatch: '+name)
    config=ROOT/'src/cone_distance_diagnostic_config.json'
    settings=pin.parse_json(pin.read_regular(config,256*1024))
    profile=ROOT/'Experimental_results/2026-11-09/cone_motion_evaluation_r01/prepared_r01/motion_profile_r01.json'
    pin.require(engine['config_sha256']==pin.sha(pin.read_regular(config,256*1024)),'config SHA mismatch')
    pin.require(engine['weights_sha256']==settings['weights_sha256'],'recorded checkpoint differs')
    pin.require(engine['profile_sha256']==pin.sha(pin.read_regular(profile,256*1024)),'profile SHA mismatch')
    report.update(pin_files_sha256={name:pin.sha(blob) for name,blob in pin_payload.items()},
        display_guard_enabled=True,display_guard_code_files_rehashed=len(hashes),
        display_gate_code_sha256=hashes,engine_summary=engine,display_guard_gui_output_NOT_verified=True,
        exact_primary_pin_line_NOT_supplied=True,remote_witness_still_valid_NOT_verified=True,
        checkpoint_file_independently_rehashed=False)
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive',type=Path,required=True)
    parser.add_argument('--intake-dir',type=Path,required=True)
    parser.add_argument('--output-dir',type=Path,required=True)
    args=parser.parse_args()
    pin.require(not args.intake_dir.exists() and not args.output_dir.exists(),'new output paths required')
    pin.require(args.archive.stat().st_size<=5*1024*1024,'bounded archive required')
    payload=pin.read_archive(args.archive,'1113body');report=check(payload)
    report.update(archive_sha256=pin.sha(pin.read_regular(args.archive,5*1024*1024)),
        supplied_files_sha256={name:pin.sha(blob) for name,blob in payload.items()},
        source_sha256={str(p.relative_to(ROOT)):pin.sha(p.read_bytes()) for p in (Path(__file__),Path(pin.__file__))})
    args.intake_dir.mkdir(parents=True)
    for name,blob in payload.items():
        with (args.intake_dir/name).open('xb') as stream:stream.write(blob)
    args.output_dir.mkdir(parents=True)
    with (args.output_dir/'audit.json').open('x') as stream:json.dump(report,stream,indent=2);stream.write('\n')
    print(json.dumps({k:report[k] for k in ('state','session','source_frame','snapshot_latest_frame','display_guard_enabled','display_guard_code_files_rehashed')},indent=2))


if __name__=='__main__':main()
