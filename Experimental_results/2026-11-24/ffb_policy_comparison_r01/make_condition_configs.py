"""Generate the M/A/B bird_eye configs from the day's FFB-enabled config.

The base config must be the one that actually reaches the G923 (publish
enabled, and either the relay intent path or the direct command path). This
tool refuses a display-only/minimal config so a comparison cannot silently
produce no force.
"""
import argparse
import json
from pathlib import Path

CONDITIONS = ('M', 'A', 'B')
DIRECTION = {'M': 0, 'A': 1, 'B': 1}
POLICY = {'M': None, 'A': 'gradient_direction', 'B': 'side_direction'}


def checked_base(params):
    problems = []
    if type(params) is not dict:
        return ['JSON object required']
    if params.get('collision_ffb_publish_enabled') != 1:
        problems.append('collision_ffb_publish_enabled must be 1 (otherwise no force reaches the wheel)')
    relay = params.get('collision_ffb_relay_enabled', 0)
    if relay not in (0, 1):
        problems.append('collision_ffb_relay_enabled must be 0 or 1')
    elif relay == 1:
        topic = params.get('collision_ffb_intent_topic')
        if not isinstance(topic, str) or not topic.startswith('/'):
            problems.append('relay enabled but collision_ffb_intent_topic is missing')
    else:
        topic = params.get('collision_ffb_command_topic')
        if not isinstance(topic, str) or not topic.startswith('/'):
            problems.append('direct path needs collision_ffb_command_topic')
    if params.get('collision_ffb_direction_enabled') not in (0, 1, None):
        problems.append('collision_ffb_direction_enabled must be 0 or 1')
    return problems


def condition_config(base, condition):
    if condition not in CONDITIONS:
        raise ValueError('unknown condition: ' + str(condition))
    value = dict(base)
    value['collision_ffb_direction_enabled'] = DIRECTION[condition]
    if POLICY[condition] is not None:
        value['collision_ffb_mapping_policy'] = POLICY[condition]
    if condition == 'B':
        value['collision_ffb_side_deadband_m'] = 0.05
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', type=Path, required=True,
                        help='the day\'s FFB-enabled bird_eye config')
    parser.add_argument('--output-dir', type=Path, required=True,
                        help='NEW directory for bird_eye_config_M/A/B.json')
    args = parser.parse_args()
    output = args.output_dir.resolve()
    if output.exists():
        raise SystemExit('unused output directory required')
    base = json.loads(args.base.read_bytes())
    problems = checked_base(base)
    if problems:
        raise SystemExit('base config rejected: ' + '; '.join(problems))
    output.mkdir(parents=True, exist_ok=False)
    for condition in CONDITIONS:
        (output / f'bird_eye_config_{condition}.json').write_text(
            json.dumps(condition_config(base, condition), indent=2) + '\n')
    relay = base.get('collision_ffb_relay_enabled', 0)
    print(json.dumps(dict(base=str(args.base.resolve()), output=str(output),
                          relay_enabled=relay,
                          publish_topic=(base.get('collision_ffb_intent_topic') if relay
                                         else base.get('collision_ffb_command_topic')),
                          conditions=list(CONDITIONS),
                          publish_enabled=base['collision_ffb_publish_enabled']), indent=2))


if __name__ == '__main__':
    main()
