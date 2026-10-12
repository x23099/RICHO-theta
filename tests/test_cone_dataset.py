import csv
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

import cv2
import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from cone_dataset import (PLAN_FIELDS,dataset_yaml,invalidate_label_caches,label_path,load_plan,mark_review,parse_label,
                          prepare,read_csv,sha256,validate,write_csv)
from annotate_cone_dataset import label_preview,normalized_box


class ConeDatasetTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.rows=[]
        for index,split in enumerate(('train','val','test')):
            session=self.root/split
            session.mkdir()
            (session/'metadata.json').write_text(json.dumps(dict(requested_camera_width=160,
                requested_camera_height=96,parameters={})))
            write_csv(session/'detections.csv',[dict(frame=i,time_sec=i/30) for i in range(1,4)])
            video=cv2.VideoWriter(str(session/'raw.avi'),cv2.VideoWriter_fourcc(*'MJPG'),30,(160,96))
            self.assertTrue(video.isOpened())
            for i in range(3):
                frame=np.full((96,160,3),30+index*60+i*10,np.uint8)
                frame[30:60,50:100,1]=200-index*30
                video.write(frame)
            video.release()
            self.rows.append(dict(session_dir=str(session),group_id=split+'_capture',split=split,
                                  start_frame='1',end_frame='',stride_frames='1',notes='SYNTHETIC TEST'))
        self.plan=self.root/'plan.csv'
        write_csv(self.plan,self.rows,PLAN_FIELDS)
        self.output=self.root/'dataset'

    def prepared(self):
        prepare(self.plan,self.output)
        return read_csv(self.output/'manifest.csv')

    def reviewed(self):
        rows=self.prepared()
        for r in rows:
            label_path(self.output,r['image']).write_text('0 0.5 0.5 0.2 0.3\n')
            mark_review(self.output,r['image'],'positive','synthetic unit-test annotation')
        return rows

    def test_whole_frame_export_and_pending_labels(self):
        rows=self.prepared()
        self.assertEqual(len(rows),9)
        self.assertTrue(all(r['status']=='pending' for r in read_csv(self.output/'reviews.csv')))
        self.assertFalse(list((self.output/'labels').rglob('*.txt')))
        for r in rows:
            frame=cv2.imread(str(self.output/r['image']))
            self.assertEqual(frame.shape,(96,160,3))
            self.assertEqual(hashlib.sha256(frame.tobytes()).hexdigest(),r['decoded_bgr_sha256'])

    def test_pending_annotations_never_pass_check(self):
        self.prepared()
        with self.assertRaisesRegex(ValueError,'unreviewed'): validate(self.output)

    def test_complete_reviewed_dataset_passes(self):
        self.reviewed()
        result=validate(self.output)
        self.assertEqual(result['status'],'PASS_DATASET_INTEGRITY_NOT_MODEL_ACCURACY')
        self.assertEqual(result['counts']['test']['boxes'],3)

    def test_plan_group_cannot_cross_splits(self):
        self.rows[1]['group_id']=self.rows[0]['group_id']
        write_csv(self.plan,self.rows,PLAN_FIELDS)
        with self.assertRaisesRegex(ValueError,'group crosses'): load_plan(self.plan)

    def test_session_cannot_be_randomly_split(self):
        self.rows[1]['session_dir']=self.rows[0]['session_dir']
        write_csv(self.plan,self.rows,PLAN_FIELDS)
        with self.assertRaisesRegex(ValueError,'session can appear only once'): load_plan(self.plan)

    def test_identical_source_video_is_detected_under_another_path(self):
        shutil.copyfile(self.root/'train/raw.avi',self.root/'val/raw.avi')
        with self.assertRaisesRegex(ValueError,'source video crosses'): prepare(self.plan,self.output)
        self.assertFalse(self.output.exists())

    def test_blank_template_is_rejected(self):
        self.rows[0]['session_dir']=''
        write_csv(self.plan,self.rows,PLAN_FIELDS)
        with self.assertRaisesRegex(ValueError,'template'): load_plan(self.plan)

    def test_all_three_splits_are_required(self):
        write_csv(self.plan,self.rows[:2],PLAN_FIELDS)
        with self.assertRaises(ValueError): load_plan(self.plan)

    def test_nonpositive_or_fractional_stride_rejected(self):
        for stride in ('0','-1','1.5'):
            self.rows[0]['stride_frames']=stride
            write_csv(self.plan,self.rows,PLAN_FIELDS)
            with self.assertRaises(ValueError): load_plan(self.plan)

    def test_source_video_csv_count_mismatch_leaves_no_dataset(self):
        write_csv(self.root/'train/detections.csv',[dict(frame=i,time_sec=i/30) for i in range(1,3)])
        with self.assertRaisesRegex(ValueError,'longer'): prepare(self.plan,self.output)
        self.assertFalse(self.output.exists())

    def test_no_dataset_overwrite(self):
        self.output.mkdir()
        marker=self.output/'user.txt'; marker.write_text('keep')
        with self.assertRaises(ValueError): prepare(self.plan,self.output)
        self.assertEqual(marker.read_text(),'keep')

    def test_positive_review_needs_boxes(self):
        r=self.prepared()[0]
        with self.assertRaisesRegex(ValueError,'positive review'): mark_review(self.output,r['image'],'positive','review')

    def test_negative_review_is_explicit_and_cannot_erase_boxes(self):
        rows=self.reviewed()
        label=label_path(self.output,rows[0]['image'])
        before=label.read_bytes()
        with self.assertRaisesRegex(ValueError,'discard'): mark_review(self.output,rows[0]['image'],'negative','review')
        self.assertEqual(label.read_bytes(),before)
        label.unlink()  # synthetic fixture only, tests explicit negative transition
        mark_review(self.output,rows[0]['image'],'negative','synthetic no cone')
        self.assertEqual(label.read_text(),'')
        self.assertEqual(validate(self.output)['counts']['train']['negative'],1)

    def test_labels_reject_other_classes_nonfinite_and_outside_boxes(self):
        path=self.root/'label.txt'
        for line in ('1 .5 .5 .2 .2','0 nan .5 .2 .2','0 .5 .5 0 .2','0 .99 .5 .2 .2','0 .5 .5 .2'):
            path.write_text(line)
            with self.subTest(line=line),self.assertRaises(ValueError): parse_label(path)

    def test_unreviewed_note_rejected(self):
        r=self.prepared()[0]
        with self.assertRaises(ValueError): mark_review(self.output,r['image'],'negative','')

    def test_positive_negative_review_mismatch_rejected(self):
        rows=self.reviewed()
        label_path(self.output,rows[0]['image']).write_text('')
        with self.assertRaisesRegex(ValueError,'disagree'): validate(self.output)

    def test_modified_image_rejected(self):
        rows=self.reviewed()
        path=self.output/rows[0]['image']
        frame=cv2.imread(str(path)); frame[0,0]=255; cv2.imwrite(str(path),frame)
        with self.assertRaisesRegex(ValueError,'PNG changed'): validate(self.output)

    def test_valid_but_changed_label_requires_another_review(self):
        rows=self.reviewed()
        label_path(self.output,rows[0]['image']).write_text('0 .5 .5 .1 .2\n')
        with self.assertRaisesRegex(ValueError,'changed since human review'): validate(self.output)
        mark_review(self.output,rows[0]['image'],'positive','synthetic corrected review')
        validate(self.output)

    def test_unmanifested_files_rejected(self):
        self.reviewed()
        (self.output/'labels/train/extra.txt').write_text('')
        with self.assertRaisesRegex(ValueError,'unmanifested'): validate(self.output)

    def test_test_must_have_a_positive(self):
        rows=self.reviewed()
        for r in rows:
            if r['split']=='test':
                label_path(self.output,r['image']).unlink()
                mark_review(self.output,r['image'],'negative','synthetic no cone')
        with self.assertRaisesRegex(ValueError,'positive image'): validate(self.output)

    def test_relocation_changes_only_yaml_root(self):
        self.reviewed()
        moved=self.root/'moved'
        self.output.rename(moved)
        with self.assertRaisesRegex(ValueError,'dataset moved'): validate(moved)
        (moved/'data.yaml').write_text(dataset_yaml(moved))
        self.assertEqual(validate(moved)['counts']['val']['positive'],3)

    def test_roi_conversion_uses_original_dimensions(self):
        self.assertEqual(normalized_box((10,20,40,20),100,100),(.3,.3,.4,.2))
        with self.assertRaises(ValueError): normalized_box((90,0,20,20),100,100)

    def test_screen_preview_does_not_edit_original_pixels(self):
        frame=np.zeros((96,160,3),np.uint8)
        preview=label_preview(frame,[(.5,.5,.2,.3)])
        self.assertFalse(frame.any())
        self.assertTrue(preview.any())

    def test_path_traversal_and_label_symlink_rejected(self):
        with self.assertRaises(ValueError): label_path(self.root,'images/train/../../../escape.png')
        rows=self.prepared()
        label=label_path(self.output,rows[0]['image'])
        target=self.root/'external.txt'; target.write_text('')
        label.symlink_to(target)
        with self.assertRaises(ValueError): mark_review(self.output,rows[0]['image'],'negative','review')

    def test_generated_cache_is_not_an_extra_label_and_only_cache_is_removed(self):
        rows=self.reviewed()
        label=label_path(self.output,rows[0]['image'])
        before=label.read_bytes()
        (self.output/'labels/train.cache').write_bytes(b'synthetic framework cache')
        validate(self.output)
        self.assertEqual(invalidate_label_caches(self.output),['labels/train.cache'])
        self.assertEqual(label.read_bytes(),before)

    def test_identical_pixels_in_reencoded_video_are_rejected(self):
        original=(self.root/'train/raw.avi').read_bytes()
        (self.root/'val/raw.avi').write_bytes(original+b'synthetic unused AVI tail')
        with self.assertRaisesRegex(ValueError,'decoded frame crosses'): prepare(self.plan,self.output)


if __name__=='__main__': unittest.main()
