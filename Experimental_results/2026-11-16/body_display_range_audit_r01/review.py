"""Audit the closed 11/16 run and three reported UI points; no live I/O."""
import argparse
import csv
from decimal import Decimal
import importlib.util
import io
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


intake = module('range_closed_intake', ROOT/'Experimental_results/2026-11-13/body_display_occlusion_live_audit_r01/review.py')
shared = intake.shared
require, file_sha = shared.require, shared.file_sha
SESSION = 'e52bb32f03d6488ebf37d769f46ec37a'
PIN = f'decoded_{SESSION}_f005186'
PREFIXES = {'primary': 'Experimental_results/2026-11-16/driver_body_guard_live_r01',
            'comparison': 'recordings/2026-11-16/body_guard_live_r01'}
FILES = {'primary': shared.FILES['primary'],
         'comparison': ('comparison_frames.jsonl', 'comparison_status.json',
                        'reference.json', 'request.json', PIN+'.json', PIN+'.png')}
BASE = Path(__file__).resolve().parent
OBSERVATIONS = BASE.parent/'body_display_range_check_r01/observations.csv'


def check_observation(observation, row):
    """A reported point must match its exact logged frame, not a nearby value."""
    require(row['session'] == observation['session'] == SESSION
            and row['frame'] == int(observation['frame']), 'screen frame/session mismatch')
    require(row['display_permitted'] is True and row['bridge_accepted'] is True
            and row['original_available'] is True, 'screen value not accepted/permitted')
    require(row['reference_generation'] == int(observation['body_review_generation']) == 1,
            'screen reference generation mismatch')
    require(row['display_range_m'] == row['original_range_m'], 'display substituted raw value')
    require(format(row['display_range_m'], '.3f') == format(Decimal(observation['displayed_range_m']), '.3f'),
            'screen rounded distance mismatch')
    measured = Decimal(observation['reported_floor_range_m'])
    difference = Decimal(observation['displayed_range_m']) - measured
    require(measured > 0 and difference == Decimal(observation['signed_difference_m']),
            'reported measurement/difference mismatch')
    require(abs(difference/measured*100-Decimal(observation['signed_difference_percent'])) < Decimal('1e-12'),
            'reported percentage mismatch')
    return dict(frame=row['frame'], session=row['session'], source_time_sec=row['source_time_sec'],
        reference_generation=row['reference_generation'], reported_measured_m=float(measured),
        screenshot_range_m=float(observation['displayed_range_m']), logged_raw_range_m=row['original_range_m'],
        logged_display_range_m=row['display_range_m'], rounded_screen_value_matches=True,
        displayed_minus_reported_m=float(difference), measurement_uncertainty_m=None,
        screenshot_original_file_supplied=False, source='user_report_and_conversation_screenshot',
        raw_age_ms=row['raw_age_ms'], review_completion_age_ms=row['review_age_ms'],
        raw_to_review_ms=row['raw_to_review_ms'], comparison_range_m=row['comparison_range_m'],
        original_reason=row['original_reason'], display_reason=row['display_reason'])


def run(args):
    args.archive = args.archive.resolve()
    args.intake_dir = args.intake_dir.resolve()
    args.output_dir = args.output_dir.resolve()
    require(not args.intake_dir.exists() and not args.output_dir.exists(), 'new output paths required')
    allowed = {PREFIXES[role]+'/'+name: role+'/'+name for role, names in FILES.items() for name in names}
    directories = {*PREFIXES.values(), PREFIXES['primary']+'/ultralytics_config',
                   PREFIXES['primary']+'/ultralytics_config/matplotlib',
                   PREFIXES['primary']+'/ultralytics_config/Ultralytics'}
    hashes = intake.extract_checked(args.archive, args.intake_dir, allowed, directories)
    print(f'{len(hashes)} original files safely preserved; auditing logs.', flush=True)
    summary = json.loads((args.intake_dir/'primary/driver_motion_summary.json').read_bytes())
    pending = summary['sent'] - summary['returned']
    require(pending in (0, 1), 'unexpected pending primary results')
    result, timings = shared.analyze(args.intake_dir, pin_stem=PIN, request_count=2, pending_sent=pending,
        issued_reference_path=BASE.parent/'body_display_reference_r01/reference.json',
        prior_pin_directory=ROOT/'recordings/2026-11-16/body_display_pin_intake_r01')
    require(result['session'] == SESSION and result['pin_frame'] == 5186, 'unexpected run identity')
    status = result['shutdown']['comparison']
    unprocessed = status['offered']-status['processed']-status['latest_slot_overwrites']-status['tap_busy_drops']
    require(unprocessed in (0, 1), 'comparison loss not explained by counters/final pending')
    rows = list(csv.DictReader(OBSERVATIONS.open()))
    require(len(rows) == 3 and len({r['frame'] for r in rows}) == 3, 'three distinct reported points required')
    by_frame = {r['frame']: r for r in timings}
    points = [check_observation(r, by_frame[int(r['frame'])]) for r in rows]
    require(all(file_sha(args.intake_dir/name) == digest for name, digest in hashes.items()), 'original bytes changed')
    derived = args.intake_dir/'derived'
    derived.mkdir()
    blob = io.StringIO(newline='')
    writer = csv.DictWriter(blob, fieldnames=timings[0])
    writer.writeheader()
    writer.writerows(timings)
    with (derived/'display_timing.csv').open('xb') as stream:
        stream.write(blob.getvalue().encode())
    result.update(schema='body_display_three_distance_closed_audit_v1', archive_sha256=file_sha(args.archive),
        supplied_files_sha256=hashes, all_submitted_bytes_unchanged=True, reported_points=points,
        screenshot_observations_sha256=file_sha(OBSERVATIONS),
        sampled_max_absolute_displayed_difference_m=max(abs(p['displayed_minus_reported_m']) for p in points),
        comparison_final_pending=unprocessed,
        complete_timing_csv=dict(path=str((derived/'display_timing.csv').relative_to(ROOT)),
                                 sha256=file_sha(derived/'display_timing.csv')),
        audit_code_sha256={str(p.relative_to(ROOT)): file_sha(p) for p in
            (Path(__file__), Path(intake.__file__), Path(shared.__file__), Path(shared.shared.__file__),
             ROOT/'src/report_driver_motion_logs.py', ROOT/'src/verify_driver_withheld_evidence.py')})
    result['limits'].update(measured_stationary_intervals_verified=False,
        measurement_uncertainty_known=False, independent_metric_accuracy_certified=False,
        all_screenshot_original_files_supplied=False, all_screenshot_draws_verified=False)
    args.output_dir.mkdir(parents=True)
    with (args.output_dir/'audit.json').open('x') as stream:
        json.dump(result, stream, indent=2)
        stream.write('\n')
    print(json.dumps(dict(state=result['state'], points=points, post_load=result['phases']['post_load'],
                          shutdown=result['shutdown']), indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--intake-dir', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    run(parser.parse_args())


if __name__ == '__main__':
    main()
