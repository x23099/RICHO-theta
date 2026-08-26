import sys
import unittest
from pathlib import Path


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

from frame_timing import (  # noqa: E402
    PROCESSING_TIMING_FIELDS,
    elapsed_ms,
    format_processing_timings,
)


class FrameTimingTest(unittest.TestCase):
    def test_elapsed_ms_uses_nonnegative_milliseconds(self):
        self.assertAlmostEqual(elapsed_ms(10.0, now=10.0125), 12.5)
        self.assertEqual(elapsed_ms(10.0, now=9.0), 0.0)

    def test_csv_values_follow_schema_and_leave_missing_fields_empty(self):
        values = {
            PROCESSING_TIMING_FIELDS[0]: 1.23456,
            PROCESSING_TIMING_FIELDS[-1]: 30,
        }

        serialized = format_processing_timings(values)

        self.assertEqual(len(serialized), len(PROCESSING_TIMING_FIELDS))
        self.assertEqual(serialized[0], "1.235")
        self.assertEqual(serialized[1], "")
        self.assertEqual(serialized[-1], "30.000")


if __name__ == "__main__":
    unittest.main()
