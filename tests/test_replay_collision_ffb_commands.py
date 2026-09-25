"""Tests for recorded collision-risk command replay."""

import csv
import io
import tarfile

import pytest

from replay_collision_ffb_commands import (
    read_detection_rows,
    select_detection_member,
    summarize_replay,
    validate_replay_settings,
    write_results,
)


def write_detections(path):
    """Write a minimal detections CSV fixture."""
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "frame",
                "time_sec",
                "collision_risk_level",
            ],
        )
        writer.writeheader()
        writer.writerow({
            "frame": 1,
            "time_sec": 0.0,
            "collision_risk_level": "CLEAR",
        })
        writer.writerow({
            "frame": 2,
            "time_sec": 0.033,
            "collision_risk_level": "WARNING",
        })


def test_select_detection_member_requires_unambiguous_session():
    """Archive selection must reject an ambiguous session request."""
    members = ["r01/detections.csv", "r02/detections.csv"]

    with pytest.raises(ValueError, match="specify --session"):
        select_detection_member(members, None)

    assert select_detection_member(members, "r02") == "r02/detections.csv"


def test_read_detection_rows_from_csv(tmp_path):
    """Detection rows can be read directly from CSV."""
    path = tmp_path / "detections.csv"
    write_detections(path)

    session, rows = read_detection_rows(path)

    assert session == tmp_path.name
    assert [row["collision_risk_level"] for row in rows] == [
        "CLEAR",
        "WARNING",
    ]


def test_read_detection_rows_from_tar_xz(tmp_path):
    """Detection rows can be read from one exact archive session."""
    path = tmp_path / "recording.tar.xz"
    content = (
        "frame,time_sec,collision_risk_level\n"
        "1,0.0,CLEAR\n"
        "2,0.033,WARNING\n"
    ).encode()
    with tarfile.open(path, mode="w:xz") as archive:
        info = tarfile.TarInfo("session_r01/detections.csv")
        info.size = len(content)
        archive.addfile(info, io.BytesIO(content))

    session, rows = read_detection_rows(path, "session_r01")

    assert session == "session_r01"
    assert len(rows) == 2


def test_hardware_replay_requires_physical_acknowledgement():
    """Recorded replay must not trigger hardware without a separate gate."""
    with pytest.raises(ValueError, match="acknowledge-physical-output"):
        validate_replay_settings(
            expected_output_mode="hardware",
            freshness_mode="challenge",
            acknowledge_physical_output=False,
        )

    validate_replay_settings(
        expected_output_mode="hardware",
        freshness_mode="challenge",
        acknowledge_physical_output=True,
    )


def test_replay_report_records_unknown_single_pulse(tmp_path):
    """Replay provenance must include the distinct UNKNOWN cadence."""
    summary = {
        "decision": "PASS",
        "checks": {"synthetic": True},
        "command_count": 1,
        "active_command_count": 0,
        "status_count": 1,
        "active_status_count": 0,
        "fault_count": 0,
        "max_applied_magnitude": 0.0,
    }

    write_results(
        tmp_path,
        input_path=tmp_path / "synthetic.csv",
        session="synthetic",
        rate_hz=30.0,
        cadence="triple",
        cadence_duration_sec=0.5,
        cadence_rate_hz=30.0,
        unknown_pulse_duration_sec=0.1,
        expected_output_mode="dry_run",
        freshness_mode="challenge",
        acknowledge_physical_output=False,
        command_rows=[{"collision_ffb_publish_success": 1}],
        status_rows=[{"output_active": 0}],
        summary=summary,
    )

    report = (tmp_path / "replay_report.md").read_text()
    payload = (tmp_path / "replay_summary.json").read_text()
    assert "UNKNOWN cadence: `single` / `0.100 s`" in report
    assert '"unknown_pulse_duration_sec": 0.1' in payload


def test_replay_summary_passes_dry_run_transport():
    """A complete dry-run transport trace must pass."""
    commands = [
        {
            "collision_ffb_publish_success": 1,
            "collision_ffb_active": 1,
        },
        {
            "collision_ffb_publish_success": 1,
            "collision_ffb_active": 0,
        },
    ]
    statuses = [
        {
            "output_active": 1,
            "fault": 0,
            "output_mode": "dry_run",
            "applied_magnitude": 0.05,
        },
        {
            "output_active": 0,
            "fault": 0,
            "output_mode": "dry_run",
            "applied_magnitude": 0.0,
        },
    ]

    summary = summarize_replay(commands, statuses, expected_mode="dry_run")

    assert summary["decision"] == "PASS"
    assert summary["active_command_count"] == 1
    assert summary["active_status_count"] == 1


@pytest.mark.parametrize(
    "field,value,failed_check",
    [
        ("fault", 1, "no_fault"),
        ("output_mode", "hardware", "expected_mode_only"),
        ("applied_magnitude", 0.051, "adapter_cap_respected"),
    ],
)
def test_replay_summary_rejects_unsafe_status(field, value, failed_check):
    """A fault or unexpected adapter mode must fail the replay."""
    commands = [{
        "collision_ffb_publish_success": 1,
        "collision_ffb_active": 1,
    }]
    statuses = [{
        "output_active": 1,
        "fault": 0,
        "output_mode": "dry_run",
        "applied_magnitude": 0.05,
    }]
    statuses[0][field] = value

    summary = summarize_replay(commands, statuses, expected_mode="dry_run")

    assert summary["decision"] == "FAIL"
    assert not summary["checks"][failed_check]
