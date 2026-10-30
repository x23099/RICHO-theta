#!/usr/bin/env python3
"""現USBキャプチャの保存2画像を、保存済みCPU bboxで診断ログ経路へ通す。"""
import argparse
import json
from pathlib import Path
import sys

import cv2

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
from cone_distance_core import ConeDistanceEngine, digest
from theta_rtc_frames import NativeFrame


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=False)
    inputs = ROOT / "Experimental_results/2026-10-30/floor_board_pair_r01"
    sources = [Path(__file__).resolve(), ROOT / "src/cone_distance_core.py",
               ROOT / "src/cone_colour_support_candidate.py", ROOT / "src/cone_support_completion_candidate.py"]
    rows = []
    # Independent stills: do NOT invent a continuous scene/temporal confirmation.
    for number in (1259, 1655):
        image_path = inputs / "originals" / f"decoded_15ae673c24484d119952ae391df611aa_f{number:06d}.png"
        audit = inputs / "cone_same_session_r01" / f"inference_f{number:06d}" / "audit.json"
        pixels = cv2.imread(str(image_path))
        boxes = json.loads(audit.read_text())["all_predictions"]
        engine = ConeDistanceEngine(target_roi=(270, 0, 350, 720), colour_support_shadow=True,
                                    support_completion_shadow=True)
        session = f"independent_still_f{number:06d}"
        engine.reset(session)
        row = engine.measure(NativeFrame(session, 1, 0., 0., pixels), boxes, .01)
        assert not row["distance_available"] and not row["scene_initialized"]
        assert row["physical_metric_verified"] is False and row["usable_for_ffb"] is False
        old, new = row["colour_support_shadow"]["candidate"], row["support_completion_shadow"]["candidate"]
        assert new["point"] == ([299, 385] if number == 1259 else [300, 385])
        assert new["completion_granted"] == (number == 1259)
        assert old["point"] == (None if number == 1259 else [300, 385])
        rows.append(dict(source_native_frame=number, result=row))
        sources += [image_path, audit, ROOT / engine.settings["camera_candidate"],
                    ROOT / engine.settings["floor_candidate"]]
    report = dict(status="PASS_NONCONTROLLING_CURRENT_STILLS", rows=rows,
        source_sha256={str(p): digest(p) for p in sources},
        timing="logical time + 10 ms; not a live timing test", continuous_frames=False,
        inference="existing CPU predictions reused; not fresh GPU or original live boxes",
        physical_metric_verified=False, usable_for_ffb=False, physical_output=False)
    (args.output_dir / "results.json").write_text(json.dumps(report, indent=2)+"\n")
    print(report["status"])


if __name__ == "__main__":
    raise SystemExit(main())
