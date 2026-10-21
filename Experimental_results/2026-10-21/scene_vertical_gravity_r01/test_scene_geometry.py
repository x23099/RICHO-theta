import inspect
import json
from pathlib import Path
import sys
import unittest

import cv2
import numpy as np

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
sys.path.insert(0,str(ROOT/'src'))
from angular_fisheye_geometry import AngularCamera,project
from cone_dataset import read_csv,sha256
from scene_geometry import plane_from_pixels,extract_planes,infer_up,unit,angle_degrees,align_up_preserving_heading_reference
from curve_geometry import extract_curve_planes


class SceneGeometryTests(unittest.TestCase):
    def setUp(self):
        self.camera=AngularCamera([[190,0,320],[0,190,317],[0,0,1]],[-.04,.035,-.014,.001],np.deg2rad(100))
        self.T=np.eye(4);self.T[:3,:3]=[[0,0,1],[-1,0,0],[0,-1,0]];self.T[2,3]=.59

    def normals(self,g,count=12):
        g=unit(g);u=unit(np.cross(g,[0,0,1]));v=np.cross(g,u)
        angles=np.linspace(-1,1,count)
        return np.array([np.cos(a)*u+np.sin(a)*v for a in angles])

    def test_unit_refuses_nonfinite_and_zero(self):
        for v in ([0,0,0],[np.nan,1,0],[1,2]):
            with self.assertRaises(ValueError):unit(v)

    def test_synthetic_up_recovered_without_metric_data(self):
        g=unit([.06,-1,.1]);r=infer_up(self.normals(g),[0,-1,0])
        self.assertTrue(r['accepted']);np.testing.assert_allclose(r['up'],g,atol=1e-12)
        self.assertEqual(r['inliers'],12);self.assertFalse(r['usable_for_ffb'])

    def test_outlier_planes_do_not_define_consensus(self):
        g=unit([.06,-1,.1]);n=np.vstack((self.normals(g),unit([.2,.8,.3]),unit([-.3,.8,-.4])))
        r=infer_up(n,[0,-1,0]);self.assertTrue(r['accepted'])
        np.testing.assert_allclose(r['up'],g,atol=1e-12)

    def test_insufficient_planes_return_no_direction(self):
        r=infer_up(self.normals([0,-1,0])[:5],[0,-1,0])
        self.assertFalse(r['accepted']);self.assertIsNone(r['up'])
        self.assertFalse(infer_up([], [0,-1,0])['accepted'])

    def test_insufficient_diversity_return_no_direction(self):
        n=self.normals([0,-1,0])
        n=np.array([unit([1,0,.001*i]) for i in range(8)])
        self.assertFalse(infer_up(n,[0,-1,0])['accepted'])

    def test_wrong_direction_outside_prior_is_not_adopted(self):
        g=unit([0,-.5,.866]);self.assertFalse(infer_up(self.normals(g),[0,-1,0])['accepted'])

    def test_sign_is_fixed_without_yaw_or_height(self):
        g=unit([.06,-1,.1]);a=infer_up(self.normals(g),[0,-1,0]);b=infer_up(-self.normals(g),[0,-1,0])
        np.testing.assert_allclose(a['up'],b['up'],atol=1e-12)

    def test_shortest_rotation_aligns_up_preserving_translation(self):
        g=unit([.06,-1,.1]);T=align_up_preserving_heading_reference(self.T,g)
        np.testing.assert_allclose(T[:3,:3]@g,[0,0,1],atol=1e-12)
        np.testing.assert_array_equal(T[:3,3],self.T[:3,3])
        np.testing.assert_allclose(T[:3,:3].T@T[:3,:3],np.eye(3),atol=1e-12)
        self.assertAlmostEqual(np.linalg.det(T[:3,:3]),1)

    def test_up_identity_and_antiparallel_guard(self):
        np.testing.assert_allclose(align_up_preserving_heading_reference(self.T,[0,-1,0]),self.T,atol=1e-12)
        with self.assertRaises(ValueError):align_up_preserving_heading_reference(self.T,[0,1,0])

    def test_inference_apis_accept_no_object_labels(self):
        for function in (extract_planes,extract_curve_planes,infer_up):
            params=inspect.signature(function).parameters
            self.assertFalse(set(params)&{'reference_z_m','height_m','tip','paper_points'})

    def test_integer_observed_projection_restores_line_plane(self):
        # A native vertical image chord is generally NOT a 3D line in fisheye.
        # Project a true synthetic spatial line, then quantize to native pixels.
        world=np.column_stack((np.full(200,-.2),np.linspace(-1.5,-.2,200),np.ones(200)))
        pixels,valid=project(world,self.camera);self.assertTrue(valid.all())
        points=np.rint(pixels)
        _,indices=np.unique(points,axis=0,return_index=True);points=points[np.sort(indices)]
        r=plane_from_pixels(points,self.camera)
        self.assertTrue(r['accepted'])
        self.assertLess(r['plane_rms_deg'],.15)

    def test_subpixel_or_short_pixel_support_rejected(self):
        with self.assertRaises(ValueError):plane_from_pixels([[300,y] for y in range(20)],self.camera)
        with self.assertRaises(ValueError):plane_from_pixels(np.array([[300,y] for y in range(100)])+.1,self.camera)

    def test_detector_does_not_modify_native_image_and_blank_is_empty(self):
        image=np.zeros((720,1280,3),np.uint8);original=image.copy()
        self.assertEqual(extract_planes(image,self.camera),[])
        self.assertEqual(extract_curve_planes(image,self.camera),[])
        np.testing.assert_array_equal(image,original)

    def test_wrong_dimensions_are_rejected(self):
        for function in (extract_planes,extract_curve_planes):
            with self.assertRaises(ValueError):function(np.zeros((360,640,3),np.uint8),self.camera)


class SavedSceneTests(unittest.TestCase):
    def test_sources_outputs_images_and_hardware_flags(self):
        for folder in ('results_r01','curve_results_r01'):
            p=HERE/folder/'summary.json'
            if not p.exists():self.skipTest('Run both independent detector comparisons first')
            data=json.loads(p.read_text())
            self.assertEqual(data['native_images'],86)
            for path,digest in data['source_sha256'].items():self.assertEqual(sha256(Path(path)),digest,path)
            for name,digest in data['output_sha256'].items():self.assertEqual(sha256(p.parent/name),digest,name)
            for flag in ('pose_inference_used_metric_labels','intrinsics_refitted','source_images_edited','physical_output','usable_for_ffb'):
                self.assertFalse(data[flag])

    def test_same_frozen_frame_split_and_metric_row_retention(self):
        a=read_csv(HERE/'results_r01/image_diagnostics.csv');b=read_csv(HERE/'curve_results_r01/image_diagnostics.csv')
        self.assertEqual([(r['session'],r['frame'],r['role']) for r in a],[(r['session'],r['frame'],r['role']) for r in b])
        for folder in ('results_r01','curve_results_r01'):
            rows=read_csv(HERE/folder/'cone_all_frames.csv')
            self.assertEqual(len(rows),6876);self.assertEqual(len({(r['session'],r['frame']) for r in rows}),6876)
            self.assertTrue(all(r['usable_for_ffb']=='False' for r in rows))

    def test_scene_support_is_actual_native_canny_pixels_without_cones(self):
        cache={}
        paths={(r['session'],r['frame']):r['source_native_png'] for r in read_csv(HERE/'results_r01/image_diagnostics.csv')}
        for folder in ('results_r01','curve_results_r01'):
            for r in read_csv(HERE/folder/'line_candidates.csv'):
                pixels=np.array(json.loads(r['actual_edge_pixels_json']),int)
                if not len(pixels):continue
                key=r['session'],r['frame']
                if key not in cache:
                    gray=cv2.cvtColor(cv2.imread(paths[key])[:,:640],cv2.COLOR_BGR2GRAY)
                    cache[key]=cv2.Canny(gray,60,120)
                self.assertTrue(np.all(cache[key][pixels[:,1],pixels[:,0]]>0))
                self.assertTrue(np.all((pixels[:,1]>=60)&(pixels[:,1]<=300)))


if __name__=='__main__':unittest.main()
