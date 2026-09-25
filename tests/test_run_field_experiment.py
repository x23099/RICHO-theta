import contextlib
import io
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock


SRC_DIR = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC_DIR))

from run_field_experiment import (  # noqa: E402
    build_bird_eye_command,
    build_ffb_relay_command,
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

    def test_v10_starts_and_stops_relay_around_application(self):
        args = parsed_args(
            "--config",
            str(SRC_DIR / "bird_eye_config_ttc_v10_ffb_relay_20260925.json"),
        )
        runner_calls = []

        def runner(command, cwd):
            runner_calls.append((command, cwd))
            return subprocess.CompletedProcess(command, 0)

        class FakeProcess:
            def __init__(self):
                self.signal = None
                self.waited = False

            def poll(self):
                return None

            def send_signal(self, sent_signal):
                self.signal = sent_signal

            def wait(self, timeout):
                self.waited = True
                return 0

        process = FakeProcess()
        popen_calls = []

        def popen_factory(command, cwd):
            popen_calls.append((command, cwd))
            return process

        with contextlib.redirect_stdout(io.StringIO()):
            result = run_experiment(
                args,
                runner=runner,
                popen_factory=popen_factory,
                startup_wait=lambda _seconds: None,
            )

        self.assertEqual(result, 0)
        self.assertEqual(len(runner_calls), 2)
        self.assertEqual(len(popen_calls), 1)
        self.assertIn("collision_ffb_relay.py", popen_calls[0][0][1])
        self.assertEqual(process.signal, __import__("signal").SIGINT)
        self.assertTrue(process.waited)

    def test_v10_relay_command_keeps_topics_and_age_limits_explicit(self):
        args = parsed_args(
            "--config",
            str(SRC_DIR / "bird_eye_config_ttc_v10_ffb_relay_20260925.json"),
        )

        command = build_ffb_relay_command(args)

        self.assertIn("/collision/ffb_intent", command)
        self.assertIn("/collision/ffb_command", command)
        self.assertIn("/collision/ffb_challenge", command)
        self.assertEqual(
            command[command.index("--challenge-max-age-sec") + 1], "0.06"
        )

    def test_v11_relay_command_includes_stability_and_diagnostics(self):
        args = parsed_args(
            "--config",
            str(
                SRC_DIR
                / "bird_eye_config_ttc_v11_ffb_reliability_20260925.json"
            ),
        )

        command = build_ffb_relay_command(args)

        self.assertEqual(
            command[command.index("--challenge-stable-sec") + 1], "1.0"
        )
        self.assertEqual(
            command[command.index("--diagnostic-topic") + 1],
            "/collision/ffb_relay_diagnostics",
        )

    def test_relay_startup_failure_does_not_start_camera(self):
        args = parsed_args(
            "--config",
            str(SRC_DIR / "bird_eye_config_ttc_v10_ffb_relay_20260925.json"),
        )
        runner_calls = []

        def runner(command, cwd):
            runner_calls.append((command, cwd))
            return subprocess.CompletedProcess(command, 0)

        process = Mock()
        process.poll.return_value = 9
        output = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()):
            with contextlib.redirect_stderr(output):
                result = run_experiment(
                    args,
                    runner=runner,
                    popen_factory=lambda *_args, **_kwargs: process,
                    startup_wait=lambda _seconds: None,
                )

        self.assertEqual(result, 9)
        self.assertEqual(len(runner_calls), 1)
        self.assertIn("bird_eye.py was not started", output.getvalue())

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

    def test_dynamic_profile_is_forwarded_to_preflight_only(self):
        args = parsed_args(
            "--dynamic-ttc-profile",
            "src/dynamic_ttc_evaluation_profile_v3_candidate.json",
        )
        preflight = build_preflight_command(args)
        application = build_bird_eye_command(args)

        self.assertIn("--dynamic-ttc-profile", preflight)
        self.assertNotIn("--dynamic-ttc-profile", application)

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
