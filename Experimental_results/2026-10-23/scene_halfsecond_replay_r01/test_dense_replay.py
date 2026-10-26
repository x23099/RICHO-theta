"""Nested sampling, privacy boundaries and causal completion replay invariants."""
from collections import Counter
import copy
import json
from pathlib import Path
import unittest

import numpy as np

import dense_common as d
from replay_dense import private_samples, private_observations, paper_pose_only, audit_initializations
from angular_fisheye_geometry import camera_from_candidate


class GridTests(unittest.TestCase):
    def test_nested_time_grid(self):
        rows = [dict(frame=i + 1, time_sec=.03 + i / 30) for i in range(301)]
        dense, _ = d.time_grid(rows, .5)
        sparse, _ = d.time_grid(rows, 1.)
        self.assertEqual([r['frame'] for r in dense[::2]], [r['frame'] for r in sparse])

    def test_grid_uses_first_at_or_after_target(self):
        rows = [dict(frame=i + 1, time_sec=t) for i, t in enumerate([.03, .49, .54, 1.04, 1.56])]
        selected, _ = d.time_grid(rows, .5)
        self.assertEqual([r['frame'] for r in selected], [1, 3, 4, 5])
        self.assertTrue(all(r['time_sec'] >= r['target_time_sec'] for r in selected))

    def test_duplicate_target_frames_are_not_duplicate_evidence(self):
        selected, duplicates = d.time_grid([dict(frame=1, time_sec=0.), dict(frame=2, time_sec=2.)], .5)
        self.assertEqual([r['frame'] for r in selected], [1, 2])
        self.assertEqual(duplicates, 3)

    def test_bad_clock_rejected(self):
        with self.assertRaises(ValueError):
            d.time_grid([dict(frame=1, time_sec=1.), dict(frame=2, time_sec=.5)], .5)

    def test_bad_frame_sequence_rejected(self):
        with self.assertRaises(ValueError):
            d.time_grid([dict(frame=2, time_sec=0.)], .5)

    def test_nonpositive_interval_rejected(self):
        with self.assertRaises(ValueError):
            d.time_grid([dict(frame=1, time_sec=0.)], 0.)


class PrivateBoundaryTests(unittest.TestCase):
    def test_samples_strip_role_distance_and_identity(self):
        row = dict(frame='1', time_sec='.03', accepted='True', up_optical_json='[0,0,1]',
                   reference_z_m='999', condition='fabricated', role='heldout', session='foreign')
        result = private_samples([row])[0]
        self.assertEqual(set(result), {'frame', 'time_sec', 'accepted', 'up_optical_json'})

    def test_observations_strip_ground_truth(self):
        row = dict(frame='1', time_sec='.03', native_colour_pair_json='', reference_z_m='999',
                   condition='fabricated', session='foreign')
        self.assertEqual(set(private_observations([row])[0]), {'frame', 'time_sec', 'native_colour_pair_json'})

    def test_missing_current_observation_not_filled(self):
        with self.assertRaises(KeyError):
            private_observations([dict(frame='1', time_sec='0')])

    def test_no_mutation_of_supplied_samples(self):
        rows = [dict(frame='1', time_sec='0', accepted='False', up_optical_json='')]
        original = copy.deepcopy(rows)
        private_samples(rows)
        self.assertEqual(rows, original)

    def test_initialization_needs_four_accepted_images(self):
        samples = [dict(frame=str(i), time_sec=str(float(i)), accepted='True', up_optical_json='[0,0,1]') for i in range(1, 5)]
        jobs, events = paper_pose_only(samples[:3], samples[:3], {i: 0. for i in range(1, 4)})
        self.assertFalse(any(e['initialization_event'] for e in events))
        jobs, events = paper_pose_only(samples, samples, {i: 0. for i in range(1, 5)})
        audit, _ = audit_initializations(samples, jobs, events)
        self.assertEqual(len(audit), 1)
        self.assertEqual(audit[0]['four_evidence_span_sec'], 3.)
        self.assertFalse(audit[0]['physically_independent_observations_verified'])

    def test_audit_excludes_completion_after_recording_ends(self):
        samples = [dict(frame=str(i), time_sec=str(float(i)), accepted='True', up_optical_json='[0,0,1]') for i in range(1, 5)]
        jobs, events = paper_pose_only(samples, samples, {i: .15 for i in range(1, 5)})
        self.assertEqual([e['scene_frame'] for e in events], [1, 2, 3])
        audit, _ = audit_initializations(samples, jobs, events)
        self.assertEqual(audit, [])


class SavedDenseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.intake = json.loads((d.HERE / 'intake_r01/summary.json').read_text())
        cls.scene = json.loads((d.HERE / 'scene_results_r01/summary.json').read_text())
        cls.replay = json.loads((d.HERE / 'replay_r01/summary.json').read_text())
        cls.features = d.read_csv(d.HERE / 'scene_results_r01/image_diagnostics.csv')
        cls.rows = d.read_csv(d.HERE / 'replay_r01/frame_metrics.csv')
        cls.sessions = d.read_csv(d.HERE / 'replay_r01/session_summary.csv')

    def test_all_978_images_and_nine_recordings(self):
        self.assertEqual(len(self.features), 978)
        self.assertEqual(len({r['session'] for r in self.features}), 9)
        self.assertEqual(self.intake['reused_1s_images'], 492)
        self.assertEqual(self.intake['additional_images'], 486)

    def test_original_492_still_match(self):
        selected = [r for r in self.features if r['sparse_1s_member'] == 'True']
        self.assertEqual(len(selected), 492)
        self.assertTrue(all(r['common_1s_result_matches'] == 'True' for r in selected))
        self.assertEqual(sum(r['accepted'] == 'True' for r in selected), 27)

    def test_three_passes_per_image(self):
        rows = d.read_csv(d.HERE / 'scene_results_r01/scene_stage_measurements.csv')
        counts = Counter((r['session'], r['frame']) for r in rows)
        self.assertEqual(len(counts), 978)
        self.assertEqual(set(counts.values()), {3})
        self.assertTrue(all(float(r['scene_service_ms']) > 0 for r in rows))
        self.assertTrue(self.scene['all_pass_results_exact'])

    def test_all_original_pixels_unchanged(self):
        for r in d.read_csv(d.HERE / 'intake_r01/native_sample_manifest.csv'):
            self.assertEqual(d.sha256(Path(r['source_native_png'])), r['png_sha256'])
            self.assertEqual((r['width'], r['height'], r['image_edited']), ('1280', '720', 'False'))

    def test_saved_sources_and_outputs_frozen(self):
        for name in ('intake_r01', 'scene_results_r01', 'replay_r01'):
            d.check_manifest(d.HERE / name / 'summary.json')

    def test_all_four_scenarios_keep_all_sessions(self):
        self.assertEqual(len(self.sessions), 36)
        self.assertEqual(len({r['session'] for r in self.sessions}), 9)
        self.assertEqual(set(Counter(r['scenario'] for r in self.sessions).values()), {9})

    def test_paper_recording_has_no_fabricated_cone(self):
        paper = 'itiawase2_20261015_183552_599'
        self.assertEqual({r['cone_query_frames'] for r in self.sessions if r['session'] == paper}, {'0'})
        self.assertFalse(any(r['session'] == paper for r in self.rows))

    def test_no_frame_omissions_in_cone_scenarios(self):
        self.assertEqual(len(self.rows), 4 * 6876)
        scenarios = {r['scenario'] for r in self.rows}
        populations = [{(r['session'], r['frame']) for r in self.rows if r['scenario'] == s} for s in scenarios]
        self.assertTrue(all(p == populations[0] for p in populations))

    def test_zero_cost_reference_unchanged(self):
        selected = [r for r in self.rows if r['scenario'] == 'sparse_1s__zero_service']
        self.assertEqual(sum(r['diagnostic_available'] == 'True' for r in selected), 377)
        self.assertEqual(self.replay['reference_1s_zero_mismatches'], 0)

    def test_pending_inputs_block_outputs(self):
        self.assertTrue(all(r['diagnostic_available'] == 'False'
                            for r in self.rows if r['newer_scene_input_pending'] == 'True'))

    def test_withheld_values_are_blank(self):
        self.assertTrue(all(r['diagnostic_z_m'] == '' for r in self.rows if r['diagnostic_available'] == 'False'))

    def test_no_stale_or_future_source_for_output(self):
        for r in self.rows:
            if r['diagnostic_available'] == 'True':
                self.assertTrue(0 <= float(r['source_age_sec']) <= 1.)
                self.assertLessEqual(int(r['latest_completed_scene_frame']), int(r['frame']))
                self.assertTrue(float(r['diagnostic_z_m']) > 0)

    def test_physical_and_ffb_not_promoted(self):
        self.assertTrue(all(r['physical_metric_verified'] == 'False' and r['usable_for_ffb'] == 'False' for r in self.rows))
        self.assertFalse(self.replay['production_changed'])
        self.assertFalse(self.replay['current_cone_compute_cost_included'])

    def test_initialization_evidence_is_not_called_independent(self):
        rows = d.read_csv(d.HERE / 'replay_r01/initialization_evidence.csv')
        self.assertTrue(rows)
        self.assertTrue(all(r['physically_independent_observations_verified'] == 'False' for r in rows))
        for r in rows:
            times = json.loads(r['four_source_times_json'])
            self.assertEqual(len(times), 4)
            self.assertAlmostEqual(float(r['four_evidence_span_sec']), times[-1] - times[0])

    def test_real_prefix_and_unused_future_poison(self):
        session = 'floor_cone_same_pose_r01_20261015_160621_378'
        samples = [r for r in self.features if r['session'] == session]
        obpath = d.ROOT / 'Experimental_results/2026-10-21/cone_known_height_pinhole_r01/results_r01/observed_pixels.csv'
        obs = [r for r in d.read_csv(obpath) if r['session'] == session]
        quality = {int(r['frame']): r for r in d.read_csv(d.UNIFORM / 'quality_results_r01/all_frame_quality.csv') if r['session'] == session}
        camera = camera_from_candidate(json.loads(d.CAMERA.read_text()))
        T = np.array(json.loads(d.FLOOR.read_text())['transform_target_from_source'])
        service = {int(r['frame']): .15 for r in samples}
        clean = private_samples(samples)
        prefix_obs = private_observations([r for r in obs if int(r['frame']) <= 720])
        clean_rows, jobs, _ = d.replay(clean, prefix_obs, quality, service, camera, T)
        clean_rows = d.apply_pending(clean_rows, jobs)
        poison = copy.deepcopy(clean)
        for r in poison:
            if int(r['frame']) > 720:
                r.update(accepted='True', up_optical_json='unused_invalid_future_value')
        poisoned_rows, jobs2, _ = d.replay(poison, prefix_obs, quality, service, camera, T)
        self.assertEqual(d.canonical(clean_rows), d.canonical(d.apply_pending(poisoned_rows, jobs2)))
        short = [r for r in clean if int(r['frame']) <= 720]
        short_rows, jobs3, _ = d.replay(short, prefix_obs, quality, service, camera, T)
        self.assertEqual(d.canonical(clean_rows), d.canonical(d.apply_pending(short_rows, jobs3)))


if __name__ == '__main__':
    unittest.main()
