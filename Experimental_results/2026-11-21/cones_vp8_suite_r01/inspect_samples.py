"""Print per-image colour/reason/distance from a submitted or local samples.jsonl.

Reads an archive (.tar.xz containing samples.jsonl) or the jsonl directly.
No camera, GPU, ROS or network. Useful for a 2-frame colour pre-check.
"""
import argparse
import collections
import io
import json
from pathlib import Path
import tarfile


def load(path):
    path = Path(path)
    if path.suffixes[-2:] == ['.tar', '.xz']:
        with tarfile.open(path, mode='r:xz') as bundle:
            for member in bundle:
                if member.isfile() and member.name.split('/')[-1] == 'samples.jsonl':
                    return [json.loads(line) for line in bundle.extractfile(member).read().decode().splitlines()
                            if line.strip()]
        raise SystemExit('samples.jsonl not found in archive')
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--samples', type=Path, required=True)
    args = parser.parse_args()
    rows = load(args.samples)
    if not rows:
        raise SystemExit('no samples')
    seen = collections.OrderedDict()
    for row in rows:
        key = (row['source_path'].split('/')[-1], row['variant'])
        measurement = row['measurement']
        support = measurement.get('support_observation') or {}
        value = dict(colour=support.get('selected_colour'),
                     reason=measurement.get('reason'),
                     distance_m=measurement.get('horizontal_camera_foot_range_m'),
                     completion=support.get('completion_reason'))
        seen.setdefault(key, value)
        if seen[key] != value:
            raise SystemExit('repeated samples disagree: ' + str(key))
    print(f"{'image':52s} {'variant':8s} {'colour':7s} {'distance':>10s}  reason")
    for (image, variant), value in seen.items():
        distance = '-' if value['distance_m'] is None else f"{value['distance_m']:.4f}"
        print(f"{image:52s} {variant:8s} {str(value['colour']):7s} {distance:>10s}  {value['reason']}"
              + ('' if not value['completion'] else ' / ' + str(value['completion'])))
    colours = collections.Counter(value['colour'] for value in seen.values())
    numeric = collections.Counter((key[1], value['distance_m'] is not None) for key, value in seen.items())
    print('\ncolours:', dict(colours))
    print('numeric:', {(variant, has): count for (variant, has), count in numeric.items()})


if __name__ == '__main__':
    main()
