"""Synthetic train-only mining, label gating and protected-val merge tests."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

import cv2
import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from cone_dataset import dataset_yaml, label_path, read_csv, sha256, validate, write_csv
from prepare_cone_training_review import (apply_selection_policy,candidate_features, manifest_tables, merge_reviewed_queue,
                                         pending_train_inventory, prepare_queue, select_queue)


class ConeTrainingReviewTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.dev=self.root/'dev';self.baseline=self.root/'baseline'
        self.rows=[]
        for name,split,group,frame,value in [('t1','train','a',1,30),('t2','train','a',31,90),('v1','val','b',1,150)]:
            pixels=np.full((72,128,3),value,np.uint8)
            path=self.dev/f'images/{split}/{name}.png';path.parent.mkdir(parents=True,exist_ok=True)
            cv2.imwrite(str(path),pixels)
            self.rows.append(dict(image=str(path.relative_to(self.dev)),split=split,group_id=group,session=group,
                frame=str(frame),time_sec=str(frame/30),width='128',height='72',
                png_sha256=sha256(path),decoded_bgr_sha256=hashlib.sha256(pixels.tobytes()).hexdigest(),
                source_raw_sha256=group*64))
        self.write_dataset(self.dev,self.rows,pending={'t2'})
        for row in (self.rows[0],self.rows[2]):
            path=self.baseline/row['image'];path.parent.mkdir(parents=True,exist_ok=True)
            path.write_bytes((self.dev/row['image']).read_bytes())
        self.write_dataset(self.baseline,[self.rows[0],self.rows[2]])
        self.pool=self.root/'pool';self.inference=self.root/'inference';self.queue=self.root/'queue'

    def write_dataset(self,root,rows,pending=()):
        write_csv(root/'manifest.csv',rows)
        reviews=[]
        for row in rows:
            label=label_path(root,row['image']);label.parent.mkdir(parents=True,exist_ok=True)
            unreviewed=Path(row['image']).stem in pending
            if not unreviewed:label.write_text('0 0.5 0.5 0.2 0.2\n')
            reviews.append(dict(image=row['image'],status='pending' if unreviewed else 'positive',
                note='' if unreviewed else 'human full-frame review: synthetic test only',
                label_sha256='' if unreviewed else sha256(label)))
        write_csv(root/'reviews.csv',reviews)
        (root/'dataset.json').write_text(json.dumps(dict(schema_version=1,classes=['traffic_cone'],
            development_only=True,available_splits=['train','val'],manifest_sha256=sha256(root/'manifest.csv'),sources=[])))
        (root/'data.yaml').write_text(dataset_yaml(root,development_only=True))

    def make_queue(self):
        rows=pending_train_inventory(self.dev,self.baseline)
        self.pool.mkdir();self.inference.mkdir()
        write_csv(self.pool/'candidate_manifest.csv',rows)
        digest=sha256(self.pool/'candidate_manifest.csv')
        (self.pool/'inventory.json').write_text(json.dumps(dict(manifest_sha256=digest,reference_dataset=str(self.baseline),
            input_sha256={str(root/name):sha256(root/name) for root in (self.dev,self.baseline)
                          for name in ('manifest.csv','reviews.csv','dataset.json')})))
        (self.inference/'provenance.json').write_text(json.dumps(dict(manifest_sha256=digest,input_dir=str(self.dev),
            status='COMPLETED_SYNTHETIC',weights_sha256='c'*64)))
        (self.inference/'summary.json').write_text(json.dumps(dict(status='COMPLETED_SYNTHETIC',images=len(rows),predictions=0)))
        write_csv(self.inference/'predictions.csv',[],('image','prediction_index','class_id','confidence','x1','y1','x2','y2'))
        return prepare_queue(self.dev,self.pool,self.inference,self.queue,16,2.)

    def approve_synthetic_queue(self):
        row=read_csv(self.queue/'manifest.csv')[0]
        label=label_path(self.queue,row['image']);label.write_text('0 0.5 0.5 0.2 0.2\n')
        write_csv(self.queue/'reviews.csv',[dict(image=row['image'],status='positive',
            note='human full-frame review: SYNTHETIC TEST ONLY',label_sha256=sha256(label))])

    def test_pool_only_new_pending_train(self):
        rows=pending_train_inventory(self.dev,self.baseline)
        self.assertEqual([r['file'] for r in rows],['images/train/t2.png'])
        self.assertTrue(all(r['split']=='train' for r in rows))

    def test_pending_existing_label_refused(self):
        label_path(self.dev,self.rows[1]['image']).write_text('')
        with self.assertRaisesRegex(ValueError,'existing label'):pending_train_inventory(self.dev,self.baseline)

    def test_source_split_leakage_refused(self):
        rows=[dict(r) for r in self.rows];rows[1]['source_raw_sha256']='b'*64
        self.write_dataset(self.dev,rows,pending={'t2'})
        with self.assertRaises(ValueError):pending_train_inventory(self.dev,self.baseline)

    def test_stale_manifest_and_review_table_refused(self):
        (self.dev/'manifest.csv').write_text('invalid\n')
        with self.assertRaises(ValueError):manifest_tables(self.dev)
        self.write_dataset(self.dev,self.rows,pending={'t2'})
        write_csv(self.dev/'reviews.csv',read_csv(self.dev/'reviews.csv')[:-1])
        with self.assertRaises(ValueError):manifest_tables(self.dev)

    def test_empty_model_output_is_not_a_negative_label(self):
        self.make_queue()
        self.assertEqual(read_csv(self.queue/'reviews.csv')[0]['status'],'pending')
        self.assertFalse(list((self.queue/'labels').rglob('*.txt')))
        self.assertFalse((self.queue/'data.yaml').exists())
        self.assertEqual((self.queue/'images/train/t2.png').read_bytes(),(self.dev/'images/train/t2.png').read_bytes())
        with self.assertRaises(ValueError):validate(self.queue)

    def test_pending_merge_refused_and_no_output_created(self):
        self.make_queue();output=self.root/'merged'
        with self.assertRaisesRegex(ValueError,'human full-frame'):merge_reviewed_queue(self.queue,self.baseline,output)
        self.assertFalse(output.exists())

    def test_reviewed_merge_preserves_val_bytes_and_old_dataset(self):
        self.make_queue();self.approve_synthetic_queue()
        before=sha256(self.baseline/'manifest.csv');output=self.root/'merged'
        result=merge_reviewed_queue(self.queue,self.baseline,output)
        self.assertEqual(result['train_images_added'],1);self.assertTrue(result['val_test_unchanged'])
        self.assertEqual(result['counts']['train']['images'],2);self.assertEqual(result['counts']['val']['images'],1)
        for relative in ('images/val/v1.png','labels/val/v1.txt'):
            self.assertEqual((output/relative).read_bytes(),(self.baseline/relative).read_bytes())
        self.assertEqual(sha256(self.baseline/'manifest.csv'),before)

    def test_changed_label_after_review_refused(self):
        self.make_queue();self.approve_synthetic_queue()
        (self.queue/'labels/train/t2.txt').write_text('0 0.4 0.5 0.2 0.2\n')
        with self.assertRaises(ValueError):merge_reviewed_queue(self.queue,self.baseline,self.root/'merged')

    def test_reference_snapshot_changes_refused(self):
        self.make_queue();self.approve_synthetic_queue()
        rows=read_csv(self.baseline/'reviews.csv');rows[0]['note']='human full-frame review: changed synthetic note'
        write_csv(self.baseline/'reviews.csv',rows)
        with self.assertRaisesRegex(ValueError,'snapshot changed'):
            merge_reviewed_queue(self.queue,self.baseline,self.root/'merged')

    def test_assistant_review_not_human_confirmation(self):
        self.make_queue();self.approve_synthetic_queue()
        rows=read_csv(self.queue/'reviews.csv');rows[0]['note']='assistant candidate suggestion'
        write_csv(self.queue/'reviews.csv',rows)
        with self.assertRaises(ValueError):merge_reviewed_queue(self.queue,self.baseline,self.root/'merged')

    def test_existing_or_overlapping_merge_output_refused(self):
        self.make_queue();self.approve_synthetic_queue()
        for target in (self.baseline,self.queue/'new',self.root):
            with self.assertRaises(ValueError):merge_reviewed_queue(self.queue,self.baseline,target)

    def test_features_are_priority_not_ground_truth(self):
        images=[dict(file='a',session='s',frame='1',time_sec='0',width='128',height='72')]
        self.assertEqual(candidate_features(images,[])[0]['priority_kind'],'zero_at_0p25')
        pred=dict(image='a',prediction_index='0',class_id='0',confidence='.9',x1='0',y1='10',x2='10',y2='40')
        self.assertEqual(candidate_features(images,[pred])[0]['priority_kind'],'edge_band_candidate')
        second=dict(pred,prediction_index='1',x1='20',x2='40')
        self.assertEqual(candidate_features(images,[pred,second])[0]['priority_kind'],'multiple_at_0p25')
        with self.assertRaises(ValueError):candidate_features(images,[pred,pred])
        with self.assertRaises(ValueError):candidate_features(images,[dict(pred,confidence='nan')])

    def test_selection_spacing_and_limits(self):
        rows=[dict(session='s',frame=i,time_sec=i,max_score=.1,priority_kind='zero_at_0p25') for i in range(10)]
        chosen=select_queue(rows,3,2)
        self.assertEqual([r['frame'] for r in chosen],[0,2,4])
        with self.assertRaises(ValueError):select_queue(rows,0,2)
        with self.assertRaises(ValueError):select_queue(rows,3,float('nan'))

    def test_policy_covers_each_image_and_uses_intact_pixel_hash(self):
        rows=pending_train_inventory(self.dev,self.baseline)
        policy=self.root/'policy.csv'
        decision=dict(image=rows[0]['image'],png_sha256=rows[0]['png_sha256'],decision='include',reason='synthetic include')
        write_csv(policy,[decision])
        selected,held=apply_selection_policy(self.dev,rows,policy)
        self.assertEqual(len(selected),1);self.assertEqual(held,[])
        for decisions in ([],[decision,decision],[dict(decision,png_sha256='c'*64)],[dict(decision,decision='hold')]):
            write_csv(policy,decisions,tuple(decision))
            with self.assertRaises(ValueError):apply_selection_policy(self.dev,rows,policy)

    def test_policy_is_recorded_in_reviewed_merge(self):
        self.make_queue();self.approve_synthetic_queue()
        row=read_csv(self.queue/'manifest.csv')[0];policy=self.root/'policy.csv'
        write_csv(policy,[dict(image=row['image'],png_sha256=row['png_sha256'],decision='include',reason='synthetic')])
        result=merge_reviewed_queue(self.queue,self.baseline,self.root/'merged',policy)
        self.assertEqual(result['train_images_added'],1);self.assertEqual(result['train_images_held'],0)
        metadata=json.loads((self.root/'merged/dataset.json').read_text())
        self.assertEqual(metadata['augmentation']['selection_policy_sha256'],sha256(policy))

    def test_held_pending_image_is_not_merged_or_assumed_negative(self):
        row=dict(self.rows[1],image='images/train/t3.png',frame='121',time_sec=str(121/30))
        pixels=np.full((72,128,3),110,np.uint8)
        cv2.imwrite(str(self.dev/row['image']),pixels)
        row.update(png_sha256=sha256(self.dev/row['image']),decoded_bgr_sha256=hashlib.sha256(pixels.tobytes()).hexdigest())
        self.rows.append(row);self.write_dataset(self.dev,self.rows,pending={'t2','t3'})
        self.make_queue()
        reviews=read_csv(self.queue/'reviews.csv');first=read_csv(self.queue/'manifest.csv')[0]
        label=label_path(self.queue,first['image']);label.write_text('0 0.5 0.5 0.2 0.2\n')
        reviews[0].update(status='positive',note='human full-frame review: synthetic',label_sha256=sha256(label))
        write_csv(self.queue/'reviews.csv',reviews)
        policy=self.root/'policy.csv'
        write_csv(policy,[dict(image=r['image'],png_sha256=r['png_sha256'],decision='include' if i==0 else 'hold',reason='synthetic')
                          for i,r in enumerate(read_csv(self.queue/'manifest.csv'))])
        result=merge_reviewed_queue(self.queue,self.baseline,self.root/'merged',policy)
        self.assertEqual(result['train_images_added'],1);self.assertEqual(result['train_images_held'],1)
        self.assertFalse((self.root/'merged'/row['image']).exists())
        self.assertEqual(read_csv(self.queue/'reviews.csv')[1]['status'],'pending')


if __name__=='__main__':unittest.main()
