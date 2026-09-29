#!/usr/bin/env python3
"""Publish a repeatable stop/move/stop mock-odometry scenario.

This utility deliberately refuses ``/odom`` so it cannot replace live Kobuki
odometry by accident.  Every attempted publish is flushed to CSV immediately,
including the actual monotonic, wall-clock, and ROS timestamps.
"""

from __future__ import annotations

import argparse
import csv
import math
import select
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


MAX_DURATION_SEC = 120.0
MIN_RATE_HZ = 10.0
MAX_RATE_HZ = 60.0
MAX_SPEED_MPS = 0.5


@dataclass(frozen=True)
class ScenarioSample:
    sequence: int
    phase: str
    planned_elapsed_sec: float
    linear_mps: float


def build_scenario_schedule(
    *,
    lead_in_sec=5.0,
    motion_sec=15.0,
    lead_out_sec=5.0,
    speed_mps=0.25,
    rate_hz=30.0,
):
    """Build deterministic samples for stop -> move -> stop."""
    durations = tuple(
        float(value) for value in (lead_in_sec, motion_sec, lead_out_sec)
    )
    rate_hz = float(rate_hz)
    speed_mps = float(speed_mps)
    if any(
        not math.isfinite(value) or not 0.0 < value <= MAX_DURATION_SEC
        for value in durations
    ):
        raise ValueError(
            "each phase duration must be within "
            f"(0, {MAX_DURATION_SEC:g}]"
        )
    if not math.isfinite(rate_hz) or not MIN_RATE_HZ <= rate_hz <= MAX_RATE_HZ:
        raise ValueError(
            f"rate must be within [{MIN_RATE_HZ:g}, {MAX_RATE_HZ:g}] Hz"
        )
    if not math.isfinite(speed_mps) or not 0.0 < speed_mps <= MAX_SPEED_MPS:
        raise ValueError(f"speed must be within (0, {MAX_SPEED_MPS:g}] m/s")

    samples = []
    sequence = 0
    elapsed = 0.0
    phases = (
        ("initial_stop", durations[0], 0.0),
        ("forward_0p25", durations[1], speed_mps),
        ("final_stop", durations[2], 0.0),
    )
    for phase, duration, velocity in phases:
        count = max(1, int(round(duration * rate_hz)))
        for phase_index in range(count):
            samples.append(
                ScenarioSample(
                    sequence=sequence,
                    phase=phase,
                    planned_elapsed_sec=elapsed + phase_index / rate_hz,
                    linear_mps=velocity,
                )
            )
            sequence += 1
        elapsed += duration
    return samples


def validate_topic(topic: str) -> str:
    topic = str(topic).strip()
    if topic == "/odom":
        raise ValueError("publishing mock data to /odom is forbidden")
    if not topic.startswith("/phase5/") or topic == "/phase5/":
        raise ValueError("mock ODOM topic must be below /phase5/")
    return topic


def build_parser():
    parser = argparse.ArgumentParser(
        description=(
            "Publish stop -> 0.25 m/s -> stop mock ODOM and log actual "
            "send times"
        )
    )
    parser.add_argument("--topic", default="/phase5/mock_odom")
    parser.add_argument("--lead-in-sec", type=float, default=5.0)
    parser.add_argument("--motion-sec", type=float, default=15.0)
    parser.add_argument("--lead-out-sec", type=float, default=5.0)
    parser.add_argument("--speed-mps", type=float, default=0.25)
    parser.add_argument("--rate-hz", type=float, default=30.0)
    parser.add_argument("--output-csv", type=Path, required=True)
    parser.add_argument(
        "--wait-for-enter",
        action="store_true",
        help=(
            "keep the same publisher alive at zero speed until Enter, then "
            "run the scenario"
        ),
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="validate and print the schedule without importing ROS or writing CSV",
    )
    return parser


CSV_FIELDS = (
    "sequence", "phase", "planned_elapsed_sec", "actual_elapsed_sec",
    "run_elapsed_sec",
    "monotonic_sec", "wall_time_utc", "ros_stamp_sec", "ros_stamp_nanosec",
    "linear_mps", "angular_radps", "publish_success",
)


def poll_stdin_for_enter(timeout_sec: float, input_stream=sys.stdin) -> bool:
    """Return True after consuming one input line, or False on timeout."""
    readable, _, _ = select.select(
        [input_stream], [], [], max(0.0, float(timeout_sec))
    )
    if not readable:
        return False
    if input_stream.readline() == "":
        raise RuntimeError("standard input closed while waiting for Enter")
    return True


def publish_waiting_zeros(*, publish_zero, rate_hz, poll_start) -> int:
    """Publish zero continuously until the operator requests scenario start."""
    count = 0
    period_sec = 1.0 / float(rate_hz)
    while True:
        publish_zero(count)
        count += 1
        if poll_start(period_sec):
            return count


def run_scenario(
    args,
    *,
    monotonic_clock=time.monotonic,
    sleep=time.sleep,
    poll_start=poll_stdin_for_enter,
) -> int:
    topic = validate_topic(args.topic)
    schedule = build_scenario_schedule(
        lead_in_sec=args.lead_in_sec,
        motion_sec=args.motion_sec,
        lead_out_sec=args.lead_out_sec,
        speed_mps=args.speed_mps,
        rate_hz=args.rate_hz,
    )
    total_sec = args.lead_in_sec + args.motion_sec + args.lead_out_sec
    if args.dry_run:
        print(
            f"[DRY-RUN] topic={topic}, samples={len(schedule)}, "
            f"duration={total_sec:.3f}s, speed={args.speed_mps:.3f}m/s, "
            f"wait_for_enter={bool(args.wait_for_enter)}"
        )
        return 0

    try:
        import rclpy
        from nav_msgs.msg import Odometry
    except ImportError as error:
        raise RuntimeError(
            "ROS 2 rclpy/nav_msgs is unavailable; source the ROS workspace"
        ) from error

    output_csv = args.output_csv.expanduser().resolve()
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    rclpy.init(args=None)
    node = rclpy.create_node("phase5_mock_odom_scenario")
    publisher = node.create_publisher(Odometry, topic, 10)
    run_start = monotonic_clock()
    interrupted = False
    try:
        with output_csv.open("w", newline="") as output_file:
            writer = csv.DictWriter(output_file, fieldnames=CSV_FIELDS)
            writer.writeheader()
            output_file.flush()
            last_phase = None

            def publish(
                *,
                sequence,
                phase,
                planned_elapsed_sec,
                linear_mps,
                scenario_start,
            ):
                now_mono = monotonic_clock()
                stamp = node.get_clock().now().to_msg()
                message = Odometry()
                message.header.stamp = stamp
                message.header.frame_id = "odom"
                message.child_frame_id = "base_footprint"
                message.twist.twist.linear.x = float(linear_mps)
                success = True
                try:
                    publisher.publish(message)
                except Exception:
                    success = False
                writer.writerow({
                    "sequence": sequence,
                    "phase": phase,
                    "planned_elapsed_sec": (
                        ""
                        if planned_elapsed_sec is None
                        else f"{planned_elapsed_sec:.9f}"
                    ),
                    "actual_elapsed_sec": (
                        ""
                        if scenario_start is None
                        else f"{now_mono - scenario_start:.9f}"
                    ),
                    "run_elapsed_sec": f"{now_mono - run_start:.9f}",
                    "monotonic_sec": f"{now_mono:.9f}",
                    "wall_time_utc": datetime.now(timezone.utc).isoformat(),
                    "ros_stamp_sec": int(stamp.sec),
                    "ros_stamp_nanosec": int(stamp.nanosec),
                    "linear_mps": f"{linear_mps:.6f}",
                    "angular_radps": "0.000000",
                    "publish_success": int(success),
                })
                output_file.flush()
                if not success:
                    raise RuntimeError("mock ODOM publish failed")

            sequence_offset = 0
            if args.wait_for_enter:
                print(
                    "[WAIT] Publishing linear.x=0.000 m/s. "
                    "Press Enter to start the stop/move/stop scenario.",
                    flush=True,
                )
                sequence_offset = publish_waiting_zeros(
                    publish_zero=lambda sequence: publish(
                        sequence=sequence,
                        phase="waiting_for_start",
                        planned_elapsed_sec=None,
                        linear_mps=0.0,
                        scenario_start=None,
                    ),
                    rate_hz=args.rate_hz,
                    poll_start=poll_start,
                )
                print("[START] Enter received; scenario begins.", flush=True)

            start = monotonic_clock()
            for sample in schedule:
                deadline = start + sample.planned_elapsed_sec
                remaining = deadline - monotonic_clock()
                if remaining > 0.0:
                    sleep(remaining)
                if sample.phase != last_phase:
                    print(
                        f"[PHASE] {sample.phase}: "
                        f"t={sample.planned_elapsed_sec:.3f}s, "
                        f"linear.x={sample.linear_mps:.3f}m/s",
                        flush=True,
                    )
                    last_phase = sample.phase
                publish(
                    sequence=sequence_offset + sample.sequence,
                    phase=sample.phase,
                    planned_elapsed_sec=sample.planned_elapsed_sec,
                    linear_mps=sample.linear_mps,
                    scenario_start=start,
                )
    except KeyboardInterrupt:
        interrupted = True
    finally:
        # Always leave the mock topic at zero, including Ctrl-C/error paths.
        try:
            for _ in range(3):
                stamp = node.get_clock().now().to_msg()
                message = Odometry()
                message.header.stamp = stamp
                message.header.frame_id = "odom"
                message.child_frame_id = "base_footprint"
                message.twist.twist.linear.x = 0.0
                publisher.publish(message)
                sleep(0.02)
        finally:
            node.destroy_node()
            rclpy.shutdown()
    if interrupted:
        print(f"[INTERRUPTED] Safety stop sent; partial log: {output_csv}")
        return 130
    print(f"[PASS] Scenario log: {output_csv}")
    return 0


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        return run_scenario(args)
    except (ValueError, RuntimeError) as error:
        print(f"[FAIL] {error}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
