from pathlib import Path
import sys
import unittest

import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[3]/'src'))
from view_registration import match_region


class ViewRegistrationTests(unittest.TestCase):
    def test_synthetic_translation_and_reverse(self):
        rng=np.random.default_rng(41)
        reference=rng.integers(0,256,size=(720,1280),dtype=np.uint8)
        current=np.zeros_like(reference)
        # Synthetic shift only; no real source image is modified or exported.
        current[:-5,7:]=reference[5:,:-7]
        row=match_region(reference,current,('synthetic',300,500,45,40))
        self.assertEqual(row['delta_x_current_minus_reference_px'],7)
        self.assertEqual(row['delta_y_current_minus_reference_px'],-5)
        self.assertTrue(row['reliable_for_local_feature_comparison'])
        self.assertEqual(row['reverse_return_error_px'],0)

    def test_identity_returns_zero(self):
        array=np.random.default_rng(4).integers(0,256,size=(720,1280),dtype=np.uint8)
        row=match_region(array,array,('identity',300,500,45,40))
        self.assertEqual((row['delta_x_current_minus_reference_px'],row['delta_y_current_minus_reference_px']),(0,0))

    def test_flat_and_invalid_shape_rejected(self):
        blank=np.zeros((720,1280),np.uint8)
        with self.assertRaises(ValueError):match_region(blank,blank,('flat',300,500,45,40))
        with self.assertRaises(ValueError):match_region(blank,blank[:,:100],('shape',300,500,45,40))

    def test_search_must_stay_native(self):
        array=np.zeros((720,1280),np.uint8)
        for region in (('outside',1,1,20,20),('invalid',300,500,0,0)):
            with self.assertRaises(ValueError):match_region(array,array,region)


if __name__=='__main__':unittest.main()
