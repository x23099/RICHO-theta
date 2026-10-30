#!/usr/bin/env python3
"""CPU再推論の保存枠から色別の診断JSONと座標グラフを作る。カメラ画像は加工しない。"""
import argparse
import hashlib
import json
import os
from pathlib import Path

import cv2
from audit_saved_frame import contour_details


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--image", type=Path, required=True)
    p.add_argument("--prediction-audit", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    args = p.parse_args()
    if args.output_dir.exists():
        raise ValueError("new output required")
    evidence = json.loads(args.prediction_audit.read_text())
    if evidence["status"] != "OFFLINE_CPU_REINFERENCE_NOT_ORIGINAL_LIVE_BOXES_NOT_PHYSICAL_APPROVAL":
        raise ValueError("explicit CPU reinference lineage required")
    image = cv2.imread(str(args.image))
    if image is None or image.shape != (720, 1280, 3):
        raise ValueError("native saved image required")
    args.output_dir.mkdir(parents=True)
    rows = [dict(prediction=b, colour_controls=[contour_details(image, b, m, c)
                                               for m in (4, 24) for c in ("both", "red", "yellow")])
            for b in evidence["all_predictions"]]
    result = dict(status="COLOUR_COMPONENT_DIAGNOSTICS_NOT_CONTACT_OR_DISTANCE",
                  boxes=rows, scene=evidence["scene"], physical_metric_verified=False,
                  usable_for_ffb=False, production_settings_changed=False,
                  source_sha256={str(x.resolve()): hashlib.sha256(x.read_bytes()).hexdigest()
                                 for x in (args.image, args.prediction_audit, Path(__file__).resolve(),
                                           Path(__file__).with_name("audit_saved_frame.py"))})
    (args.output_dir / "colour_controls.json").write_text(json.dumps(result, indent=2)+"\n")
    os.environ["MPLCONFIGDIR"] = str(args.output_dir / "matplotlib_config")
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle
    fig, axes = plt.subplots(len(rows), 3, figsize=(12, 5*len(rows)), squeeze=False, layout="constrained")
    for row_index, row in enumerate(rows):
        box = row["prediction"]
        for axis, details in zip(axes[row_index], row["colour_controls"][:3]):
            l, t, r, b = details["crop_xyxy"]
            points = details.get("contour_points_xy", [])
            if points:
                axis.plot([v[0] for v in points]+[points[0][0]],
                          [v[1] for v in points]+[points[0][1]], linewidth=1.)
            axis.add_patch(Rectangle((l, t), r-l, b-t, fill=False, color="black", label="crop (+4 px)"))
            axis.add_patch(Rectangle((box["x1"], box["y1"]), box["x2"]-box["x1"],
                                    box["y2"]-box["y1"], fill=False, color="gray", linestyle="--", label="CPU YOLO bbox"))
            touched = ",".join(k for k, v in details.get("touches", {}).items() if v) or "none"
            axis.set(title=f"box {box['prediction_index']} / {details['colour']} / touched: {touched}",
                     xlabel="Native image x [px]", ylabel="Native image y [px]",
                     xlim=(l-6, r+6), ylim=(b+6, t-6), aspect="equal")
            axis.grid(alpha=.2)
            axis.legend(fontsize=7)
    fig.suptitle("Contour coordinate plots ONLY (not edited camera images)\nCPU recomputation; no verified floor contact or distance")
    fig.savefig(args.output_dir / "colour_contour_coordinates.png", dpi=130)
    plt.close(fig)
    print("Saved findings:", args.output_dir)


if __name__ == "__main__":
    main()
