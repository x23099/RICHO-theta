import subprocess
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "start_recording_analysis.sh"


class StartRecordingAnalysisScriptTest(unittest.TestCase):
    def run_script(self, *arguments):
        return subprocess.run(
            ["bash", str(SCRIPT), *arguments],
            check=False,
            capture_output=True,
            text=True,
        )

    def test_help_does_not_start_analysis(self):
        result = self.run_script("--help")

        self.assertEqual(result.returncode, 0)
        self.assertIn("Usage:", result.stdout)
        self.assertIn("never accesses a", result.stdout)

    def test_missing_input_is_usage_error(self):
        result = self.run_script()

        self.assertEqual(result.returncode, 2)
        self.assertIn("Usage:", result.stderr)

    def test_rejects_non_archive_input_before_running_python(self):
        result = self.run_script("recording.zip")

        self.assertEqual(result.returncode, 2)
        self.assertIn("must have a .tar.xz extension", result.stderr)


if __name__ == "__main__":
    unittest.main()
