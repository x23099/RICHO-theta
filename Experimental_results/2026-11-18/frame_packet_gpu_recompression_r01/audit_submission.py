"""Read submitted GPU JSON, reproduce packet pixels, diagnose offline ROI only.

Never run YOLO/GPU or relabel a post-hoc calculation as the original GPU run.
Archive contents are data, not instructions. No general-purpose extraction.
"""
import argparse
import csv
import importlib.util
import io
import json
import math
from pathlib import Path, PurePosixPath
import tarfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SPEC = importlib.util.spec_from_file_location('submitted_packet_probe', HERE/'run.py')
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)
MAX_ARCHIVE = 16 * 1024 * 1024
PREFIX = 'packet_recompression_gpu_r01/'
PROTOCOL_ROI = {'r01': [270, 0, 350, 720], 'r02': [200, 0, 280, 720]}
JSON_NAMES = ('summary.json', 'samples.jsonl', 'pairs.jsonl')


def protocol_prefix(protocol):
    if protocol not in PROTOCOL_ROI:
        raise ValueError('explicit supported protocol required')
    return 'packet_recompression_gpu_' + protocol + '/'


def parse(data):
    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                raise ValueError('duplicate JSON key')
            value[key] = item
        return value
    def reject(value):
        raise ValueError('nonfinite JSON: '+value)
    def finite_float(value):
        number = float(value)
        if not math.isfinite(number):
            raise ValueError('nonfinite JSON number')
        return number
    return json.loads(data, object_pairs_hook=pairs, parse_constant=reject, parse_float=finite_float)


def read_archive(path, *, protocol='r01'):
    prefix = protocol_prefix(protocol)
    data = probe.bounded_regular_bytes(path, MAX_ARCHIVE)
    selected, names, expanded = {}, set(), 0
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:xz') as archive:
        for n, member in enumerate(archive):
            path = PurePosixPath(member.name)
            if (n >= 64 or path.is_absolute() or '..' in path.parts or member.name in names
                    or not (member.isfile() or member.isdir()) or member.size < 0
                    or not path.parts or path.parts[0] != prefix.rstrip('/')):
                raise ValueError('unsafe/unexpected archive member')
            names.add(member.name)
            expanded += member.size
            if expanded > 64 * 1024 * 1024:
                raise ValueError('expanded archive size limit')
            for name in JSON_NAMES:
                if member.name == prefix + name:
                    if not member.isfile() or member.size > probe.MAX_LOG:
                        raise ValueError('bounded regular result JSON required')
                    selected[name] = archive.extractfile(member).read(probe.MAX_LOG+1)
    if set(selected) != set(JSON_NAMES):
        raise ValueError('three result JSON files required')
    summary = parse(selected['summary.json'])
    rows = [parse(line) for line in selected['samples.jsonl'].splitlines()]
    pairs = [parse(line) for line in selected['pairs.jsonl'].splitlines()]
    if (summary.get('schema') != 'offline_packet_recompression_GPU_audit_v1'
            or summary.get('state') != 'complete' or summary.get('actual_cuda_inference') is not True):
        raise ValueError('completed CUDA probe required')
    for name in ('samples.jsonl', 'pairs.jsonl'):
        if probe.sha_bytes(selected[name]) != summary['result_sha256'][name]:
            raise ValueError('submitted result SHA mismatch')
    return data, selected, summary, rows, pairs


def equivalent(actual, expected):
    if isinstance(expected, dict):
        return (isinstance(actual, dict) and set(actual) == set(expected)
                and all(equivalent(actual[k], v) for k, v in expected.items()))
    if isinstance(expected, (list, tuple)):
        return (isinstance(actual, (list, tuple)) and len(actual) == len(expected)
                and all(equivalent(a, b) for a, b in zip(actual, expected)))
    if type(expected) is float:
        return type(actual) in (int, float) and math.isfinite(actual) and math.isclose(actual, expected, rel_tol=1e-10, abs_tol=1e-10)
    return type(actual) is type(expected) and actual == expected


def checked_rows(summary, rows, pairs, *, protocol='r01'):
    protocol_prefix(protocol)  # Never infer the intended protocol from the result.
    # Both submitted protocols use one image/five cycles; only explicit ROI differs.
    if (summary.get('image_count') != 1 or summary.get('repetitions') != 5
            or summary.get('warmup_calls_excluded') != 6 or summary.get('measured_samples') != 20
            or summary.get('paired_samples') != 10 or len(rows) != 20 or len(pairs) != 10
            or summary.get('target_roi_native_xyxy') != PROTOCOL_ROI[protocol]
            or any(summary.get(k) is not False for k in probe.FLAGS)):
        raise ValueError('exact '+protocol+' preliminary protocol required')
    expected_pairs = []
    for i, row in enumerate(rows):
        if (row.get('schema') != 'offline_packet_recompression_sample_v1'
                or row.get('variant') != ('original','packet','packet','original')[i % 4]
                or row.get('sequence') != i+7 or row.get('cycle') != i//4
                or row.get('abba_position') != i % 4
                or row.get('geometry_age_basis') != 'synthetic_zero_age_OFFLINE_NOT_live_freshness'
                or row.get('source_freshness_verified') is not False
                or list(row['measurement'].get('target_roi_native_xyxy', ())) != PROTOCOL_ROI[protocol]
                or any(row.get(k) is not False or row['measurement'].get(k) is not False for k in probe.FLAGS)
                or row.get('detector_signature') != probe.detector_signature(row['raw_detector_boxes'])):
            raise ValueError('sample order/identity/authority/signature mismatch')
        if i % 4 == 3:
            a,b,c,d = rows[i-3:i+1]
            expected_pairs.extend((probe.compare_pair(a,b), probe.compare_pair(d,c)))
    if not equivalent(pairs, expected_pairs):
        raise ValueError('submitted pairs do not reproduce')
    values = probe.summarize(rows, pairs)
    if any(not equivalent(summary.get(key), value) for key, value in values.items()):
        raise ValueError('submitted aggregate does not reproduce')
    return values


def run(archive_path, source_image, intake, output, *, protocol='r01'):
    intake, output = Path(intake).resolve(), Path(output).resolve()
    source_image, archive_path = Path(source_image).absolute(), Path(archive_path).absolute()
    if (intake.exists() or output.exists() or intake == output or intake in output.parents or output in intake.parents
            or any(d == p.resolve() or d in p.resolve().parents for d in (intake, output) for p in (archive_path, source_image))):
        raise ValueError('separate unused intake/results outside inputs required')
    data, files, summary, rows, pairs = read_archive(archive_path, protocol=protocol)
    values = checked_rows(summary, rows, pairs, protocol=protocol)
    code = summary['source_code_sha256']
    expected_names = {'src/'+name for name in probe.CODE} | {str((HERE/'run.py').relative_to(ROOT))}
    if set(code) != expected_names or any(probe.digest(ROOT/name) != sha for name, sha in code.items()):
        raise ValueError('GPU probe/source version differs from current audited calculation')
    job = probe.load_images([source_image])[0]
    settings, camera, _, _ = probe.load_config()
    profile, profile_sha = probe.load_motion_profile(probe.PROFILE, settings)
    pin = summary['original_pngs']
    if (len(pin) != 1 or pin[0]['png_sha256'] != job['png_sha256'] or pin[0]['pixel_sha256'] != job['pixel_sha256']
            or summary['config_sha256'] != probe.digest(probe.DEFAULT_CONFIG) or summary['profile_sha256'] != profile_sha
            or set(summary['input_sha256'].values()) != {job['png_sha256'], settings['weights_sha256'],
                                                       profile_sha, probe.digest(probe.DEFAULT_CONFIG)}):
        raise ValueError('original/config/profile/weights evidence mismatch')
    recalculated, detector_centres = [], []
    posthoc_roi = [200, 0, 280, 720]  # Post-hoc for r01; already the measured scope for r02.
    for row in rows:
        image = job['image']
        if row['variant'] == 'packet':
            image, codec = probe.packet_roundtrip(image, row['sequence'])
            if any(codec[k] != row[k] for k in ('packet_bytes','packet_sha256','packet_candidate')):
                raise ValueError('GPU packet bytes/identity cannot be reproduced')
        if (probe.sha_bytes(image.tobytes()) != row['inference_pixel_sha256']
                or row['source_png_sha256'] != job['png_sha256'] or row['source_pixel_sha256'] != job['pixel_sha256']):
            raise ValueError('actual GPU inference pixels cannot be reproduced')
        frame = probe.NativeFrame('c'*32, row['sequence'], row['measurement']['media_time_sec'], float(row['sequence']), image)
        def calculate(roi):
            engine = probe.MotionRangeEngine(settings, camera, profile, profile_sha, acknowledged=True,
                target_roi=roi, observer=probe.observe_upper_completion)
            return engine.measure(frame, row['raw_detector_boxes'], float(row['sequence']))
        baseline = calculate(summary['target_roi_native_xyxy'])
        if not equivalent(row['measurement'], baseline):
            raise ValueError('original GPU logged geometry does not reproduce')
        proposal = calculate(posthoc_roi) if protocol == 'r01' else baseline
        recalculated.append(dict(row, measurement=proposal))
        detector_centres.append(dict(sequence=row['sequence'], variant=row['variant'],
            raw_box_centres_xy=[[(b['x1']+b['x2'])/2, (b['y1']+b['y2'])/2] for b in row['raw_detector_boxes']],
            logged_front_candidates=baseline['front_candidates'], posthoc_front_candidates=proposal['front_candidates']))
    posthoc_pairs = []
    for i in range(0, len(recalculated), 4):
        a,b,c,d = recalculated[i:i+4]
        posthoc_pairs.extend((probe.compare_pair(a,b), probe.compare_pair(d,c)))
    probe.assert_originals([job])
    intake.mkdir(parents=True, exist_ok=False)
    with (intake/archive_path.name).open('xb') as target:
        target.write(data)
    for name, content in files.items():
        with (intake/name).open('xb') as target:
            target.write(content)
    output.mkdir(parents=True, exist_ok=False)
    geometry_file = 'posthoc_geometry.jsonl' if protocol == 'r01' else 'reproduced_geometry.jsonl'
    pair_file = 'posthoc_pairs.csv' if protocol == 'r01' else 'verified_pairs.csv'
    with (output/geometry_file).open('xb') as target:
        for row in recalculated:
            target.write(probe.json_bytes(dict(sequence=row['sequence'], variant=row['variant'],
                GPU_inference_pixel_sha256=row['inference_pixel_sha256'],
                result_kind=('posthoc_ROI_recalculation_NOT_original_GPU_measurement' if protocol == 'r01'
                             else 'same_ROI_reproduction_of_submitted_GPU_geometry'),
                corrected_target_roi=posthoc_roi, measurement=row['measurement'],
                new_GPU_inference_performed=False, corrected_GPU_support_service_time_measured=False)))
    with (output/pair_file).open('x') as target:
        writer = csv.DictWriter(target, fieldnames=list(posthoc_pairs[0]))
        writer.writeheader()
        writer.writerows(posthoc_pairs)
    with (output/'timing.csv').open('x') as target:
        keys = ['variant','sequence','encode_ms','decode_validate_copy_ms','predict_sync_ms','support_geometry_ms','receiver_stage_ms']
        writer = csv.DictWriter(target, fieldnames=keys)
        writer.writeheader()
        writer.writerows({k:r[k] for k in keys} for r in rows)
    audit = dict(schema='packet_GPU_recompression_submission_audit_v1', state='pass',
        archive_sha256=probe.sha_bytes(data), archive_path=str(archive_path), raw_intake=str(intake),
        submission_protocol=protocol,
        source_code_sha256=code, audit_script_sha256=probe.digest(__file__),
        original_summary_and_all_pairs_reproduced=True, original_ROI_reproduced=True,
        actual_GPU_inference_pixels_reproduced=True, packet_wire_hashes_reproduced=True,
        image_count=1, measured_samples=20, paired_samples=10, actual_CUDA_report=summary['gpu'],
        original_target_roi=summary['target_roi_native_xyxy'], original_groups=values['groups'],
        original_pair_counts=values['pair_counts'], original_numeric_distance_pairs=values['pair_counts']['both_numeric'],
        detector_centres=detector_centres,
        verified_absolute_range_delta_m=values['absolute_range_delta_m'],
        verified_representative={v: next(r['measurement'] for r in rows if r['variant']==v) for v in ('original','packet')},
        posthoc_ROI_change_performed=protocol == 'r01',
        additional_inference_or_image_capture_performed=False, images_modified_or_written=False,
        live_rate_or_deadline_verified=False, source_freshness_verified=False, **probe.FLAGS)
    if protocol == 'r01':
        audit.update(posthoc_target_roi=posthoc_roi, posthoc_pairs=posthoc_pairs,
            posthoc_absolute_range_delta_m=probe.describe([p['absolute_range_delta_m'] for p in posthoc_pairs if p['both_numeric']]),
            posthoc_representative={v: next(r['measurement'] for r in recalculated if r['variant']==v) for v in ('original','packet')},
            posthoc_geometry_only_NOT_GPU_full_pipeline_timing=True)
    with (output/'audit.json').open('xb') as target:
        target.write(probe.json_bytes(audit))
    print(json.dumps({k:audit[k] for k in ('state','submission_protocol','measured_samples',
        'original_numeric_distance_pairs','original_target_roi','verified_absolute_range_delta_m')}, indent=2))
    return audit


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--source-image', type=Path, required=True)
    parser.add_argument('--intake-dir', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--protocol', choices=tuple(PROTOCOL_ROI), default='r01')
    args = parser.parse_args()
    run(args.archive, args.source_image, args.intake_dir, args.output_dir, protocol=args.protocol)
