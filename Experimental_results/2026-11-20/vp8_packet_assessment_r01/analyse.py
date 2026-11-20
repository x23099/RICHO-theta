"""Offline VP8 packet vs original comparison from saved GPU submissions.

No camera, GPU, ROS or network is used. Inputs are the samples.jsonl files that
were submitted from the GPU PC on 2026-11-18; this script only re-aggregates
them and refuses inconsistent rows.
"""
import argparse
import collections
import json
from pathlib import Path

SCHEMA = 'vp8_packet_offline_assessment_v1'
GROUP = ('original', 'packet')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def load(paths):
    rows = []
    for path in paths:
        path = Path(path)
        for line in path.read_text().splitlines():
            if line.strip():
                value = json.loads(line)
                value['_source'] = str(path)
                rows.append(value)
    require(rows, 'saved samples required')
    return rows


def per_image(rows):
    groups = collections.defaultdict(lambda: collections.defaultdict(list))
    for row in rows:
        require(row.get('variant') in GROUP, 'explicit original/packet variant required')
        require(row.get('usable_for_ffb') is False and row.get('physical_metric_verified') is False,
                'sample claims authority')
        key = row['source_path'].split('/')[-1]
        groups[key][row['variant']].append(row)
    images = []
    for name, variants in sorted(groups.items()):
        require(set(variants) == set(GROUP), 'both original and packet groups required: ' + name)
        summary = dict(image=name)
        for variant in GROUP:
            items = variants[variant]
            require(len(items) >= 1, 'empty variant group: ' + name + '/' + variant)
            distances = {item['measurement']['horizontal_camera_foot_range_m'] for item in items}
            reasons = {item['measurement']['reason'] for item in items}
            require(len(distances) == 1 and len(reasons) == 1, 'repeated samples disagree: ' + name)
            distance = distances.pop()
            summary[variant] = dict(
                samples=len(items), distance_m=distance, reason=reasons.pop(),
                median_psnr_db=median([item.get('psnr_db') for item in items]),
                median_pixel_difference=median([item.get('mean_absolute_pixel_difference') for item in items]),
                median_packet_bytes=median([item.get('packet_bytes') for item in items]))
            if variant == 'original':
                require(all(item.get('mean_absolute_pixel_difference') == 0 for item in items),
                        'original group must be the untransformed frame')
        original, packet = summary['original'], summary['packet']
        summary['gate_changed'] = (original['distance_m'] is None) != (packet['distance_m'] is None)
        summary['range_delta_m'] = (None if original['distance_m'] is None or packet['distance_m'] is None
                                    else packet['distance_m'] - original['distance_m'])
        images.append(summary)
    return images


def median(values):
    values = sorted(value for value in values if type(value) in (int, float))
    if not values:
        return None
    middle = len(values) // 2
    return values[middle] if len(values) % 2 else (values[middle - 1] + values[middle]) / 2


def aggregate(images):
    both = [image for image in images if image['original']['distance_m'] is not None
            and image['packet']['distance_m'] is not None]
    flips = [image for image in images if image['gate_changed']]
    return dict(
        schema=SCHEMA, state='offline_saved_samples_NOT_live_NOT_accuracy',
        images=len(images), both_numeric=len(both), gate_changes=len(flips),
        both_withheld=len([i for i in images if i['original']['distance_m'] is None
                           and i['packet']['distance_m'] is None]),
        original_withheld_packet_numeric=len([i for i in images if i['original']['distance_m'] is None
                                              and i['packet']['distance_m'] is not None]),
        original_numeric_packet_withheld=len([i for i in images if i['original']['distance_m'] is not None
                                              and i['packet']['distance_m'] is None]),
        range_delta_m=dict(count=len(both),
                           minimum=min((i['range_delta_m'] for i in both), default=None),
                           maximum=max((i['range_delta_m'] for i in both), default=None)),
        median_packet_bytes=median([i['packet']['median_packet_bytes'] for i in images]),
        median_psnr_db=median([i['packet']['median_psnr_db'] for i in images]),
        camera_or_gpu_used=False, rtp_or_live_path_used=False,
        network_measured=False, fps_measured=False, one_way_delay_measured=False,
        absolute_ground_truth_verified=False, physical_metric_verified=False,
        usable_for_ffb=False, published_to_ros=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--samples', type=Path, nargs='+', required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    output = args.output_dir.resolve()
    require(not output.exists(), 'unused output directory required')
    images = per_image(load(args.samples))
    report = aggregate(images)
    report['images_detail'] = images
    report['sources'] = [dict(file=Path(path).name, lines=len(Path(path).read_text().splitlines()))
                         for path in args.samples]
    output.mkdir(parents=True, exist_ok=False)
    with (output / 'assessment.json').open('x') as target:
        json.dump(report, target, indent=2, allow_nan=False)
        target.write('\n')
    with (output / 'per_image.csv').open('x') as target:
        target.write('image,original_distance_m,packet_distance_m,range_delta_m,gate_changed,'
                     'original_reason,packet_reason,psnr_db,pixel_difference,packet_bytes\n')
        for image in images:
            target.write(','.join(str(value) for value in (
                image['image'], image['original']['distance_m'], image['packet']['distance_m'],
                image['range_delta_m'], image['gate_changed'], image['original']['reason'],
                image['packet']['reason'], image['packet']['median_psnr_db'],
                image['packet']['median_pixel_difference'], image['packet']['median_packet_bytes'])) + '\n')
    print(json.dumps({key: report[key] for key in (
        'images', 'both_numeric', 'gate_changes', 'original_withheld_packet_numeric',
        'range_delta_m', 'median_packet_bytes', 'median_psnr_db')}, indent=2))


if __name__ == '__main__':
    main()
