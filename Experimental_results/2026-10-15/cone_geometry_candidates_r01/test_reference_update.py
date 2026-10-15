import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parents[2]/'src'))
from cone_dataset import read_csv,sha256,write_csv
import update_cone_reference as module


class ReferenceUpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        (self.root/'results_r01').mkdir()
        (self.root/'cone_reference_confirmation.json').write_text(json.dumps(dict(base_side_m=.375,lateral_inner_edge_abs_x_m=.4)))
        (self.root/'results_r01/candidate_parameters.json').write_text('{"frozen": true}\n')
        rows=[]
        for name,x,z in (('center_080',0,.8),('center_130',0,1.3),('center_200',0,2.),('left_130',-.4,1.3),('right_130',.4,1.3),('none',0,0)):
            active=name!='none'
            rows.append(dict(condition=name,reference_x_m=x,reference_z_m=z,
                baseline_used=active,candidate_used=active,baseline_x_m=x-.05 if active else None,
                baseline_z_m=z+.1 if active else None,candidate_x_m=x-.01 if active else None,
                candidate_z_m=z+.02 if active else None,candidate_error_x_m=-.01 if active else None,
                candidate_error_z_m=.02 if active else None,usable_for_ffb=False))
        self.source=self.root/'results_r01/cone_transfer_frames.csv'
        write_csv(self.source,rows)
        self.original_hash=sha256(self.source)
        with patch.object(module,'HERE',self.root),contextlib.redirect_stdout(io.StringIO()):module.main()
        self.output=self.root/'reference_update_r01'

    def test_inner_edge_not_mistaken_for_centre(self):
        refs={r['condition']:r for r in read_csv(self.output/'reference_conditions.csv')}
        self.assertEqual(float(refs['left_130']['reference_x_m']),-.5875)
        self.assertEqual(float(refs['right_130']['reference_x_m']),.5875)

    def test_front_edge_distance_not_shifted_to_base_centre(self):
        for r in read_csv(self.output/'cone_transfer_frames_updated.csv'):
            self.assertEqual(float(r['reference_z_m']),float(r['capture_label_reference_z_m']))

    def test_no_fit_or_prediction_change(self):
        self.assertEqual(sha256(self.source),self.original_hash)
        original=read_csv(self.source)
        updated=read_csv(self.output/'cone_transfer_frames_updated.csv')
        for a,b in zip(original,updated):
            for field in ('baseline_x_m','baseline_z_m','candidate_x_m','candidate_z_m','usable_for_ffb'):
                self.assertEqual(a[field],b[field])

    def test_missing_cone_stays_missing(self):
        r=next(r for r in read_csv(self.output/'cone_transfer_frames_updated.csv') if r['condition']=='none')
        self.assertEqual(r['candidate_z_m'],'')
        self.assertEqual(r['baseline_error_z_updated_m'],'')
        self.assertEqual(r['usable_for_ffb'],'False')

    def test_uniform_csv_schema_and_no_overwrite(self):
        rows=read_csv(self.output/'cone_transfer_summary_updated.csv')
        self.assertEqual(len(rows),5)
        self.assertEqual(rows[0]['hypothetical_base_rotation_0_to_45deg_error_x_min_m'],'')
        self.assertNotEqual(rows[-1]['hypothetical_base_rotation_0_to_45deg_error_x_min_m'],'')
        with patch.object(module,'HERE',self.root),self.assertRaises(ValueError):module.main()


if __name__=='__main__':unittest.main()
