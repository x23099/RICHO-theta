import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch
import cv2
import numpy as np
import extract_review as study
from fisheye_intrinsic_calibration import Board,SCREEN,corner_rms,partition_views,fit_candidate


class TargetSelectionTests(unittest.TestCase):
    def setUp(self):
        self.board=Board(square_mm=20.)
        self.image=np.full((720,1280,3),128,np.uint8)

    def grid(self,centre=(330,330),step=12):
        p=np.mgrid[0:9,0:6].T.reshape(-1,2).astype(np.float32)
        p=(p-[4,2.5])*step+centre
        return p.astype(np.float32).reshape(-1,1,2)

    def inspect(self,corners,found=True):
        with patch.object(study.cv2,'findChessboardCornersSB',return_value=(found,corners)):
            return study.inspect(self.image,self.board)

    def test_fixed_window_excluded_before_spacing_or_retention(self):
        r=self.inspect(self.grid((200,260),4))
        self.assertTrue(r['detected'])
        self.assertTrue(r['excluded_fixed_window'])
        self.assertFalse(r['eligible'])
        self.assertEqual(r['reason'],'stationary_window_or_ambiguous_overlap')

    def test_moving_target_elsewhere_eligible_but_needs_review(self):
        r=self.inspect(self.grid())
        self.assertTrue(r['eligible'])
        self.assertEqual(r['reason'],'handheld_candidate_needs_native_review')
        self.assertAlmostEqual(r['median_spacing_px'],12.)

    def test_large_foreground_not_rejected_for_covering_background(self):
        r=self.inspect(self.grid((330,330),28))
        self.assertTrue(r['eligible'])
        self.assertFalse(r['excluded_fixed_window'])

    def test_small_grid_not_upsampled_into_valid_observation(self):
        r=self.inspect(self.grid(step=5))
        self.assertEqual(r['reason'],'grid_too_small')
        self.assertFalse(r['eligible'])
        self.assertEqual(len(r['corners_native']),54)

    def test_no_detection_not_fabricated(self):
        r=self.inspect(None,False)
        self.assertEqual(r['reason'],'board_not_found')
        self.assertIsNone(r['corners_native'])

    def test_native_contract_and_no_mutation(self):
        original=self.image.copy()
        self.inspect(self.grid())
        np.testing.assert_array_equal(original,self.image)
        with self.assertRaises(ValueError):
            study.inspect(self.image[:600],self.board)

    def test_invalid_or_other_lens_points_rejected(self):
        self.assertEqual(self.inspect(self.grid((900,300)))['reason'],'roi_edge_or_invalid_grid')
        p=self.grid()
        p[0,0,0]=np.nan
        self.assertEqual(self.inspect(p)['reason'],'roi_edge_or_invalid_grid')


class SavedRealStudyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder=Path(__file__).resolve().parent
        cls.intake=json.loads((cls.folder/'intake_summary.json').read_text())
        cls.extraction=json.loads((cls.folder/'extraction_r01/observations.json').read_text())

    def test_archive_and_complete_native_capture(self):
        self.assertEqual(self.intake['frames'],2844)
        self.assertEqual(self.intake['integrity']['decision'],'PASS')
        for p,digest in self.intake['source_sha256'].items():
            self.assertEqual(study.sha256(Path(p)),digest,p)

    def test_source_hashes_and_measured_size(self):
        self.assertEqual(self.extraction['board']['square_mm'],20.)
        self.assertEqual(self.extraction['image_size'],[1280,720])
        self.assertEqual(self.extraction['selected_lens'],'front_left')
        self.assertFalse(self.extraction['source_pixels_edited'])
        self.assertFalse(self.extraction['usable_for_ffb'])
        for p,digest in self.extraction['source_sha256'].items():
            self.assertEqual(study.sha256(Path(p)),digest,p)

    def test_dense_initial_and_regular_full_video_sampling(self):
        expected=[i for i in range(1,2845) if i<=150 or (i-1)%5==0]
        self.assertEqual([r['frame'] for r in self.extraction['attempts']],expected)
        self.assertEqual(self.extraction['frames_decoded'],2844)

    def test_all_retained_are_distinct_and_not_fixed_window(self):
        views=self.extraction['retained_views']
        for i,r in enumerate(views):
            self.assertFalse(r['excluded_fixed_window'])
            self.assertTrue(r['eligible'])
            self.assertGreaterEqual(r['median_spacing_px'],SCREEN['min_grid_spacing_px'])
            for old in views[:i]:
                self.assertGreaterEqual(corner_rms(np.asarray(r['corners_native']),np.asarray(old['corners_native'])),SCREEN['duplicate_rms_px'])

    def test_all_native_review_pngs_unchanged(self):
        cap=cv2.VideoCapture(str(Path(self.intake['session'])/'raw.avi'))
        selected={r['frame']:r for r in self.extraction['retained_views']}
        try:
            for i in range(1,2845):
                ok,image=cap.read()
                self.assertTrue(ok)
                if i in selected:
                    r=selected[i]
                    p=self.folder/'extraction_r01'/r['native_png']
                    self.assertEqual(study.sha256(p),r['png_sha256'])
                    np.testing.assert_array_equal(cv2.imread(str(p)),image)
                    self.assertEqual(hashlib.sha256(image.tobytes()).hexdigest(),r['decoded_bgr_sha256'])
        finally:
            cap.release()

    def test_insufficient_views_refused_without_fit(self):
        if len(self.extraction['retained_views'])<SCREEN['min_views']:
            with patch('fisheye_intrinsic_calibration.cv2.fisheye.calibrate') as solver:
                with self.assertRaises(ValueError):
                    fit_candidate([np.asarray(r['corners_native']) for r in self.extraction['retained_views']],Board(square_mm=20.))
                solver.assert_not_called()
            self.assertEqual(self.extraction['decision'],'NO_FIT_INSUFFICIENT_OBSERVATIONS')
            self.assertFalse(self.extraction['prefit_checks']['enough_views'])
            self.assertEqual(self.extraction['train_indices'],[])
            self.assertEqual(self.extraction['validation_indices'],[])


if __name__=='__main__':
    unittest.main()
