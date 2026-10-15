import json
from pathlib import Path
import sys
import unittest

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parents[2]/'src'))
from cone_dataset import read_csv
from analyze import phase_at,select_central


class SequenceAnalysisTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scope=json.loads((HERE/'scope.json').read_text())
        cls.rows=read_csv(HERE/'analysis_r01/observations.csv')

    def test_all_frames_have_one_phase(self):
        for number in range(1,1548):
            self.assertIn('name',phase_at(number,self.scope))
        for number in (0,1548):
            with self.assertRaises(ValueError):phase_at(number,self.scope)

    def test_hand_contact_not_assigned_static_truth(self):
        self.assertEqual(phase_at(480,self.scope)['name'],'placement_transition')
        self.assertIsNone(phase_at(480,self.scope)['reference_z_m'])
        self.assertEqual(phase_at(563,self.scope)['reference_z_m'],1.3)

    def test_central_scope_does_not_call_other_cones_false_positives(self):
        rows=[dict(x1=190,x2=210),dict(x1=280,x2=340),dict(x1=540,x2=580)]
        self.assertEqual(select_central(rows,[270,350]),[rows[1]])
        self.assertEqual(len(rows),3)

    def test_multiple_central_outputs_not_silently_argmaxed(self):
        rows=[dict(x1=280,x2=340,confidence=.9),dict(x1=300,x2=330,confidence=.7)]
        self.assertEqual(len(select_central(rows,[270,350])),2)

    def test_missing_and_outlier_rows_kept_not_filled(self):
        missing=next(r for r in self.rows if r['model']=='recorded58' and r['frame']=='1125')
        self.assertEqual(missing['z_m'],'')
        self.assertEqual(missing['reason'],'no_central_prediction')
        outlier=next(r for r in self.rows if r['model']=='frozen_centre2' and r['frame']=='1134')
        self.assertGreater(float(outlier['z_m']),3.5)
        self.assertEqual(outlier['usable_for_ffb'],'False')

    def test_no_final_floor_or_new_fit_fabricated(self):
        summary=json.loads((HERE/'analysis_r01/summary.json').read_text())
        self.assertEqual(self.scope['floor_after'],'NOT_RECORDED_CONFIRMED_BY_USER')
        self.assertEqual(summary['floor_points_used_for_fit'],0)
        self.assertEqual(summary['cone_points_used_for_fit'],0)
        self.assertFalse(summary['new_geometry_fitted'])
        self.assertFalse(summary['physical_output'])
        self.assertEqual(len(self.rows),1547*3)
        self.assertTrue(all(r['usable_for_ffb']=='False' and r['physical_contact_verified']=='False' for r in self.rows))


if __name__=='__main__':unittest.main()
