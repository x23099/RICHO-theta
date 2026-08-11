import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

from evaluate_observation_gates import (  # noqa: E402
    contour_shape_features,
    find_session_directories,
    load_detector_parameters,
    load_phase_labels,
    phase_for_frame,
)


class ObservationReplayDiscoveryTest(unittest.TestCase):
    def test_computes_contour_shape_features(self):
        contour = np.array(
            [[[0, 0]], [[9, 0]], [[9, 4]], [[0, 4]]], dtype=np.int32
        )

        features = contour_shape_features(contour)

        self.assertEqual(features["bbox_width_px"], 10)
        self.assertEqual(features["bbox_height_px"], 5)
        self.assertEqual(features["bbox_aspect_ratio"], 2.0)
        self.assertAlmostEqual(features["contour_solidity"], 1.0)

    def test_finds_nested_recording_sessions(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            complete = root / "group" / "session_a"
            incomplete = root / "session_b"
            complete.mkdir(parents=True)
            incomplete.mkdir()
            (complete / "raw.avi").touch()
            (complete / "metadata.json").write_text("{}")
            (incomplete / "raw.avi").touch()

            self.assertEqual(find_session_directories([root]), [complete.resolve()])

    def test_current_detector_settings_override_recording_metadata(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            session = Path(temp_dir)
            metadata = {
                "parameters": {
                    "camera_height": 0.58,
                    "pitch_deg": 1.0,
                    "blue_ground_contact_min_area": 100.0,
                }
            }
            (session / "metadata.json").write_text(json.dumps(metadata))

            parameters = load_detector_parameters(
                session,
                {
                    "blue_ground_contact_min_area": 300.0,
                    "white_thresh": 135,
                },
            )

            self.assertEqual(parameters["camera_height"], 0.58)
            self.assertEqual(parameters["pitch_deg"], 1.0)
            self.assertEqual(parameters["blue_ground_contact_min_area"], 300.0)
            self.assertNotIn("white_thresh", parameters)

    def test_loads_inclusive_non_overlapping_phase_labels(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            label_path = Path(temp_dir) / "labels.csv"
            label_path.write_text(
                "session,event,phase,start_frame,end_frame\n"
                "shield_z1.0m,1,visible,0,10\n"
                "shield_z1.0m,1,partial_occlusion,11,12\n"
            )

            labels = load_phase_labels(label_path)

            self.assertEqual(
                phase_for_frame(labels["shield_z1.0m"], 10), ("1", "visible")
            )
            self.assertEqual(
                phase_for_frame(labels["shield_z1.0m"], 11),
                ("1", "partial_occlusion"),
            )
            self.assertEqual(
                phase_for_frame(labels["shield_z1.0m"], 20), ("", "")
            )


if __name__ == "__main__":
    unittest.main()
