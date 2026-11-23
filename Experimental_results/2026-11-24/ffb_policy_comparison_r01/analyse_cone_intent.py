"""Analyse one cone FFB intent dry-run JSONL (policy B).

Reports cadence, side episodes, confirmation latency, raw-side and emitted
direction flips, magnitude distribution and the no-authority flags. Offline
only; it never publishes or drives the wheel.

Episode definition: a run of active risk levels whose `left_m` is beyond the
same side deadband used by the mapping. A zero, inactive level or a side
change ends the episode. Latency is from the first record of the episode to
the first confirmed record of that episode.
"""
import argparse
import json
import math
from pathlib import Path
import statistics

SCHEMA = 'cone_ffb_intent_live_v1'
OUT_SCHEMA = 'cone_intent_live_analysis_v1'
ACTIVE = {'WARNING', 'CRITICAL', 'UNKNOWN'}
SIDE_DEADBAND_M = 0.05
MAX_GAP_SEC = 0.5
FLAGS = ('dry_run', 'published_to_ros', 'control_authority')


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def read_records(path):
    """Whole lines only; a truncated final line is counted, not fatal."""
    records, truncated = [], 0
    lines = Path(path).read_text().splitlines()
    for index, line in enumerate(lines):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except ValueError:
            if index == len(lines) - 1:
                truncated = 1
                break
            raise ValueError(f'malformed intent record at line {index + 1}')
        if type(record) is not dict or record.get('schema') != SCHEMA:
            raise ValueError(f'unexpected intent record at line {index + 1}')
        records.append(record)
    return records, truncated


def raw_side(record):
    left = record.get('left_m')
    if not finite(left) or record.get('risk_level') not in ACTIVE or abs(left) <= SIDE_DEADBAND_M:
        return 0
    return -1 if left > 0 else 1


def episodes(records):
    found, current, previous_time = [], None, None
    for record in records:
        at_sec = record.get('recorded_at_sec')
        if finite(at_sec) and previous_time is not None:
            if at_sec < previous_time or at_sec - previous_time > MAX_GAP_SEC:
                if current is not None:
                    found.append(current)
                    current = None
        elif not finite(at_sec) and current is not None:
            found.append(current)
            current = None
        if finite(at_sec):
            previous_time = at_sec
        side = raw_side(record)
        if side == 0:
            if current is not None:
                found.append(current)
                current = None
            continue
        if current is None or current['side'] != side:
            if current is not None:
                found.append(current)
            current = dict(side=side, start_sec=at_sec,
                           confirmed_at_sec=None, confirmed_direction=None,
                           risk_level=record.get('risk_level'))
        if (current['confirmed_at_sec'] is None and record.get('confirmed') is True
                and record.get('direction') == side and finite(at_sec)):
            current['confirmed_at_sec'] = at_sec
            current['confirmed_direction'] = side
    if current is not None:
        found.append(current)
    return found


def flips(records, field):
    changes, previous = 0, 0
    for record in records:
        value = record.get(field)
        if type(value) is not int or value == 0:
            continue
        if previous and value != previous:
            changes += 1
        previous = value
    return changes


def raw_side_flips(records):
    changes, previous = 0, 0
    for record in records:
        side = raw_side(record)
        if side and previous and side != previous:
            changes += 1
        if side:
            previous = side
    return changes


def cadence(records):
    times = sorted(record['recorded_at_sec'] for record in records
                   if finite(record.get('recorded_at_sec')))
    deltas = [b - a for a, b in zip(times, times[1:])]
    if not deltas:
        return dict(count=0, median_sec=None, p90_sec=None, max_sec=None)
    ordered = sorted(deltas)
    return dict(count=len(ordered),
                median_sec=round(statistics.median(ordered), 4),
                p90_sec=round(ordered[min(len(ordered) - 1, int(len(ordered) * .9))], 4),
                max_sec=round(ordered[-1], 4))


def analyse(records, truncated=0):
    sides = episodes(records)
    latencies = [round(item['confirmed_at_sec'] - item['start_sec'], 4)
                 for item in sides
                 if item['confirmed_at_sec'] is not None and finite(item['start_sec'])]
    magnitudes = [record['normalized_magnitude'] for record in records
                  if record.get('confirmed') is True and finite(record.get('normalized_magnitude'))
                  and record['normalized_magnitude'] > 0]
    directions = {'-1': 0, '0': 0, '1': 0}
    levels, reasons, box_counts = {}, {}, {}
    for record in records:
        direction = record.get('direction')
        if direction in (-1, 0, 1):
            directions[str(direction)] += 1
        level = str(record.get('risk_level') or '')
        levels[level] = levels.get(level, 0) + 1
        reason = str(record.get('snapshot_reason') or '')
        reasons[reason] = reasons.get(reason, 0) + 1
        boxes = record.get('box_count')
        box_counts[str(boxes)] = box_counts.get(str(boxes), 0) + 1
    frames = {(record.get('session'), record.get('frame')) for record in records
              if record.get('session') and type(record.get('frame')) is int}
    flags = {name: all(record.get(name) is (False if name != 'dry_run' else True)
                       for record in records) for name in FLAGS}
    return dict(schema=OUT_SCHEMA, records=len(records), truncated_final_lines=truncated,
                distinct_frames=len(frames),
                available_records=sum(1 for record in records
                                      if record.get('snapshot_available') is True),
                confirmed_records=sum(1 for record in records if record.get('confirmed') is True),
                directions=directions, risk_levels=levels,
                snapshot_reasons=reasons, box_counts=box_counts,
                raw_side_flips=raw_side_flips(records),
                emitted_direction_flips=flips(records, 'direction'),
                side_episodes=len(sides),
                confirmed_episodes=len(latencies),
                unconfirmed_episodes=len(sides) - len(latencies),
                latency_sec=dict(count=len(latencies),
                                 min=min(latencies) if latencies else None,
                                 median=round(statistics.median(latencies), 4) if latencies else None,
                                 max=max(latencies) if latencies else None),
                magnitude_confirmed=dict(count=len(magnitudes),
                                         min=round(min(magnitudes), 4) if magnitudes else None,
                                         mean=round(statistics.mean(magnitudes), 4) if magnitudes else None,
                                         max=round(max(magnitudes), 4) if magnitudes else None),
                cadence=cadence(records), flags=flags,
                authority_free=all(flags.values()))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--intent', type=Path, required=True,
                        help='cone_ffb_intent.jsonl from --cone-ffb-intent-dir')
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    output = args.output_dir.resolve()
    if output.exists():
        raise SystemExit('unused output directory required')
    records, truncated = read_records(args.intent)
    report = analyse(records, truncated)
    report['source'] = str(args.intent.resolve())
    output.mkdir(parents=True, exist_ok=False)
    (output / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({key: report[key] for key in (
        'records', 'distinct_frames', 'confirmed_records', 'side_episodes',
        'confirmed_episodes', 'unconfirmed_episodes', 'raw_side_flips',
        'emitted_direction_flips', 'latency_sec', 'cadence', 'authority_free')}, indent=2))
    if not report['authority_free']:
        raise SystemExit('authority flags are not all false; do not use this log')
    if report['records'] == 0:
        raise SystemExit('no intent records')


if __name__ == '__main__':
    main()
