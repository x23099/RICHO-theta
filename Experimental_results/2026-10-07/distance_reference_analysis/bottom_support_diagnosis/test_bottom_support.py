import unittest
import numpy as np
import analyze_bottom_support as analysis

P=dict(camera_height=.58,radius_scale=.86,front_cx_offset=-80,front_cy_offset=-21,pitch_deg=1,roll_deg=2)


class SupportTests(unittest.TestCase):
    def test_bottom_points_keep_holes_and_spatial_thirds(self):
        mask=np.zeros((5,12),np.uint8)
        mask[1,:]=255;mask[3,::2]=255;mask[:,5]=0
        points,zones=analysis.bottom_columns(dict(mask=mask,origin=(300,420)),1.)
        self.assertEqual(len(points),11)
        self.assertNotIn(305,points[:,0])
        self.assertTrue(np.array_equal(points[0],[300,423]))
        self.assertEqual(list(zones[:4]),[0,0,0,0])
        self.assertEqual(list(zones[-4:]),[2,2,2,2])

    def test_no_component_is_missing_not_zero_distance(self):
        points,zones=analysis.bottom_columns(None,.8)
        self.assertEqual(points.shape,(0,2))
        self.assertIsNone(analysis.project_columns(points,zones,P,(720,1280,3)))
        self.assertEqual(analysis.support_statistics(points,points,1.1),dict(points=0))

    def test_fraction_margin_matches_frozen_estimator(self):
        points,_=analysis.bottom_columns(dict(mask=np.ones((3,10),np.uint8),origin=(300,420)),.8)
        # Use the same floating-point floor rule as the existing estimator.
        margin=int(np.floor(10*(1-.8)/2))
        self.assertEqual(points[0,0],300+margin)
        self.assertEqual(points[-1,0],309-margin)

    def test_projection_preserves_zone_alignment_when_lens_filters_pixels(self):
        points=np.array([[0.,0.],[310.,432.],[312.,432.],[314.,432.],[316.,432.]])
        zones=np.array([2,0,0,1,2])
        pixels,ground,aligned=analysis.project_columns(points,zones,P,(720,1280,3))
        self.assertEqual(len(ground),4)
        self.assertEqual(list(aligned),[0,0,1,2])
        self.assertTrue((pixels[:,1]==432).all())

    def test_envelope_and_nearest_gap_do_not_select_by_reference(self):
        pixels=np.array([[300.,432.],[301.,432.],[302.,432.]])
        ground=np.array([[0.,1.02],[0.,1.03],[0.,1.04]])
        before=ground.copy()
        a=analysis.support_statistics(pixels,ground,1.1)
        b=analysis.support_statistics(pixels,ground,1.03)
        self.assertEqual(a['nominal_inside_point_envelope'],0)
        self.assertAlmostEqual(a['nearest_support_gap_m'],.06)
        self.assertEqual(b['nominal_inside_point_envelope'],1)
        self.assertEqual(a['z_median_m'],b['z_median_m'])
        self.assertTrue(np.array_equal(before,ground))

    def test_mismatched_points_and_zones_rejected(self):
        with self.assertRaises(ValueError):
            analysis.project_columns(np.array([[310,432]]),np.array([]),P,(720,1280,3))

    def test_summary_does_not_use_first_two_seconds(self):
        base=dict(condition='z1p10',zone='all',points=3,z_median_m=1.03,z_min_m=1.02,z_max_m=1.04,
                  nominal_inside_point_envelope=0,nearest_support_gap_m=.06)
        rows=[dict(base,time_sec=1.,z_median_m=99.),dict(base,time_sec=2.)]
        summary=analysis.summarize(rows)[0]
        self.assertEqual(summary['frames'],1)
        self.assertAlmostEqual(summary['z_median_over_frames_m'],1.03)


if __name__=='__main__':
    unittest.main()
