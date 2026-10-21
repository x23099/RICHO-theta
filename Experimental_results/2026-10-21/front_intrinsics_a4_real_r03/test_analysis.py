import hashlib
import json
import math
from pathlib import Path
import sys
import unittest

import cv2
import numpy as np

from merge_and_fit import merge_views,merge_sources
from initialization_diagnosis import fit_from_initial,initial_angles
from fisheye_intrinsic_calibration import fit_candidate,Board,coverage,FRONT_ROI,partition_views

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
sys.path.insert(0,str(ROOT/'tests'))
from test_fisheye_intrinsic_calibration import synthetic_views


class AnalysisTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cv2.setNumThreads(1)
        cls.combined=json.loads((HERE/'combined_candidate_r01/merged_observations.json').read_text())

    def test_real_sources_keep_session_and_frame_identity(self):
        rows=self.combined['selected_views']
        self.assertEqual(len(rows),57)
        self.assertEqual([r['source_frame'] for r in rows[-3:]],[2761,2771,2786])
        self.assertTrue(all(r['session']=='front_intrinsics_a4_real_r02' for r in rows[:54]))
        self.assertTrue(all(r['session']=='front_intrinsics_a4_real_r03' for r in rows[54:]))
        self.assertEqual(len({(r['session'],r['source_frame']) for r in rows}),57)

    def test_original_r02_split_is_preserved(self):
        old=json.loads((HERE.parent/'front_intrinsics_a4_real_r02/extraction_r01/observations.json').read_text())
        self.assertEqual([i for i in self.combined['validation_indices'] if i<54],old['validation_indices'])
        self.assertEqual(self.combined['validation_indices'][-1],54)
        self.assertEqual([i for i in self.combined['train_indices'] if i>=54],[55,56])

    def test_new_coverage_matches_pre_fit_checks(self):
        rows=self.combined['selected_views']
        c=coverage([np.asarray(rows[i]['corners_native']) for i in self.combined['train_indices']],FRONT_ROI)
        self.assertEqual(c,self.combined['train_coverage'])
        self.assertEqual(c['centre_bins'],4)
        self.assertGreater(c['span_fraction_y'],.50)
        self.assertTrue(all(self.combined['prefit_checks'].values()))

    def test_conflicting_source_hash_is_not_silently_replaced(self):
        sources={'file':'first'}
        with self.assertRaisesRegex(ValueError,'inconsistent'):
            merge_sources(sources,{'file':'different'})

    def test_global_duplicate_preserves_source_priority(self):
        data=json.loads((HERE/'extraction_r01/observations.json').read_text())
        sample=dict(data,retained_views=[dict(data['retained_views'][0],retained_index=0)])
        rows,decisions=merge_views([('first',Path('/first/observations.json'),sample),
                                   ('second',Path('/second/observations.json'),sample)])
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['session'],'first')
        self.assertFalse(decisions[-1]['selected'])

    def test_native_r03_images_are_full_size_and_hash_identical(self):
        data=json.loads((HERE/'extraction_r01/observations.json').read_text())
        for row in data['retained_views']:
            path=HERE/'extraction_r01'/row['native_png']
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),row['png_sha256'])
            image=cv2.imread(str(path))
            self.assertEqual(image.shape,(720,1280,3))
            self.assertEqual(hashlib.sha256(image.tobytes()).hexdigest(),row['decoded_bgr_sha256'])

    def test_initial_angle_issue_is_model_assumption_not_physical_measurement(self):
        row=self.combined['selected_views'][55]
        f=640/math.pi
        K=np.array([[f,0,319.5],[0,f,359.5],[0,0,1.]])
        self.assertGreater(initial_angles(row['corners_native'],K).max(),90.)
        K[1,2]=300.
        self.assertLess(initial_angles(row['corners_native'],K).max(),80.)

    def test_diagnostic_equations_match_core_on_synthetic_observations(self):
        board,_,_,views=synthetic_views()
        f=640/math.pi
        K=np.array([[f,0,319.5],[0,f,359.5],[0,0,1.]])
        baseline=fit_candidate(views,board)
        diagnostic=fit_from_initial(views,board,K)
        for key in ['K','D','calibration_rms_px','pose_validation_rms_px','normal_spread_deg']:
            np.testing.assert_allclose(diagnostic[key],baseline[key],rtol=1e-9,atol=1e-9)
        self.assertEqual(diagnostic['checks'],baseline['checks'])
        self.assertEqual(diagnostic['flags'],baseline['flags'])
        self.assertFalse(diagnostic['usable_for_ffb'])


if __name__=='__main__':
    unittest.main()
