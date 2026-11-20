"""Audit the t0/t1 completion-tolerance runs against the 11/18 baseline.

Reads the submitted archives in place. No GPU, camera, ROS or network.
"""
import argparse
import collections
import hashlib
import io
import json
from pathlib import Path
import tarfile

ROOT = Path(__file__).resolve().parents[3]
BASELINE = ROOT / 'recordings/2026-11-18/packet_recompression_multi_gpu_intake_r01/pairs.jsonl'
ROI = [270, 0, 350, 720]


def require(condition, message):
    if not condition:
        raise ValueError(message)


def archive(path):
    path = Path(path)
    require(path.is_file(), 'submitted archive required: ' + str(path))
    original = path.read_bytes()
    require(len(original) <= 8 * 1024 * 1024, 'bounded archive required')
    members, ignored = {}, 0
    with tarfile.open(fileobj=io.BytesIO(original), mode='r:xz') as bundle:
        for member in bundle:
            if member.isdir():
                continue
            require(member.isfile() and member.size <= 4 * 1024 * 1024, 'regular bounded members required')
            name = member.name.split('/', 1)[-1]
            if name not in ('summary.json', 'pairs.jsonl', 'samples.jsonl'):
                ignored += 1
                continue
            require(name not in members, 'duplicate result member: ' + name)
            members[name] = bundle.extractfile(member).read()
    require(set(members) == {'summary.json', 'pairs.jsonl', 'samples.jsonl'}, 'three result files required')
    summary = json.loads(members['summary.json'])
    pairs = [json.loads(line) for line in members['pairs.jsonl'].decode().splitlines() if line.strip()]
    samples = [json.loads(line) for line in members['samples.jsonl'].decode().splitlines() if line.strip()]
    require(summary.get('state') == 'complete' and summary.get('image_count') == 3
            and summary.get('target_roi_native_xyxy') == ROI, 'complete three-image ROI run required')
    for flag in ('controlling_distance', 'floor_contact_verified', 'physical_metric_verified'):
        require(summary.get(flag) is False, 'summary claims authority: ' + flag)
    return dict(sha256=hashlib.sha256(original).hexdigest(), summary=summary, pairs=pairs,
                samples=samples, ignored_members=ignored)


def decisions(pairs):
    result = collections.defaultdict(collections.Counter)
    for row in pairs:
        require(row['both_numeric'] + row['original_withheld_packet_numeric']
                + row['original_numeric_packet_withheld'] + (not (
                    row['both_numeric'] or row['original_withheld_packet_numeric']
                    or row['original_numeric_packet_withheld'])) == 1, 'one decision class required')
        if row['both_numeric']:
            kind = 'both_numeric'
        elif row['original_withheld_packet_numeric']:
            kind = 'original_withheld_packet_numeric'
        elif row['original_numeric_packet_withheld']:
            kind = 'original_numeric_packet_withheld'
        else:
            kind = 'both_withheld'
        result[row['source_png_sha256']][kind] += 1
    return result


def sample_state(samples):
    result = {}
    for row in samples:
        require(row['controlling_distance'] is False and row['physical_metric_verified'] is False
                and row['usable_for_ffb'] is False, 'sample claims authority')
        key = (row['source_png_sha256'], row['variant'])
        value = dict(distance_m=row['measurement']['horizontal_camera_foot_range_m'],
                     reason=row['measurement']['reason'],
                     completion=(row['measurement'].get('support_observation') or {}).get('completion_reason'))
        require(result.setdefault(key, value) == value, 'repeated samples disagree: ' + str(key))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--t0', type=Path, required=True)
    parser.add_argument('--t1', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    output = args.output_dir.resolve()
    require(not output.exists(), 'unused output directory required')
    t0, t1 = archive(args.t0), archive(args.t1)
    require(t0['summary']['input_sha256'] == t1['summary']['input_sha256'], 'input sets differ')
    require(t0['summary']['config_sha256'] == t1['summary']['config_sha256'], 'configs differ')
    require(t0['summary']['profile_sha256'] == t1['summary']['profile_sha256'], 'profiles differ')
    require(len(t0['pairs']) == len(t1['pairs']) == 30, 'thirty paired samples required')
    base = [json.loads(line) for line in BASELINE.read_text().splitlines() if line.strip()]
    base_decisions = decisions(base)
    require(decisions(t0['pairs']) == base_decisions, 't0 does not reproduce the 11/18 decisions')

    before, after = sample_state(t0['samples']), sample_state(t1['samples'])
    changed = []
    for key, value in after.items():
        if value != before[key]:
            require(key[1] == 'original' and before[key]['distance_m'] is None
                    and value['distance_m'] is not None, 'only original withheld->numeric may change')
            require(value['completion'] == 'experiment_bbox_tolerance_applied',
                    'accepted original must carry the harness marker')
            changed.append(dict(source_png_sha256=key[0], original_distance_m=value['distance_m'],
                                packet_distance_m=after[(key[0], 'packet')]['distance_m'],
                                delta_m=value['distance_m'] - after[(key[0], 'packet')]['distance_m']))
    require(len(changed) == 1, 'exactly one expected image changes under tolerance 1')
    require(all(before[key] == after[key] for key in before if key[0] != changed[0]['source_png_sha256']),
            'other images must not change')

    report = dict(schema='completion_bbox_tolerance_audit_v1',
                  state='paired_tolerance_check_verified_NOT_accuracy_or_ffb',
                  roi_native_xyxy=ROI, paired_samples=len(t0['pairs']),
                  t0_sha256=t0['sha256'], t1_sha256=t1['sha256'],
                  ignored_auxiliary_members=[t0['ignored_members'], t1['ignored_members']],
                  t0_decisions={k: dict(v) for k, v in decisions(t0['pairs']).items()},
                  t1_decisions={k: dict(v) for k, v in decisions(t1['pairs']).items()},
                  t0_reproduces_11_18=True, changed_images=changed,
                  remaining_gate_change_images=[k for k, v in decisions(t1['pairs']).items()
                                                if 'original_withheld_packet_numeric' in v],
                  harness_marker_observed=True, harness_provenance_file_submitted=False,
                  tolerance_value_recorded_in_archive=False, run_name_implies_tolerance_px=1,
                  gpu_or_camera_used_by_audit=False, live_transport_adopted=False,
                  video_fps_measured=False, physical_metric_verified=False,
                  usable_for_ffb=False, published_to_ros=False)
    output.mkdir(parents=True, exist_ok=False)
    with (output / 'audit.json').open('x') as target:
        json.dump(report, target, indent=2, allow_nan=False)
        target.write('\n')
    print(json.dumps({key: report[key] for key in ('state', 't0_reproduces_11_18', 'changed_images',
                                                   'remaining_gate_change_images')}, indent=2))


if __name__ == '__main__':
    main()
