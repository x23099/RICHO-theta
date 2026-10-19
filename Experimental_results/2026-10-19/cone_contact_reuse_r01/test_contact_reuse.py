"""Image-point diagnostics: no contact/accuracy approval or source mutations."""
from collections import Counter,defaultdict
import hashlib
import json
from pathlib import Path
import sys
import unittest

import cv2
import numpy as np

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import analyze as audit
from contact_pixels import colour_bottom
from cone_dataset import read_csv,sha256
from diagnose_box_contact_calibration import project_pixel


class ColourReaderTest(unittest.TestCase):
    def setUp(self):
        self.image=np.zeros((720,1280,3),np.uint8)
        self.box=dict(x1=300,y1=300,x2=340,y2=400)

    def rectangle(self,colour=(0,0,200)):
        image=self.image.copy()
        image[304:397,304:337]=colour
        return image

    def test_blank_is_not_filled(self):
        r=colour_bottom(self.image,self.box)
        self.assertFalse(r["colour_candidate"])
        self.assertIsNone(r["pixel_x"])

    def test_red_bottom_uses_native_coordinates(self):
        r=colour_bottom(self.rectangle(),self.box)
        self.assertTrue(r["colour_candidate"])
        self.assertEqual(r["pixel_y"],396.)
        self.assertTrue(304<=r["pixel_x"]<=336)

    def test_yellow_supported_and_gray_not_colour(self):
        self.assertTrue(colour_bottom(self.rectangle((0,200,200)),self.box)["colour_candidate"])
        self.assertFalse(colour_bottom(self.rectangle((200,200,200)),self.box)["colour_candidate"])

    def test_two_competing_components_not_chosen(self):
        image=self.image.copy()
        image[304:397,304:317]=(0,0,200)
        image[304:397,324:337]=(0,0,200)
        r=colour_bottom(image,self.box)
        self.assertFalse(r["colour_candidate"])
        self.assertEqual(r["reason"],"ambiguous_competing_colour_contours")

    def test_roi_contact_is_rejected(self):
        image=self.rectangle()
        image[304:397,296:337]=(0,0,200)
        r=colour_bottom(image,self.box)
        self.assertEqual(r["reason"],"colour_contour_reaches_roi_edge")

    def test_small_extent_rejected(self):
        image=self.image.copy();image[304:397,318:321]=(0,0,200)
        self.assertEqual(colour_bottom(image,self.box)["reason"],"insufficient_colour_extent")

    def test_v_sensitivity_fixed(self):
        image=self.rectangle((0,0,25))
        self.assertTrue(colour_bottom(image,self.box,20)["colour_candidate"])
        self.assertFalse(colour_bottom(image,self.box,30)["colour_candidate"])
        with self.assertRaises(ValueError):colour_bottom(image,self.box,25)

    def test_bad_shape_dtype_and_bbox_rejected(self):
        for image in (self.image[:600],self.image.astype(float)):
            with self.assertRaises(ValueError):colour_bottom(image,self.box)
        with self.assertRaises(ValueError):colour_bottom(self.image,dict(self.box,x2=299))

    def test_native_boundary_not_clipped_to_valid_roi(self):
        r=colour_bottom(self.image,dict(x1=1,y1=300,x2=40,y2=400))
        self.assertEqual(r["reason"],"expanded_roi_outside_native_image")

    def test_no_source_modification(self):
        image=self.rectangle()
        before=image.copy()
        colour_bottom(image,self.box)
        np.testing.assert_array_equal(before,image)

    def test_reference_fields_do_not_affect_reader(self):
        image=self.rectangle()
        first=colour_bottom(image,self.box)
        self.assertEqual(first,colour_bottom(image,dict(self.box,reference_z_m=999,model="unknown",frame=999)))

    def test_visible_partial_fragment_never_proves_contact(self):
        image=self.image.copy();image[320:351,304:337]=(0,0,200)
        r=colour_bottom(image,self.box)
        self.assertTrue(r["colour_candidate"])
        self.assertFalse(r["floor_contact_verified"])
        self.assertFalse(r["usable_for_ffb"])


class SavedResultsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sample=HERE/"results_r01"
        cls.full=HERE/"full_replay_r01"
        cls.pixels=read_csv(cls.full/"pixels.csv")
        cls.positions=read_csv(cls.full/"positions.csv")
        cls.provenance=json.loads((cls.full/"provenance.json").read_text())
        cls.models=cls.provenance["models"]

    def test_all_frames_thresholds_and_models_retained(self):
        self.assertEqual(len(self.pixels),15429)
        self.assertEqual(len(self.positions),46287)
        groups=Counter((r["dataset"],r["session"],r["frame"]) for r in self.pixels)
        self.assertEqual(len(groups),5143)
        self.assertEqual(set(groups.values()),{3})
        self.assertEqual(set(Counter((r["dataset"],r["session"],r["frame"]) for r in self.positions).values()),{9})

    def test_native_sample_pixels_and_hashes_verified(self):
        samples=audit.sample_manifest()
        self.assertEqual(len(samples),41)
        for row in samples:
            image=cv2.imread(row["path"])
            self.assertEqual(image.shape,(720,1280,3))
            self.assertEqual(sha256(Path(row["path"])),row["png_sha256"])
            self.assertEqual(hashlib.sha256(image.tobytes()).hexdigest(),row["decoded_bgr_sha256"])

    def test_full_raw_matches_all_pre_exported_png_results(self):
        full={(r["dataset"],r["session"],r["frame"],r["v_min"]):r for r in self.pixels}
        samples=read_csv(self.sample/"pixel_observations.csv")
        self.assertEqual(len(samples),123)
        for row in samples:
            other=full[row["dataset"],row["session"],row["frame"],row["v_min"]]
            self.assertEqual(row["colour_candidate"],other["colour_candidate"])
            self.assertEqual(row["reason"],other["colour_reason"])
            for key in ("pixel_x","pixel_y"):
                self.assertEqual(row[key],other[key])

    def test_sample_reader_independently_recomputed(self):
        sources,models,refs,conditions,phases,_=audit.previous.load_inputs()
        from cone_observation import ConeGroundProjector
        scope=ConeGroundProjector(models["recorded58"],width=1280,height=720,front_lens="left",confidence_threshold=.5)
        ledger,selected=audit.previous.make_ledger(sources,scope,refs,conditions,phases)
        recomputed=audit.images_and_pixels(audit.sample_manifest(),ledger,selected)
        saved=read_csv(self.sample/"pixel_observations.csv")
        for a,b in zip(recomputed,saved):
            for key in ("colour_candidate","reason","pixel_x","pixel_y"):
                self.assertEqual("" if a[key] is None else str(a[key]),b[key])

    def test_all_projected_points_recomputed(self):
        for row in self.positions:
            p=self.models[row["model"]]
            if row["pixel_x"]:
                point=project_pixel((float(row["pixel_x"]),float(row["pixel_y"])),p)
                if point is None:self.assertEqual(row["colour_z_m"],"")
                else:np.testing.assert_allclose([float(row["colour_x_m"]),float(row["colour_z_m"])],point,atol=1e-10,rtol=0)
            self.assertEqual(row["floor_contact_verified"],"False")
            self.assertEqual(row["usable_for_ffb"],"False")

    def test_pair_terms_telescope_without_fabricated_static_floor(self):
        pairs=read_csv(self.sample/"paired_anchors.csv")
        self.assertEqual(len(pairs),21)
        for row in pairs:
            self.assertAlmostEqual(float(row["total_error_m"]),float(row["two_term_sum_m"]),places=12)
            if row["dataset"]=="sequence":
                self.assertAlmostEqual(float(row["three_term_sum_m"]),float(row["total_error_m"]),places=12)
            else:self.assertEqual(row["floor_z_m"],"")
            self.assertEqual(row["manual_is_physical_gt"],"False")

    def test_no_target_and_ambiguous_frames_not_filled(self):
        for row in self.pixels:
            if row["candidates"]!="1":
                self.assertEqual(row["colour_candidate"],"False")
                self.assertEqual(row["pixel_x"],"")
        negative=[r for r in self.pixels if r["dataset"]=="static" and r["condition"]=="none"]
        self.assertEqual(len(negative),332*3)
        self.assertTrue(all(r["colour_candidate"]=="False" for r in negative))

    def test_saved_summary_independently_recomputed(self):
        by_key=defaultdict(list)
        for row in self.positions:by_key[row["dataset"],row["condition"],row["model"],row["v_min"]].append(row)
        for summary in read_csv(self.full/"summary.csv"):
            group=by_key[summary["dataset"],summary["condition"],summary["model"],summary["v_min"]]
            self.assertEqual(len(group),int(summary["frames"]))
            values=[float(r["colour_z_m"]) for r in group if r["colour_z_m"]]
            self.assertEqual(len(values),int(summary["colour_projected_frames"]))
            if values:self.assertAlmostEqual(float(np.median(values)),float(summary["colour_z_median_m"]))

    def test_partial_occlusion_is_not_promoted_to_contact(self):
        rows=[r for r in self.positions if r["dataset"]=="sequence" and r["frame"] in ("1133","1134")]
        self.assertEqual(len(rows),18)
        self.assertTrue(all(r["usable_for_ffb"]=="False" for r in rows))
        # Some colors remain visible; a candidate is NOT proof of valid base.
        self.assertTrue(any(r["colour_candidate"]=="True" for r in rows))

    def test_original_raw_hashes_match_1015_intakes(self):
        static=json.loads((audit.OLD/"cone_static_distance_r01/intake_summary.json").read_text())
        for source in static["inputs"]:
            for name,digest in source["hashes"].items():
                self.assertEqual(self.provenance["source_sha256"][str(Path(source["path"])/name)],digest)
        intake=json.loads((audit.OLD/"floor_cone_same_pose_analysis_r01/intake_summary.json").read_text())
        original=intake["source_sha256"]
        self.assertEqual(set(original),{"raw.avi","metadata.json","detections.csv"})
        for filename,digest in original.items():
            path=str(Path(intake["session"])/filename)
            self.assertEqual(self.provenance["source_sha256"][path],digest)

    def test_existing_bbox_results_are_not_redefined(self):
        earlier=read_csv(audit.PREVIOUS/"results_r01/observations.csv")
        earlier={(r["dataset"],r["session"],r["frame"],r["model"]):r for r in earlier if r["model"]!="bbox_area"}
        compared=0
        for row in self.positions:
            if row["v_min"]!="30":continue
            old=earlier[row["dataset"],row["session"],row["frame"],row["model"]]
            self.assertEqual(bool(row["bbox_z_m"]),bool(old["z_m"]))
            if old["z_m"]:self.assertAlmostEqual(float(row["bbox_z_m"]),float(old["z_m"]),places=10)
            compared+=1
        self.assertEqual(compared,5143*3)

    def test_source_result_and_config_hashes_unchanged(self):
        for folder in (self.sample,self.full):
            provenance=json.loads((folder/"provenance.json").read_text())
            for path,digest in provenance["source_sha256"].items():self.assertEqual(sha256(Path(path)),digest,path)
            for name,digest in provenance["output_sha256"].items():self.assertEqual(sha256(folder/name),digest,name)
            self.assertFalse(provenance["usable_for_ffb"])
            self.assertFalse(provenance["physical_output"])


if __name__=="__main__":unittest.main()
