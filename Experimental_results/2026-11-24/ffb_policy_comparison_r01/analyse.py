"""Summarise the Tuesday G923 policy comparison from ratings and bird_eye logs.

Ratings: the filled record_template.csv. Logs: optional bird_eye recording CSVs
(one per condition), which contain the collision_ffb_* columns.

Offline only. A single non-blinded subject is exploratory, not statistical proof.
"""
import argparse
import csv
import json
from pathlib import Path
import statistics

CONDITIONS = ('M', 'A', 'B')


def number(value):
    if value is None or str(value).strip() == '':
        return None
    try:
        return float(value)
    except ValueError:
        return None


def ratings(path):
    rows = list(csv.DictReader(Path(path).open(newline='')))
    result = {condition: dict(toward=[], away=[], wrong=[], aborts=[], notes=[]) for condition in CONDITIONS}
    for row in rows:
        condition = str(row.get('condition', '')).strip().upper()
        if condition not in result:
            continue
        for key, target in (('toward_1to5', 'toward'), ('away_1to5', 'away'),
                            ('wrong_direction_count', 'wrong'), ('abort_count', 'aborts')):
            value = number(row.get(key))
            if value is not None:
                result[condition][target].append(value)
        if str(row.get('notes', '')).strip():
            result[condition]['notes'].append(str(row['notes']).strip())
    return {condition: dict(
        toward_mean=round(statistics.mean(values['toward']), 3) if values['toward'] else None,
        away_mean=round(statistics.mean(values['away']), 3) if values['away'] else None,
        wrong_direction_total=int(sum(values['wrong'])) if values['wrong'] else 0,
        abort_total=int(sum(values['aborts'])) if values['aborts'] else 0,
        notes=values['notes']) for condition, values in result.items()}


def log_summary(path):
    with Path(path).open(newline='') as stream:
        rows = list(csv.DictReader(stream))
    directions = {'-1': 0, '0': 0, '1': 0}
    magnitudes, levels = [], {}
    for row in rows:
        direction = str(row.get('collision_ffb_direction', '')).strip()
        if direction in directions:
            directions[direction] += 1
        magnitude = number(row.get('collision_ffb_requested_magnitude'))
        if magnitude is not None:
            magnitudes.append(magnitude)
        level = str(row.get('collision_ffb_risk_level', '')).strip().upper()
        if level:
            levels[level] = levels.get(level, 0) + 1
    return dict(rows=len(rows), directions=directions, levels=levels,
                magnitude_mean=round(statistics.mean(magnitudes), 4) if magnitudes else None,
                magnitude_max=round(max(magnitudes), 4) if magnitudes else None)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ratings', type=Path, required=True)
    parser.add_argument('--log', action='append', default=[], metavar='CONDITION=PATH')
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    output = args.output_dir.resolve()
    if output.exists():
        raise SystemExit('unused output directory required')
    report = dict(schema='ffb_policy_comparison_summary_v1',
                  state='exploratory_single_subject_NOT_statistical',
                  ratings=ratings(args.ratings), logs={})
    for item in args.log:
        if '=' not in item:
            raise SystemExit('log must be CONDITION=PATH')
        condition, path = item.split('=', 1)
        condition = condition.strip().upper()
        if condition not in CONDITIONS:
            raise SystemExit('unknown condition: ' + condition)
        if not Path(path).is_file():
            raise SystemExit('missing log: ' + path)
        report['logs'][condition] = log_summary(path)
    output.mkdir(parents=True, exist_ok=False)
    (output / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
