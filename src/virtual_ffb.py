#!/usr/bin/env python3
"""Generate and summarize virtual FFB demand without touching hardware."""

from __future__ import annotations

import argparse
import csv
import math
from dataclasses import dataclass
from pathlib import Path

from diagnose_lateral_gate_asymmetry import load_sessions


@dataclass(frozen=True)
class VirtualFfbCommand:
    risk_level: str
    active: bool
    normalized_magnitude: float
    pattern: str
    reason: str


class VirtualFfbPolicy:
    """Map collision states to an abstract, device-independent FFB demand."""

    def __init__(
        self,
        warning_magnitude=0.25,
        critical_magnitude=0.40,
        unknown_magnitude=0.15,
    ):
        values = tuple(
            float(value)
            for value in (
                unknown_magnitude,
                warning_magnitude,
                critical_magnitude,
            )
        )
        if any(not math.isfinite(value) for value in values):
            raise ValueError("virtual FFB magnitudes must be finite")
        if not 0.0 <= values[0] <= values[1] <= values[2] <= 1.0:
            raise ValueError(
                "virtual FFB magnitudes must satisfy "
                "0 <= unknown <= warning <= critical <= 1"
            )
        self.unknown_magnitude, self.warning_magnitude, self.critical_magnitude = (
            values
        )

    def command(self, risk_level) -> VirtualFfbCommand:
        level = str(risk_level or "").strip().upper()
        if level in {"CLEAR", "PATH"}:
            return VirtualFfbCommand(level, False, 0.0, "off", "no_alert")
        if level == "WARNING":
            return VirtualFfbCommand(
                level, True, self.warning_magnitude, "steady", "ttc_warning"
            )
        if level == "WARNING_HOLD":
            return VirtualFfbCommand(
                level,
                True,
                self.warning_magnitude,
                "steady_hold",
                "finite_warning_hold",
            )
        if level == "CRITICAL":
            return VirtualFfbCommand(
                level, True, self.critical_magnitude, "steady", "ttc_critical"
            )
        return VirtualFfbCommand(
            "UNKNOWN",
            True,
            self.unknown_magnitude,
            "pulse",
            "invalid_or_unknown_perception",
        )


SUMMARY_FIELDS = (
    "session",
    "experiment_label",
    "frames",
    "active_frames",
    "active_rate",
    "warning_frames",
    "warning_hold_frames",
    "critical_frames",
    "unknown_frames",
    "peak_normalized_magnitude",
    "mean_normalized_magnitude",
    "activation_events",
)


def summarize_rows(session, label, rows, policy=None):
    policy = policy or VirtualFfbPolicy()
    commands = [policy.command(row.get("collision_risk_level")) for row in rows]
    active = [command.active for command in commands]
    activation_events = sum(
        current and (index == 0 or not active[index - 1])
        for index, current in enumerate(active)
    )
    magnitudes = [command.normalized_magnitude for command in commands]
    total = len(commands)
    return {
        "session": session,
        "experiment_label": label,
        "frames": total,
        "active_frames": sum(active),
        "active_rate": sum(active) / total if total else math.nan,
        "warning_frames": sum(c.risk_level == "WARNING" for c in commands),
        "warning_hold_frames": sum(
            c.risk_level == "WARNING_HOLD" for c in commands
        ),
        "critical_frames": sum(c.risk_level == "CRITICAL" for c in commands),
        "unknown_frames": sum(c.risk_level == "UNKNOWN" for c in commands),
        "peak_normalized_magnitude": max(magnitudes, default=0.0),
        "mean_normalized_magnitude": (
            sum(magnitudes) / total if total else math.nan
        ),
        "activation_events": activation_events,
    }


def evaluate_inputs(inputs, policy=None):
    results = []
    for label, source, _metadata, rows in load_sessions(inputs):
        session = source.rsplit("::", 1)[-1] if "::" in source else Path(source).name
        results.append(summarize_rows(session, label, rows, policy=policy))
    return results


def write_results(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=SUMMARY_FIELDS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Replay collision states as device-independent virtual FFB demand"
    )
    parser.add_argument("--input", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    results = evaluate_inputs(args.input)
    if not results:
        parser.error("no recording session was found")
    write_results(args.output, results)
    for row in results:
        print(
            f"{row['experiment_label']}: active={row['active_frames']}/"
            f"{row['frames']}, peak={row['peak_normalized_magnitude']:.2f}, "
            f"events={row['activation_events']}"
        )
    print(f"Results saved: {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
