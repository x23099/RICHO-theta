"""Offline experiment regression: real VP8/geometry, synthetic detector, no GPU."""
import copy
import importlib.util
import io
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('packet_gpu_probe', ROOT /
    'Experimental_results/2026-11-18/frame_packet_gpu_recompression_r01/run.py')
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)
BOX = dict(x1=290., y1=300., x2=350., y2=405., confidence=.95, class_id=0)


class PacketRecompressionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        image = np.full((720, 1280, 3), 180, np.uint8)
        cv2.fillPoly(image, [np.array([[320, 310], [298, 399], [342, 399]], np.int32)], (0, 0, 255))
        image.flags.writeable = False
        self.path = self.directory/'fixture.png'
        data = cv2.imencode('.png', image)[1].tobytes()
        self.path.write_bytes(data)
        self.job = dict(image=image, path=str(self.path), png_sha256=probe.sha_bytes(data),
                        pixel_sha256=probe.sha_bytes(image.tobytes()))
        self.settings, self.camera, _, _ = probe.load_config()
        self.profile, self.profile_sha = probe.load_motion_profile(probe.PROFILE, self.settings)

    def engine(self):
        return probe.MotionRangeEngine(self.settings, self.camera, self.profile, self.profile_sha,
            acknowledged=True, target_roi=[270, 0, 350, 720], observer=probe.observe_upper_completion)

    def predictor(self, frame):
        return [dict(BOX, image=f'{frame.session}:{frame.sequence}')]

    def test_original_calls_new_predictor_and_preserves_pixels(self):
        seen = []
        def predict(frame):
            seen.append(frame)
            return self.predictor(frame)
        row = probe.measure(self.job, 'original', 1, self.engine(), predict)
        self.assertIs(seen[0].image, self.job['image'])
        self.assertEqual(row['inference_pixel_sha256'], self.job['pixel_sha256'])
        self.assertTrue(row['measurement']['distance_available'])
        self.assertEqual(row['pixel_mse'], 0.)
        self.assertIsNone(row['psnr_db'])
        self.assertIsNone(row['packet_candidate'])
        self.assertFalse(row['usable_for_ffb'])
        probe.assert_originals([self.job])

    def test_packet_real_codec_native_image_and_no_invented_odometry(self):
        row = probe.measure(self.job, 'packet', 2, self.engine(), self.predictor)
        self.assertNotEqual(row['inference_pixel_sha256'], self.job['pixel_sha256'])
        self.assertGreater(row['pixel_mse'], 0)
        self.assertGreater(row['packet_bytes'], 100)
        self.assertGreater(row['encode_ms'], 0)
        self.assertGreater(row['decode_validate_copy_ms'], 0)
        self.assertFalse(row['packet_candidate']['local_pair_available'])
        self.assertIsNone(row['packet_candidate']['odometry_observation'])
        self.assertEqual(row['packet_candidate']['capture_sequence'], 2)
        self.assertEqual(row['geometry_age_basis'], 'synthetic_zero_age_OFFLINE_NOT_live_freshness')
        self.assertTrue(all(row[k] is False for k in probe.FLAGS))
        probe.assert_originals([self.job])

    def test_empty_detection_stays_withheld_not_historical_fallback(self):
        a = probe.measure(self.job, 'original', 1, self.engine(), self.predictor)
        b = probe.measure(self.job, 'packet', 2, self.engine(), lambda frame: [])
        pair = probe.compare_pair(a, b)
        self.assertEqual(b['raw_detector_boxes'], [])
        self.assertEqual(b['measurement']['reason'], 'no_candidate')
        self.assertTrue(pair['original_numeric_packet_withheld'])
        self.assertIsNone(pair['range_delta_m'])

    def test_real_abba_warmup_excluded_all_pairs_logged(self):
        calls = []
        def predict(frame):
            calls.append(frame.sequence)
            return self.predictor(frame)
        rows, pairs, summary = probe.benchmark([self.job], predict, self.engine,
            repetitions=1, warmup=1, output=self.directory)
        self.assertEqual(calls, [1, 2, 3, 4, 5, 6])
        self.assertEqual([r['variant'] for r in rows], ['original', 'packet', 'packet', 'original'])
        self.assertEqual(len(pairs), 2)
        self.assertEqual(len((self.directory/'samples.jsonl').read_text().splitlines()), 4)
        self.assertEqual(summary['groups']['packet']['samples'], 2)
        self.assertEqual(summary['repeat_stability'][0]['original']['detector_signatures'], 1)
        self.assertFalse(summary['absolute_ground_truth_accuracy_verified'])
        self.assertFalse(summary['live_rate_or_deadline_verified'])

    def test_detector_signature_ignores_only_replay_label(self):
        a = dict(BOX, image='s:1')
        b = dict(BOX, image='s:2')
        self.assertEqual(probe.detector_signature([a]), probe.detector_signature([b]))
        b['confidence'] = .9
        self.assertNotEqual(probe.detector_signature([a]), probe.detector_signature([b]))

    def test_mutating_predictor_rejected(self):
        def corrupt(frame):
            frame.image.flags.writeable = True
            frame.image[0, 0, 0] = 0
            frame.image.flags.writeable = False
            return []
        with self.assertRaisesRegex(ValueError, 'modified inference pixels'):
            probe.measure(self.job, 'original', 1, self.engine(), corrupt)

    def test_log_overflow_fails_without_truncated_row(self):
        with patch.object(probe, 'MAX_LOG', 10):
            with self.assertRaisesRegex(ValueError, 'byte limit'):
                probe.benchmark([self.job], self.predictor, self.engine,
                    repetitions=1, warmup=1, output=self.directory)
        self.assertEqual((self.directory/'samples.jsonl').read_bytes(), b'')

    def test_input_allowlist_sha_duplicate_and_native_checks(self):
        with patch.dict(probe.KNOWN_IMAGES, {self.path.name: self.job['png_sha256']}, clear=True):
            loaded = probe.load_images([self.path])
            self.assertFalse(loaded[0]['image'].flags.writeable)
            with self.assertRaisesRegex(ValueError, 'duplicate'):
                probe.load_images([self.path, self.path])
            self.path.write_bytes(self.path.read_bytes() + b'x')
            with self.assertRaisesRegex(ValueError, 'changed'):
                probe.load_images([self.path])
        with self.assertRaises(ValueError):
            probe.load_images([])

    def test_final_symlink_rejected(self):
        link = self.directory/'link.png'
        link.symlink_to(self.path)
        with self.assertRaises((ValueError, OSError)):
            probe.load_images([link])

    def test_guarded_durations_and_memory_are_not_GPU_utilization(self):
        a = probe.measure(self.job, 'original', 1, self.engine(), self.predictor)
        b = copy.deepcopy(a)
        b.update(variant='packet', sequence=2, receiver_stage_ms=201.,
                 pytorch_memory_bytes=dict(peak_allocated=100, peak_reserved=200))
        pair = probe.compare_pair(a, b)
        summary = probe.summarize([a, b], [pair])
        self.assertEqual(summary['groups']['packet']['receiver_stage_over_200ms'], 1)
        self.assertEqual(summary['groups']['packet']['pytorch_memory_bytes']['peak_reserved']['maximum'], 200)
        self.assertFalse(summary['GPU_utilization_percent_measured'])
        self.assertFalse(summary['usable_for_ffb'])

    def test_pair_mismatched_sources_rejected(self):
        a = probe.measure(self.job, 'original', 1, self.engine(), self.predictor)
        b = dict(a, variant='packet', source_png_sha256='f'*64)
        with self.assertRaisesRegex(ValueError, 'same original'):
            probe.compare_pair(a, b)

    def test_options_require_bounded_run_and_explicit_ack(self):
        for kwargs in (dict(repetitions=0), dict(repetitions=21), dict(warmup=0),
                       dict(repetitions=True), dict(timeout_sec=181)):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                probe.benchmark([self.job], self.predictor, self.engine, **kwargs)
        output = self.directory/'no-create'
        with patch('sys.stderr', io.StringIO()):
            status = probe.main(['--image', str(self.path), '--weights', str(self.directory/'none.pt'),
                                 '--output-dir', str(output)])
        self.assertEqual(status, 1)
        self.assertFalse(output.exists())

    def test_output_file_not_overwritten(self):
        (self.directory/'samples.jsonl').write_text('original')
        with self.assertRaises(FileExistsError):
            probe.benchmark([self.job], self.predictor, self.engine, repetitions=1, warmup=1, output=self.directory)
        self.assertEqual((self.directory/'samples.jsonl').read_text(), 'original')

    def test_archive_results_only_and_no_overwrite(self):
        result = self.directory/'result'
        result.mkdir()
        probe.save_summary(result, dict(state='complete'))
        archive = self.directory/'out.tar.xz'
        probe.pack_result(result, archive)
        with tarfile.open(archive) as bundle:
            self.assertIn('result/summary.json', bundle.getnames())
        with self.assertRaises(FileExistsError):
            probe.pack_result(result, archive)
        (result/'forbidden.png').write_bytes(b'x')
        with self.assertRaisesRegex(ValueError, 'images/checkpoints'):
            probe.pack_result(result, self.directory/'images.tar.xz')
        self.assertFalse((self.directory/'images.tar.xz').exists())

    def test_failed_result_not_packaged_and_status_only_owned_run(self):
        result = self.directory/'result'
        result.mkdir()
        probe.save_summary(result, dict(state='initializing'))
        probe.save_summary(result, dict(state='failed', error='fixture'))
        with self.assertRaisesRegex(ValueError, 'only complete'):
            probe.pack_result(result, self.directory/'failed.tar.xz')
        self.assertEqual(json.loads((result/'summary.json').read_bytes())['error'], 'fixture')

    def test_original_file_mutation_detected(self):
        self.path.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'original PNG/pixels modified'):
            probe.assert_originals([self.job])


if __name__ == '__main__':
    unittest.main()
