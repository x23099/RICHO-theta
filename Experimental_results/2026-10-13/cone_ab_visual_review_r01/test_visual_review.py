"""Synthetic checks for the dated visual-review aggregation; no GPU or real images."""
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('cone_visual_review', Path(__file__).with_name('analyze_visual_review.py'))
review = importlib.util.module_from_spec(spec)
spec.loader.exec_module(review)


class VisualReviewTest(unittest.TestCase):
    def setUp(self):
        self.image = 'images/val/example_f000001.png'
        self.images = [dict(image=self.image,session='synthetic',frame=1,time_sec=0)]
        self.truths = [dict(image=self.image,gt_index=0,class_id=0,x1=0.,y1=0.,x2=10.,y2=10.,
            label_sha256='synthetic',size_band='small',image_half='left',
            color='unknown',lens='unknown',occlusion='unknown')]
        self.catalog = dict(date='2026-10-13',groups=[dict(prefix='example_f',frames=[1],
            gt_colors_in_existing_label_order=['red'])],
            fp_review_at_confidence_0p05=[],fn_review_at_confidence_0p05=[])
        self.config = dict(confidence_thresholds=[.05],match_iou=.5)

    def test_explicit_color_only_assignment(self):
        result = review.review_attributes(self.catalog,self.images,self.truths)
        self.assertEqual(result[0]['color'],'red')
        self.assertEqual(result[0]['lens'],'unknown')
        self.assertEqual(result[0]['occlusion'],'unknown')
        self.assertEqual(result[0]['label_sha256'],'synthetic')
        self.assertIn('assistant',result[0]['note'])

    def test_duplicate_review_image_rejected(self):
        self.catalog['groups'][0]['frames']=[1,1]
        with self.assertRaisesRegex(ValueError,'duplicate'):
            review.review_attributes(self.catalog,self.images,self.truths)

    def test_unreviewed_image_rejected(self):
        with self.assertRaisesRegex(ValueError,'exactly'):
            review.review_attributes(self.catalog,[],self.truths)

    def test_changed_gt_order_or_count_rejected(self):
        self.truths[0]['gt_index']=2
        with self.assertRaisesRegex(ValueError,'order/count'):
            review.review_attributes(self.catalog,self.images,self.truths)

    def test_unsupported_color_rejected(self):
        self.catalog['groups'][0]['gt_colors_in_existing_label_order']=['blue']
        with self.assertRaisesRegex(ValueError,'red/yellow'):
            review.review_attributes(self.catalog,self.images,self.truths)

    def test_nonfinite_or_degenerate_bbox_rejected(self):
        for value in (float('nan'),float('inf'),0.):
            row=dict(self.truths[0],x2=value)
            with self.subTest(value=value),self.assertRaises(ValueError):
                review.numeric_rows([row],'gt_index')

    def test_wrong_class_or_confidence_rejected(self):
        for change in (dict(class_id='1'),dict(confidence='nan'),dict(confidence='1.1')):
            with self.subTest(change=change),self.assertRaises(ValueError):
                review.numeric_rows([dict(self.truths[0],**change)],'gt_index')

    def test_fp_duplicate_reports_iou_to_already_matched_gt(self):
        predictions=[dict(self.truths[0],prediction_index=0,confidence=.9),
                     dict(self.truths[0],prediction_index=1,confidence=.1)]
        self.catalog['fp_review_at_confidence_0p05']=[dict(image=self.image,prediction_index=1,
            category='duplicate_red',note='synthetic duplicate')]
        result=review.case_rows(self.catalog,self.images,self.truths,predictions,self.config)
        self.assertEqual(result[0]['best_any_gt_iou'],1.)
        self.assertEqual(result[0]['category'],'duplicate_red')

    def test_fn_reports_candidate_below_threshold(self):
        predictions=[dict(self.truths[0],prediction_index=0,confidence=.04)]
        self.catalog['fn_review_at_confidence_0p05']=[dict(image=self.image,gt_index=0,
            category='low_confidence',note='synthetic low score')]
        result=review.case_rows(self.catalog,self.images,self.truths,predictions,self.config)
        self.assertEqual(result[0]['confidence'],.04)
        self.assertEqual(result[0]['best_any_gt_iou'],1.)

    def test_missing_fp_review_rejected(self):
        predictions=[dict(self.truths[0],prediction_index=0,confidence=.9,x1=20.,x2=30.)]
        with self.assertRaisesRegex(ValueError,'FP review'):
            review.case_rows(self.catalog,self.images,self.truths,predictions,self.config)


if __name__ == '__main__':
    unittest.main()
