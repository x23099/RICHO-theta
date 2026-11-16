"""Describe +/-0.5 s around screen anchors; NOT verified stationary intervals."""
import argparse
from collections import Counter
import csv
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def windows(rows, points):
    result = []
    for point in points:
        matching = [r for r in rows if r['session'] == point['session'] and int(r['frame']) == point['frame']]
        if len(matching) != 1:
            raise ValueError('exact unique anchor required')
        anchor = float(matching[0]['source_time_sec'])
        selected = [r for r in rows if r['session'] == point['session']
                    and abs(float(r['source_time_sec'])-anchor) <= .5]
        if any(r['display_permitted'] not in ('True', 'False') for r in selected):
            raise ValueError('strict CSV display flag required')
        values = [float(r['display_range_m']) for r in selected if r['display_permitted'] == 'True']
        result.append(dict(frame=point['frame'], session=point['session'], half_window_sec=.5,
            rows=len(selected), numeric_rows=len(values), min_m=min(values) if values else None,
            max_m=max(values) if values else None, reasons=dict(Counter(r['display_reason'] for r in selected)),
            stationary_or_measured_interval_verified=False))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--audit', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    audit = json.loads(args.audit.read_bytes())
    timing = ROOT/audit['complete_timing_csv']['path']
    if hashlib.sha256(timing.read_bytes()).hexdigest() != audit['complete_timing_csv']['sha256']:
        raise ValueError('timing table changed')
    result = dict(state='pass', anchor_context=windows(list(csv.DictReader(timing.open())), audit['reported_points']),
        audit_sha256=hashlib.sha256(args.audit.read_bytes()).hexdigest(),
        timing_sha256=audit['complete_timing_csv']['sha256'],
        code_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    with args.output.open('x') as stream:
        json.dump(result, stream, indent=2)
        stream.write('\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
