"""Frozen result regression checks; run after run.py and plot_results.py."""
import csv
import json
from collections import Counter
from pathlib import Path
import sys
import unittest

import numpy as np

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
sys.path.insert(0,str(ROOT/'src'))
from cone_dataset import read_csv,sha256
from angular_fisheye_geometry import camera_from_candidate,unproject,project,floor_from_rays


class MetricResultTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder=HERE/'results_r01'
        cls.summary=json.loads((cls.folder/'summary.json').read_text())
        cls.camera=camera_from_candidate(json.loads((HERE.parent/'front_fisheye_solver_audit_r01/angular_results_r01/angular_diagnostic_candidate.json').read_text()))

    def test_all_frozen_sources_and_outputs_unchanged(self):
        for manifest in (self.folder/'summary.json',HERE/'plots_r01/manifest.json'):
            data=json.loads(manifest.read_text())
            for path,digest in data['source_sha256'].items():self.assertEqual(sha256(Path(path)),digest,path)
            for name,digest in data['output_sha256'].items():self.assertEqual(sha256(manifest.parent/name),digest,name)

    def test_every_observed_frame_has_nine_rows_including_missing(self):
        observed=read_csv(HERE.parent/'cone_known_height_pinhole_r01/results_r01/observed_pixels.csv')
        expected={(r['session'],int(r['frame'])) for r in observed}
        groups=Counter();missing=0
        with (self.folder/'cone_all_frame_results.csv').open(newline='') as stream:
            for row in csv.DictReader(stream):
                groups[(row['session'],int(row['frame']))]+=1
                self.assertEqual(row['usable_for_ffb'],'False')
                self.assertEqual(row['physical_endpoint_correspondence_verified'],'False')
                if row['estimated']=='False':
                    missing+=1
                    self.assertEqual(row['z_forward_m'],'')
        self.assertEqual(set(groups),expected)
        self.assertEqual(set(groups.values()),{9})
        self.assertEqual(len(expected),6876)
        self.assertEqual(sum(groups.values()),61884)
        self.assertEqual(missing,1907*9)

    def test_observed_pixels_roundtrip_without_reordering(self):
        rows=read_csv(HERE.parent/'cone_known_height_pinhole_r01/results_r01/observed_pixels.csv')
        pairs=[json.loads(r['native_colour_pair_json']) for r in rows if r['native_colour_pair_json']]
        pixels=np.asarray(pairs).reshape(-1,2)
        rays,valid=unproject(pixels,self.camera,image_size=(1280,720))
        self.assertTrue(valid.all())
        recovered,valid=project(rays,self.camera)
        self.assertTrue(valid.all())
        np.testing.assert_allclose(recovered,pixels,atol=1e-10)

    def test_only_rotation_fitted_and_holdout_separate(self):
        tf=self.summary['floor_fit']
        self.assertEqual(tf['fit_ids'],['C080','C130','C200','L130','R130'])
        self.assertFalse(tf['intrinsics_refitted'])
        self.assertEqual(tf['fixed_height_m'],.59)
        self.assertEqual(tf['fixed_xy_m'],[0,0])
        self.assertEqual(tf['active_bounds'],[0,0,0])
        self.assertEqual(tf['numerical_rank'],3)
        rows=read_csv(self.folder/'floor_reference_results.csv')
        for model in ('ideal59_nominal','angular_nominal','angular_paper5_rotation'):
            selected=[r for r in rows if r['model']==model]
            self.assertEqual(Counter(r['role'] for r in selected),
                {'fit':5,'same_recording_holdout':2,'cross_recording_not_fitted':1})

    def test_saved_floor_coordinates_recompute(self):
        rows=[r for r in read_csv(self.folder/'floor_reference_results.csv') if r['model']=='angular_paper5_rotation']
        uv=[[float(r['pixel_x']),float(r['pixel_y'])] for r in rows]
        rays,valid=unproject(uv,self.camera,image_size=(1280,720))
        xyz,valid=floor_from_rays(rays,valid,self.summary['floor_fit']['transform_target_from_source'])
        self.assertTrue(valid.all())
        np.testing.assert_allclose(xyz[:,0],[float(r['z_forward_m']) for r in rows],atol=1e-12)
        np.testing.assert_allclose(-xyz[:,1],[float(r['x_right_m']) for r in rows],atol=1e-12)

    def test_legacy_baseline_and_no_hardware_approval(self):
        self.assertEqual(self.summary['legacy_height_replayed_frames'],4969)
        self.assertLess(self.summary['legacy_height_max_depth_difference_m'],1e-8)
        for key in ('physical_output','original_images_edited','intrinsics_refitted','usable_for_ffb'):
            self.assertFalse(self.summary[key])
        self.assertFalse(self.summary['floor_fit']['published_to_ros'])

    def test_metadata_is_not_optical_state_proof(self):
        rows=read_csv(self.folder/'metadata_comparison.csv')
        self.assertEqual(len(rows),13)
        self.assertTrue(all(r['requested_capture_equal']=='True' for r in rows))
        self.assertTrue(all(r['capture_properties_equal']=='True' for r in rows))
        self.assertTrue(all(r['serial_recorded']=='False' for r in rows))
        self.assertTrue(all(r['optical_state_independently_verified']=='False' for r in rows))


if __name__=='__main__':unittest.main()
