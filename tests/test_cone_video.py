"""Synthetic video and temporal-statistics checks; no real model/GPU."""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

import cv2
import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from cone_dataset import read_csv,sha256,write_csv
from run_cone_video import (associate,build_parser,load_plan,run_video,stats,validated_args,zero_runs)


def box(x1=10,y1=10,x2=30,y2=30,track_id=1):
    return dict(image='synthetic',prediction_index=0,class_id=0,confidence=.9,
                x1=x1,y1=y1,x2=x2,y2=y2,track_id=track_id)


def result(shape=(72,128),coords=(),scores=(),classes=()):
    tensors={}
    for key,values in (('xyxy',coords),('conf',scores),('cls',classes)):
        value=Mock();value.detach.return_value.cpu.return_value.tolist.return_value=list(values)
        tensors[key]=value
    return SimpleNamespace(orig_shape=shape,boxes=SimpleNamespace(**tensors),
                           speed=dict(preprocess=1.,inference=2.,postprocess=3.))


class ConeVideoTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.session=self.root/'synthetic_session';self.session.mkdir()
        video=cv2.VideoWriter(str(self.session/'raw.avi'),cv2.VideoWriter_fourcc(*'MJPG'),30,(128,72))
        self.assertTrue(video.isOpened())
        for n in range(3): video.write(np.full((72,128,3),50+n*10,np.uint8))
        video.release()
        (self.session/'metadata.json').write_text(json.dumps(dict(requested_camera_width=128,requested_camera_height=72)))
        self.rows=[dict(frame=n,time_sec=n/30) for n in (1,2,3)]
        write_csv(self.session/'detections.csv',self.rows)
        self.plan=self.root/'plan.csv';write_csv(self.plan,[dict(session_dir=str(self.session),note='synthetic')])
        (self.root/'checkpoint').mkdir();self.weights=self.root/'checkpoint/weights.pt'
        self.weights.write_bytes(b'synthetic placeholder, never deserialized')
        self.args=validated_args(build_parser().parse_args(['video','--plan',str(self.plan),
            '--weights',str(self.weights),'--output-dir',str(self.root/'output')]))

    def test_plan_checks_and_hashes(self):
        sessions=load_plan(self.plan,self.args.output_dir,self.weights)
        self.assertEqual(len(sessions[0]['rows']),3)
        self.assertEqual(sessions[0]['hashes']['raw.avi'],sha256(self.session/'raw.avi'))

    def test_empty_plan_and_missing_files_refused(self):
        write_csv(self.plan,[],('session_dir','note'))
        with self.assertRaises(ValueError):load_plan(self.plan,self.args.output_dir,self.weights)
        write_csv(self.plan,[dict(session_dir=str(self.root/'nonexistent'),note='synthetic')])
        with self.assertRaises(ValueError):load_plan(self.plan,self.args.output_dir,self.weights)

    def test_duplicate_session_or_raw_content_refused(self):
        write_csv(self.plan,[dict(session_dir=str(self.session),note='a')]*2)
        with self.assertRaisesRegex(ValueError,'duplicate session'):load_plan(self.plan,self.args.output_dir,self.weights)

    def test_timestamp_nonfinite_or_nonmonotonic_refused(self):
        for times in ([0,.1,.1],[0,float('nan'),.2],[-1,0,.1]):
            write_csv(self.session/'detections.csv',[dict(frame=n+1,time_sec=value) for n,value in enumerate(times)])
            with self.subTest(times=times),self.assertRaises(ValueError):
                load_plan(self.plan,self.args.output_dir,self.weights)

    def test_noncontiguous_csv_frames_refused(self):
        write_csv(self.session/'detections.csv',[dict(frame=2,time_sec=.1)])
        with self.assertRaisesRegex(ValueError,'contiguous'):load_plan(self.plan,self.args.output_dir,self.weights)

    def test_overlap_and_existing_output_refused(self):
        with self.assertRaisesRegex(ValueError,'overlap'):
            load_plan(self.plan,self.session/'analysis',self.weights)
        self.args.output_dir.mkdir()
        with self.assertRaisesRegex(ValueError,'new output'):validated_args(self.args)

    def test_invalid_settings_and_weights_refused(self):
        for name,value in (('confidence',float('nan')),('track_iou',0),('nms_iou',1.1),('device',-1),('imgsz',641)):
            original=getattr(self.args,name);setattr(self.args,name,value)
            with self.subTest(name=name),self.assertRaises(ValueError):validated_args(self.args)
            setattr(self.args,name,original)
        self.args.weights=self.root/'missing.pt'
        with self.assertRaises(ValueError):validated_args(self.args)

    def test_iou_link_and_bottom_delta(self):
        linked,next_id=associate([box()],[box(x1=11,y1=11,x2=31,y2=31)],128,2,.3)
        self.assertEqual(linked[0]['track_id'],1)
        self.assertEqual(next_id,2)
        self.assertEqual((linked[0]['bottom_dx_px'],linked[0]['bottom_dy_px']),(1,1))

    def test_no_cross_image_half_link(self):
        linked,next_id=associate([box(x1=50,x2=70)],[box(x1=55,x2=75)],128,2,.3)
        self.assertEqual(linked[0]['track_id'],2)
        self.assertEqual(linked[0]['previous_iou'],'')

    def test_duplicate_prediction_one_to_one_link(self):
        linked,next_id=associate([box()],[box(),box()],128,2,.3)
        self.assertEqual(len({row['track_id'] for row in linked}),2)
        self.assertEqual(sum(row['previous_iou']!='' for row in linked),1)

    def test_dropped_frame_does_not_bridge_identity(self):
        empty,next_id=associate([box()],[],128,2,.3)
        linked,next_id=associate(empty,[box()],128,next_id,.3)
        self.assertEqual(linked[0]['track_id'],2)

    def test_zero_runs_include_head_tail_and_truth_unknown(self):
        rows=[dict(session='synthetic',frame=i+1,time_sec=i/30,detections=value)
              for i,value in enumerate([0,1,0,0,1,0])]
        runs=zero_runs(rows)
        self.assertEqual([row['zero_frames'] for row in runs],[1,2,1])
        self.assertEqual([row['bounded_by_detection'] for row in runs],[0,1,0])
        self.assertTrue(all('unknown' in row['truth'] for row in runs))

    def test_empty_statistics_are_not_zero_noise(self):
        self.assertIsNone(stats([])['p95'])
        self.assertEqual(stats([1,2,3])['p50'],2)

    def test_mocked_run_reads_all_frames_without_changing_source(self):
        sessions=load_plan(self.plan,self.args.output_dir,self.weights)
        hashes={path.name:sha256(path) for path in self.session.iterdir()}
        self.args.output_dir.mkdir()
        model=Mock();model.predict.side_effect=[[result(coords=[(10,10,30,30)],scores=[.9],classes=[0])],
                                                [result()],[result(coords=[(11,10,31,30)],scores=[.9],classes=[0])]]
        with contextlib.redirect_stdout(io.StringIO()): report=run_video(model,self.args,sessions,([],[]))
        self.assertEqual(report['total_frames'],3)
        self.assertEqual(report['sessions'][0]['tracks'],2)
        self.assertEqual(report['sessions'][0]['internal_zero_runs'],1)
        self.assertEqual(len(read_csv(self.args.output_dir/'predictions.csv')),2)
        self.assertEqual(hashes,{path.name:sha256(path) for path in self.session.iterdir()})
        self.assertFalse(report['physical_output'])
        model.train.assert_not_called();model.val.assert_not_called()

    def test_video_csv_length_mismatch_refused(self):
        write_csv(self.session/'detections.csv',self.rows[:2])
        sessions=load_plan(self.plan,self.args.output_dir,self.weights)
        self.args.output_dir.mkdir();model=Mock();model.predict.return_value=[result()]
        with self.assertRaisesRegex(ValueError,'longer'),contextlib.redirect_stdout(io.StringIO()):
            run_video(model,self.args,sessions,([],[]))

    def test_invalid_result_count_refused(self):
        sessions=load_plan(self.plan,self.args.output_dir,self.weights)
        self.args.output_dir.mkdir();model=Mock();model.predict.return_value=[]
        with self.assertRaisesRegex(ValueError,'one detector'),contextlib.redirect_stdout(io.StringIO()):
            run_video(model,self.args,sessions,([],[]))


if __name__=='__main__':unittest.main()
