#!/usr/bin/env python3
"""保存済みログと無加工画像のみを読む。YOLO・GPU・通信・ROSは起動しない。"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

import cv2

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
from cone_distance_core import load_config
from cone_scene_diagnostic import estimate_scene


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output-json", type=Path, required=True)
    args = parser.parse_args()
    rows_path = args.input_dir / "distance_frames.jsonl"
    rows = [json.loads(line) for line in rows_path.read_text().splitlines()]
    image_path = args.input_dir / "decoded_f1f1b17f34a6447a9789291af128f991_f004903.png"
    image = cv2.imread(str(image_path))
    if image is None:
        raise ValueError("saved native frame missing")
    _, camera, _, prior = load_config()
    source_files = [Path(__file__).resolve(), rows_path, image_path,
                    ROOT / "src/cone_distance_core.py",
                    ROOT / "src/cone_scene_diagnostic.py",
                    ROOT / "src/cone_distance_diagnostic_config.json"]
    result = dict(
        diagnostic="OFFLINE_SAVED_FRAME_NO_YOLO_RERUN_NOT_PHYSICAL_APPROVAL",
        processed_frames=len(rows),
        distance_available=sum(r["distance_available"] for r in rows),
        quality_accepted=sum(r["quality_accepted"] for r in rows),
        scene_initialized=sum(r["scene_initialized"] for r in rows),
        counts={key: dict(Counter(str(r[key]) for r in rows)) for key in (
            "front_candidates", "reason", "colour_reason", "scene_reason",
            "pose_reason", "inference_source")},
        blockers=dict(Counter(b for r in rows for b in set(r["blockers"]))),
        saved_frame_log=[r for r in rows if r["frame"] == 4903],
        saved_frame_scene_recalculation=estimate_scene(image, camera, prior),
        cv2_version=cv2.__version__,
        source_sha256={str(p.resolve()): sha(p) for p in source_files},
        raw_bboxes_recorded=False, physical_metric_verified=False, usable_for_ffb=False,
    )
    with args.output_json.open("x") as stream:
        json.dump(result, stream, indent=2, allow_nan=False)
        stream.write("\n")
    print("Saved:", args.output_json)


if __name__ == "__main__":
    main()
