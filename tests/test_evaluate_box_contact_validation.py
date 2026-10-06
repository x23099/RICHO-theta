from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from evaluate_box_contact_validation import (label_rows, occlusion_events, phase_summary,
                                             position_summary, statistic, warning_comparison)


def rows(count=10):
    return [dict(session='s', variant='baseline', frame=str(i + 1), time_sec=i * .1,
                 detected=1, measurement_accepted=1, track_available=1, track_predicted=0,
                 x_m=.2, z_m=.9, relative_vz_mps=0, odom_available=1, odom_linear_mps=.1,
                 risk='CLEAR') for i in range(count)]


def reference(**kwargs):
    return dict(session='s', reference_kind='static', start_frame=1, end_frame=10,
                expected_x_m=.3, expected_z_m=1, expected_distance_m='', reference_source='test', **kwargs)


def intervals():
    return [dict(start_frame=0, end_frame=1, event='0', phase='visible'),
            dict(start_frame=2, end_frame=5, event='1', phase='fully_occluded'),
            dict(start_frame=6, end_frame=7, event='1', phase='reappearing'),
            dict(start_frame=8, end_frame=9, event='0', phase='visible')]


class BoxContactValidationTests(unittest.TestCase):
    def test_zero_based_labels_map_to_one_based_recording_frames(self):
        labelled = label_rows(rows(), intervals())
        self.assertEqual(labelled[1]['phase_label'], 'visible')
        self.assertEqual(labelled[2]['frame'], '3')
        self.assertEqual(labelled[2]['video_index_zero_based'], 2)
        self.assertEqual(labelled[2]['phase_label'], 'fully_occluded')
        self.assertEqual(labelled[6]['phase_label'], 'reappearing')

    def test_label_gaps_and_out_of_video_are_rejected(self):
        with self.assertRaises(ValueError):
            label_rows(rows(), intervals()[1:])
        labels = intervals()
        labels[-1]['end_frame'] = 10
        with self.assertRaises(ValueError):
            label_rows(rows(), labels)

    def test_nonconsecutive_frames_are_not_silently_shifted(self):
        sample = rows()
        sample[2]['frame'] = '4'
        with self.assertRaises(ValueError):
            label_rows(sample, intervals())
        with self.assertRaises(ValueError):
            position_summary(sample, reference())

    def test_position_error_uses_all_detections_not_only_accepted(self):
        sample = rows()
        sample[0].update(x_m=.8, measurement_accepted=0)
        summary = position_summary(sample, reference())
        self.assertEqual(summary['detected'], 10)
        self.assertEqual(summary['accepted'], 9)
        self.assertAlmostEqual(summary['x_mae_m'], .14)
        self.assertAlmostEqual(summary['z_mae_m'], .1)

    def test_missing_detections_are_not_zero_distance_or_zero_error(self):
        sample = rows()
        for r in sample:
            r.update(detected=0, measurement_accepted=0, track_available=0, x_m='', z_m='')
        summary = position_summary(sample, reference())
        self.assertEqual(summary['detected'], 0)
        self.assertIsNone(summary['z_mae_m'])
        self.assertIsNone(summary['estimated_distance_median_m'])

    def test_initial_distance_reference_does_not_become_stopped_z_truth(self):
        ref = reference()
        ref.update(reference_kind='initial_distance_only', expected_x_m='', expected_z_m='', expected_distance_m=1.3)
        summary = position_summary(rows(), ref)
        self.assertIsNone(summary['z_mae_m'])
        self.assertAlmostEqual(summary['distance_mae_m'], 1.3 - (.2 ** 2 + .9 ** 2) ** .5)

    def test_position_interval_missing_frame_or_invalid_bounds_rejected(self):
        with self.assertRaises(ValueError):
            position_summary(rows(9), reference())
        ref = reference()
        ref['start_frame'] = 0
        with self.assertRaises(ValueError):
            position_summary(rows(), ref)

    def test_occlusion_grace_and_recovery_use_real_times(self):
        sample = rows()
        for r in sample[2:6]:
            r['measurement_accepted'] = 0
        sample[5]['track_available'] = 0
        sample[6]['measurement_accepted'] = 0
        sample[7]['measurement_accepted'] = 0
        event = occlusion_events(sample, intervals(), grace_sec=.25)[0]
        self.assertEqual(event['fully_occluded_frames'], 4)
        self.assertEqual(event['fully_occluded_accepted'], 0)
        self.assertAlmostEqual(event['first_loss_delay_sec'], .3)
        self.assertEqual(event['track_after_grace_frames'], 0)
        self.assertEqual(event['first_recovery_recording_frame'], 9)
        self.assertAlmostEqual(event['recovery_delay_sec'], .2)

    def test_missing_reappearance_is_rejected(self):
        with self.assertRaises(ValueError):
            occlusion_events(rows(), intervals()[:2], grace_sec=.25)

    def test_no_recovery_has_missing_delay_not_zero(self):
        sample = rows()
        for r in sample[6:]:
            r.update(measurement_accepted=0, track_available=0)
        event = occlusion_events(sample, intervals(), grace_sec=.25)[0]
        self.assertEqual(event['recovery_observed'], 0)
        self.assertIsNone(event['recovery_delay_sec'])

    def test_empty_phase_and_statistic_do_not_claim_zero_error(self):
        summary = phase_summary([], 's', 'v', 'fully_occluded')
        self.assertIsNone(summary['accepted_rate'])
        self.assertIsNone(statistic([], 'median'))

    def test_warning_disappearance_is_flagged_and_missing_onset_not_zero(self):
        session = 'approach_center_v0p20_r01'
        grouped = {session: {'baseline': rows(), 'seeded_s130_bottom': rows()}}
        template = dict(warning_frames=10, hold_frames=0, critical_frames=0, unknown_frames=0,
                        virtual_active_groups=3, first_warning_sec=1)
        summaries = {(session, 'baseline'): template,
                     (session, 'seeded_s130_bottom'): dict(template, warning_frames=0, first_warning_sec='')}
        result = warning_comparison(grouped, summaries)[1]
        self.assertEqual(result['baseline_warning_lost'], 1)
        self.assertIsNone(result['warning_onset_delta_sec'])


if __name__ == '__main__':
    unittest.main()
