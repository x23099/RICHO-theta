import sys
import unittest
from pathlib import Path


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

from diagnose_recording_timing import summarize_rows  # noqa: E402


class RecordingTimingDiagnosisTest(unittest.TestCase):
    def test_summarizes_monotonic_intervals_and_video_sizes(self):
        rows = [
            {
                "monotonic_time_sec": value,
                "time_sec": "bad",
                "processing_capture_read_ms": "2.0",
                "processing_total_before_csv_ms": total,
            }
            for value, total in zip(
                ("0.0", "0.033", "0.066", "0.105"),
                ("30", "32", "34", "36"),
            )
        ]
        summary = summarize_rows(
            "trial",
            "/recording/trial",
            {"requested_camera_fps": 30},
            rows,
            {"raw": 4096, "bev": 2048, "detection": 1024},
        )

        self.assertEqual(summary["frames"], 4)
        self.assertAlmostEqual(summary["effective_fps"], 3 / 0.105)
        self.assertEqual(summary["fps_within_one_percent"], 0)
        self.assertAlmostEqual(summary["raw_kib_per_frame"], 1.0)
        self.assertAlmostEqual(summary["dt_over_40ms_rate"], 0.0)
        self.assertAlmostEqual(summary["capture_read_median_ms"], 2.0)
        self.assertAlmostEqual(summary["processing_total_median_ms"], 33.0)
        self.assertAlmostEqual(summary["processing_over_budget_rate"], 0.5)


if __name__ == "__main__":
    unittest.main()
