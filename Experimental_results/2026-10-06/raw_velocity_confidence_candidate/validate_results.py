#!/usr/bin/env python3
"""保存済み比較結果の件数・再現対照・実装hashを確認。実機は操作しない。"""
import csv
import hashlib
import json
from pathlib import Path

root = Path(__file__).resolve().parent
source_root = root.parents[2] / "src"
sessions = frames = changed = virtual_changed = control_risk_changed = withheld = 0
for group in (root, root / "controls", root / "motion_controls"):
    with (group / "frame_results.csv").open(newline="") as stream:
        rows = list(csv.DictReader(stream))
    baseline = {(r["session"], r["frame"]): r for r in rows if r["variant"] == "raw_video_baseline"}
    candidate = [r for r in rows if r["variant"] == "raw_video_candidate"]
    control = [r for r in rows if r["variant"] == "logged_measurement_rebuild"]
    assert len(baseline) == len(candidate) == len(control)
    sessions += len({r["session"] for r in candidate})
    frames += len(candidate)
    changed += sum(r["risk"] != baseline[(r["session"], r["frame"])]["risk"] for r in candidate)
    virtual_changed += sum(r["virtual_active"] != baseline[(r["session"], r["frame"])]["virtual_active"] for r in candidate)
    control_risk_changed += sum(r["risk"] != r["recorded_risk"] for r in control)
    withheld += sum(int(r["alert_withheld"]) for r in candidate)
    provenance = json.loads((group / "provenance.json").read_text())
    for name, expected in provenance["implementation_sha256"].items():
        assert hashlib.sha256((source_root / name).read_bytes()).hexdigest() == expected, name
result = {"sessions": sessions, "frames": frames, "logged_measurement_control_risk_difference_frames": control_risk_changed,
          "candidate_added_risk_difference_frames": changed, "candidate_added_virtual_active_difference_frames": virtual_changed,
          "candidate_withheld_frames": withheld, "current_implementation_hash_matches": True,
          "scope": "OFFLINE_COMPARISON_NOT_HARDWARE_ACCEPTANCE", "hardware_approved": False}
assert sessions == 7 and frames == 5030
assert control_risk_changed == changed == virtual_changed == withheld == 0
(root / "validation.json").write_text(json.dumps(result, indent=2) + "\n")
print(json.dumps(result, indent=2))
