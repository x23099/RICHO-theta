#!/usr/bin/env python3
"""既存実機r02のsession拒否と、現床画像2枚のログ経路をオフライン確認。"""
import argparse
from collections import Counter
import copy
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import cv2

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
from cone_distance_core import ConeDistanceEngine, digest, load_config
from cone_fixed_floor_shadow import FixedFloorShadow, enforce_freshness
from summarize_cone_distance_live import load_frames, summarize
from theta_rtc_frames import NativeFrame


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=False)
    bundle = ROOT / "Experimental_results/2026-10-30/floor_pose_fixed_mode_r01/evaluation_r01/explicit_floor_models.json"
    source = ROOT.parent / "recordings/2026-10-30/live_frame_evidence_r02_20261030_185348/distance_frames.jsonl"
    rows, _, _ = load_frames(source)
    settings, camera, transform, _ = load_config()
    adapter = FixedFloorShadow(bundle, settings, "support_completion_shadow")
    derived = args.output_dir / "derived_recording"
    derived.mkdir()
    reasons = Counter()
    unchanged = 0
    with (derived / "distance_frames.jsonl").open("x") as stream:
        for row in rows:
            observation = row["support_completion_shadow"]["candidate"]
            frame = SimpleNamespace(session=row["session"], sequence=row["frame"], received_at=row["source_time_sec"])
            fixed = adapter.observe(frame, observation, camera, transform)
            enforce_freshness(fixed, row["frame_age_ms"])
            if any(m["range_available"] for m in fixed["models"]):
                raise AssertionError("different session must never produce ranges")
            after = copy.deepcopy(row)
            after["fixed_floor_shadow"] = fixed
            before_override = copy.deepcopy(after)
            before_override.pop("fixed_floor_shadow")
            unchanged += before_override == row
            # Recorded log replay, not fresh real-time inference or completion.
            after["inference_source"] = "recorded_fixed_floor_comparison_not_live_inference"
            reasons[fixed["reason"]] += 1
            stream.write(json.dumps(after, separators=(",", ":"), allow_nan=False)+"\n")
    report = summarize(derived, args.output_dir / "report", plots=False)
    stills = []
    paper = ROOT / "Experimental_results/2026-10-30/floor_board_pair_r01"
    session = json.loads(bundle.read_text())["session"]
    hashes = [source, bundle, Path(__file__).resolve()]
    for number in (1259, 1655):
        path = paper / "originals" / f"decoded_15ae673c24484d119952ae391df611aa_f{number:06d}.png"
        audit = paper / "cone_same_session_r01" / f"inference_f{number:06d}" / "audit.json"
        engine = ConeDistanceEngine(target_roi=(270, 0, 350, 720), support_completion_shadow=True,
                                   fixed_floor_models=bundle)
        engine.reset(session)
        boxes = json.loads(audit.read_text())["all_predictions"]
        row = engine.measure(NativeFrame(session, number, 0., 0., cv2.imread(str(path))), boxes, .01)
        # Separate stills: never duplicate a frame to invent 3-frame evidence.
        assert row["fixed_floor_shadow"]["reason"] == "image_support_quality_not_confirmed"
        assert not row["distance_available"]
        stills.append(row)
        hashes += [path, audit]
    (args.output_dir / "still_engine_results.json").write_text(json.dumps(stills, indent=2)+"\n")
    hashes += [ROOT / "src" / n for n in ("cone_distance_core.py", "cone_distance_worker.py",
        "cone_fixed_floor_shadow.py", "cone_fixed_floor_candidate.py", "summarize_cone_distance_live.py")]
    summary = dict(status="PASS_SESSION_GUARD_AND_LOG_ONLY", recorded_frames=len(rows),
        baseline_fields_unchanged=unchanged, comparison_range_frames=0, reasons=dict(reasons),
        report_status=report["status"], independent_stills=len(stills),
        stills_have_no_temporal_confirmation=True,
        timings="recorded local timestamps/ages reused, not fresh live or CPU latency measurements",
        no_live_summary_fabricated=True, physical_metric_verified=False, usable_for_ffb=False,
        source_sha256={str(p.resolve()): digest(p) for p in hashes})
    (args.output_dir / "summary.json").write_text(json.dumps(summary, indent=2)+"\n")
    print(json.dumps({k: v for k, v in summary.items() if k != "source_sha256"}, indent=2))


if __name__ == "__main__":
    main()
