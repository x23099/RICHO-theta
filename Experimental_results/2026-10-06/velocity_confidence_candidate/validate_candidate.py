#!/usr/bin/env python3
"""人工シナリオの追加応答遅延・UNKNOWN通知を保存。実機を駆動しない。"""
import csv
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))
from evaluate_velocity_confidence_replay import evaluate_rows, write_csv
from offline_velocity_confidence import ConfidenceSettings

root = Path(__file__).resolve().parent


def scenario(name, *, noisy=False, prefix=False, unstable=False):
    result = []
    for i in range(45):
        t = i / 30
        moving_t = (i - 12) / 30 if prefix else t
        available = moving_t >= 0
        # Entire interval remains a constant-speed approach (no artificial stop
        # at a distance floor while visual velocity incorrectly stays at -1).
        z = 1.8 - moving_t
        if noisy:
            z += [.003, -.003, .004, -.001, .002][i % 5]
        if unstable:
            z = [1.1708, 1.0510, 1.0951, 1.0387][i % 4]
        result.append({"frame": i + 1, "time_sec": t, "monotonic_time_sec": t,
                       "track_available": int(available), "track_predicted": "0", "measurement_accepted": int(available),
                       "calibration_valid": int(available), "z_m": z if available else "",
                       "rejection_reason": "initialized" if available and (i == 12 if prefix else i == 0) else "accepted",
                       "relative_vz_mps": -.7 if unstable else -1,
                       "visual_smoothed_vz_mps": -.7 if unstable else -1,
                       "ttc_velocity_source": "conservative_visual", "ttc_sec": z / (.7 if unstable else 1) if available else "",
                       "odom_available": "1", "odom_linear_mps": 0,
                       "path_in_collision_corridor": int(available), "collision_risk_level": "CRITICAL" if available else "CLEAR"})
    return result


summaries, frames = [], []
for name, kwargs, expect_critical in [
    ("clean_fast_moving_target_stationary_robot", {}, True),
    ("noisy_5mm_fast_moving_target", {"noisy": True}, True),
    ("reacquired_fast_moving_target", {"prefix": True}, True),
    ("oscillating_contact_not_real_motion", {"unstable": True}, False),
]:
    source = scenario(name, **kwargs)
    for variant in ["baseline", "maturity_only_control", "confidence_candidate"]:
        settings = ConfidenceSettings(fast_critical_evidence=variant != "maturity_only_control")
        _, rows = evaluate_rows(name, {}, source, settings=settings, candidate=variant != "baseline")
        first_baseline = next(float(r["time_sec"]) for r in source if r["track_available"])
        first = next((float(r["time_sec"]) for r in rows if r["risk"] == "CRITICAL"), None)
        first_alert = next((float(r["time_sec"]) for r in rows if r["virtual_active"]), None)
        delay = first - first_baseline if first is not None else None
        first_index = next((i for i, r in enumerate(rows) if r["risk"] == "CRITICAL"), None)
        continuous = first_index is not None and all(r["risk"] == "CRITICAL" for r in rows[first_index:])
        check = (delay is not None and delay <= .1 + 1e-9 and continuous) if expect_critical else first is None
        summaries.append({"scenario": name, "variant": variant, "additional_critical_delay_sec": delay,
                          "first_virtual_alert_delay_sec": first_alert - first_baseline if first_alert is not None else None,
                          "critical_frames": sum(r["risk"] == "CRITICAL" for r in rows),
                          "critical_continuous_after_onset": continuous,
                          "unknown_frames": sum(r["risk"] == "UNKNOWN" for r in rows),
                          "scenario_check": "PASS" if check else "FAIL"})
        for r in rows:
            r["variant"] = variant
        frames.extend(rows)

write_csv(root / "synthetic_summary.csv", summaries)
write_csv(root / "synthetic_frames.csv", frames)
checks = {"candidate_synthetic_checks": all(r["scenario_check"] == "PASS" for r in summaries if r["variant"] == "confidence_candidate"),
          "maturity_only_fast_delay_detected": any(r["scenario_check"] == "FAIL" for r in summaries if r["variant"] == "maturity_only_control"),
          "hardware_approved": False, "independent_fast_target_recording_tested": False}
(root / "synthetic_checks.json").write_text(json.dumps(checks, indent=2) + "\n")
assert checks["candidate_synthetic_checks"] and checks["maturity_only_fast_delay_detected"]
print(json.dumps(checks, indent=2))
