import contextlib
import io
import subprocess
import sys
import unittest
from pathlib import Path


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

from run_field_experiment import (  # noqa: E402
    build_bird_eye_command,
    build_parser,
    build_preflight_command,
    run_experiment,
    validate_args,
)


def parsed_args(*extra):
    parser = build_parser()
    args = parser.parse_args(
        [
            "--record-dir",
            "recordings/test run",
            "--experiment-label",
            "left_x-0.3_z0.9",
            *extra,
        ]
    )
    validate_args(parser, args)
    return args


class FieldExperimentRunnerTest(unittest.TestCase):
    def test_shared_arguments_are_identical_between_commands(self):
        args = parsed_args(
            "--camera-device",
            "2",
            "--camera-width",
            "640",
            "--camera-height",
            "480",
            "--camera-fps",
            "20",
            "--odom-topic",
            "/robot/odom",
        )

        preflight = build_preflight_command(args)
        application = build_bird_eye_command(args)

        def option(command, name):
            return command[command.index(name) + 1]

        self.assertEqual(
            option(preflight, "--config"), option(application, "--config")
        )
        self.assertEqual(
            option(preflight, "--record-dir"), option(application, "--record-dir")
        )
        self.assertEqual(option(preflight, "--camera-device"), "2")
        self.assertEqual(option(application, "--device"), "2")
        self.assertEqual(option(preflight, "--camera-width"), "640")
        self.assertEqual(option(application, "--cam-width"), "640")
        self.assertEqual(option(preflight, "--camera-height"), "480")
        self.assertEqual(option(application, "--cam-height"), "480")
        self.assertEqual(option(preflight, "--camera-fps"), "20.0")
        self.assertEqual(option(application, "--camera-fps"), "20.0")
        self.assertEqual(option(preflight, "--odom-topic"), "/robot/odom")
        self.assertEqual(option(application, "--odom-topic"), "/robot/odom")
        self.assertIn("--require-clean-git", preflight)

    def test_preflight_failure_does_not_start_application(self):
        calls = []

        def failing_runner(command, cwd):
            calls.append((command, cwd))
            return subprocess.CompletedProcess(command, 7)

        with contextlib.redirect_stdout(io.StringIO()):
            with contextlib.redirect_stderr(io.StringIO()):
                result = run_experiment(parsed_args(), runner=failing_runner)

        self.assertEqual(result, 7)
        self.assertEqual(len(calls), 1)

    def test_success_starts_application_after_preflight(self):
        calls = []

        def passing_runner(command, cwd):
            calls.append((command, cwd))
            return subprocess.CompletedProcess(command, 0)

        with contextlib.redirect_stdout(io.StringIO()):
            result = run_experiment(parsed_args(), runner=passing_runner)

        self.assertEqual(result, 0)
        self.assertEqual(len(calls), 2)
        self.assertIn("preflight_field_experiment.py", calls[0][0][1])
        self.assertIn("bird_eye.py", calls[1][0][1])

    def test_dry_run_executes_nothing_and_quotes_paths(self):
        calls = []
        args = parsed_args("--dry-run")
        output = io.StringIO()

        with contextlib.redirect_stdout(output):
            result = run_experiment(
                args,
                runner=lambda *runner_args, **runner_kwargs: calls.append(
                    (runner_args, runner_kwargs)
                ),
            )

        self.assertEqual(result, 0)
        self.assertEqual(calls, [])
        self.assertIn("Decision: DRY-RUN", output.getvalue())
        self.assertIn("'", output.getvalue())

    def test_allow_dirty_git_is_explicit(self):
        command = build_preflight_command(parsed_args("--allow-dirty-git"))

        self.assertNotIn("--require-clean-git", command)

    def test_rejects_blank_odom_topic(self):
        parser = build_parser()
        args = parser.parse_args(
            [
                "--record-dir",
                "recordings/test",
                "--experiment-label",
                "trial",
                "--odom-topic",
                " ",
            ]
        )

        with self.assertRaises(SystemExit):
            with contextlib.redirect_stderr(io.StringIO()):
                validate_args(parser, args)

    def test_rejects_non_finite_numeric_values(self):
        parser = build_parser()

        with self.assertRaises(SystemExit):
            with contextlib.redirect_stderr(io.StringIO()):
                parser.parse_args(
                    [
                        "--record-dir",
                        "recordings/test",
                        "--experiment-label",
                        "trial",
                        "--camera-fps",
                        "nan",
                    ]
                )


if __name__ == "__main__":
    unittest.main()
