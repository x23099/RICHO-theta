"""Synthetic provenance/fail-closed tests; no checkpoint loading or GPU."""
import contextlib
import hashlib
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from cone_dataset import read_csv, sha256, write_csv
from run_cone_review_frames import build_parser, infer_frames, load_manifest, validate_args, verify_frame
from test_cone_video import result


class ConeReviewFramesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.inputs = self.root / 'inputs'; self.inputs.mkdir()
        self.pixels = np.full((72,128,3), 50, np.uint8)
        self.image = self.inputs / 'raw.png'; self.assertTrue(cv2.imwrite(str(self.image), self.pixels))
        self.manifest = self.inputs / 'raw_review_manifest.csv'
        self.row = dict(file='raw.png', session='synthetic', frame=1, time_sec=.1, width=128, height=72,
            reason='synthetic', png_sha256=sha256(self.image),
            decoded_bgr_sha256=hashlib.sha256(self.pixels.tobytes()).hexdigest(), source_raw_sha256='a'*64)
        write_csv(self.manifest, [self.row])
        self.weights = self.root / 'model/weights.pt'; self.weights.parent.mkdir()
        self.weights.write_bytes(b'synthetic placeholder, never loaded')
        self.args = build_parser().parse_args(['--input-dir',str(self.inputs), '--weights',str(self.weights),
                                             '--output-dir',str(self.root/'output')])

    def test_intact_manifest_pixels(self):
        rows = load_manifest(self.inputs)
        self.assertEqual(len(rows),1)
        self.assertTrue(np.array_equal(verify_frame(self.inputs,rows[0])[1],self.pixels))

    def test_tampered_png_refused(self):
        cv2.imwrite(str(self.image), self.pixels+1)
        with self.assertRaisesRegex(ValueError,'PNG hash'): load_manifest(self.inputs)

    def test_geometry_and_pixel_hash_refused(self):
        for key,value in [('width',127),('decoded_bgr_sha256','b'*64)]:
            with self.subTest(key=key):
                with self.assertRaises(ValueError): verify_frame(self.inputs,dict(self.row,**{key:value}))

    def test_traversal_absolute_and_symlink_refused(self):
        for value in ['../outside.png',str(self.image)]:
            with self.assertRaises(ValueError): verify_frame(self.inputs,dict(self.row,file=value))
        (self.inputs/'link.png').symlink_to(self.image)
        with self.assertRaises(ValueError): verify_frame(self.inputs,dict(self.row,file='link.png'))

    def test_empty_duplicate_missing_metadata_refused(self):
        for rows in [[],[self.row,self.row],[dict(self.row,source_raw_sha256='invalid')],
                     [dict(self.row,time_sec='nan')],[dict(self.row,frame=0)], [{'file':'raw.png'}]]:
            write_csv(self.manifest,rows,tuple(self.row))
            with self.assertRaises(ValueError): load_manifest(self.inputs)

    def test_output_overlap_and_existing_refused(self):
        for output in [self.inputs/'new',self.root,self.weights.parent/'new']:
            self.args.output_dir=output
            with self.assertRaises(ValueError): validate_args(self.args)

    def test_invalid_arguments_refused(self):
        for key,value in [('device',-1),('imgsz',33),('max_det',0),('prediction_floor',float('nan')),
                          ('prediction_floor',0),('nms_iou',1.1)]:
            args=build_parser().parse_args(['--input-dir',str(self.inputs),'--weights',str(self.weights),
                                           '--output-dir',str(self.root/'output')])
            setattr(args,key,value)
            with self.assertRaises(ValueError):validate_args(args)

    def run_fake(self, prediction):
        args=validate_args(self.args);args.output_dir.mkdir()
        model=Mock();model.predict.return_value=[prediction]
        with contextlib.redirect_stdout(io.StringIO()):
            report=infer_frames(model,args,load_manifest(self.inputs))
        return report, model

    def test_empty_candidates_are_not_accuracy_pass(self):
        report,model=self.run_fake(result())
        self.assertEqual(report['predictions'],0)
        self.assertFalse(report['physical_output']);self.assertFalse(report['training_performed'])
        self.assertIn('NOT_ACCURACY',report['status'])
        self.assertFalse(model.predict.call_args.kwargs['save'])
        self.assertEqual(read_csv(self.args.output_dir/'predictions.csv'),[])

    def test_exports_original_coordinates_without_overlays(self):
        report,_=self.run_fake(result(coords=[(1,2,30,40)],scores=[.04],classes=[0]))
        row=read_csv(self.args.output_dir/'predictions.csv')[0]
        self.assertEqual(float(row['y2']),40);self.assertEqual(report['predictions'],1)
        self.assertEqual(sha256(self.image),self.row['png_sha256'])

    def test_external_manifest_and_existing_image_column(self):
        row=dict(self.row,image=self.row['file'],split='train')
        external=self.root/'external_manifest.csv';write_csv(external,[row])
        self.args.manifest=external
        args=validate_args(self.args);args.output_dir.mkdir()
        model=Mock();model.predict.return_value=[result()]
        with contextlib.redirect_stdout(io.StringIO()):
            report=infer_frames(model,args,load_manifest(args.input_dir,args.manifest))
        self.assertEqual(report['images'],1)
        self.assertFalse((self.inputs/'labels').exists())

    def test_below_floor_and_wrong_class_refused(self):
        for score,class_id in [(.001,0),(.1,1)]:
            with tempfile.TemporaryDirectory() as output:
                args=validate_args(self.args);args.output_dir=Path(output)
                model=Mock();model.predict.return_value=[result(coords=[(1,2,30,40)],scores=[score],classes=[class_id])]
                with self.assertRaises(ValueError):infer_frames(model,args,load_manifest(self.inputs))


if __name__=='__main__':
    unittest.main()
