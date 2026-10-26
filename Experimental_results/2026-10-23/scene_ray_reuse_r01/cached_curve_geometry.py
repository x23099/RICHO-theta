"""Experimental same-frame ray reuse; no global cache or production imports."""
import cv2
import numpy as np
from angular_fisheye_geometry import unproject
from scene_geometry import angle_degrees


def _plane_from_subset(native, rays, indices):
    """Only called with indices into this extractor's own paired frame arrays."""
    ids = np.asarray(indices)
    if ids.ndim != 1 or not np.issubdtype(ids.dtype, np.integer):
        raise ValueError('one-dimensional integer pool indices required')
    if len(native) != len(rays) or np.any(ids < 0) or np.any(ids >= len(native)):
        raise ValueError('paired same-frame pool and in-range indices required')
    p = np.asarray(native[ids], float)
    if (p.ndim != 2 or p.shape[1] != 2 or len(p) < 30
            or not np.isfinite(p).all() or not np.equal(p, np.rint(p)).all()):
        raise ValueError('30 actual native edge pixels required')
    selected = rays[ids]
    if selected.shape != (len(p), 3) or not np.isfinite(selected).all():
        raise ValueError('finite paired rays required')
    # The pool has already passed unproject.valid and the exact old 75-degree
    # filter. Keep the old plane evaluator's angular/span/SVD tests verbatim.
    if np.max(np.degrees(np.arccos(np.clip(selected[:, 2], -1, 1)))) > 75:
        return dict(accepted=False, reason='outside_75degree_scene_domain')
    span = angle_degrees(selected[0], selected[-1])
    if span < 12:
        return dict(accepted=False, reason='insufficient_ray_span', ray_span_deg=span)
    _, singular, vt = np.linalg.svd(selected, full_matrices=False)
    normal = vt[-1]
    if normal[0] < 0:
        normal = -normal
    errors = np.degrees(np.arcsin(np.clip(abs(selected @ normal), 0, 1)))
    rms = float(np.sqrt(np.mean(errors ** 2)))
    maximum = float(errors.max())
    accepted = rms <= .15 and maximum <= .4
    return dict(accepted=accepted,
                reason='accepted_plane' if accepted else 'not_one_ray_plane',
                normal=normal.tolist() if accepted else None,
                plane_rms_deg=rms, plane_max_deg=maximum,
                ray_span_deg=span, edge_points=len(p))


def extract_cached_curve_planes(image, camera):
    if image.shape != (720, 1280, 3) or image.dtype != np.uint8:
        raise ValueError('native uint8 BGR frame required')
    gray = cv2.cvtColor(image[:, :640], cv2.COLOR_BGR2GRAY)
    ys, xs = np.nonzero(cv2.Canny(gray, 60, 120))
    native = np.column_stack((xs, ys)).astype(float)
    roi = (xs >= 40) & (xs <= 600) & (ys >= 60) & (ys <= 300)
    native = native[roi]
    rays, valid = unproject(native, camera, image_size=(1280, 720))
    valid &= rays[:, 2] >= np.cos(np.deg2rad(75))
    native = native[valid]
    rays = rays[valid]
    points = 200 * rays[:, :2] / rays[:, 2, None]
    if not len(points):
        return []
    candidates = cv2.HoughLinesPointSet(
        points.astype(np.float32).reshape(-1, 1, 2),
        200, 40, -1000, 1000, 1, 0, np.pi, np.pi / 720)
    rows = []
    for index, (votes, rho, theta) in enumerate(
            candidates.reshape(-1, 3) if candidates is not None else []):
        distance = abs(points @ np.array([np.cos(theta), np.sin(theta)]) - rho)
        ids = np.flatnonzero(distance <= 1)
        bins = np.floor(native[ids, 1] / 2).astype(int)
        chosen = []
        for bin_id in np.unique(bins):
            options = ids[bins == bin_id]
            chosen.append(options[np.argmin(distance[options])])
        chosen = np.asarray(chosen, dtype=np.intp)
        observed = native[chosen]
        pieces = np.split(chosen, np.flatnonzero(np.diff(observed[:, 1]) > 6) + 1)
        for part, indices in enumerate(pieces):
            actual = native[indices]
            if len(actual) < 30:
                continue
            span = np.ptp(actual, axis=0)
            if span[1] < 60 or span[1] < 1.5 * span[0]:
                continue
            plane = _plane_from_subset(native, rays, indices)
            rows.append(dict(line_index=index, part=part, hough_votes=float(votes),
                             rho=float(rho), theta=float(theta),
                             native_y_span=float(span[1]),
                             actual_edge_pixels_json=actual.tolist(), **plane))
    kept = []
    for row in sorted((r for r in rows if r['accepted']), key=lambda r: -r['native_y_span']):
        n = np.array(row['normal'])
        if any(np.degrees(np.arccos(np.clip(abs(n @ np.array(r['normal'])), -1, 1))) < 2
               for r in kept):
            row.update(accepted=False, reason='duplicate_ray_plane')
        else:
            kept.append(row)
    return rows
