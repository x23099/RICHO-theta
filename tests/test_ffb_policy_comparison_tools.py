"""Offline checks for the Tuesday policy comparison helpers; no ROS/hardware."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'Experimental_results/2026-11-24/ffb_policy_comparison_r01'
sys.path.insert(0, str(ROOT / 'src'))


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


analysis = load('analyse_cone_intent', BASE / 'analyse_cone_intent.py')
preflight = load('ffb_preflight', BASE / 'preflight.py')
configs = load('make_condition_configs', BASE / 'make_condition_configs.py')

CAL = dict(schema='lateral_calibration_table_v1', distances=[1.0, 1.5, 2.0],
           cx_ref=[306.5, 308.2, 305.7],
           k_left_m_per_px=[0.004158, 0.005945, 0.007732],
           k_right_m_per_px=[0.003924, 0.005341, 0.006758])


def record(frame, left, direction, confirmed, risk='WARNING', magnitude=0.25,
           recorded_at=None, **changes):
    value = dict(schema='cone_ffb_intent_live_v1', dry_run=True, published_to_ros=False,
                 control_authority=False, recorded_at_sec=(frame * 0.1 if recorded_at is None
                                                           else recorded_at),
                 session='a' * 32, frame=frame, snapshot_available=risk in analysis.ACTIVE,
                 snapshot_reason='synthetic', box_count=1, range_m=1.5,
                 box_center_x=264.6, linear_mps=0.5, angular_radps=0.0,
                 left_m=left, forward_m=1.5, gradient=1.0, risk_level=risk,
                 direction=direction, normalized_magnitude=magnitude,
                 confirmed=confirmed, reason='synthetic', consistency_reason='synthetic')
    value.update(changes)
    return value


class AnalysisTests(unittest.TestCase):
    def test_two_side_episodes_latency_flips_and_cadence(self):
        records = [
            record(1, 0.25, 0, False), record(2, 0.25, 0, False),
            record(3, 0.25, -1, True), record(4, 0.25, -1, True),
            record(5, -0.25, 0, False), record(6, -0.25, 0, False),
            record(7, -0.25, 1, True),
        ]
        report = analysis.analyse(records)
        self.assertEqual(report['records'], 7)
        self.assertEqual(report['distinct_frames'], 7)
        self.assertEqual(report['confirmed_records'], 3)
        self.assertEqual(report['side_episodes'], 2)
        self.assertEqual(report['confirmed_episodes'], 2)
        self.assertEqual(report['unconfirmed_episodes'], 0)
        self.assertEqual(report['raw_side_flips'], 1)
        self.assertEqual(report['emitted_direction_flips'], 1)
        self.assertEqual(report['latency_sec']['min'], 0.2)
        self.assertEqual(report['latency_sec']['max'], 0.2)
        self.assertEqual(report['cadence']['median_sec'], 0.1)
        self.assertEqual(report['magnitude_confirmed']['max'], 0.25)
        self.assertTrue(report['authority_free'])

    def test_unconfirmed_episode_and_inactive_gap(self):
        records = [
            record(1, 0.0, 0, False), record(2, 0.0, 0, False),
            record(3, 0.25, 0, False), record(4, 0.25, 0, False),
            record(5, 0.25, 0, False, risk='CLEAR'),
        ]
        report = analysis.analyse(records)
        self.assertEqual(report['side_episodes'], 1)
        self.assertEqual(report['confirmed_episodes'], 0)
        self.assertEqual(report['unconfirmed_episodes'], 1)
        self.assertEqual(report['latency_sec']['count'], 0)
        self.assertIsNone(report['latency_sec']['median'])

    def test_authority_flag_is_not_hidden(self):
        report = analysis.analyse([record(1, 0.25, 0, False, published_to_ros=True)])
        self.assertFalse(report['authority_free'])
        self.assertFalse(report['flags']['published_to_ros'])

    def test_gap_breaks_an_episode_like_the_gate(self):
        records = [
            record(1, 0.25, 0, False), record(2, 0.25, 0, False),
            record(3, 0.25, -1, True),
            record(4, 0.25, 0, False, recorded_at=3.0),
            record(5, 0.25, 0, False, recorded_at=3.1),
            record(6, 0.25, -1, True, recorded_at=3.2),
        ]
        report = analysis.analyse(records)
        self.assertEqual(report['side_episodes'], 2)
        self.assertEqual(report['confirmed_episodes'], 2)
        self.assertEqual(report['latency_sec']['min'], 0.2)
        self.assertEqual(report['latency_sec']['max'], 0.2)

    def test_p90_uses_sorted_deltas(self):
        times = [0.0, 1.0, 1.1, 1.2, 1.3]
        records = [record(index + 1, 0.0, 0, False, recorded_at=time)
                   for index, time in enumerate(times)]
        report = analysis.analyse(records)
        self.assertEqual(report['cadence']['median_sec'], 0.1)
        self.assertEqual(report['cadence']['p90_sec'], 1.0)
        self.assertEqual(report['cadence']['max_sec'], 1.0)

    def test_truncated_final_line_is_counted_but_earlier_garbage_raises(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'intent.jsonl'
            good = json.dumps(record(1, 0.25, 0, False)) + '\n'
            path.write_text(good + '{"schema": "cone_ffb_intent_live_v1"')
            records, truncated = analysis.read_records(path)
            self.assertEqual((len(records), truncated), (1, 1))
            path.write_text('not json\n' + good)
            with self.assertRaises(ValueError):
                analysis.read_records(path)
            path.write_text(json.dumps(dict(record(1, 0.25, 0, False), schema='other')) + '\n')
            with self.assertRaises(ValueError):
                analysis.read_records(path)


class MakeConditionConfigTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / 'recordings',
                                                prefix='ffb_configs_test_')
        self.addCleanup(self.temp.cleanup)

    def base(self, **changes):
        value = dict(collision_ffb_publish_enabled=1,
                     collision_ffb_command_topic='/collision/ffb_command',
                     collision_ffb_direction_enabled=0,
                     collision_ffb_gradient_deadband=0.1)
        value.update(changes)
        return value

    def test_base_must_publish_and_declare_a_topic(self):
        self.assertEqual(configs.checked_base(self.base()), [])
        self.assertTrue(configs.checked_base(self.base(collision_ffb_publish_enabled=0)))
        missing_topic = self.base()
        del missing_topic['collision_ffb_command_topic']
        self.assertTrue(configs.checked_base(missing_topic))
        self.assertTrue(configs.checked_base(self.base(collision_ffb_relay_enabled=1)))
        self.assertEqual(configs.checked_base(self.base(
            collision_ffb_relay_enabled=1, collision_ffb_intent_topic='/collision/ffb_intent')), [])

    def test_condition_overrides_only_the_direction_fields(self):
        base = self.base(collision_ffb_warning_magnitude=0.25)
        m = configs.condition_config(base, 'M')
        a = configs.condition_config(base, 'A')
        b = configs.condition_config(base, 'B')
        self.assertEqual((m['collision_ffb_direction_enabled'],
                          a['collision_ffb_direction_enabled'],
                          b['collision_ffb_direction_enabled']), (0, 1, 1))
        self.assertEqual(a['collision_ffb_mapping_policy'], 'gradient_direction')
        self.assertEqual(b['collision_ffb_mapping_policy'], 'side_direction')
        self.assertEqual(b['collision_ffb_side_deadband_m'], 0.05)
        self.assertEqual(m['collision_ffb_warning_magnitude'], 0.25)

    def test_cli_writes_three_preflight_clean_configs(self):
        base = Path(self.temp.name) / 'base.json'
        base.write_text(json.dumps(self.base()))
        output = Path(self.temp.name) / 'out'
        with mock.patch('sys.argv', ['make_condition_configs.py', '--base', str(base),
                                     '--output-dir', str(output)]):
            configs.main()
        for condition, expect in (('M', 'magnitude_only'), ('A', 'gradient_direction'),
                                  ('B', 'side_direction')):
            report = preflight.config_report(output / f'bird_eye_config_{condition}.json', expect)
            self.assertTrue(report['ok'], (condition, report['warnings']))


class PreflightTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / 'recordings',
                                                prefix='ffb_preflight_test_')
        self.addCleanup(self.temp.cleanup)
        self.calibration = Path(self.temp.name) / 'calibration.json'
        self.calibration.write_text(json.dumps(CAL))
        self.config = Path(self.temp.name) / 'config.json'
        self.config.write_text(json.dumps(dict(
            collision_ffb_publish_enabled=1,
            collision_ffb_command_topic='/collision/ffb_command',
            collision_ffb_direction_enabled=1,
            collision_ffb_mapping_policy='side_direction',
            collision_ffb_side_deadband_m=0.05,
            collision_ffb_gradient_deadband=0.1,
            collision_ffb_gradient_prediction_time_sec=3.5)))

    def test_config_condition_is_checked(self):
        report = preflight.config_report(self.config, 'side_direction')
        self.assertTrue(report['ok'])
        self.assertEqual(report['path_reach_at_0_5_mps_m'], 1.75)
        report = preflight.config_report(self.config, 'gradient_direction')
        self.assertFalse(report['ok'])
        self.assertTrue(any('expected gradient_direction' in item for item in report['warnings']))

    def test_magnitude_only_ignores_the_stored_policy(self):
        magnitude = Path(self.temp.name) / 'magnitude.json'
        magnitude.write_text(json.dumps(dict(
            collision_ffb_publish_enabled=1,
            collision_ffb_command_topic='/collision/ffb_command',
            collision_ffb_direction_enabled=0,
            collision_ffb_mapping_policy='gradient_direction')))
        report = preflight.config_report(magnitude, 'magnitude_only')
        self.assertTrue(report['ok'])
        self.assertEqual(report['warnings'], [])
        wrong = preflight.config_report(magnitude, 'side_direction')
        self.assertFalse(wrong['ok'])

    def test_publish_disabled_is_rejected(self):
        path = Path(self.temp.name) / 'display_only.json'
        path.write_text(json.dumps(dict(
            collision_ffb_publish_enabled=0,
            collision_ffb_command_topic='/collision/ffb_command',
            collision_ffb_direction_enabled=1,
            collision_ffb_mapping_policy='side_direction')))
        report = preflight.config_report(path, 'side_direction')
        self.assertFalse(report['ok'])
        self.assertTrue(any('publish_enabled' in item for item in report['warnings']))
        self.assertEqual(report['publish_enabled'], 0)

    def test_cone_intent_setup_accepts_only_a_new_recordings_directory(self):
        new = Path(self.temp.name) / 'intent'
        report = preflight.cone_intent_report(new, self.calibration)
        self.assertTrue(report['ok'])
        self.assertTrue(report['enabled'])
        existing = Path(self.temp.name) / 'existing'
        existing.mkdir()
        self.assertFalse(preflight.cone_intent_report(existing, self.calibration)['ok'])
        with tempfile.TemporaryDirectory() as outside:
            self.assertFalse(preflight.cone_intent_report(Path(outside) / 'intent',
                                                          self.calibration)['ok'])
        self.assertFalse(preflight.cone_intent_report(new, None)['ok'])
        self.assertFalse(preflight.cone_intent_report(None, self.calibration)['ok'])

    def test_bad_calibration_is_reported(self):
        bad = Path(self.temp.name) / 'bad.json'
        bad.write_text(json.dumps(dict(CAL, schema='other')))
        report = preflight.cone_intent_report(Path(self.temp.name) / 'intent', bad)
        self.assertFalse(report['ok'])
        self.assertTrue(any('calibration rejected' in item for item in report['warnings']))

    def test_calibration_range_is_reported(self):
        short = Path(self.temp.name) / 'short.json'
        short.write_text(json.dumps(dict(CAL, distances=[0.5, 1.0], cx_ref=[1.0, 2.0],
                                         k_left_m_per_px=[0.004, 0.005],
                                         k_right_m_per_px=[0.004, 0.005])))
        report = preflight.cone_intent_report(Path(self.temp.name) / 'intent', short)
        self.assertFalse(report['ok'])
        self.assertTrue(any('1.0-2.0 m' in item for item in report['warnings']))


if __name__ == '__main__':
    unittest.main()
