"""Same-frame base-point versus bbox diagnosis; no fit, image edits or ROS.

Assistant-selected native-image points are nonblind illustrations, not GT.
The +/-3 pixel envelope is a hypothetical sensitivity probe, NOT a CI.
"""
import json
import math
import os
from pathlib import Path
import sys

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "src"))
from cone_dataset import read_csv, sha256, write_csv
from cone_observation import CAMERA_KEYS, ConeGroundProjector
from ground_contact import dual_fisheye_pixels_to_vehicle_rays


def project_point(pixel, parameters):
    """Existing front-left ray/ground equation, deliberately no blue affine."""
    point = np.asarray(pixel, dtype=float)
    if point.shape != (2,) or not np.isfinite(point).all():
        raise ValueError("finite two-coordinate native point required")
    if not (0 <= point[0] < 1280 and 0 <= point[1] < 720):
        raise ValueError("native point outside image")
    height = float(parameters["camera_height"])
    if not math.isfinite(height) or height <= 0:
        raise ValueError("positive camera height required")
    _, rays = dual_fisheye_pixels_to_vehicle_rays(
        point.reshape(1, 2), 1280, 720, parameters, lens="front", front_lens="left")
    if len(rays) != 1 or rays[0, 1] >= -.03:
        return None
    scale = -height / rays[0, 1]
    x, z = map(float, (scale * rays[0, 0], scale * rays[0, 2]))
    if not all(map(math.isfinite, (x, z))) or z <= 0 or not .2 <= math.hypot(x, z) <= 4:
        return None
    return x, z


def envelope(pixel, parameters, half_width=3):
    if type(half_width) is not int or not 0 <= half_width <= 10:
        raise ValueError("small nonnegative integer sensitivity width required")
    results = [project_point((pixel[0]+dx, pixel[1]+dy), parameters)
               for dx in range(-half_width, half_width+1)
               for dy in range(-half_width, half_width+1)]
    if any(value is None for value in results):
        raise ValueError("sensitivity probe contains rejected points")
    return min(value[1] for value in results), max(value[1] for value in results)


def main():
    output = HERE / "contact_diagnosis_r01"
    if output.exists():
        raise ValueError("new run required; existing contact diagnosis not overwritten")
    intake = json.loads((HERE / "intake_summary.json").read_text())
    sources = {r["condition"]:r for r in intake["inputs"]}
    samples = {r["file"]:r for r in read_csv(HERE / "raw_sample_manifest.csv")}
    frames = {(r["condition"], int(r["frame"])):r
              for r in read_csv(HERE / "analysis_r01/positions.csv")}
    anchors = read_csv(HERE / "manual_contact_candidates.csv")
    if len(anchors) != 5 or len({r["condition"] for r in anchors}) != 5:
        raise ValueError("five distinct positive conditions required")
    tracked = [Path(__file__), HERE / "manual_contact_candidates.csv",
               HERE / "raw_sample_manifest.csv", HERE / "intake_summary.json",
               HERE / "analysis_r01/positions.csv", ROOT / "src/cone_observation.py",
               ROOT / "src/ground_contact.py"]
    rows = []
    for anchor in anchors:
        if anchor["reviewer"] != "assistant" or anchor["review_kind"] != "nonblind_illustrative":
            raise ValueError("review provenance must not be silently upgraded to GT")
        sample = samples[anchor["file"]]
        key = (anchor["condition"], int(anchor["frame"]))
        if (sample["condition"], int(sample["frame"])) != key:
            raise ValueError("manual point / source frame mismatch")
        png = HERE / anchor["file"]
        pixels = cv2.imread(str(png), cv2.IMREAD_COLOR)
        if pixels is None or pixels.shape != (720, 1280, 3) or sha256(png) != sample["png_sha256"]:
            raise ValueError("original native PNG changed")
        import hashlib
        if hashlib.sha256(pixels.tobytes()).hexdigest() != sample["decoded_bgr_sha256"]:
            raise ValueError("decoded raw pixels changed")
        tracked.append(png)
        source = sources[anchor["condition"]]
        if sample["session"] != Path(source["path"]).name:
            raise ValueError("source session mismatch")
        parameters = {k:source["metadata"]["parameters"][k] for k in CAMERA_KEYS}
        frame = frames[key]
        if frame["measurement_used"] != "True" or int(frame["front_detections"]) != 1:
            raise ValueError("unambiguous same-frame bbox required")
        manual_pixel = tuple(float(anchor[k]) for k in ("pixel_x", "pixel_y"))
        bbox_pixel = tuple(float(frame[k]) for k in ("bottom_pixel_x", "bottom_pixel_y"))
        manual, bbox = project_point(manual_pixel, parameters), project_point(bbox_pixel, parameters)
        if manual is None or bbox is None:
            raise ValueError("diagnostic point did not project")
        if not np.allclose(bbox, [float(frame[k]) for k in ("x_m", "z_m")], rtol=0, atol=1e-12):
            raise ValueError("point equation differs from recorded bbox projection")
        low, high = envelope(manual_pixel, parameters)
        ref_x, ref_z = (float(frame[k]) for k in ("reference_x_m", "reference_z_m"))
        rows.append(dict(condition=key[0], session=sample["session"], frame=key[1],
            time_sec=frame["time_sec"], file=anchor["file"], png_sha256=sample["png_sha256"],
            reference_x_m=ref_x, reference_z_m=ref_z,
            bbox_pixel_x=bbox_pixel[0], bbox_pixel_y=bbox_pixel[1],
            manual_pixel_x=manual_pixel[0], manual_pixel_y=manual_pixel[1],
            manual_minus_bbox_y_px=manual_pixel[1]-bbox_pixel[1],
            bbox_x_m=bbox[0], bbox_z_m=bbox[1], manual_x_m=manual[0], manual_z_m=manual[1],
            bbox_z_error_m=bbox[1]-ref_z, manual_z_error_m=manual[1]-ref_z,
            manual_x_error_m=manual[0]-ref_x, hypothetical_3px_z_min_m=low,
            hypothetical_3px_z_max_m=high, nominal_in_hypothetical_3px_interval=low <= ref_z <= high,
            reviewer=anchor["reviewer"], review_kind=anchor["review_kind"],
            floor_contact_verified=False, usable_for_ffb=False))
    before = {str(path):sha256(path) for path in tracked}
    output.mkdir(exist_ok=False)
    write_csv(output / "paired_contact_comparison.csv", rows)
    os.environ.setdefault("MPLCONFIGDIR", str(output / ".mplconfig"))
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(10, 5), constrained_layout=True)
    indices = np.arange(len(rows))
    ax.scatter(indices-.09, [r["reference_z_m"] for r in rows], label="Nominal placement Z", marker="x", c="black", zorder=4)
    ax.scatter(indices, [r["bbox_z_m"] for r in rows], label="Same-frame bbox bottom", marker="s")
    manual = np.array([r["manual_z_m"] for r in rows])
    ax.errorbar(indices+.09, manual,
        yerr=np.array([[r["manual_z_m"]-r["hypothetical_3px_z_min_m"] for r in rows],
                       [r["hypothetical_3px_z_max_m"]-r["manual_z_m"] for r in rows]]),
        fmt="o", capsize=4, label="Assistant visible-base point (hypothetical +/-3px)")
    ax.set(xticks=indices, xticklabels=[r["condition"] for r in rows], ylabel="Forward distance Z [m]",
           title="Same raw frame / same frozen projection; NOT calibration or accuracy approval")
    ax.grid(axis="y", alpha=.3)
    ax.legend(fontsize=8)
    fig.savefig(output / "paired_contact_comparison.png", dpi=160)
    plt.close(fig)
    if any(sha256(Path(path)) != digest for path, digest in before.items()):
        raise ValueError("source/image/code changed during diagnosis")
    result = dict(status="COMPLETED_NONBLIND_CONTACT_DIAGNOSIS_NOT_CAUSAL_PROOF_OR_CALIBRATION",
        point_count=len(rows), original_images_unchanged=True, physical_output=False,
        calibration_changed=False, corrections_applied=False, fitted_parameters=False,
        source_sha256=before, manual_point_definition="visible lower base edge near centre; not independently surveyed",
        selection="one pre-exported mid-session frame per positive condition; assistant had seen nominal/bbox results",
        uncertainty="+/-3 pixels is a hypothetical 49-point sensitivity square, NOT measured annotation uncertainty or a confidence interval",
        camera_geometry={k:{name:sources[k]["metadata"]["parameters"][name] for name in CAMERA_KEYS}
                         for k in [r["condition"] for r in rows]},
        output_sha256={name:sha256(output / name) for name in ("paired_contact_comparison.csv", "paired_contact_comparison.png")})
    (output / "provenance.json").write_text(json.dumps(result, indent=2)+"\n")
    print(json.dumps(rows, indent=2))


if __name__ == "__main__":
    main()
