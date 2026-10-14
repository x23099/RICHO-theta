"""Human-confirmed editing and exact-repeat prevention, no GUI/GPU execution."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import cv2
import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from cone_dataset import label_path,parse_label,read_csv,sha256,write_csv
from annotate_cone_dataset import import_visual_reviews,main,overlapping_boxes,save_reviewed_boxes,unique_roi_boxes


class ConeAnnotationEditTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)/'dataset';self.root.mkdir()
        pixels=np.full((72,128,3),80,np.uint8)
        image=self.root/'images/train/raw.png';image.parent.mkdir(parents=True)
        cv2.imwrite(str(image),pixels)
        self.row=dict(image='images/train/raw.png',split='train',group_id='a',session='s',frame='1',time_sec='0.1',
            width='128',height='72',png_sha256=sha256(image),decoded_bgr_sha256=hashlib.sha256(pixels.tobytes()).hexdigest(),
            source_raw_sha256='a'*64)
        write_csv(self.root/'manifest.csv',[self.row])
        write_csv(self.root/'reviews.csv',[dict(image=self.row['image'],status='pending',note='',label_sha256='')])
        (self.root/'dataset.json').write_text(json.dumps(dict(schema_version=1,classes=['traffic_cone'],
            manifest_sha256=sha256(self.root/'manifest.csv'))))
        self.label=label_path(self.root,self.row['image']);self.label.parent.mkdir(parents=True)
        self.box=(.5,.5,.2,.2)

    def test_same_new_roi_selected_twice_is_one_box(self):
        self.assertEqual(len(unique_roi_boxes([(10,20,30,20)]*3,128,72)),1)
        self.assertEqual(len(unique_roi_boxes([(10,20,30,20),(60,20,20,20)],128,72)),2)

    def test_bad_new_roi_refused(self):
        with self.assertRaises(ValueError):unique_roi_boxes([(0,0,0,20)],128,72)

    def test_nonidentical_overlaps_warn_but_are_not_automatically_removed(self):
        boxes=[(.5,.5,.2,.2),(.51,.5,.2,.2),(.8,.5,.1,.1)]
        self.assertEqual(overlapping_boxes(boxes),[(1,2)])
        self.assertEqual(len(boxes),3)

    def test_save_new_confirmed_label_keeps_raw_image(self):
        backup=save_reviewed_boxes(self.root,self.row,[self.box])
        self.assertIsNone(backup)
        review=read_csv(self.root/'reviews.csv')[0]
        self.assertEqual(review['status'],'positive');self.assertEqual(review['label_sha256'],sha256(self.label))
        self.assertEqual(sha256(self.root/self.row['image']),self.row['png_sha256'])

    def test_different_existing_label_needs_edit_option(self):
        save_reviewed_boxes(self.root,self.row,[self.box]);before=self.label.read_bytes()
        with self.assertRaises(ValueError):save_reviewed_boxes(self.root,self.row,[(.4,.5,.2,.2)])
        self.assertEqual(self.label.read_bytes(),before)
        self.assertFalse((self.root/'annotation_backups').exists())

    def test_confirmed_replacement_backs_up_label_and_review(self):
        save_reviewed_boxes(self.root,self.row,[self.box])
        old_label=self.label.read_bytes();old_review=(self.root/'reviews.csv').read_bytes()
        backup=save_reviewed_boxes(self.root,self.row,[(.4,.5,.2,.2)],replace_existing=True)
        self.assertEqual((backup/'label.txt').read_bytes(),old_label)
        self.assertEqual((backup/'reviews.csv').read_bytes(),old_review)
        self.assertEqual(read_csv(self.root/'reviews.csv')[0]['label_sha256'],sha256(self.label))
        self.assertEqual(sha256(self.root/self.row['image']),self.row['png_sha256'])

    def test_duplicate_old_label_can_be_explicitly_corrected_with_backup(self):
        old='0 0.5 0.5 0.2 0.2\n'*2;self.label.write_text(old)
        with self.assertRaisesRegex(ValueError,'duplicate annotation'):parse_label(self.label)
        self.assertEqual(len(parse_label(self.label,reject_duplicates=False)),2)
        backup=save_reviewed_boxes(self.root,self.row,[self.box],replace_existing=True)
        self.assertEqual((backup/'label.txt').read_text(),old)
        self.assertEqual(len(parse_label(self.label)),1)

    def test_empty_or_duplicate_proposed_boxes_cannot_overwrite(self):
        save_reviewed_boxes(self.root,self.row,[self.box]);before=self.label.read_bytes()
        for boxes in ([],[self.box,self.box]):
            with self.assertRaises(ValueError):save_reviewed_boxes(self.root,self.row,boxes,replace_existing=True)
        self.assertEqual(self.label.read_bytes(),before)

    def test_stale_image_or_manifest_cannot_be_edited(self):
        for row in (dict(self.row,png_sha256='b'*64),dict(self.row,frame='2')):
            with self.assertRaises(ValueError):save_reviewed_boxes(self.root,row,[self.box])
        self.assertFalse(self.label.exists())

    def test_backup_symlink_cannot_be_used(self):
        save_reviewed_boxes(self.root,self.row,[self.box]);before=self.label.read_bytes()
        (self.root/'annotation_backups').symlink_to(self.root.parent,target_is_directory=True)
        with self.assertRaises(ValueError):save_reviewed_boxes(self.root,self.row,[(.4,.5,.2,.2)],replace_existing=True)
        self.assertEqual(self.label.read_bytes(),before)

    def test_skip_after_redraw_keeps_old_label_and_review(self):
        save_reviewed_boxes(self.root,self.row,[self.box])
        before=(self.label.read_bytes(),(self.root/'reviews.csv').read_bytes())
        argv=['annotate_cone_dataset.py','--dataset',str(self.root),'--edit-existing','--image',self.row['image']]
        with patch.object(sys,'argv',argv),patch('annotate_cone_dataset.cv2.imshow'),patch('annotate_cone_dataset.cv2.destroyAllWindows'),\
             patch('annotate_cone_dataset.cv2.selectROIs',return_value=[(10,10,30,20)]),\
             patch('annotate_cone_dataset.wait_choice',side_effect=[ord('p'),ord('r'),ord('s')]):
            main()
        self.assertEqual((self.label.read_bytes(),(self.root/'reviews.csv').read_bytes()),before)

    def test_visual_import_duplicate_is_refused_before_write(self):
        source=self.root.parent/'import.csv'
        write_csv(source,[dict(image=self.row['image'],status='positive',boxes_xyxy_json=json.dumps([[10,10,30,30]]*2),note='synthetic')])
        with self.assertRaisesRegex(ValueError,'duplicate visual'):import_visual_reviews(self.root,source)
        self.assertFalse(self.label.exists())


if __name__=='__main__':unittest.main()
