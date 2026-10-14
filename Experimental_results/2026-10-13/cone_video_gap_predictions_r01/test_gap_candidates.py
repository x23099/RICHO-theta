"""Regression checks for the hash-bound selected-frame review, no GPU/GT interpolation."""
import copy
import json
from pathlib import Path
import unittest

from analyze_gap_candidates import read_csv, review_candidates


class GapCandidateReviewTest(unittest.TestCase):
    def setUp(self):
        root=Path(__file__).resolve().parent
        self.manifest=read_csv(root.parent/'cone_video_b_r01/raw_review_manifest.csv')
        self.predictions=read_csv(root/'predictions.csv')
        self.catalog=json.loads((root/'review_catalog.json').read_text())

    def run_review(self):
        return review_candidates(self.manifest,self.predictions,self.catalog)

    def test_actual_selected_review_counts(self):
        reviewed,points,summaries=self.run_review()
        self.assertEqual(len(reviewed),33);self.assertEqual(len(points),12)
        self.assertEqual([(r['candidates'],r['zero_examples_with_red_overlap'],r['noncone_hand_candidates'])
                          for r in summaries],[(33,9,2),(18,9,1),(2,0,0)])
        self.assertTrue(all(r['geometry_accuracy']=='unmeasured' and not r['ground_contact_validated'] for r in points))
        self.assertEqual([r['frame'] for r in points if not r['zero_output_example']],[4553,4554])

    def test_noncone_top_candidate_not_substituted_for_red(self):
        _,points,_=self.run_review()
        row=next(r for r in points if r['frame']==3213)
        self.assertEqual(row['selected_red_score'],'')
        self.assertEqual(row['selected_red_candidate_index'],'')

    def test_missing_and_duplicate_review_refused(self):
        self.catalog['frames'].pop()
        with self.assertRaises(ValueError): self.run_review()
        self.catalog['frames'].append(copy.deepcopy(self.catalog['frames'][0]))
        with self.assertRaises(ValueError): self.run_review()

    def test_unreviewed_candidate_above_floor_refused(self):
        del self.catalog['frames'][0]['roles']['1']
        with self.assertRaises(ValueError): self.run_review()

    def test_invalid_role_refused(self):
        self.catalog['frames'][0]['roles']['0']='true_positive'
        with self.assertRaises(ValueError): self.run_review()

    def test_invalid_selected_candidate_refused(self):
        self.catalog['frames'][0]['red_candidate_index']=1
        with self.assertRaises(ValueError): self.run_review()

    def test_unknown_and_duplicate_prediction_refused(self):
        self.predictions.append(dict(self.predictions[0],image='unknown.png'))
        with self.assertRaises(ValueError): self.run_review()
        self.predictions[-1]=dict(self.predictions[0])
        with self.assertRaises(ValueError): self.run_review()


if __name__=='__main__':unittest.main()
