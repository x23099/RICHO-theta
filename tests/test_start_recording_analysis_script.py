import os
import subprocess
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "start_recording_analysis.sh"


class StartRecordingAnalysisScriptTest(unittest.TestCase):
    def run_script(self, *arguments, env=None):
        return subprocess.run(
            ["bash", str(SCRIPT), *arguments],
            check=False,
            capture_output=True,
            text=True,
            env=env,
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

    def test_default_invocation_uses_current_config_and_profile(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fake_python = root / "fake-python"
            call_log = root / "calls.txt"
            fake_python.write_text(
                "#!/bin/bash\n"
                "printf 'CALL\\n' >> \"$CALL_LOG\"\n"
                "printf '%s\\n' \"$@\" >> \"$CALL_LOG\"\n"
            )
            fake_python.chmod(0o755)
            environment = dict(os.environ)
            environment.update(
                {"PYTHON_BIN": str(fake_python), "CALL_LOG": str(call_log)}
            )

            result = self.run_script(
                str(root / "recording.tar.xz"),
                str(root / "output"),
                env=environment,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            calls = call_log.read_text()
            self.assertEqual(calls.count("CALL\n"), 2)
            self.assertIn(
                "src/bird_eye_config_ttc_conservative_candidate_20260903.json",
                calls,
            )
            self.assertIn(
                "src/dynamic_ttc_evaluation_profile_v5_candidate.json",
                calls,
            )
            self.assertIn("--profile", calls)


if __name__ == "__main__":
    unittest.main()
