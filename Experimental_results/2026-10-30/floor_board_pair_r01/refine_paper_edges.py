#!/usr/bin/env python3
"""Offline observed paper-edge controls; never a calibrated live transform.

Contour centres and interpolated intensity level crossings are two distinct
observations. Both are threshold dependent. Line intersections are MODELLED
corners, not newly observed physical corners or certified floor contacts.
"""
import argparse
import json
from pathlib import Path
import sys

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "src"))
from angular_fisheye_geometry import project, unproject
from cone_distance_core import DEFAULT_CONFIG, digest, load_config
from floor_reference_pose import planar_floor_pose_candidates


def tls_line(points):
    """Orthogonal least squares in normalized perspective coordinates."""
    p = np.asarray(points, float)
    if p.ndim != 2 or p.shape[1] != 2 or len(p) < 6 or not np.isfinite(p).all():
        raise ValueError("six finite 2D samples required")
    centre = p.mean(axis=0)
    _, singular, vt = np.linalg.svd(p-centre, full_matrices=False)
    if singular[0] < 1e-8 or singular[1] > .5*singular[0]:
        raise ValueError("line samples lack longitudinal spread")
    normal = vt[-1]
    return np.r_[normal, -normal@centre]


def intersect_lines(first, second):
    p = np.cross(first, second)
    if not np.isfinite(p).all() or abs(p[2]) < 1e-8:
        raise ValueError("parallel or invalid adjacent edges")
    return p[:2]/p[2]


def boundary_observations(gray, roi, seed, threshold):
    """Return observed contour centres and external level crossings, no fill-ins."""
    x, y, w, h = roi
    local = gray[y:y+h, x:x+w]
    if local.shape != (h, w):
        raise ValueError("full ROI required")
    contours = cv2.findContours(cv2.inRange(local, threshold, 255),
        cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)[0]
    centre = np.asarray(seed, float).mean(axis=0)-[x, y]
    matches = [c for c in contours if cv2.contourArea(c) >= 200
               and cv2.pointPolygonTest(c, tuple(centre), False) >= 0]
    if len(matches) != 1:
        raise ValueError("one exterior containing the frozen seed centre required")
    contour = matches[0]
    bx, by, bw, bh = cv2.boundingRect(contour)
    if bx == 0 or by == 0 or bx+bw >= w or by+bh >= h:
        raise ValueError("paper contour touches ROI")
    filled = np.zeros_like(local)
    cv2.drawContours(filled, [contour], -1, 255, cv2.FILLED)
    crossings = []
    for px, py in contour[:, 0, :]:
        inside = float(local[py, px])
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            qx, qy = px+dx, py+dy
            if filled[qy, qx] != 0:
                continue  # excludes black checkerboard holes/interior edges
            outside = float(local[qy, qx])
            if not outside < threshold <= inside:
                continue
            fraction = (threshold-inside)/(outside-inside)
            crossings.append([x+px+fraction*dx, y+py+fraction*dy])
    if len(crossings) < 24:
        raise ValueError("insufficient external threshold crossings")
    return {"contour_centres": contour[:, 0, :].astype(float)+[x, y],
            "intensity_crossings": np.unique(np.asarray(crossings), axis=0)}


def refine_quad(samples, seed, camera, *, trim_fraction=.15, seed_edge_gate_px=2.5):
    """Four observed edge supports -> normalized TLS -> modelled intersections."""
    p, q = np.asarray(samples, float), np.asarray(seed, float)
    if (p.ndim != 2 or p.shape[1] != 2 or q.shape != (4, 2)
            or not np.isfinite(p).all() or not np.isfinite(q).all()
            or not 0 <= trim_fraction < .4
            or not np.isfinite(seed_edge_gate_px) or not 0 < seed_edge_gate_px <= 6):
        raise ValueError("finite native points, cyclic quad and valid trim required")
    projections, distances = [], []
    for a, b in zip(q, np.roll(q, -1, axis=0)):
        v = b-a
        if np.linalg.norm(v) < 5:
            raise ValueError("edge too short")
        t = (p-a)@v/(v@v)
        projections.append(t)
        distances.append(np.linalg.norm(p-(a+t[:, None]*v), axis=1))
    distances = np.asarray(distances).T
    assignment = np.argmin(distances, axis=1)
    lines, diagnostics = [], []
    for edge, t in enumerate(projections):
        within_span = (assignment == edge) & (t >= trim_fraction) & (t <= 1-trim_fraction)
        use = within_span & (distances[:, edge] <= seed_edge_gate_px)
        pixels = p[use]
        if len(pixels) < 6 or np.ptp(t[use]) < .4:
            raise ValueError(f"edge {edge}: insufficient observed extent")
        rays, valid = unproject(pixels, camera, image_size=(1280, 720))
        if not valid.all() or np.any(rays[:, 2] <= 1e-6):
            raise ValueError("edge outside calibrated positive hemisphere")
        norm = rays[:, :2]/rays[:, 2, None]
        line = tls_line(norm)
        signed = norm@line[:2]+line[2]
        closest = norm-signed[:, None]*line[:2]
        uv, valid = project(np.column_stack((closest, np.ones(len(closest)))), camera)
        rmse = float(np.sqrt(np.mean(np.sum((uv-pixels)**2, axis=1))))
        if not valid.all() or rmse > 1:
            raise ValueError("edge residual exceeds fixed one-pixel diagnostic guard")
        lines.append(line)
        diagnostics.append(dict(edge=edge, count=len(pixels), observed_fraction_span=float(np.ptp(t[use])),
            pre_gate_count=int(within_span.sum()), excluded_by_seed_gate_count=int((within_span & ~use).sum()),
            maximum_observed_fraction_gap=float(np.max(np.diff(np.sort(t[use])))),
            line_normalized=line.tolist(), native_rms_px=rmse, native_samples_xy=pixels.tolist()))
    normalized_corners = np.array([intersect_lines(lines[(i-1) % 4], lines[i]) for i in range(4)])
    corners, valid = project(np.column_stack((normalized_corners, np.ones(4))), camera)
    shifts = np.linalg.norm(corners-q, axis=1)
    if not valid.all() or np.any(shifts > 3) or not cv2.isContourConvex(corners.astype(np.float32).reshape(-1, 1, 2)):
        raise ValueError("modelled quad invalid or exceeds frozen three-pixel seed guard")
    return dict(corners_native_xy=corners.tolist(), seed_shift_px=shifts.tolist(), edges=diagnostics,
                corners_are_line_intersections=True, physical_paper_edge_identity_verified=False,
                usable_for_ffb=False)


def canonical(candidate):
    signed = candidate["camera_height_above_floor_m"]
    return np.asarray(candidate["up_optical"])*np.sign(signed), abs(signed)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=False)
    source = HERE / "white_paper_quad_measured_r01.json"
    frozen = json.loads(source.read_text())
    config, camera, _, _ = load_config()
    sources = {str(source): digest(source), str(Path(__file__).resolve()): digest(Path(__file__).resolve()),
               str(DEFAULT_CONFIG): digest(DEFAULT_CONFIG),
               str(ROOT / config["camera_candidate"]): digest(ROOT / config["camera_candidate"]),
               str(ROOT / "src/floor_reference_pose.py"): digest(ROOT / "src/floor_reference_pose.py"),
               str(ROOT / "src/angular_fisheye_geometry.py"): digest(ROOT / "src/angular_fisheye_geometry.py")}
    rows = []
    for row in frozen["rows"]:
        if row["threshold"] != frozen["primary_threshold"]:
            continue
        if len(row["quads"]) != 1:
            raise ValueError("one frozen primary seed required")
        frame, roi = row["frame"], row["roi_native_xywh"]
        seed = row["quads"][0]["quad_xy"]
        path = HERE / "originals" / f"decoded_15ae673c24484d119952ae391df611aa_f{frame:06d}.png"
        image = cv2.imread(str(path))
        if image is None or image.shape != (720, 1280, 3):
            raise ValueError("unaltered native source required")
        sources[str(path)] = digest(path)
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        for threshold in (150, 170, 190, 210):
            try:
                observations = boundary_observations(gray, roi, seed, threshold)
            except ValueError as exc:
                observations = None
                reason = str(exc)
            for method in ("contour_centres", "intensity_crossings"):
                for trim, gate in [(t, g) for t in (.15, .25) for g in (2.5, 4., 6.)]:
                    result = dict(frame=frame, threshold=threshold, method=method, trim_fraction=trim,
                                  seed_edge_gate_px=gate,
                                  status="REJECTED", physical_metric_verified=False, usable_for_ffb=False)
                    try:
                        if observations is None:
                            raise ValueError(reason)
                        refined = refine_quad(observations[method], seed, camera, trim_fraction=trim, seed_edge_gate_px=gate)
                        poses = {}
                        long_m, short_m = np.asarray(frozen["paper_size_mm"])/1000
                        for orientation, (width, depth) in {
                            "image_far_edge_long": (long_m, short_m),
                            "image_far_edge_short": (short_m, long_m)}.items():
                            world = [[0, 0, 0], [width, 0, 0], [width, depth, 0], [0, depth, 0]]
                            poses[orientation] = planar_floor_pose_candidates(refined["corners_native_xy"], world, camera)
                        result.update(status="EDGE_POSE_CANDIDATES_NOT_APPROVED", refinement=refined, poses=poses)
                    except ValueError as exc:
                        result["reason"] = str(exc)
                    rows.append(result)
    comparisons = []
    for threshold in (150, 170, 190, 210):
        for method in ("contour_centres", "intensity_crossings"):
            for trim, gate in [(t, g) for t in (.15, .25) for g in (2.5, 4., 6.)]:
                pair = [r for r in rows if r["threshold"] == threshold and r["method"] == method and r["trim_fraction"] == trim and r["seed_edge_gate_px"] == gate]
                comparison = dict(threshold=threshold, method=method, trim_fraction=trim,
                                  seed_edge_gate_px=gate,
                                  usable_pair=False, frames=[dict(frame=r["frame"], status=r["status"], reason=r.get("reason")) for r in pair])
                if len(pair) == 2 and all("poses" in r for r in pair):
                    candidates = [r["poses"]["image_far_edge_long"]["candidates"][0] for r in pair]
                    (n1, h1), (n2, h2) = map(canonical, candidates)
                    comparison.update(usable_pair=True, plane_normal_difference_deg=float(np.degrees(np.arccos(np.clip(n1@n2, -1, 1)))),
                        height_difference_mm=1000*abs(h1-h2), frames=[dict(frame=r["frame"], height_m=h,
                            normal_optical=n.tolist(), reprojection_rmse_px=c["fit_native_rmse_px"],
                            max_seed_shift_px=max(r["refinement"]["seed_shift_px"]))
                            for r, c, n, h in zip(pair, candidates, (n1, n2), (h1, h2))])
                comparisons.append(comparison)
    result = dict(schema="offline_paper_edge_refinement_controls_v1", paper_size_mm=frozen["paper_size_mm"],
        primary_control=dict(threshold=170, method="intensity_crossings", trim_fraction=.15, seed_edge_gate_px=2.5),
        gate_control_note="4px and 6px added after observing missing middle edge samples at 2.5px; diagnostic sampling-bias controls, not selected by height closeness. Three-pixel corner shift guard unchanged.",
        all_controls=rows, comparisons=comparisons, input_source_sha256=sources,
        measured_height_used_in_estimation=False, intrinsics_refitted=False,
        physical_metric_verified=False, live_integrated=False, usable_for_ffb=False)
    with (args.output_dir / "edge_refinement.json").open("x") as f:
        json.dump(result, f, indent=2, allow_nan=False)
        f.write("\n")
    print(json.dumps(comparisons, indent=2))


if __name__ == "__main__":
    main()
