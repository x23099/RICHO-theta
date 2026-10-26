"""Exclusive timers around the frozen same-frame ray-reuse operations."""
from time import perf_counter_ns

import cv2
import numpy as np

from angular_fisheye_geometry import unproject
from cached_curve_geometry import _plane_from_subset
from scene_geometry import infer_up

STAGES = ('native_edges', 'inverse_projection', 'hough', 'candidate_distance',
          'bin_selection', 'segment_filter', 'plane_evaluation',
          'row_materialization', 'plane_deduplication', 'up_estimation')


def compute_profiled(image, camera, prior):
    wall_start = perf_counter_ns()
    timers = dict.fromkeys(STAGES, 0)
    counts = dict(raw_edge_pixels=0, roi_edge_pixels=0, valid_ray_pixels=0,
                  hough_candidates=0, bin_winners=0, gap_pieces=0,
                  evaluated_planes=0, distinct_planes=0, potential_up_pairs=0)
    start = perf_counter_ns()
    if image.shape != (720, 1280, 3) or image.dtype != np.uint8:
        raise ValueError('native uint8 BGR frame required')
    gray = cv2.cvtColor(image[:, :640], cv2.COLOR_BGR2GRAY)
    ys, xs = np.nonzero(cv2.Canny(gray, 60, 120))
    native = np.column_stack((xs, ys)).astype(float)
    roi = (xs >= 40) & (xs <= 600) & (ys >= 60) & (ys <= 300)
    native = native[roi]
    timers['native_edges'] += perf_counter_ns() - start
    counts['raw_edge_pixels'] = len(xs)
    counts['roi_edge_pixels'] = len(native)

    start = perf_counter_ns()
    rays, valid = unproject(native, camera, image_size=(1280, 720))
    valid &= rays[:, 2] >= np.cos(np.deg2rad(75))
    native = native[valid]
    rays = rays[valid]
    points = 200 * rays[:, :2] / rays[:, 2, None]
    timers['inverse_projection'] += perf_counter_ns() - start
    counts['valid_ray_pixels'] = len(points)

    start = perf_counter_ns()
    candidates = cv2.HoughLinesPointSet(
        points.astype(np.float32).reshape(-1, 1, 2),
        200, 40, -1000, 1000, 1, 0, np.pi, np.pi / 720) if len(points) else None
    timers['hough'] += perf_counter_ns() - start
    proposals = candidates.reshape(-1, 3) if candidates is not None else []
    counts['hough_candidates'] = len(proposals)
    rows = []
    for index, (votes, rho, theta) in enumerate(proposals):
        start = perf_counter_ns()
        distance = abs(points @ np.array([np.cos(theta), np.sin(theta)]) - rho)
        ids = np.flatnonzero(distance <= 1)
        bins = np.floor(native[ids, 1] / 2).astype(int)
        timers['candidate_distance'] += perf_counter_ns() - start

        start = perf_counter_ns()
        chosen = []
        for bin_id in np.unique(bins):
            options = ids[bins == bin_id]
            chosen.append(options[np.argmin(distance[options])])
        chosen = np.asarray(chosen, dtype=np.intp)
        timers['bin_selection'] += perf_counter_ns() - start
        counts['bin_winners'] += len(chosen)

        start = perf_counter_ns()
        observed = native[chosen]
        pieces = np.split(chosen, np.flatnonzero(np.diff(observed[:, 1]) > 6) + 1)
        timers['segment_filter'] += perf_counter_ns() - start
        counts['gap_pieces'] += len(pieces)
        for part, indices in enumerate(pieces):
            start = perf_counter_ns()
            actual = native[indices]
            eligible = len(actual) >= 30
            if eligible:
                span = np.ptp(actual, axis=0)
                eligible = span[1] >= 60 and span[1] >= 1.5 * span[0]
            timers['segment_filter'] += perf_counter_ns() - start
            if not eligible:
                continue
            start = perf_counter_ns()
            plane = _plane_from_subset(native, rays, indices)
            timers['plane_evaluation'] += perf_counter_ns() - start
            counts['evaluated_planes'] += 1
            start = perf_counter_ns()
            rows.append(dict(line_index=index, part=part, hough_votes=float(votes),
                             rho=float(rho), theta=float(theta),
                             native_y_span=float(span[1]),
                             actual_edge_pixels_json=actual.tolist(), **plane))
            timers['row_materialization'] += perf_counter_ns() - start

    start = perf_counter_ns()
    kept = []
    for row in sorted((r for r in rows if r['accepted']), key=lambda r: -r['native_y_span']):
        n = np.array(row['normal'])
        if any(np.degrees(np.arccos(np.clip(abs(n @ np.array(r['normal'])), -1, 1))) < 2
               for r in kept):
            row.update(accepted=False, reason='duplicate_ray_plane')
        else:
            kept.append(row)
    timers['plane_deduplication'] += perf_counter_ns() - start

    start = perf_counter_ns()
    normals = np.array([r['normal'] for r in rows if r['accepted']]).reshape(-1, 3)
    up = infer_up(normals, prior)
    timers['up_estimation'] += perf_counter_ns() - start
    counts['distinct_planes'] = len(normals)
    counts['potential_up_pairs'] = len(normals) * (len(normals) - 1) // 2
    wall = perf_counter_ns() - wall_start
    residual = wall - sum(timers.values())
    assert residual >= 0
    record = dict(wall_ns=wall, other_and_instrumentation_ns=residual,
                  **{k + '_ns': v for k, v in timers.items()}, **counts)
    return rows, up, record
