"""Synthetic diagnostics checks. These do not execute YOLO or measure accuracy."""
import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from cone_dataset import read_csv, sha256, write_csv
from cone_detection_diagnostics import (ATTR_FIELDS, aggregate, diagnostic_config,
    extract_predictions, intersection_over_union, load_attributes, match_image,
    prediction_kwargs, prepare_inputs, run_diagnostics)
from run_cone_yolo import build_parser, main, validated_args


def prediction(index=0, score=.8, box=(10, 10, 30, 40), image='images/val/example.png'):
    return dict(image=image, prediction_index=index, confidence=score, class_id=0,
                **dict(zip(('x1', 'y1', 'x2', 'y2'), box)))


def truth(index=0, box=(10, 10, 30, 40), image='images/val/example.png'):
    return dict(image=image, gt_index=index, class_id=0,
                **dict(zip(('x1', 'y1', 'x2', 'y2'), box)),
                height_px=box[3]-box[1], size_band='small', image_half='left',
                label_sha256='synthetic-label-hash', color='unknown', lens='unknown',
                occlusion='unknown', attribute_note='')


def result(boxes=(), scores=(), classes=(), shape=(72, 128)):
    tensors = {}
    for name, values in (('xyxy', boxes), ('conf', scores), ('cls', classes)):
        tensor = Mock()
        tensor.detach.return_value.cpu.return_value.tolist.return_value = list(values)
        tensors[name] = tensor
    return SimpleNamespace(orig_shape=shape, boxes=SimpleNamespace(**tensors),
                           speed=dict(preprocess=1., inference=2., postprocess=3.))


class DiagnosticTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.dataset = self.root / 'dataset'
        (self.dataset / 'images/val').mkdir(parents=True)
        (self.dataset / 'labels/val').mkdir(parents=True)
        self.image = 'images/val/example.png'
        cv2.imwrite(str(self.dataset / self.image), np.full((72, 128, 3), 42, np.uint8))
        (self.dataset / 'labels/val/example.txt').write_text('0 .25 .5 .25 .5\n')
        self.images = [dict(image=self.image, split='val', session='synthetic_session',
                            frame='1', time_sec='.033', width='128', height='72',
                            png_sha256=sha256(self.dataset / self.image))]
        write_csv(self.dataset / 'manifest.csv', self.images)
        (self.root / 'checkpoint').mkdir()
        self.weights = self.root / 'checkpoint/weights.pt'
        self.weights.write_bytes(b'synthetic dummy; NEVER loaded as torch checkpoint')
        self.args = validated_args(build_parser().parse_args(['diagnose',
            '--dataset', str(self.dataset), '--weights', str(self.weights),
            '--output-dir', str(self.root / 'output')]))

    def test_diagnose_needs_explicit_weights(self):
        with self.assertRaisesRegex(ValueError, 'explicit trained'):
            validated_args(build_parser().parse_args(['diagnose', '--dataset', str(self.dataset),
                                                     '--output-dir', str(self.root / 'unused')]))

    def test_thresholds_reject_nan_range_duplicates_and_below_floor(self):
        for values in ([float('nan')], [float('inf')], [0], [1.1], [.25, .25], [.001]):
            self.args.confidence_thresholds = values
            with self.subTest(values=values), self.assertRaises(ValueError):
                diagnostic_config(self.args)

    def test_iou_and_maxdet_reject_invalid_values(self):
        for name, value in (('nms_iou', 0), ('match_iou', float('nan')),
                            ('prediction_floor', 2), ('max_det', 0)):
            original = getattr(self.args, name)
            setattr(self.args, name, value)
            with self.subTest(name=name), self.assertRaises(ValueError):
                diagnostic_config(self.args)
            setattr(self.args, name, original)

    def test_predict_settings_are_explicit_and_disable_images(self):
        kwargs = prediction_kwargs(self.args)
        self.assertEqual(kwargs['quantize'], 32)
        self.assertFalse(kwargs['rect'])
        self.assertEqual(kwargs['batch'], 1)
        for name in ('save', 'save_txt', 'show', 'visualize', 'augment', 'stream'):
            self.assertFalse(kwargs[name])
        self.assertNotIn('data', kwargs)

    def test_unavailable_test_not_replaced_by_val(self):
        with self.assertRaisesRegex(ValueError, 'unavailable'):
            prepare_inputs(self.dataset, 'test')

    def test_label_conversion_geometry_size_half_unknown_attributes(self):
        images, truths = prepare_inputs(self.dataset, 'val')
        self.assertEqual(len(images), 1)
        self.assertEqual([truths[0][k] for k in ('x1', 'y1', 'x2', 'y2')], [16, 18, 48, 54])
        self.assertEqual(truths[0]['size_band'], 'medium')
        self.assertEqual(truths[0]['image_half'], 'left')
        self.assertEqual(truths[0]['color'], 'unknown')
        self.assertEqual(truths[0]['lens'], 'unknown')

    def test_attributes_accept_human_note_and_reject_stale_duplicate_unknown_gt(self):
        _, truths = prepare_inputs(self.dataset, 'val')
        row = dict(image=self.image, gt_index=0, label_sha256=truths[0]['label_sha256'],
                   color='red', lens='front', occlusion='none', note='synthetic human review')
        path = self.root / 'attributes.csv'
        write_csv(path, [row], ATTR_FIELDS)
        _, updated = prepare_inputs(self.dataset, 'val', path)
        self.assertEqual(updated[0]['color'], 'red')
        self.assertEqual(updated[0]['attribute_note'], row['note'])
        for rows in ([dict(row, label_sha256='stale')], [row, row], [dict(row, gt_index=9)],
                     [dict(row, color='blue')], [dict(row, note='')]):
            write_csv(path, rows, ATTR_FIELDS)
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                load_attributes(path, truths)

    def test_iou_identical_disjoint_partial(self):
        a = truth(box=(0, 0, 10, 10))
        self.assertEqual(intersection_over_union(a, a), 1)
        self.assertEqual(intersection_over_union(a, truth(box=(10, 10, 20, 20))), 0)
        self.assertAlmostEqual(intersection_over_union(a, truth(box=(5, 0, 15, 10))), 1/3)

    def test_confidence_boundary_and_one_to_one_duplicate(self):
        rows = match_image([truth()], [prediction(0, .25), prediction(1, .9)], .25, .5)
        self.assertEqual([row['outcome'] for row in rows], ['TP', 'FP'])
        self.assertEqual(rows[0]['prediction_index'], 1)

    def test_missed_and_negative_images(self):
        self.assertEqual(match_image([truth()], [], .25, .5)[0]['outcome'], 'FN')
        self.assertEqual(match_image([], [prediction()], .25, .5)[0]['outcome'], 'FP')
        self.assertEqual(match_image([], [], .25, .5), [])

    def test_wrong_location_is_fp_and_fn(self):
        rows = match_image([truth()], [prediction(box=(60, 0, 80, 10))], .25, .5)
        self.assertEqual([row['outcome'] for row in rows], ['FP', 'FN'])

    def test_iou_boundary_and_best_unmatched_gt(self):
        rows = match_image([truth(0), truth(1, (50, 10, 70, 40))],
                           [prediction(box=(50, 10, 70, 40))], .25, 1.)
        self.assertEqual(rows[0]['gt_index'], 1)
        self.assertEqual(rows[1]['gt_index'], 0)

    def test_aggregate_thresholds_and_unknown_strata(self):
        config = dict(confidence_thresholds=[.1, .5], match_iou=.5)
        image_rows, matches, totals, strata = aggregate(self.images, [truth()], [prediction(score=.3)], config)
        self.assertEqual((totals[0]['tp'], totals[1]['fn']), (1, 1))
        self.assertEqual(totals[1]['precision'], '')
        self.assertEqual(totals[1]['recall'], 0)
        self.assertEqual(len(image_rows), 2)
        self.assertEqual({row['value'] for row in strata if row['dimension'] == 'color'}, {'unknown'})

    def test_valid_and_empty_prediction_export(self):
        rows = extract_predictions(result([(10, 10, 30, 40)], [.8], [0]), self.images[0])
        self.assertEqual(rows[0]['x1'], 10)
        self.assertEqual(extract_predictions(result(), self.images[0]), [])

    def test_invalid_result_arrays_geometry_class_finite_and_bounds(self):
        invalid = [result(shape=(10, 10)), result([(1, 1, 3, 3)], [], [0]),
                   result([(1, 1, 3, 3)], [.5], [1]), result([(1, 1, 3, 3)], [float('nan')], [0]),
                   result([(-1, 1, 3, 3)], [.5], [0]), result([(1, 1, 129, 3)], [.5], [0]),
                   result([(1, 1, 1, 3)], [.5], [0])]
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValueError):
                extract_predictions(value, self.images[0])

    def test_run_exports_empty_predictions_and_preserves_raw_images_and_labels(self):
        before = {str(path): sha256(path) for path in self.dataset.rglob('*') if path.is_file()}
        self.args.output_dir.mkdir()
        model = Mock()
        model.predict.return_value = [result()]
        with contextlib.redirect_stdout(io.StringIO()):
            report = run_diagnostics(model, self.args, prepare_inputs(self.dataset, 'val'))
        self.assertEqual(report['image_count'], 1)
        self.assertEqual(report['threshold_summary'][0]['fn'], 1)
        self.assertEqual(read_csv(self.args.output_dir / 'predictions.csv'), [])
        self.assertEqual(len(read_csv(self.args.output_dir / 'matches.csv')), 5)
        self.assertEqual(sha256(self.dataset / self.image), sha256(self.args.output_dir / 'raw_examples/example.png'))
        self.assertEqual(before, {str(path): sha256(path) for path in self.dataset.rglob('*') if path.is_file()})
        self.assertIn('synthetic_session', (self.args.output_dir / 'raw_example_manifest.csv').read_text())
        self.assertFalse(report['physical_output'])
        model.train.assert_not_called()
        model.val.assert_not_called()
        self.assertNotIn('\r', (self.args.output_dir / 'threshold_summary.csv').read_bytes().decode())

    def test_invalid_timing_or_model_result_count_fails(self):
        self.args.output_dir.mkdir()
        model = Mock()
        model.predict.return_value = []
        with self.assertRaisesRegex(ValueError, 'exactly one'):
            run_diagnostics(model, self.args, prepare_inputs(self.dataset, 'val'))
        value = result()
        value.speed['inference'] = float('nan')
        model.predict.return_value = [value]
        with self.assertRaisesRegex(ValueError, 'timing'):
            run_diagnostics(model, self.args, prepare_inputs(self.dataset, 'val'))

    def test_main_refuses_dataset_before_gpu_import_or_output_creation(self):
        argv = ['run_cone_yolo.py', 'diagnose', '--dataset', str(self.dataset),
                '--weights', str(self.weights), '--output-dir', str(self.args.output_dir)]
        with patch.object(sys, 'argv', argv), patch('run_cone_yolo.validate', side_effect=ValueError('unreviewed')):
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
                main()
        self.assertEqual(raised.exception.code, 2)
        self.assertFalse(self.args.output_dir.exists())

    def test_main_test_split_requires_independent_test_before_output(self):
        argv = ['run_cone_yolo.py', 'diagnose', '--dataset', str(self.dataset),
                '--weights', str(self.weights), '--output-dir', str(self.args.output_dir),
                '--diagnostic-split', 'test']
        with patch.object(sys, 'argv', argv), patch('run_cone_yolo.validate',
                side_effect=ValueError('no independent test')) as check:
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                main()
        check.assert_called_once_with(self.dataset, require_test=True)
        self.assertFalse(self.args.output_dir.exists())

    def test_output_and_attributes_guards(self):
        self.args.output_dir = self.weights.parent / 'nested'
        with self.assertRaisesRegex(ValueError, 'checkpoint directory'):
            validated_args(self.args)
        self.args.output_dir = self.root / 'output'
        self.args.object_attributes = self.root / 'missing.csv'
        with self.assertRaisesRegex(ValueError, 'attribute file'):
            validated_args(self.args)

    def test_low_floor_and_max_det_violations_fail(self):
        self.args.output_dir.mkdir()
        model = Mock()
        model.predict.return_value = [result([(1, 1, 3, 3)], [.001], [0])]
        with self.assertRaisesRegex(ValueError, 'contract violated'):
            run_diagnostics(model, self.args, prepare_inputs(self.dataset, 'val'))
        self.args.max_det = 1
        model.predict.return_value = [result([(1, 1, 3, 3), (10, 10, 20, 20)], [.2, .3], [0, 0])]
        with self.assertRaisesRegex(ValueError, 'contract violated'):
            run_diagnostics(model, self.args, prepare_inputs(self.dataset, 'val'))

    def test_mocked_main_records_provenance_and_does_not_invalidate_dataset_caches(self):
        model = Mock(names={0: 'traffic_cone'})
        model.predict.return_value = [result([(16, 18, 48, 54)], [.8], [0])]
        module = SimpleNamespace(YOLO=Mock(return_value=model), settings={})
        argv = ['run_cone_yolo.py', 'diagnose', '--dataset', str(self.dataset),
                '--weights', str(self.weights), '--output-dir', str(self.args.output_dir)]
        with patch.object(sys, 'argv', argv), patch.dict(os.environ), \
                patch.dict(sys.modules, {'torch': Mock(), 'ultralytics': module}), \
                patch('run_cone_yolo.validate', return_value={'synthetic_test': True}), \
                patch('run_cone_yolo.check_cuda', return_value={'synthetic_gpu': True}), \
                patch('run_cone_yolo.importlib.metadata.version', return_value='synthetic'), \
                patch('run_cone_yolo.subprocess.check_output', return_value='synthetic-test-only\n'), \
                patch('run_cone_yolo.invalidate_label_caches') as caches, \
                contextlib.redirect_stdout(io.StringIO()):
            main()
            self.assertEqual(os.environ['YOLO_CONFIG_DIR'], str(self.args.output_dir / 'ultralytics_config'))
        self.assertTrue((self.args.output_dir / 'ultralytics_config/Ultralytics').is_dir())
        provenance = json.loads((self.args.output_dir / 'provenance.json').read_text())
        self.assertEqual(provenance['mode'], 'diagnose')
        self.assertEqual(provenance['weights_sha256'], sha256(self.weights))
        self.assertEqual(provenance['status'], 'COMPLETED_NOT_HARDWARE_OR_SAFETY_APPROVAL')
        self.assertFalse(provenance['physical_output'])
        caches.assert_not_called()
        model.train.assert_not_called()
        model.val.assert_not_called()

    def test_attribute_notes_survive_template_export(self):
        images, truths = prepare_inputs(self.dataset, 'val')
        truths[0].update(color='yellow', attribute_note='synthetic human note')
        self.args.output_dir.mkdir()
        model = Mock()
        model.predict.return_value = [result()]
        with contextlib.redirect_stdout(io.StringIO()):
            run_diagnostics(model, self.args, (images, truths))
        loaded = load_attributes(self.args.output_dir / 'attributes_template.csv', truths)
        self.assertEqual(loaded[(self.image, 0)]['attribute_note'], 'synthetic human note')


if __name__ == '__main__':
    unittest.main()
