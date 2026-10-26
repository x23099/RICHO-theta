"""Same exact winner indices, using contiguous-bin reductions, offline only."""
import cv2
import numpy as np

from angular_fisheye_geometry import unproject
from cached_curve_geometry import _plane_from_subset


def bin_winners(ids, bins, distance):
    ids = np.asarray(ids)
    bins = np.asarray(bins)
    distance = np.asarray(distance)
    if (ids.ndim != 1 or bins.ndim != 1 or distance.ndim != 1
            or len(ids) != len(bins) or not np.issubdtype(ids.dtype, np.integer)
            or not np.issubdtype(bins.dtype, np.integer)):
        raise ValueError('paired integer one-dimensional ids/bins and one-dimensional distances required')
    if (np.any(ids < 0) or np.any(ids >= len(distance))
            or np.any(np.diff(ids) <= 0) or np.any(np.diff(bins) < 0)):
        raise ValueError('strictly increasing in-range ids and nondecreasing bins required')
    values = distance[ids]
    if not np.isfinite(values).all():
        raise ValueError('finite distances for selected indices required')
    if not len(ids):
        return np.empty(0, dtype=np.intp)
    starts = np.r_[0, np.flatnonzero(np.diff(bins) != 0) + 1]
    minima = np.minimum.reduceat(values, starts)
    lengths = np.diff(np.r_[starts, len(ids)])
    positions = np.flatnonzero(values == np.repeat(minima, lengths))
    winning_bins = bins[positions]
    first = np.r_[True, winning_bins[1:] != winning_bins[:-1]]
    return ids[positions[first]].astype(np.intp, copy=False)


def extract_fast_curve_planes(image, camera):
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
        chosen = bin_winners(ids, bins, distance)
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
