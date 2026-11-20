"""Synthetic VP8-offline-assessment tests; no saved image, GPU or camera."""
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('vp8_assessment_test',
    ROOT / 'Experimental_results/2026-11-20/vp8_packet_assessment_r01/analyse.py')
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


def row(variant, distance, reason='ok', *, image='frame.png', pixel=0.0, psnr=None, size=None):
    return dict(variant=variant, source_path='/x/' + image, usable_for_ffb=False,
                physical_metric_verified=False, psnr_db=psnr, packet_bytes=size,
                mean_absolute_pixel_difference=pixel,
                measurement=dict(horizontal_camera_foot_range_m=distance, reason=reason))


class Vp8AssessmentTests(unittest.TestCase):
    def test_both_numeric_reports_signed_delta(self):
        images = audit.per_image([row('original', 1.2, pixel=0.0),
                                  row('packet', 1.17, pixel=1.7, psnr=39.5, size=98000)])
        self.assertFalse(images[0]['gate_changed'])
        self.assertAlmostEqual(images[0]['range_delta_m'], -0.03)
        summary = audit.aggregate(images)
        self.assertEqual(summary['both_numeric'], 1)
        self.assertEqual(summary['gate_changes'], 0)
        self.assertEqual(summary['median_packet_bytes'], 98000)

    def test_withheld_to_numeric_is_a_gate_change(self):
        images = audit.per_image([row('original', None, 'colour_contour_reaches_roi_edge'),
                                  row('packet', 1.61, 'numeric', pixel=1.7)])
        self.assertTrue(images[0]['gate_changed'])
        summary = audit.aggregate(images)
        self.assertEqual(summary['original_withheld_packet_numeric'], 1)
        self.assertEqual(summary['gate_changes'], 1)
        self.assertIsNone(summary['range_delta_m']['minimum'])

    def test_disagreeing_repeats_are_rejected(self):
        with self.assertRaises(ValueError):
            audit.per_image([row('original', 1.2), row('original', 1.3),
                             row('packet', 1.17, pixel=1.7)])

    def test_authority_claims_are_rejected(self):
        bad = row('original', 1.2)
        bad['usable_for_ffb'] = True
        with self.assertRaises(ValueError):
            audit.per_image([bad, row('packet', 1.17, pixel=1.7)])

    def test_missing_variant_is_rejected(self):
        with self.assertRaises(ValueError):
            audit.per_image([row('original', 1.2)])


if __name__ == '__main__':
    unittest.main()
