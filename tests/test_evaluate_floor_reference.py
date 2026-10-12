import copy
import csv
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"src"))
from evaluate_floor_reference import (FIELDS, evaluate_point, evaluate_session,
                                     validate_points, write_csv)
from diagnose_box_contact_calibration import project_pixel

P = dict(camera_height=.58, radius_scale=.86, front_cx_offset=-80, front_cy_offset=-21,
         back_cx_offset=82, back_cy_offset=-18, pitch_deg=1, roll_deg=2, yaw_deg=0)


class FloorReferenceTest(unittest.TestCase):
    def point(self, **overrides):
        row=dict(point_id="synthetic_marker",frame="2",pixel_x="320",pixel_y="450",
                 measured_x_m="0",measured_z_m="1.1",x_half_width_m=".01",
                 z_half_width_m=".01",pixel_half_width_px="1",
                 measurement_note="SYNTHETIC TEST ONLY; not real surveyed truth")
        row.update(overrides)
        return row

    def validated(self, **overrides):
        return validate_points([self.point(**overrides)],1280,720)[0]

    def test_empty_table_rejected(self):
        with self.assertRaises(ValueError): validate_points([],1280,720)

    def test_blank_truth_is_not_inferred_from_name(self):
        with self.assertRaises(ValueError):
            self.validated(point_id="center_z1p10",measured_z_m="")

    def test_nonfinite_coordinates_rejected(self):
        for key in FIELDS[1:-1]:
            with self.subTest(key=key),self.assertRaises(ValueError):
                self.validated(**{key:"nan"})

    def test_positive_integral_one_based_frame(self):
        for frame in ("0","-1","1.5"):
            with self.subTest(frame=frame),self.assertRaises(ValueError):
                self.validated(frame=frame)

    def test_pixel_band_inside_raw_image_required(self):
        for overrides in (dict(pixel_x="1280"),dict(pixel_y="0",pixel_half_width_px="1"),
                          dict(pixel_half_width_px="-1")):
            with self.assertRaises(ValueError): self.validated(**overrides)

    def test_duplicate_point_identity_rejected(self):
        with self.assertRaises(ValueError):
            validate_points([self.point(),self.point()],1280,720)

    def test_measurement_note_and_nonnegative_uncertainty_required(self):
        for overrides in (dict(measurement_note=""),dict(z_half_width_m="-.1"),
                          dict(x_half_width_m="-.1"),dict(measured_z_m="0")):
            with self.assertRaises(ValueError): self.validated(**overrides)

    def test_projection_matches_existing_geometry(self):
        r=evaluate_point(self.validated(),P,1280,720)
        x,z=project_pixel((320,450),P)
        self.assertEqual((r["raw_x_m"],r["raw_z_m"]),(x,z))
        self.assertAlmostEqual(r["error_z_m"],z-1.1)

    def test_box_affine_bev_and_ui_offsets_are_ignored(self):
        p=dict(P,blue_ground_contact_x_scale=999,blue_ground_contact_x_offset_m=99,
               blue_ground_contact_z_offset_m=99,blue_calibration_z_scale=99,
               car_offset_x=99,car_offset_z=99)
        self.assertEqual(evaluate_point(self.validated(),P,1280,720),
                         evaluate_point(self.validated(),p,1280,720))

    def test_invalid_ray_is_not_zero_error(self):
        r=evaluate_point(self.validated(pixel_y="200"),P,1280,720)
        self.assertEqual(r["projection_status"],"INVALID_FLOOR_RAY")
        self.assertIsNone(r["position_error_m"])
        self.assertIsNone(r["z_within_measured_band"])

    def test_ground_truth_does_not_change_selected_ray(self):
        a=evaluate_point(self.validated(),P,1280,720)
        b=evaluate_point(self.validated(measured_z_m="2.0"),P,1280,720)
        self.assertEqual(a["raw_z_m"],b["raw_z_m"])

    def test_does_not_mutate_inputs(self):
        p=copy.deepcopy(P)
        row=self.validated()
        old=copy.deepcopy(row)
        evaluate_point(row,p,1280,720)
        self.assertEqual(p,P)
        self.assertEqual(row,old)

    def test_zero_pixel_band_and_exact_synthetic_point(self):
        x,z=project_pixel((320,450),P)
        row=self.validated(measured_x_m=str(x),measured_z_m=str(z),pixel_half_width_px="0")
        r=evaluate_point(row,P,1280,720)
        self.assertEqual(r["position_error_m"],0.)
        self.assertEqual(r["sampled_z_min_m"],r["sampled_z_max_m"])

    def session(self,root):
        session=root/"synthetic_test_session"
        session.mkdir()
        (session/"metadata.json").write_text(json.dumps(dict(parameters=P,
            requested_camera_width=1280,requested_camera_height=720)))
        write_csv(session/"detections.csv",[dict(frame=i,time_sec=i/30) for i in range(1,4)])
        writer=cv2.VideoWriter(str(session/"raw.avi"),cv2.VideoWriter_fourcc(*"MJPG"),30,(1280,720))
        self.assertTrue(writer.isOpened(),"MJPG writer required for integration test")
        for i in range(3): writer.write(np.full((720,1280,3),50+i*20,np.uint8))
        writer.release()
        points=root/"synthetic_points.csv"
        write_csv(points,[self.point()])
        return session,points

    def test_cli_workflow_full_resolution_pixel_export_and_no_fit(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            session,points=self.session(root)
            before=(session/"metadata.json").read_bytes()
            output=root/"results"
            summary=evaluate_session(session,points,output)
            self.assertFalse(summary["fitted_coefficients"])
            self.assertFalse(summary["box_lateral_affine_applied"])
            self.assertEqual(summary["decision"],"DIAGNOSTIC_ONLY_NO_CALIBRATION_PROMOTION")
            self.assertEqual(before,(session/"metadata.json").read_bytes())
            with (output/"raw_frame_manifest.csv").open() as f: manifest=list(csv.DictReader(f))[0]
            frame=cv2.imread(str(output/manifest["png"]))
            self.assertEqual(frame.shape,(720,1280,3))
            self.assertEqual(hashlib.sha256(frame.tobytes()).hexdigest(),manifest["decoded_bgr_pixels_sha256"])
            with self.assertRaises(ValueError): evaluate_session(session,points,output)

    def test_missing_frame_or_geometry_never_produces_result(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            session,points=self.session(root)
            write_csv(points,[self.point(frame="4")])
            with self.assertRaises(ValueError): evaluate_session(session,points,root/"results")
            self.assertFalse((root/"results").exists())
            metadata=json.loads((session/"metadata.json").read_text())
            del metadata["parameters"]["pitch_deg"]
            (session/"metadata.json").write_text(json.dumps(metadata))
            with self.assertRaises(ValueError): evaluate_session(session,points,root/"results")


if __name__=="__main__":
    unittest.main()
