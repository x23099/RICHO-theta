#!/usr/bin/env python3
"""Re-apply the frozen V30 union HSV mask to a saved PNG and count edge contacts.

Read-only: no inference, threshold change, or distance recomputation.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2
import numpy as np


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--png", type=Path, required=True)
    parser.add_argument("--crop", type=int, nargs=4, required=True,
                        metavar=("X1", "Y1", "X2", "Y2"))
    parser.add_argument("--output-json", type=Path, required=True)
    args = parser.parse_args()
    if args.output_json.exists():
        raise ValueError("new output JSON required")
    x1, y1, x2, y2 = args.crop
    image = cv2.imread(str(args.png))
    if image is None or image.shape != (720, 1280, 3):
        raise ValueError("native 1280x720 BGR PNG required")
    if not (0 <= x1 < x2 <= 1280 and 0 <= y1 < y2 <= 720):
        raise ValueError("bounded crop required")
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    red = (cv2.inRange(hsv, (0, 80, 30), (10, 255, 255))
           | cv2.inRange(hsv, (170, 80, 30), (179, 255, 255)))
    yellow = cv2.inRange(hsv, (15, 80, 30), (40, 255, 255))
    mask = red | yellow
    crop = mask[y1:y2, x1:x2]
    out = dict(png=str(args.png), crop=[x1, y1, x2, y2],
               mask_pixels=int(crop.astype(bool).sum()))
    for name, line in (("left", crop[:, 0]), ("right", crop[:, -1]),
                       ("bottom", crop[-1, :]), ("top", crop[0, :])):
        idx = np.flatnonzero(line)
        out[name] = dict(count=int(idx.size),
                         first=int(idx[0]) if idx.size else None,
                         last=int(idx[-1]) if idx.size else None)
    for name, coords in (
            ("left", [(x1, y) for y in range(y1, y2)]),
            ("right", [(x2-1, y) for y in range(y1, y2)]),
            ("bottom", [(x, y2-1) for x in range(x1, x2)]),
            ("top", [(x, y1) for x in range(x1, x2)])):
        reds = [(x, y) for x, y in coords if red[y, x]]
        yellows = [(x, y) for x, y in coords if yellow[y, x]]
        out[name].update(red_count=len(reds), yellow_count=len(yellows),
                         red_examples=reds[:3], yellow_examples=yellows[:3])
    out["hsv_samples"] = {
        name: [(x, y, [int(v) for v in hsv[y, x]])
               for x, y in (out[name]["red_examples"] + out[name]["yellow_examples"])[:4]]
        for name in ("left", "right", "bottom", "top")}
    out["method"] = "V30 union HSV re-applied to saved native PNG; no inference or threshold change"
    out["physical_metric_verified"] = False
    out["floor_contact_verified"] = False
    args.output_json.write_text(json.dumps(out, indent=2) + "\n")
    print(json.dumps({name: {k: out[name][k] for k in ("count", "red_count", "yellow_count")}
                      for name in ("left", "right", "bottom", "top")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
