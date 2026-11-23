"""Preflight check for the Tuesday G923 policy comparison.

Reads a bird_eye config JSON and reports the effective FFB direction policy,
the deadbands and the prediction horizon. Optionally validates the cone-intent
dry-run directory and lateral calibration for the same session.

Read-only; no ROS, camera or hardware.
"""
import argparse
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
POLICIES = ('gradient_direction', 'side_direction', 'no_direction')


def number(value):
    return type(value) in (int, float) and math.isfinite(value)


def config_report(path, expect=None):
    params = json.loads(Path(path).read_bytes())
    if type(params) is not dict:
        raise ValueError('JSON object required')
    enabled = params.get('collision_ffb_direction_enabled', 0)
    policy = params.get('collision_ffb_mapping_policy', 'gradient_direction')
    side_deadband = params.get('collision_ffb_side_deadband_m', 0.05)
    gradient_deadband = params.get('collision_ffb_gradient_deadband', 0.1)
    horizon = params.get('collision_ffb_gradient_prediction_time_sec', 3.5)
    publish = params.get('collision_ffb_publish_enabled', 0)
    relay = params.get('collision_ffb_relay_enabled', 0)
    publish_topic = (params.get('collision_ffb_intent_topic') if relay == 1
                     else params.get('collision_ffb_command_topic'))
    speed_floor = 0.5
    reach_m = float(horizon) * speed_floor if number(horizon) else None
    problems = []
    if publish != 1:
        problems.append('collision_ffb_publish_enabled must be 1 (otherwise no force reaches the wheel)')
    if relay not in (0, 1):
        problems.append('collision_ffb_relay_enabled must be 0 or 1')
    elif not isinstance(publish_topic, str) or not publish_topic.startswith('/'):
        problems.append('missing publish topic for the ' + ('relay' if relay == 1 else 'direct') + ' path')
    if enabled not in (0, 1):
        problems.append('collision_ffb_direction_enabled must be 0 or 1')
    if policy not in POLICIES:
        problems.append('unknown policy: ' + str(policy))
    if not number(side_deadband) or not 0 <= side_deadband <= 0.5:
        problems.append('collision_ffb_side_deadband_m out of range')
    if not number(gradient_deadband) or not 0 <= gradient_deadband <= 1:
        problems.append('collision_ffb_gradient_deadband out of range')
    if not number(horizon) or not 0 < horizon <= 15:
        problems.append('collision_ffb_gradient_prediction_time_sec out of range')
    if enabled == 1 and policy == 'no_direction':
        problems.append('direction enabled but policy is no_direction')
    if expect == 'magnitude_only':
        if enabled != 0:
            problems.append('expected magnitude_only: collision_ffb_direction_enabled must be 0')
    elif expect is not None:
        expected_enabled = 1
        if policy != expect or enabled != expected_enabled:
            problems.append(f'expected {expect}: policy={expect}, enabled={expected_enabled}')
    elif enabled == 0 and policy in ('gradient_direction', 'side_direction'):
        problems.append('direction disabled: the policy will not reach the wheel')
    return dict(config=str(path), direction_enabled=enabled, policy=policy,
                publish_enabled=publish, relay_enabled=relay, publish_topic=publish_topic,
                side_deadband_m=side_deadband, gradient_deadband=gradient_deadband,
                prediction_time_sec=horizon,
                path_reach_at_0_5_mps_m=round(reach_m, 3) if reach_m else None,
                warnings=problems, ok=not problems)


def cone_intent_report(directory, calibration):
    problems = []
    report = dict(enabled=directory is not None, directory=None, calibration=None,
                  warnings=problems)
    if directory is None:
        if calibration is not None:
            problems.append('--cone-calibration requires --cone-intent-dir')
        report['ok'] = not problems
        return report
    path = Path(directory).expanduser().resolve()
    report['directory'] = str(path)
    if ROOT/'recordings' not in path.parents:
        problems.append('cone-intent directory must be under this repository recordings/')
    if path.exists():
        problems.append('cone-intent directory must be NEW (it already exists)')
    if calibration is None:
        problems.append('--cone-calibration required with --cone-intent-dir')
    else:
        try:
            sys.path.insert(0, str(ROOT/'src'))
            from driver_cone_ffb_intent_log import load_calibration
            table = load_calibration(calibration)
            report['calibration'] = dict(path=str(Path(calibration).expanduser().resolve()),
                                         distances=table['distances'],
                                         mounting_dependent=True)
            if table['distances'][0] > 1.0 or table['distances'][-1] < 2.0:
                problems.append('calibration does not cover the 1.0-2.0 m comparison range')
        except Exception as error:
            problems.append('calibration rejected: ' + type(error).__name__ + ': ' + str(error)[:160])
    report['ok'] = not problems
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--expect', choices=POLICIES + ('magnitude_only',), default=None)
    parser.add_argument('--cone-intent-dir', type=Path, default=None,
                        help='optional: NEW directory under recordings/ for the dry-run JSONL')
    parser.add_argument('--cone-calibration', type=Path, default=None,
                        help='optional: lateral calibration JSON for --cone-intent-dir')
    args = parser.parse_args()
    try:
        report = config_report(args.config, args.expect)
    except (ValueError, OSError) as error:
        raise SystemExit(str(error))
    report['cone_intent'] = cone_intent_report(args.cone_intent_dir, args.cone_calibration)
    report['ok'] = report['ok'] and report['cone_intent']['ok']
    print(json.dumps(report, indent=2))
    explicit = args.expect is not None or args.cone_intent_dir is not None
    if not report['ok'] and explicit:
        sys.exit(1)


if __name__ == '__main__':
    main()
