#!/usr/bin/env python3
"""Run preflight and bird_eye.py with one shared experiment configuration."""

from __future__ import annotations

import argparse
import json
import math
import shlex
import signal
import subprocess
import sys
import time
from pathlib import Path


REPOSITORY_DIR = Path(__file__).resolve().parents[1]
PREFLIGHT_SCRIPT = Path(__file__).with_name("preflight_field_experiment.py")
BIRD_EYE_SCRIPT = Path(__file__).with_name("bird_eye.py")
FFB_RELAY_SCRIPT = Path(__file__).with_name("collision_ffb_relay.py")
DEFAULT_CONFIG = Path(__file__).with_name(
    "bird_eye_config_raw_ground_distance.json"
)


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return parsed


def positive_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or parsed <= 0.0:
        raise argparse.ArgumentTypeError("must be greater than 0")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run field-experiment preflight, then launch bird_eye.py only "
            "when every required check passes"
        )
    )
    parser.add_argument("--record-dir", type=Path, required=True)
    parser.add_argument("--experiment-label", required=True)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--dynamic-ttc-profile", type=Path)
    parser.add_argument("--camera-device", default="0")
    parser.add_argument("--camera-width", type=positive_int, default=1280)
    parser.add_argument("--camera-height", type=positive_int, default=720)
    parser.add_argument("--camera-fps", type=positive_float, default=30.0)
    parser.add_argument("--camera-frames", type=positive_int, default=60)
    parser.add_argument("--odom-topic", default="/odom")
    parser.add_argument("--odom-timeout-sec", type=positive_float, default=3.0)
    parser.add_argument("--minimum-free-gb", type=float, default=20.0)
    parser.add_argument(
        "--skip-tests",
        action="store_true",
        help="Skip unit tests inside preflight (not recommended for a holdout)",
    )
    parser.add_argument(
        "--allow-dirty-git",
        action="store_true",
        help="Allow preflight to continue with uncommitted repository changes",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print both commands without opening the camera or starting ROS",
    )
    return parser


def validate_args(parser: argparse.ArgumentParser, args: argparse.Namespace) -> None:
    if not args.experiment_label.strip():
        parser.error("--experiment-label must not be blank")
    if not args.odom_topic.strip():
        parser.error("--odom-topic must not be blank")
    if not math.isfinite(args.minimum_free_gb) or args.minimum_free_gb < 0.0:
        parser.error("--minimum-free-gb must be a finite number of at least 0")


def _shared_paths(args: argparse.Namespace) -> tuple[str, str]:
    config = str(args.config.expanduser().resolve())
    record_dir = str(args.record_dir.expanduser().resolve())
    return config, record_dir


def build_preflight_command(args: argparse.Namespace) -> list[str]:
    config, record_dir = _shared_paths(args)
    command = [
        sys.executable,
        str(PREFLIGHT_SCRIPT),
        "--config",
        config,
        "--record-dir",
        record_dir,
        "--minimum-free-gb",
        str(args.minimum_free_gb),
        "--camera-device",
        str(args.camera_device),
        "--camera-width",
        str(args.camera_width),
        "--camera-height",
        str(args.camera_height),
        "--camera-fps",
        str(args.camera_fps),
        "--camera-frames",
        str(args.camera_frames),
        "--odom-topic",
        args.odom_topic,
        "--odom-timeout-sec",
        str(args.odom_timeout_sec),
    ]
    if args.skip_tests:
        command.append("--skip-tests")
    if args.dynamic_ttc_profile is not None:
        command.extend(
            [
                "--dynamic-ttc-profile",
                str(args.dynamic_ttc_profile.expanduser().resolve()),
            ]
        )
    if not args.allow_dirty_git:
        command.append("--require-clean-git")
    return command


def build_bird_eye_command(args: argparse.Namespace) -> list[str]:
    config, record_dir = _shared_paths(args)
    return [
        sys.executable,
        str(BIRD_EYE_SCRIPT),
        "--device",
        str(args.camera_device),
        "--cam-width",
        str(args.camera_width),
        "--cam-height",
        str(args.camera_height),
        "--camera-fps",
        str(args.camera_fps),
        "--config",
        config,
        "--record-dir",
        record_dir,
        "--experiment-label",
        args.experiment_label,
        "--odom-topic",
        args.odom_topic,
    ]


def load_experiment_config(args: argparse.Namespace) -> dict:
    with args.config.expanduser().resolve().open() as config_file:
        return json.load(config_file)


def build_ffb_relay_command(args: argparse.Namespace) -> list[str] | None:
    """Build the optional camera-host relay command from the shared config."""
    config = load_experiment_config(args)
    if config.get("collision_ffb_relay_enabled", 0) != 1:
        return None
    return [
        sys.executable,
        str(FFB_RELAY_SCRIPT),
        "--intent-topic",
        str(config.get("collision_ffb_intent_topic", "/collision/ffb_intent")),
        "--command-topic",
        str(config.get("collision_ffb_command_topic", "/collision/ffb_command")),
        "--challenge-topic",
        str(
            config.get(
                "collision_ffb_challenge_topic", "/collision/ffb_challenge"
            )
        ),
        "--expected-source",
        str(config.get("collision_ffb_source", "bird_eye")),
        "--intent-max-age-sec",
        str(config.get("collision_ffb_intent_max_age_sec", 0.1)),
        "--challenge-max-age-sec",
        str(config.get("collision_ffb_challenge_max_age_sec", 0.06)),
    ]


def stop_ffb_relay(process) -> None:
    """Stop the child relay and escalate only if graceful shutdown stalls."""
    if process is None or process.poll() is not None:
        return
    process.send_signal(signal.SIGINT)
    try:
        process.wait(timeout=2.0)
    except subprocess.TimeoutExpired:
        process.terminate()
        process.wait(timeout=2.0)


def run_experiment(
    args: argparse.Namespace,
    runner=subprocess.run,
    popen_factory=subprocess.Popen,
    startup_wait=time.sleep,
) -> int:
    preflight_command = build_preflight_command(args)
    bird_eye_command = build_bird_eye_command(args)
    try:
        relay_command = build_ffb_relay_command(args)
    except (OSError, json.JSONDecodeError) as error:
        print(f"[FAIL] Cannot read experiment config: {error}", file=sys.stderr)
        return 1
    print("Preflight:", shlex.join(preflight_command), flush=True)
    if relay_command is not None:
        print("FFB relay:", shlex.join(relay_command), flush=True)
    print("Application:", shlex.join(bird_eye_command), flush=True)
    if args.dry_run:
        print("Decision: DRY-RUN (no command executed)")
        return 0

    print("[INFO] Running preflight...", flush=True)
    preflight = runner(preflight_command, cwd=REPOSITORY_DIR)
    if preflight.returncode != 0:
        print(
            f"[FAIL] Preflight exited with status {preflight.returncode}; "
            "bird_eye.py was not started.",
            file=sys.stderr,
        )
        return preflight.returncode or 1

    relay_process = None
    try:
        if relay_command is not None:
            print(
                "[PASS] Preflight passed; starting collision FFB relay...",
                flush=True,
            )
            relay_process = popen_factory(relay_command, cwd=REPOSITORY_DIR)
            startup_wait(0.5)
            relay_status = relay_process.poll()
            if relay_status is not None:
                print(
                    "[FAIL] Collision FFB relay exited during startup with "
                    f"status {relay_status}; bird_eye.py was not started.",
                    file=sys.stderr,
                )
                return relay_status or 1
        print("[PASS] Preflight passed; starting bird_eye.py...", flush=True)
        application = runner(bird_eye_command, cwd=REPOSITORY_DIR)
        return application.returncode
    finally:
        stop_ffb_relay(relay_process)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    validate_args(parser, args)
    return run_experiment(args)


if __name__ == "__main__":
    raise SystemExit(main())
