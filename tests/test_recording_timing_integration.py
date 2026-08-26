import csv
import io
import sys
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

from bird_eye import CalibrationWindow, RECORDING_CSV_FIELDS  # noqa: E402
from frame_timing import PROCESSING_TIMING_FIELDS  # noqa: E402


class _Writer:
    def __init__(self):
        self.frames = 0

    def write(self, frame):
        self.frames += 1


class _Capture:
    def get(self, _property):
        return 30.0


class _Label:
    def setText(self, text):
        self.text = text


class RecordingTimingIntegrationTest(unittest.TestCase):
    def test_recorded_row_matches_header_and_contains_same_frame_timings(self):
        window = CalibrationWindow.__new__(CalibrationWindow)
        window.is_recording = True
        window._open_recording_writers = lambda _frame: True
        window.recording_writers = {
            name: _Writer() for name in ("raw", "bev", "detection")
        }
        window.current_frame_timing = {
            field: index + 0.25
            for index, field in enumerate(PROCESSING_TIMING_FIELDS[:-2])
        }
        window.frame_processing_started_perf = time.perf_counter() - 0.010
        window.recording_frame_count = 0
        window.cap = _Capture()
        window.args = SimpleNamespace(camera_fps=30)
        window.last_blue_detection = None
        window.last_blue_track = None
        window.last_blue_processing_timestamp = 2.0
        window.recording_start_monotonic = 1.0
        stream = io.StringIO(newline="")
        window.recording_csv_writer = csv.writer(stream)
        window.last_blue_tracker_diagnostics = {}
        window.last_blue_gate_diagnostics = {}
        window.odometry_is_recent = lambda: False
        window.odom_linear_x = 0.0
        window.odom_angular_z = 0.0
        window.cmd_linear_x = 0.0
        window.cmd_angular_z = 0.0
        window.last_prediction_source = "none"
        window.last_blue_collision = None
        window.record_status_label = _Label()
        frame = np.zeros((8, 8, 3), dtype=np.uint8)

        window.record_frames(frame, frame, frame)

        row = next(csv.reader(io.StringIO(stream.getvalue())))
        values = dict(zip(RECORDING_CSV_FIELDS, row))
        self.assertEqual(len(row), len(RECORDING_CSV_FIELDS))
        self.assertEqual(values["processing_capture_read_ms"], "1.250")
        self.assertNotEqual(values["processing_video_write_ms"], "")
        self.assertGreater(float(values["processing_total_before_csv_ms"]), 0.0)
        self.assertEqual(window.recording_writers["raw"].frames, 1)


if __name__ == "__main__":
    unittest.main()
