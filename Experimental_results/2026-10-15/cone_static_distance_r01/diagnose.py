"""Fixed-pixel sensitivity and one extra-output raw sample; not calibration."""
import hashlib
import json
from pathlib import Path
import sys

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "src"))
from cone_dataset import read_csv, sha256, write_csv
from cone_observation import ConeGroundProjector


def main():
    output = HERE / "diagnosis_r01"
    if output.exists():
        raise ValueError("new diagnostic output required")
    intake = json.loads((HERE / "intake_summary.json").read_text())
    frames = read_csv(HERE / "analysis_r01/positions.csv")
    conditions = read_csv(HERE / "analysis_r01/summary.csv")
    diagnostics = []
    for source in intake["inputs"]:
        key = source["condition"]
        if key == "none":
            continue
        summary = next(r for r in conditions if r["condition"] == key)
        rows = [r for r in frames if r["condition"] == key and r["measurement_used"] == "True"]
        if not rows:
            continue
        box = {name:float(np.median([float(r["bbox_"+name]) for r in rows])) for name in ("x1","y1","x2","y2")}
        box.update(class_id=0, confidence=1)  # Synthetic geometry probe, NOT a model prediction.
        p = ConeGroundProjector(source["metadata"]["parameters"], width=1280, height=720,
                                 front_lens="left", confidence_threshold=.5)
        base = p.project(box, frame_width=1280, frame_height=720)
        sampled = []
        for dx in range(-2,3):
            for dy in range(-2,3):
                probe = dict(box, x1=box["x1"]+dx, x2=box["x2"]+dx, y2=box["y2"]+dy)
                result = p.project(probe, frame_width=1280, frame_height=720)
                if result["projection_candidate"]:
                    sampled.append(result["z_m"])
        reference = float(summary["reference_z_m"])
        # Explain how much the pixel would have to move, without moving any real
        # image/label or recommending such a correction for deployment.
        lo, hi = 0.0, 30.0
        upper = p.project(dict(box, y2=box["y2"]+hi), frame_width=1280, frame_height=720)
        delta = None
        if upper["projection_candidate"] and upper["z_m"] <= reference <= base["z_m"]:
            for _ in range(50):
                mid = (lo+hi)/2
                test = p.project(dict(box, y2=box["y2"]+mid), frame_width=1280, frame_height=720)
                if test["z_m"] > reference:
                    lo = mid
                else:
                    hi = mid
            delta = (lo+hi)/2
        diagnostics.append(dict(condition=key, median_bbox_bottom_x=(box["x1"]+box["x2"])/2,
            median_bbox_bottom_y=box["y2"], nominal_z_m=reference, projected_median_pixel_z_m=base["z_m"],
            hypothetical_2px_z_min_m=min(sampled), hypothetical_2px_z_max_m=max(sampled),
            nominal_in_hypothetical_2px_interval=min(sampled) <= reference <= max(sampled),
            downward_pixel_shift_to_nominal_z=delta,
            scope="fixed median-pixel sensitivity only; +/-2px is hypothetical, not measured annotation uncertainty; no fitting"))
    output.mkdir(exist_ok=False)
    write_csv(output / "pixel_sensitivity.csv", diagnostics)
    source = next(r for r in intake["inputs"] if r["condition"] == "right_130")
    video = Path(source["path"]) / "raw.avi"
    capture = cv2.VideoCapture(str(video))
    try:
        for number in range(1,55):
            ok, pixels = capture.read()
            if not ok or pixels.shape != (720,1280,3):
                raise ValueError("native diagnostic frame decode failed")
        target = output / "right_130_f000054.png"
        if not cv2.imwrite(str(target), pixels):
            raise ValueError("raw diagnostic PNG export failed")
    finally:
        capture.release()
    pixel_hash = hashlib.sha256(pixels.tobytes()).hexdigest()
    if hashlib.sha256(cv2.imread(str(target)).tobytes()).hexdigest() != pixel_hash:
        raise ValueError("raw diagnostic pixels changed")
    write_csv(output / "raw_manifest.csv", [dict(file=target.name, session=Path(source["path"]).name,
        frame=54, width=1280, height=720, source_raw_sha256=sha256(video),
        png_sha256=sha256(target), decoded_bgr_sha256=pixel_hash,
        reason="first extra front-output sample; no overlay/crop/correction")])
    files = (Path(__file__), HERE / "analysis_r01/positions.csv", HERE / "analysis_r01/summary.csv",
             HERE / "intake_summary.json", ROOT / "src/cone_observation.py")
    (output / "provenance.json").write_text(json.dumps(dict(
        status="COMPLETED_FIXED_PIXEL_SENSITIVITY_NOT_CAUSAL_PROOF_OR_CALIBRATION", physical_output=False,
        corrections_applied=False, source_sha256={str(f):sha256(f) for f in files}), indent=2)+"\n")
    print(json.dumps(diagnostics, indent=2))


if __name__ == "__main__":
    main()
