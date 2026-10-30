#!/usr/bin/env python3
"""固定された車体領域の画像対応だけを診断する。内部校正/姿勢の承認には使わない。"""
import argparse
import hashlib
import json
from pathlib import Path
import cv2
import numpy as np


def compare(before, after):
    mask = np.zeros((720, 1280), np.uint8)
    # Frame-independent region selected from visible rigid vehicle platform.
    # No floor/cone distance labels and no moving background features are used.
    mask[430:640, 30:610] = 255
    sift = cv2.SIFT_create()
    ka, da = sift.detectAndCompute(cv2.cvtColor(before, cv2.COLOR_BGR2GRAY), mask)
    kb, db = sift.detectAndCompute(cv2.cvtColor(after, cv2.COLOR_BGR2GRAY), mask)
    result = dict(region_xyxy=[30, 430, 610, 640], keypoints=[len(ka), len(kb)],
                  intrinsics_transfer_verified=False, usable_for_ffb=False)
    if da is None or db is None:
        return dict(result, status="INSUFFICIENT_FIXED_PLATFORM_MATCHES")
    matcher = cv2.BFMatcher()
    def ratio_pairs(a, b):
        return {(m.queryIdx, m.trainIdx) for pair in matcher.knnMatch(a, b, k=2)
                if len(pair) == 2 for m, n in [pair] if m.distance < .7*n.distance}
    forward = ratio_pairs(da, db)
    reverse = ratio_pairs(db, da)
    pairs = sorted((a, b) for a, b in forward if (b, a) in reverse)
    pa = np.asarray([ka[a].pt for a, _ in pairs], np.float32).reshape(-1, 2)
    pb = np.asarray([kb[b].pt for _, b in pairs], np.float32).reshape(-1, 2)
    result.update(reciprocal_matches=len(pairs), points_before_xy=pa.tolist(), points_after_xy=pb.tolist())
    if len(pairs) < 8:
        return dict(result, status="INSUFFICIENT_FIXED_PLATFORM_MATCHES")
    cv2.setRNGSeed(0)
    model, inliers = cv2.findHomography(pa, pb, cv2.RANSAC, 2.)
    if model is None:
        return dict(result, status="NO_STABLE_PLATFORM_MAPPING")
    keep = inliers.ravel().astype(bool)
    shift = np.linalg.norm(pb[keep]-pa[keep], axis=1)
    result.update(inliers=int(keep.sum()), inlier_mask=keep.tolist(),
                  point_shift_median_px=float(np.median(shift)), point_shift_max_px=float(shift.max()),
                  inlier_span_before_xy=np.ptp(pa[keep], axis=0).tolist(),
                  inlier_span_after_xy=np.ptp(pb[keep], axis=0).tolist(),
                  plane_mapping_not_calibration=model.tolist(),
                  status="LOCAL_IMAGE_MATCHES_ONLY_NOT_INTRINSIC_OR_EXTRINSIC_VERIFICATION")
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--reference", type=Path, required=True)
    p.add_argument("--control", type=Path, required=True)
    p.add_argument("--current", type=Path, required=True)
    p.add_argument("--output-json", type=Path, required=True)
    args = p.parse_args()
    paths = [args.reference, args.control, args.current]
    images = [cv2.imread(str(x)) for x in paths]
    if any(x is None or x.shape != (720, 1280, 3) for x in images):
        raise ValueError("native 1280x720 sources required")
    result = dict(opencv=cv2.__version__, reference_to_same_recording=compare(images[0], images[1]),
                  reference_to_changed_capture=compare(images[0], images[2]),
                  source_sha256={str(x.resolve()): hashlib.sha256(x.read_bytes()).hexdigest()
                                 for x in [*paths, Path(__file__).resolve()]},
                  note="No remapping or image modification. Local vehicle matches cannot prove full-view lens mapping.")
    with args.output_json.open("x") as f:
        json.dump(result, f, indent=2, allow_nan=False)
        f.write("\n")
    print(json.dumps({k: {a: b for a, b in result[k].items() if not a.startswith("points_")}
                      for k in ("reference_to_same_recording", "reference_to_changed_capture")}, indent=2))


if __name__ == "__main__":
    main()
