from collections import Counter
import json
from pathlib import Path
import unittest

import numpy as np

from analyze import HERE,BANDS,SUPPORT,MODES,overlap_evidence,reference_filter
from cone_dataset import read_csv,sha256


class OverlapTests(unittest.TestCase):
    def box(self,**kw):return dict(prediction_index=0,x1=100,y1=300,x2=120,y2=400,**kw)
    def test_actual_support_not_endpoint_rectangle_controls_overlap(self):
        r=overlap_evidence([[90,310],[110,350],[130,390]],[self.box()])
        self.assertTrue(r['object_overlap']);self.assertEqual(r['overlap_pixels'],1)
    def test_one_observed_point_is_enough_and_closed_boundary_is_counted(self):
        r=overlap_evidence([[100,300],[90,290]],[self.box()])
        self.assertTrue(r['object_overlap']);self.assertEqual(r['overlap_pixels'],1)
    def test_no_prediction_is_not_an_invented_mask(self):
        r=overlap_evidence([[110,350]],[])
        self.assertFalse(r['object_overlap']);self.assertEqual(r['matched_prediction_indices_json'],'[]')
    def test_union_does_not_count_the_same_pixel_twice(self):
        box=self.box();other=dict(box,prediction_index=1)
        r=overlap_evidence([[110,350]],[box,other])
        self.assertEqual(r['overlap_pixels'],1);self.assertEqual(json.loads(r['matched_prediction_indices_json']),[0,1])
    def test_invalid_native_support_and_boxes_are_refused(self):
        for p in ([],[[np.nan,310]],[[10.5,310]],[[-1,310]],[[1280,310]]):
            with self.assertRaises(ValueError):overlap_evidence(p,[])
        with self.assertRaises(ValueError):overlap_evidence([[110,350]],[dict(self.box(),x2=90)])
    def test_metric_labels_do_not_enter_overlap(self):
        a=self.box();b=dict(a,reference_z_m=-999,real_height_m=999)
        self.assertEqual(overlap_evidence([[110,350]],[a]),overlap_evidence([[110,350]],[b]))
    def test_reference_filter_uses_pre_dedup_candidates(self):
        upper=[dict(normal=[1,0,0])]
        a=np.deg2rad(3);lower=[dict(normal=[np.cos(a),0,np.sin(a)])]
        b=np.deg2rad(2);extra=dict(normal=[np.cos(b),0,np.sin(b)])
        kept,rejected=reference_filter(upper,lower,[*upper,extra])
        self.assertEqual(kept,upper);self.assertEqual(rejected,lower)


class SavedObjectTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.output=HERE/'results_r01';cls.summary=json.loads((cls.output/'summary.json').read_text())
        cls.frames=read_csv(cls.output/'image_diagnostics.csv');cls.masks=read_csv(cls.output/'line_object_overlap.csv')
    def test_frozen_sources_and_outputs(self):
        for p,h in self.summary['source_sha256'].items():self.assertEqual(sha256(Path(p)),h,p)
        for name,h in self.summary['output_sha256'].items():self.assertEqual(sha256(self.output/name),h,name)
    def test_all_four_modes_keep_every_image(self):
        self.assertEqual(len(self.frames),1968)
        self.assertEqual(Counter(r['mode'] for r in self.frames),{m:492 for m in MODES})
    def test_prediction_coverage_is_explicit_not_inferred_from_empty_boxes(self):
        rows=read_csv(self.output/'bbox_coverage.csv')
        self.assertEqual(sum(r['saved_prediction_frame_present']=='True' for r in rows),176)
        self.assertEqual(sum(r['state']=='unavailable' for r in rows),316)
        self.assertTrue(any(r['state']=='saved_zero_predictions_NOT_ground_truth_absence' for r in rows))
    def test_unavailable_stream_is_withheld_in_object_modes(self):
        rows=[r for r in self.frames if r['mode'] in ('object_screen','object_and_reference') and r['bbox_stream_available']=='False']
        self.assertEqual(len(rows),632)
        self.assertTrue(all(r['accepted']=='False' and r['reason']=='saved_bbox_stream_unavailable' for r in rows))
    def test_original_and_previous_reference_controls_reproduce(self):
        old={(r['session'],r['frame']):r for r in read_csv(BANDS/'results_r01/image_diagnostics.csv') if r['mode']=='late_fusion'}
        ref={(r['session'],r['frame']):r for r in read_csv(SUPPORT/'results_r01/counterfactual_images.csv')}
        for r in self.frames:
            if r['mode'] not in ('original_fusion','reference_screen'):continue
            expected=(old if r['mode']=='original_fusion' else ref)[r['session'],r['frame']]
            for k in ('accepted','reason','inliers','up_optical_json'):self.assertEqual(r[k],expected[k])
    def test_no_object_overlapping_vote_survives_screened_modes(self):
        masks={(r['session'],r['frame'],r['band'],r['line_index'],r['part']):r for r in self.masks}
        for r in read_csv(self.output/'mode_vote_ledger.csv'):
            if r['mode'] in ('object_screen','object_and_reference'):
                mask=masks[r['session'],r['frame'],r['band'],r['line_index'],r['part']]
                self.assertEqual(mask['object_overlap'],'False')
    def test_any_point_overlap_flags_reconcile(self):
        for r in self.masks:
            self.assertEqual(r['object_overlap']=='True',int(r['overlap_pixels'])>0)
            self.assertLessEqual(int(r['overlap_pixels']),int(r['support_pixels']))
    def test_only_temporal_candidates_no_tf_or_metric_approval(self):
        rows=read_csv(self.output/'session_hypotheses.csv');self.assertEqual(len(rows),36)
        self.assertTrue(all('conditional_transform' not in r and 'metric_eligible' not in r for r in rows))
        self.assertTrue(all(r['usable_for_ffb']=='False' for r in rows))
    def test_no_inference_metric_labels_or_hardware_changes(self):
        for field in ('metric_labels_used','new_model_inference','source_images_edited','production_settings_changed','physical_output','usable_for_ffb'):
            self.assertFalse(self.summary[field])


class ReportTests(unittest.TestCase):
    def test_report_hashes(self):
        output=HERE/'report_r01';d=json.loads((output/'summary.json').read_text())
        for p,h in d['source_sha256'].items():self.assertEqual(sha256(Path(p)),h,p)
        for name,h in d['output_sha256'].items():self.assertEqual(sha256(output/name),h,name)
    def test_eight_suspected_cone_supports_overlap_saved_boxes(self):
        rows=read_csv(HERE/'report_r01/previous_new_lower_support_screen.csv')
        selected=[r for r in rows if r['session'].startswith('one_static_center_z0p80') and json.loads(r['lower_first_native_json'])[0]>=300]
        self.assertEqual(len(selected),8)
        self.assertTrue(all(r['object_overlap']=='True' for r in selected))
    def test_common_denominator_is_shown_for_all_controls(self):
        rows=read_csv(HERE/'report_r01/mode_comparison.csv');self.assertEqual(len(rows),4)
        self.assertTrue(all(r['images_with_saved_bbox_stream']=='176' for r in rows))
        self.assertTrue(all(r['bbox_stream_unsupported_images']=='316' for r in rows))


if __name__=='__main__':unittest.main()
