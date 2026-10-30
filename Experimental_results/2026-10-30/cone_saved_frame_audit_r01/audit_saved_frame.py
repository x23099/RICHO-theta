#!/usr/bin/env python3
"""保存画像だけをCPUで再推論し、bbox切り出しを監査する。本番の採否は変更しない。"""
import argparse
import importlib.metadata
import json
import math
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))

import cv2
import numpy as np
from cone_distance_core import digest, load_config, observe_support, select_front_boxes
from cone_detection_diagnostics import extract_predictions
from cone_scene_diagnostic import estimate_scene, extract_guarded_curve_planes


def contour_details(image, box, margin, colour="both"):
    x1, y1, x2, y2 = (float(box[k]) for k in ("x1", "y1", "x2", "y2"))
    l, t, r, b = math.floor(x1)-margin, math.floor(y1)-margin, math.ceil(x2)+margin, math.ceil(y2)+margin
    if l < 0 or t < 0 or r > image.shape[1] or b > image.shape[0]:
        return dict(margin=margin, crop_xyxy=[l, t, r, b], outside_image=True)
    hsv = cv2.cvtColor(image[t:b, l:r], cv2.COLOR_BGR2HSV)
    red = (cv2.inRange(hsv, (0, 80, 30), (10, 255, 255))
           | cv2.inRange(hsv, (170, 80, 30), (179, 255, 255)))
    yellow = cv2.inRange(hsv, (15, 80, 30), (40, 255, 255))
    if colour not in ("both", "red", "yellow"):
        raise ValueError("explicit colour group required")
    mask = {"both": red | yellow, "red": red, "yellow": yellow}[colour]
    contours = sorted((c for c in cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)[0]
                       if cv2.contourArea(c) >= 20), key=cv2.contourArea, reverse=True)
    out = dict(colour=colour, margin=margin, crop_xyxy=[l, t, r, b], outside_image=False,
               contour_areas=[float(cv2.contourArea(c)) for c in contours])
    if not contours:
        return out
    contour = contours[0]
    bx, by, bw, bh = cv2.boundingRect(contour)
    points = contour[:, 0, :] + [l, t]
    out.update(contour_bounds_xyxy=[l+bx, t+by, l+bx+bw-1, t+by+bh-1],
               touches=dict(left=bx == 0, top=by == 0, right=bx+bw >= r-l, bottom=by+bh >= b-t),
               contour_points_xy=points.tolist())
    xs = np.unique(points[:, 0])
    envelope = np.asarray([(x, max(points[points[:, 0] == x, 1])) for x in xs])
    lo, hi = xs[0], xs[-1]
    support = envelope[(xs >= lo+.1*(hi-lo)) & (xs <= hi-.1*(hi-lo))]
    tip_y = points[:, 1].min()
    tip_x = float(np.median(points[points[:, 1] == tip_y, 0]))
    base_x = min(xs, key=lambda x: (abs(x-tip_x), x))
    point = [int(base_x), int(max(points[points[:, 0] == base_x, 1]))]
    out.update(diagnostic_support_xy=support.tolist(), diagnostic_point_xy=point,
               point_in_trimmed_support=any(np.array_equal(point, row) for row in support),
               floor_contact_verified=False)
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--weights", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.output_dir.exists():
        raise ValueError("new output required")
    settings, camera, _, prior = load_config()
    if digest(args.weights) != settings["weights_sha256"]:
        raise ValueError("frozen trusted checkpoint hash required")
    image = cv2.imread(str(args.image))
    if image is None or image.shape != (720, 1280, 3):
        raise ValueError("native saved frame required")
    args.output_dir.mkdir(parents=True)
    config_dir = args.output_dir / "ultralytics_config"
    (config_dir / "Ultralytics").mkdir(parents=True)
    os.environ["YOLO_CONFIG_DIR"] = str(config_dir.resolve())
    from run_cone_yolo import configure_offline
    configure_offline(config_dir)
    import torch
    torch.set_num_threads(2)
    from ultralytics import YOLO
    from ultralytics.utils import ONLINE, AUTOINSTALL, USER_CONFIG_DIR
    if ONLINE or AUTOINSTALL or Path(USER_CONFIG_DIR).resolve() != (config_dir / "Ultralytics").resolve():
        raise ValueError("isolated offline inference required")
    model = YOLO(str(args.weights.resolve()))
    if model.names != {0: "traffic_cone"}:
        raise ValueError("single cone class required")
    kwargs = dict(device="cpu", imgsz=settings["imgsz"], conf=settings["confidence"],
                  iou=settings["nms_iou"], max_det=settings["max_det"], rect=False, batch=1,
                  augment=False, save=False, save_txt=False, save_crop=False, show=False,
                  visualize=False, verbose=False, stream=False, quantize=32, half=False)
    prediction = model.predict(source=image, **kwargs)[0]
    boxes = extract_predictions(prediction, dict(width=1280, height=720, image=args.image.name))
    selected = select_front_boxes(boxes, camera, settings["confidence"], (270, 0, 350, 720))
    audits = []
    for box in selected:
        baseline = observe_support(image, box, camera)
        baseline["support"] = None if baseline["support"] is None else baseline["support"]
        audits.append(dict(box=box, frozen_baseline=baseline,
                          margin_controls=[contour_details(image, box, m) for m in (4, 8, 12, 16, 24)],
                          colour_controls=[contour_details(image, box, m, colour)
                                           for m in (4, 24) for colour in ("red", "yellow")]))
    planes = extract_guarded_curve_planes(image, camera)
    sources = [Path(__file__).resolve(), args.image, args.weights,
               ROOT / "src/cone_distance_core.py", ROOT / "src/cone_scene_diagnostic.py"]
    result = dict(status="OFFLINE_CPU_REINFERENCE_NOT_ORIGINAL_LIVE_BOXES_NOT_PHYSICAL_APPROVAL",
                  software={k: importlib.metadata.version(k) for k in ("torch", "ultralytics", "opencv-python")},
                  inference_kwargs=kwargs, all_predictions=boxes, selected_audits=audits,
                  scene=estimate_scene(image, camera, prior), scene_planes=planes,
                  source_sha256={str(p.resolve()): digest(p) for p in sources},
                  production_changes=False, physical_metric_verified=False, usable_for_ffb=False,
                  note="Margins are diagnostic controls only; no distance or physical floor contact is inferred.")
    (args.output_dir / "audit.json").write_text(json.dumps(result, indent=2, allow_nan=False)+"\n")
    print(json.dumps(dict(boxes=len(boxes), selected=len(selected),
                         support_reasons=[a["frozen_baseline"]["reason"] for a in audits],
                         scene=result["scene"]), indent=2))


if __name__ == "__main__":
    main()
