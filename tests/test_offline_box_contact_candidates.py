from pathlib import Path
import sys
import unittest
import tempfile
import json
from dataclasses import asdict

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from compare_offline_box_contacts import (adjacent_residual, contact_metrics, summary_group,
                                         validate_variants, verify_frozen_candidate)
from evaluate_raw_velocity_confidence_replay import sha256
from ground_contact import estimate_ground_contact
from offline_box_contact_candidates import (BoxCandidateSettings, component_contact, seeded_components,
                                           select_component, supported_bottom_contact)


P = {"camera_height": .58, "blue_ground_contact_max_aspect_ratio": 1.5}


def image():
    return np.zeros((720, 1280, 3), np.uint8)


def choose(frame, settings=None):
    settings = settings or BoxCandidateSettings()
    return select_component(seeded_components(frame, P, settings), frame.shape, P)


class BoxContactCandidateTests(unittest.TestCase):
    def test_variant_selection_rejects_unknown_duplicates_and_empty(self):
        for variants in ([], ['baseline', 'baseline'], ['unknown']):
            with self.assertRaises(ValueError):
                validate_variants(variants)
        self.assertEqual(validate_variants(['baseline', 'seeded_s130_bottom']), ('baseline', 'seeded_s130_bottom'))

    def test_frozen_candidate_checks_settings_and_code(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'provenance.json'
            name = 'offline_box_contact_candidates.py'
            document = {'settings': asdict(BoxCandidateSettings()),
                        'implementation_sha256': {name: sha256(Path(__file__).resolve().parents[1] / 'src' / name)}}
            path.write_text(json.dumps(document))
            self.assertTrue(verify_frozen_candidate(path, BoxCandidateSettings())['settings_match'])
            document['settings']['weak_v_min'] = 20
            path.write_text(json.dumps(document))
            with self.assertRaisesRegex(ValueError, 'thresholds'):
                verify_frozen_candidate(path, BoxCandidateSettings())
            document['settings'] = asdict(BoxCandidateSettings())
            document['implementation_sha256'][name] = 'tampered'
            path.write_text(json.dumps(document))
            with self.assertRaisesRegex(ValueError, 'implementation'):
                verify_frozen_candidate(path, BoxCandidateSettings())
    def test_invalid_settings(self):
        for kwargs in ({"weak_v_min": -1}, {"body_s_min": 256}, {"opening_size": 4}, {"opening_size": 0},
                       {"minimum_seed_pixels": 0}, {"minimum_seed_fraction": float('nan')},
                       {"minimum_seed_fraction": 0}, {"bottom_central_fraction": 2}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                BoxCandidateSettings(**kwargs)

    def test_blank_has_no_components(self):
        self.assertEqual(seeded_components(image(), P, BoxCandidateSettings()), [])
        self.assertIsNone(choose(image()))

    def test_dark_box_alone_without_bright_seed_is_not_detected(self):
        frame = image()
        cv2.rectangle(frame, (380, 430), (420, 500), (20, 0, 0), -1)
        self.assertIsNone(choose(frame))

    def test_bright_seed_recovers_connected_dark_lower_face(self):
        frame = image()
        cv2.rectangle(frame, (380, 430), (420, 500), (20, 0, 0), -1)
        cv2.rectangle(frame, (380, 430), (420, 460), (180, 0, 0), -1)
        component = choose(frame)
        self.assertIsNotNone(component)
        self.assertEqual(cv2.boundingRect(component['contour']), (380, 430, 41, 71))
        self.assertGreater(component['seed_fraction'], .4)
        bottom = component_contact(component, frame.shape, P, BoxCandidateSettings(), bottom=True)
        self.assertEqual(bottom['pixel_y'], 500)

    def test_small_seed_in_large_dark_component_is_rejected(self):
        frame = image()
        cv2.rectangle(frame, (360, 400), (440, 510), (20, 0, 0), -1)
        cv2.rectangle(frame, (380, 430), (390, 440), (180, 0, 0), -1)
        self.assertIsNone(choose(frame))

    def test_opening_separates_thin_background_connection(self):
        frame = image()
        cv2.rectangle(frame, (380, 430), (420, 500), (180, 0, 0), -1)
        cv2.rectangle(frame, (450, 450), (600, 465), (180, 0, 0), -1)
        cv2.line(frame, (420, 450), (450, 450), (180, 0, 0), 1)
        selected = choose(frame)
        self.assertIsNotNone(selected)
        self.assertEqual(cv2.boundingRect(selected['contour']), (380, 430, 41, 71))

    def test_wide_floor_blob_remains_rejected_by_aspect(self):
        frame = image()
        cv2.rectangle(frame, (350, 430), (450, 450), (180, 0, 0), -1)
        self.assertIsNone(choose(frame))

    def test_outside_front_roi_not_selected(self):
        frame = image()
        cv2.rectangle(frame, (800, 430), (840, 500), (180, 0, 0), -1)
        self.assertIsNone(choose(frame))

    def test_weak_threshold_must_not_exceed_strict_threshold(self):
        with self.assertRaises(ValueError):
            seeded_components(image(), dict(P, blue_ground_contact_hsv_v_min=5), BoxCandidateSettings())

    def test_saturated_candidate_rejects_low_saturation_blue_region(self):
        hsv = np.zeros((720, 1280, 3), np.uint8)
        hsv[430:501, 380:421] = (110, 100, 180)
        frame = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)
        settings = BoxCandidateSettings()
        self.assertIsNotNone(choose(frame))
        q = dict(P, blue_ground_contact_hsv_s_min=settings.body_s_min)
        self.assertEqual(seeded_components(frame, q, settings), [])

    def test_nearest_reuses_existing_geometry(self):
        frame = image()
        cv2.rectangle(frame, (380, 430), (420, 500), (180, 0, 0), -1)
        c = choose(frame)
        actual = component_contact(c, frame.shape, P, BoxCandidateSettings())
        expected = estimate_ground_contact(c['contour'], frame.shape, P)
        for key in ('x_m', 'z_m', 'pixel_x', 'pixel_y'):
            self.assertAlmostEqual(actual[key], expected[key], places=12)

    def test_bottom_median_ignores_narrow_lower_protrusion(self):
        mask = np.zeros((101, 61), np.uint8)
        mask[:71] = 255
        mask[:, 29:32] = 255
        c = {'mask': mask, 'origin': (370, 430)}
        contact = supported_bottom_contact(c, (720, 1280, 3), P)
        self.assertEqual(contact['pixel_y'], 500)
        self.assertGreater(contact['contact_samples'], 40)

    def test_bottom_no_downward_rays_has_no_contact(self):
        c = {'mask': np.full((30, 40), 255, np.uint8), 'origin': (380, 100)}
        self.assertIsNone(supported_bottom_contact(c, (720, 1280, 3), P))

    def test_bottom_does_not_fill_missing_columns_or_invent_pixels(self):
        mask = np.zeros((100, 40), np.uint8)
        mask[:60, :15] = 255
        mask[:60, 30:] = 255
        contact = supported_bottom_contact({'mask': mask, 'origin': (380, 430)}, (720, 1280, 3), P)
        self.assertEqual(contact['pixel_y'], 489)
        self.assertLess(contact['contact_samples'], 40)

    def test_bottom_requires_at_least_three_columns(self):
        c = {'mask': np.full((30, 2), 255, np.uint8), 'origin': (380, 430)}
        self.assertIsNone(supported_bottom_contact(c, (720, 1280, 3), P))

    def test_missing_component_returns_no_contact(self):
        self.assertIsNone(component_contact(None, (720, 1280, 3), P, BoxCandidateSettings()))
        self.assertTrue(all(v is None for v in contact_metrics(None).values()))

    def test_non_finite_or_invalid_aspect_limit_rejected(self):
        for limit in (-1, float('nan')):
            with self.assertRaises(ValueError):
                select_component([], (720, 1280, 3), dict(P, blue_ground_contact_max_aspect_ratio=limit))

    def test_adjacent_residual_not_bridged_across_missing(self):
        a = {'detected': 1, 'odom_available': 1, 'odom_linear_mps': .2, 'time_sec': 0, 'raw_contact_z_m': 1}
        b = dict(a, time_sec=.1, raw_contact_z_m=.98)
        self.assertAlmostEqual(adjacent_residual(a, b), 0)
        self.assertIsNone(adjacent_residual(dict(a, detected=0), b))
        self.assertIsNone(adjacent_residual(a, dict(b, odom_available=0)))
        self.assertIsNone(adjacent_residual(None, b))

    def test_summary_empty_data_stays_missing_not_zero_error(self):
        summary = summary_group('s', 'v', 'all', [])
        self.assertEqual(summary['detected'], 0)
        self.assertIsNone(summary['residual_max_m'])
        self.assertIsNone(summary['raw_z_median_m'])


if __name__ == '__main__':
    unittest.main()
