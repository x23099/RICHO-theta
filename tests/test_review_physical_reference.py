"""Synthetic/native-coordinate review tests; never fabricate real human labels."""
import copy
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
import review_physical_reference as review


class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.patch=patch.object(review,'ROOT',self.root);self.patch.start();self.addCleanup(self.patch.stop)
        self.image=self.root/'decoded_test_f000001.png'
        ok,data=cv2.imencode('.png',np.zeros((720,1280,3),np.uint8));self.assertTrue(ok)
        self.image.write_bytes(data.tobytes())
        self.sha=hashlib.sha256(data.tobytes()).hexdigest()
        self.item=dict(id='paper_test',kind='paper',image=self.image.name,session='test',frame=1,
            sha256=self.sha,paper_sides_mm=[296,210])
        self.queue=dict(schema=review.QUEUE_SCHEMA,items=[self.item],**{k:False for k in review.FLAGS})
        self.spec=self.root/'spec.json';review.dump_new(self.spec,self.queue)
        self.points=[[290.,390.],[345.,390.],[345.,410.],[290.,410.]]
        self.folder=self.root/'decisions'

    def save(self,**kwargs):
        args=dict(folder=self.folder,queue_sha='a'*64,item=self.item,points=self.points,
            status='reviewed',reviewer='SYNTHETIC_TEST_NOT_HUMAN')
        args.update(kwargs);return review.save_decision(**args)

    def test_prepare_has_no_synthetic_approval_and_no_image_output(self):
        out=self.root/'prepared';before=self.image.read_bytes()
        r=review.prepare(self.spec,out)
        self.assertEqual(r['human_decisions'],0);self.assertEqual(list((out/'decisions').iterdir()),[])
        self.assertEqual(list(out.glob('*.png')),[]);self.assertEqual(before,self.image.read_bytes())
        with self.assertRaises(ValueError):review.prepare(self.spec,out)

    def test_bad_hash_frame_and_native_resolution_rejected(self):
        for key,value in [('sha256','0'*64),('frame',2),('session','other')]:
            item=dict(self.item,**{key:value})
            with self.assertRaises(ValueError):review.item_image(item)
        ok,data=cv2.imencode('.png',np.zeros((360,640,3),np.uint8));self.assertTrue(ok)
        self.image.write_bytes(data.tobytes())
        with self.assertRaises(ValueError):review.item_image(self.item)

    def test_path_escape_and_symlink_rejected(self):
        for path in ['../decoded_test_f000001.png',str(self.image)]:
            with self.assertRaises(ValueError):review.item_image(dict(self.item,image=path))
        link=self.root/'decoded_test_f000002.png';link.symlink_to(self.image)
        with self.assertRaises(ValueError):review.item_image(dict(self.item,image=link.name,frame=2))

    def test_duplicate_unknown_kind_and_authority_in_queue_rejected(self):
        bad=copy.deepcopy(self.queue);bad['items'].append(copy.deepcopy(self.item))
        with self.assertRaises(ValueError):review.validate_queue(bad)
        for key,value in [('kind','vehicle'),('id','../escape')]:
            bad=copy.deepcopy(self.queue);bad['items'][0][key]=value
            with self.assertRaises(ValueError):review.validate_queue(bad)
        for flag in review.FLAGS:
            with self.assertRaises(ValueError):review.validate_queue(dict(self.queue,**{flag:True}))

    def test_paper_order_and_native_coordinates(self):
        self.assertEqual(review.checked_points(self.points,'paper'),self.points)
        for points in [self.points[::-1],self.points[:3],[[True,390],*self.points[1:]],
                [[float('nan'),390],*self.points[1:]],[[650.,390],*self.points[1:]],
                [self.points[0],self.points[0],*self.points[2:]]]:
            with self.assertRaises(ValueError):review.checked_points(points,'paper')

    def test_cone_endpoints_are_not_automatic_midpoint(self):
        self.assertEqual(review.checked_points([[300,415],[340,417]],'cone_near_edge'),[[300,415],[340,417]])
        with self.assertRaises(ValueError):review.checked_points([[340,417],[300,415]],'cone_near_edge')
        with self.assertRaises(ValueError):review.checked_points([[300,415],[340,417],[320,416]],'cone_near_edge')

    def test_visual_record_no_metric_or_contact_authority(self):
        r=self.save()
        self.assertEqual(r['side_assignment'],'unknown')
        self.assertFalse(r['independently_surveyed_ground_truth'])
        self.assertTrue(all(r[k] is False for k in review.FLAGS))
        self.assertEqual(self.sha,review.digest(self.image))

    def test_unclear_discards_guesses_and_dimension_claims(self):
        r=self.save(status='unclear',side_assignment='long_01')
        self.assertEqual(r['points_native_xy'],[]);self.assertEqual(r['side_assignment'],'unknown')
        r['points_native_xy']=self.points
        with self.assertRaises(ValueError):review.validate_decision(r,self.item,'a'*64)

    def test_immutable_save_and_alternate_review_directory(self):
        r=self.save();before=(self.folder/'paper_test.json').read_bytes()
        self.assertEqual(self.save(),r)
        with self.assertRaises(ValueError):self.save(side_assignment='long_01')
        self.assertEqual(before,(self.folder/'paper_test.json').read_bytes())
        self.save(folder=self.root/'new_decisions',side_assignment='long_01')

    def test_changed_image_cannot_accept_old_clicks(self):
        self.image.write_bytes(b'not PNG')
        with self.assertRaises(ValueError):self.save()
        self.assertFalse(self.folder.exists())

    def test_decision_identity_and_false_claims_rejected(self):
        r=self.save()
        for key,value in [('queue_sha256','b'*64),('session','other'),('frame',2),
                ('physical_metric_verified',True),('reviewer',''),('confirmation_method','automatic'),
                ('independently_surveyed_ground_truth',True)]:
            with self.assertRaises(ValueError):review.validate_decision(dict(r,**{key:value}),self.item,'a'*64)

    def test_decision_folder_unknown_item_and_symlink_rejected(self):
        r=self.save()
        self.assertEqual(len(review.load_decisions(self.folder,self.queue,'a'*64)),1)
        review.dump_new(self.folder/'unknown.json',r)
        with self.assertRaises(ValueError):review.load_decisions(self.folder,self.queue,'a'*64)
        link=self.root/'linked_decisions';link.symlink_to(self.folder,target_is_directory=True)
        with self.assertRaises(ValueError):review.load_decisions(link,self.queue,'a'*64)

    def test_pending_and_unclear_report_never_fit(self):
        pending=review.report(self.spec,self.folder,self.root/'report1')
        self.assertEqual(pending['counts'],dict(pending=1));self.assertIsNone(pending['selected_model'])
        self.save(queue_sha=review.digest(self.spec),status='unclear')
        unclear=review.report(self.spec,self.folder,self.root/'report2')
        self.assertEqual(unclear['counts'],dict(unclear=1))
        self.assertNotIn('unselected_paper_hypotheses',unclear['items'][0])

    def test_unknown_dimension_keeps_both_without_selecting_height_match(self):
        self.save(queue_sha=review.digest(self.spec))
        r=review.report(self.spec,self.folder,self.root/'report')
        self.assertEqual(len(r['items'][0]['unselected_paper_hypotheses']),2)
        self.assertIsNone(r['selected_model']);self.assertFalse(r['usable_for_ffb'])
        self.assertEqual(list((self.root/'report').glob('*.png')),[])

    def test_explicit_dimension_has_only_that_correspondence_but_keeps_planar_solutions(self):
        self.save(queue_sha=review.digest(self.spec),side_assignment='long_01')
        r=review.report(self.spec,self.folder,self.root/'report')
        hypotheses=r['items'][0]['unselected_paper_hypotheses']
        self.assertEqual(len(hypotheses),1)
        self.assertEqual(hypotheses[0]['side_assignment'],'long_01')
        self.assertEqual(hypotheses[0]['pose']['solution_count'],2)

    def test_zoom_coordinate_mapping_remains_native(self):
        import matplotlib
        matplotlib.use('Agg',force=True)
        from matplotlib.figure import Figure
        from matplotlib.backends.backend_agg import FigureCanvasAgg
        fig=Figure(figsize=(8,5));FigureCanvasAgg(fig);ax=fig.subplots()
        ax.imshow(np.zeros((720,1280,3),np.uint8));ax.set_xlim(280,360);ax.set_ylim(435,390)
        fig.canvas.draw()
        native=np.array([303.25,407.5]);display=ax.transData.transform(native)
        np.testing.assert_allclose(ax.transData.inverted().transform(display),native,atol=1e-10)


if __name__=='__main__':unittest.main()
