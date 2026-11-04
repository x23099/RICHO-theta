"""Local analysis guards, not hardware or metric-accuracy tests."""
import copy
from pathlib import Path
import sys
import unittest

import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parent))
from audit import rectangle_at_height, assert_same_session, context_probe
from cone_distance_core import load_config


class FinalAuditTests(unittest.TestCase):
    def test_known_height_ray_rectangle(self):
        points=np.array([[-.148,.575,1],[.148,.575,1],[.148,.575,1.21],[-.148,.575,1.21]])
        rays=points/np.linalg.norm(points,axis=1)[:,None]
        np.testing.assert_allclose(rectangle_at_height(rays,[0,-1,0],.575),[296,210,296,210],atol=1e-10)

    def test_height_is_external_not_fitted(self):
        points=np.array([[-.148,.575,1],[.148,.575,1],[.148,.575,1.21],[-.148,.575,1.21]])
        rays=points/np.linalg.norm(points,axis=1)[:,None]
        np.testing.assert_allclose(rectangle_at_height(rays,[0,-1,0],1.15),[592,420,592,420],atol=1e-10)

    def test_horizon_or_behind_rejected(self):
        self.assertIsNone(rectangle_at_height([[0,0,1]]*4,[0,-1,0],.575))
        self.assertIsNone(rectangle_at_height([[0,1,1]]*4,[0,1,0],.575))

    def test_bad_geometry_rejected(self):
        with self.assertRaises(ValueError):rectangle_at_height([[0,1,1]]*4,[0,-2,0],.575)
        with self.assertRaises(ValueError):rectangle_at_height([[0,1,1]]*4,[0,-1,0],float('nan'))

    def test_session_and_model_never_transferred(self):
        rows=[dict(session='one',fixed_floor_load=dict(state='active'),fixed_floor_shadow=dict(model_bundle_sha256='hash1'))]
        before=copy.deepcopy(rows)
        assert_same_session(rows,'one','hash1')
        with self.assertRaises(ValueError):assert_same_session(rows,'two','hash1')
        with self.assertRaises(ValueError):assert_same_session(rows,'one','hash2')
        rows[0]['fixed_floor_load']['state']='rejected'
        with self.assertRaises(ValueError):assert_same_session(rows,'one','hash1')
        self.assertEqual(before[0]['session'],rows[0]['session'])

    def test_bottom_closure_is_not_contact_or_runtime_grant(self):
        image=np.zeros((720,1280,3),np.uint8);image[300:431,300:341]=[0,0,255]
        before=image.copy()
        candidate=dict(selected_colour='red',seed_xyxy=[310,320,321,340])
        box=dict(x1=297.,y1=298.,x2=343.,y2=418.)
        camera=load_config()[1]
        original=context_probe(image,box,candidate,camera,(4,4,4))
        larger=context_probe(image,box,candidate,camera,(4,4,16))
        self.assertIsNone(original['point']);self.assertTrue(original['touching_edges']['bottom'])
        self.assertIsNotNone(larger['point']);self.assertFalse(larger['point_in_original_bbox'])
        self.assertNotEqual(original['original_or_expanded_lower_support'],larger['support'])
        self.assertTrue(larger['diagnostic_only']);self.assertFalse(larger['usable_for_ffb'])
        np.testing.assert_array_equal(image,before)


if __name__=='__main__':unittest.main()
