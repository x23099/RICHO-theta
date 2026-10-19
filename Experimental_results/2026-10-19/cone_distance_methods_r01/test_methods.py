"""Formula, split, causality, complete-ledger and saved-result checks."""
from collections import Counter, defaultdict
from copy import deepcopy
import json
import math
from pathlib import Path
import sys
import unittest

import numpy as np

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import analyze as audit
from area_baseline import area_fraction,fit_scale,predict_z
from cone_dataset import read_csv,sha256
from cone_observation import ConeGroundProjector
from diagnose_box_contact_calibration import project_pixel


class AreaFormulaTest(unittest.TestCase):
    def setUp(self):
        p=json.loads((audit.OLD/"paper_reference7_r01/analysis_r01/centre2_offline_candidate.json").read_text())["parameters"]
        self.scope=ConeGroundProjector(p,width=1280,height=720,front_lens="left",confidence_threshold=.5)
        self.box=dict(x1=300,y1=350,x2=320,y2=400,class_id=0,confidence=.8)
        self.anchors=[dict(condition="center_080",q_median=.01,reference_z_m=.8),
                      dict(condition="center_200",q_median=.0016,reference_z_m=2.)]

    def test_scale_formula(self):
        self.assertAlmostEqual(fit_scale(self.anchors),.08)
        self.assertAlmostEqual(predict_z(.01,.08),.8)
        self.assertAlmostEqual(predict_z(.0016,.08),2.)

    def test_area_four_times_means_half_proxy_distance(self):
        self.assertAlmostEqual(predict_z(.004,.08),predict_z(.001,.08)/2)

    def test_holdout_duplicate_and_wrong_reference_rejected(self):
        for case in ([self.anchors[0]],self.anchors+[dict(condition="center_130",q_median=.005,reference_z_m=1.3)],
                     [self.anchors[0],self.anchors[0]],
                     [dict(self.anchors[0],reference_z_m=1.),self.anchors[1]]):
            with self.subTest(case=case),self.assertRaises(ValueError):
                fit_scale(case)

    def test_invalid_fraction_and_scale_rejected(self):
        for q in (0,-1,1,float("nan"),float("inf")):
            with self.subTest(q=q),self.assertRaises(ValueError):
                predict_z(q,.1)
        for k in (0,-1,float("nan"),float("inf")):
            with self.subTest(k=k),self.assertRaises(ValueError):
                predict_z(.01,k)

    def test_fraction_native_denominator(self):
        self.assertAlmostEqual(area_fraction(self.box,self.scope),1000/(1280*720))

    def test_bbox_is_not_mask_and_no_floor_projection_needed(self):
        class NoFloorScope:
            width,height=1280,720
            def _in_circle(self,x,y):return True
            def project(self,*args,**kwargs):raise AssertionError("area estimator must not use a floor ray")
        self.assertAlmostEqual(area_fraction(self.box,NoFloorScope()),1000/(1280*720))

    def test_bad_or_truncated_boxes_rejected(self):
        for changes in (dict(confidence=.49),dict(class_id=1),dict(confidence=float("nan")),
                        dict(x1=0),dict(x1=320,x2=300),dict(y2=720),dict(x1=20,x2=40)):
            with self.subTest(changes=changes),self.assertRaises(ValueError):
                area_fraction(dict(self.box,**changes),self.scope)

    def test_area_calibration_does_not_read_holdouts(self):
        ledger=[dict(dataset="static",session=str(i),condition=r["condition"],q=r["q_median"],reference_z_m=r["reference_z_m"])
                for i,r in enumerate(self.anchors)]
        ledger.append(dict(dataset="static",session="heldout",condition="center_130",q=.01,reference_z_m=1.3))
        before=deepcopy(ledger)
        first=audit.calibrate_area(ledger)
        self.assertEqual(ledger,before)
        ledger[-1].update(q=.9,reference_z_m=999.)
        self.assertEqual(first,audit.calibrate_area(ledger))

    def test_unbounded_out_of_range_value_retained_in_error_metrics(self):
        row=dict(dataset="d",condition="c",model="bbox_area",area_role="heldout",reference_z_m=2.,reference_x_m=0.,
                 z_m=None,unbounded_z_m=8.,x_m=None,projection_candidate=False,quality_accepted=False,
                 quality_z_m=None,quality_reason="not_implemented",reason="outside_range")
        result=audit.summarize([row])[0]
        self.assertEqual(result["estimated_frames"],1)
        self.assertEqual(result["range_accepted_frames"],0)
        self.assertEqual(result["z_abs_error_p95_m"],6.)


class SavedAuditTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sources,cls.models,cls.refs,cls.conditions,cls.phases,cls.hashes=audit.load_inputs()
        cls.scope=ConeGroundProjector(cls.models["recorded58"],width=1280,height=720,front_lens="left",confidence_threshold=.5)
        cls.ledger,cls.selected=audit.make_ledger(cls.sources,cls.scope,cls.refs,cls.conditions,cls.phases)
        cls.out=HERE/"results_r01"
        cls.rows=read_csv(cls.out/"observations.csv")
        cls.summary=read_csv(cls.out/"summary.csv")
        cls.provenance=json.loads((cls.out/"provenance.json").read_text())
        cls.calibration=json.loads((cls.out/"area_calibration.json").read_text())

    def test_all_frames_and_methods_retained(self):
        self.assertEqual(len(self.ledger),5143)
        self.assertEqual(len(self.rows),20572)
        self.assertEqual(Counter(r["dataset"] for r in self.ledger),dict(static=3596,sequence=1547))
        counts=Counter((r["dataset"],r["session"],int(r["frame"])) for r in self.rows)
        self.assertEqual(set(counts.values()),{4})
        self.assertEqual(len(counts),5143)

    def test_multiple_and_empty_frames_not_best_score_selected(self):
        empty=[r for r in self.rows if r["dataset"]=="static" and r["condition"]=="none"]
        self.assertEqual(len(empty),332*4)
        self.assertTrue(all(not r["z_m"] and not r["unbounded_z_m"] for r in empty))
        multi=[r for r in self.rows if r["dataset"]=="static" and r["condition"]=="right_130" and r["frame"] in ("54","56","57")]
        self.assertEqual(len(multi),12)
        self.assertTrue(all(r["reason"]=="ambiguous_candidates" and not r["z_m"] for r in multi))

    def test_no_reference_or_future_used_by_replay(self):
        prefix=deepcopy(self.ledger[:30])
        baseline=audit.replay(prefix,self.selected,self.models,self.calibration["scale"])
        altered=deepcopy(prefix)
        for row in altered:
            row.update(reference_z_m=999.,reference_x_m=-999.,condition="hidden_reference")
        current=audit.replay(altered,self.selected,self.models,self.calibration["scale"])
        fields=("model","z_m","x_m","unbounded_z_m","quality_accepted","quality_reason","quality_z_m")
        self.assertEqual([[r[k] for k in fields] for r in baseline],[[r[k] for k in fields] for r in current])
        extended=audit.replay(self.ledger[:40],self.selected,self.models,self.calibration["scale"])
        self.assertEqual(baseline,extended[:len(baseline)])

    def test_area_saved_scale_and_every_fraction_recomputed(self):
        calibration=audit.calibrate_area(self.ledger)
        self.assertEqual(calibration,self.calibration)
        keyed={(r["dataset"],r["session"],int(r["frame"])):r for r in self.ledger}
        for r in self.rows:
            if r["model"]!="bbox_area":continue
            source=keyed[r["dataset"],r["session"],int(r["frame"]) ]
            if source["q"] is None:
                self.assertEqual(r["unbounded_z_m"],"")
            else:
                # Algebra independent of predict_z: Z^2 * q must equal k^2.
                self.assertAlmostEqual(float(r["unbounded_z_m"])**2*source["q"],calibration["scale"]**2,places=12)

    def test_ground_saved_coordinates_independently_reprojected(self):
        for r in self.rows:
            if r["model"]=="bbox_area" or r["projection_candidate"]!="True":continue
            candidate=self.selected[r["dataset"],r["session"],int(r["frame"])][0]
            point=((float(candidate["x1"])+float(candidate["x2"]))/2,float(candidate["y2"]))
            expected=project_pixel(point,self.models[r["model"]])
            self.assertIsNotNone(expected)
            np.testing.assert_allclose([float(r["x_m"]),float(r["z_m"])],expected,atol=1e-10,rtol=0)

    def test_area_metrics_and_fixed_screen_recomputed(self):
        rejected=[]
        for group in self.summary:
            if group["model"]!="bbox_area" or group["area_role"]!="heldout":continue
            selected=[r for r in self.rows if (r["dataset"],r["condition"],r["model"])==
                      (group["dataset"],group["condition"],group["model"]) and r["unbounded_z_m"]]
            error=np.array([float(r["unbounded_z_m"])-float(group["reference_z_m"]) for r in selected])
            bias,p95=float(np.median(error)),float(np.percentile(abs(error),95))
            self.assertAlmostEqual(bias,float(group["z_bias_m"]))
            self.assertAlmostEqual(p95,float(group["z_abs_error_p95_m"]))
            if abs(bias)>.1 or p95>.2:rejected.append((group["dataset"],group["condition"]))
        screen=json.loads((self.out/"area_screen.json").read_text())
        self.assertEqual([(r["dataset"],r["condition"]) for r in screen["failures"]],rejected)
        self.assertEqual(screen["decision"],"DEFER_SIMPLE_BBOX_AREA")

    def test_occlusion_withheld_and_no_distance_filled(self):
        for r in self.rows:
            self.assertEqual(r["usable_for_ffb"],"False")
            if r["model"]!="bbox_area" and r["quality_accepted"]!="True":
                self.assertEqual(r["quality_z_m"],"")
            if r["dataset"]=="sequence" and r["frame"] in ("1133","1134") and r["model"]=="paper_centre2":
                self.assertEqual(r["quality_accepted"],"False")
                self.assertEqual(r["quality_reason"],"confirmation_pending")

    def test_geometry_and_source_hashes_unchanged(self):
        self.assertEqual(self.provenance["geometries"],self.models)
        for path,digest in self.provenance["source_sha256"].items():
            self.assertEqual(sha256(Path(path)),digest,path)
        for filename,digest in self.provenance["output_sha256"].items():
            self.assertEqual(sha256(self.out/filename),digest,filename)
        self.assertFalse(self.provenance["geometry_refitted"])
        self.assertFalse(self.provenance["production_settings_changed"])
        self.assertFalse(self.provenance["physical_output"])

    def test_inference_profiles_identical(self):
        a=json.loads((audit.OLD/"cone_static_distance_r01/inference_r01/provenance.json").read_text())["candidate"]
        b=json.loads((audit.OLD/"floor_cone_same_pose_analysis_r01/inference_r01/provenance.json").read_text())["candidate"]
        self.assertEqual(a,b)
        self.assertEqual(a["confidence"],.5)
        self.assertEqual(a["sha256"],"3a6e124adb15c16efd7d22c853406066371f48873c82f1d3cfc445b22ae5997b")


if __name__=="__main__":unittest.main()
