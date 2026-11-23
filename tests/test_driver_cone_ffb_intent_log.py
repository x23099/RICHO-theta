"""Dry-run cone FFB intent log tests; no ROS, G923 or camera."""
import argparse
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from driver_cone_ffb_intent_log import (ConeFfbIntentRecorder, add_cone_intent_arguments,
                                        load_calibration, recorder_from_args)

SESSION = 'a' * 32
CAL = dict(schema='lateral_calibration_table_v1', distances=[1.0, 1.5, 2.0],
           cx_ref=[306.5, 308.2, 305.7],
           k_left_m_per_px=[0.004158, 0.005945, 0.007732],
           k_right_m_per_px=[0.003924, 0.005341, 0.006758])


def box(center_x, width=10.0):
    return dict(x1=center_x - width / 2, y1=300.0, x2=center_x + width / 2, y2=440.0,
                confidence=0.9, class_id=0)


def snapshot(frame, center_x=264.6, range_m=1.5, *, available=True, reason='synthetic',
             boxes=None, source=1.0, session=SESSION):
    selected = [box(center_x)] if boxes is None else boxes
    result = dict(session=session, frame=frame, source_time_sec=source,
                  distance_available=range_m is not None,
                  horizontal_camera_foot_range_m=range_m, reason=reason,
                  selected_detector_boxes=selected)
    return dict(available=available, reason=reason, result=result)


class RecorderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / 'recordings',
                                                prefix='cone_intent_test_')
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name) / 'intent'

    def recorder(self, **kwargs):
        unit = ConeFfbIntentRecorder(self.directory, CAL, **kwargs)
        unit.start()
        self.addCleanup(unit.request_stop)
        return unit

    def feed(self, unit, frame, center_x=264.6, source=None, **changes):
        return unit.observe(snapshot(frame, center_x,
                                     source=frame * 0.1 if source is None else source, **changes),
                            0.5, 0.0, now=frame * 0.1)

    def test_repeated_ui_refreshes_do_not_confirm_the_gate(self):
        unit = self.recorder()
        first = self.feed(unit, 1)
        self.assertFalse(first['confirmed'])
        self.assertIsNone(self.feed(unit, 1))
        self.assertIsNone(self.feed(unit, 1))
        self.assertEqual(unit.offered, 1)

    def test_three_distinct_left_results_confirm_left_with_magnitude(self):
        unit = self.recorder()
        self.feed(unit, 1)
        self.feed(unit, 2)
        third = self.feed(unit, 3)
        self.assertTrue(third['confirmed'])
        self.assertEqual(third['direction'], -1)
        self.assertGreater(third['normalized_magnitude'], 0.0)
        self.assertEqual(third['box_center_x'], 264.6)
        self.assertEqual(third['range_m'], 1.5)

    def test_right_result_confirms_right(self):
        unit = self.recorder()
        result = None
        for frame in (1, 2, 3):
            result = self.feed(unit, frame, center_x=355.3)
        self.assertTrue(result['confirmed'])
        self.assertEqual(result['direction'], 1)

    def test_unavailable_result_resets_but_transient_busy_is_skipped(self):
        unit = self.recorder()
        self.feed(unit, 1)
        self.feed(unit, 2)
        busy = unit.observe(dict(available=False, reason='motion_tap_busy'), 0.5, 0.0, now=0.3)
        self.assertIsNone(busy)
        third = self.feed(unit, 3)
        self.assertTrue(third['confirmed'])
        stale = unit.observe(dict(available=False, reason='motion_input_stale'), 0.5, 0.0, now=0.4)
        self.assertFalse(stale['confirmed'])
        self.assertEqual(stale['direction'], 0)
        self.assertIsNone(unit.observe(dict(available=False, reason='motion_input_stale'),
                                       0.5, 0.0, now=0.5))

    def test_withheld_range_is_logged_without_direction(self):
        unit = self.recorder()
        self.feed(unit, 1)
        self.feed(unit, 2)
        withheld = self.feed(unit, 3, range_m=None)
        self.assertFalse(withheld['confirmed'])
        self.assertIsNone(withheld['range_m'])
        self.assertEqual(withheld['box_count'], 1)

    def test_multiple_boxes_withhold_the_box_centre(self):
        unit = self.recorder()
        result = self.feed(unit, 1, boxes=[box(250.0), box(360.0)])
        self.assertFalse(result['confirmed'])
        self.assertIsNone(result['box_center_x'])
        self.assertEqual(result['box_count'], 2)

    def test_jsonl_and_summary_are_written_with_no_authority(self):
        unit = self.recorder()
        for frame in (1, 2, 3):
            self.feed(unit, frame)
        unit.request_stop()
        lines = [json.loads(line) for line in
                 (self.directory / 'cone_ffb_intent.jsonl').read_text().splitlines()]
        self.assertEqual(len(lines), 3)
        self.assertTrue(all(row['dry_run'] and not row['published_to_ros']
                            and not row['control_authority'] for row in lines))
        self.assertEqual(lines[-1]['direction'], -1)
        summary = json.loads((self.directory / 'cone_ffb_intent_summary.json').read_text())
        self.assertEqual(summary['records_offered'], 3)
        self.assertEqual(summary['records_written'], 3)
        self.assertEqual(summary['directions']['0'], 2)
        self.assertEqual(summary['directions']['-1'], 1)
        self.assertEqual(summary['confirmed_records'], 1)
        self.assertTrue(summary['dry_run'])
        self.assertFalse(summary['published_to_ros'])
        self.assertIsNone(summary['error'])

    def test_last_text_reports_waiting_then_state(self):
        unit = self.recorder()
        self.assertIn('waiting', unit.last_text())
        for frame in (1, 2, 3):
            self.feed(unit, frame)
        self.assertIn('CONFIRMED', unit.last_text())
        self.assertIn('dir=-1', unit.last_text())


class ArgumentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / 'recordings',
                                                prefix='cone_intent_args_')
        self.addCleanup(self.temp.cleanup)
        self.calibration = Path(self.temp.name) / 'calibration.json'
        self.calibration.write_text(json.dumps(CAL))

    def parse(self, *argv):
        parser = argparse.ArgumentParser()
        add_cone_intent_arguments(parser)
        return parser.parse_args(argv)

    def test_off_by_default_and_requires_existing_calibration_pair(self):
        self.assertIsNone(recorder_from_args(self.parse()))
        with self.assertRaises(ValueError):
            recorder_from_args(self.parse('--cone-ffb-calibration', str(self.calibration)))
        with self.assertRaises(ValueError):
            recorder_from_args(self.parse('--cone-ffb-intent-dir', str(Path(self.temp.name) / 'a')))

    def test_requires_a_new_directory_under_recordings(self):
        existing = Path(self.temp.name) / 'existing'
        existing.mkdir()
        with self.assertRaises(ValueError):
            recorder_from_args(self.parse(
                '--cone-ffb-intent-dir', str(existing),
                '--cone-ffb-calibration', str(self.calibration)))
        with tempfile.TemporaryDirectory() as outside:
            with self.assertRaises(ValueError):
                recorder_from_args(self.parse(
                    '--cone-ffb-intent-dir', str(Path(outside) / 'intent'),
                    '--cone-ffb-calibration', str(self.calibration)))
        unit = recorder_from_args(self.parse(
            '--cone-ffb-intent-dir', str(Path(self.temp.name) / 'intent'),
            '--cone-ffb-calibration', str(self.calibration)))
        self.assertIsInstance(unit, ConeFfbIntentRecorder)
        unit.request_stop()

    def test_load_calibration_rejects_wrong_schema(self):
        bad = Path(self.temp.name) / 'bad.json'
        bad.write_text(json.dumps(dict(CAL, schema='other')))
        with self.assertRaises(ValueError):
            load_calibration(bad)


if __name__ == '__main__':
    unittest.main()
