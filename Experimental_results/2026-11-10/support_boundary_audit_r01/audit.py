"""保存された輪郭診断・bbox座標だけを監査。live採用／点の補間はしない。"""
import argparse
from bisect import bisect_left
from collections import Counter
import csv
import hashlib
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
from report_driver_motion_logs import FLAGS, reject_constant, unique_object

SESSION = "7f33c225af3948c2aa61d66d52765c2e"
LO, HI = 33809, 34379


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def bbox_relation(box, point):
    values = [box[k] for k in ("x1", "y1", "x2", "y2")]
    if (not all(finite(v) for v in values) or not isinstance(point, list) or len(point) != 2
            or any(type(v) is not int for v in point)):
        raise ValueError("finite float bbox / integer observed point required")
    x1, y1, x2, y2 = values
    x, y = point
    if not (0 <= x1 < x2 <= 640 and 0 <= y1 < y2 <= 720 and 0 <= x < 640 and 0 <= y < 720):
        raise ValueError("bounded native front coordinates required")
    return dict(point=point, outside_left_px=max(0., x1-x), outside_right_px=max(0., x-x2),
                outside_top_px=max(0., y1-y), outside_bottom_px=max(0., y-y2),
                inside_strict_float_bbox=x1 <= x <= x2 and y1 <= y <= y2,
                # Counterfactual coordinate conventions, NOT permission to use.
                pixel_cell_overlaps_bbox=(x+.5 >= x1 and x-.5 <= x2 and y+.5 >= y1 and y-.5 <= y2),
                inside_outward_rounded_inclusive_bbox=(math.floor(x1) <= x <= math.ceil(x2)
                                                       and math.floor(y1) <= y <= math.ceil(y2)))


def candidate_audit(row):
    """Require the logged late rejection and two identical closed contexts.

    A pixel SHA is evidence recorded by the observer, not a recoverable mask;
    this cannot independently rerun seed connectivity / old-pixel inclusion.
    """
    result = dict(frame=row["frame"], source_time_sec=row["source_time_sec"],
                  live_reason=row["reason"], live_distance_available=row["distance_available"],
                  diagnostic_only=True, adopted=False, physical_metric_verified=False,
                  floor_contact_verified=False, usable_for_ffb=False, controlling_distance=False,
                  published_to_ros=False)
    observation = row.get("support_observation") or {}
    contexts = observation.get("contexts") or []
    first = contexts[0] if contexts else ((observation.get("upper_contexts") or [{}])[0])
    result["original_touches"] = (first.get("component") or {}).get("touches")
    result["completion_reason"] = observation.get("completion_reason")
    if (row["distance_available"] or row["reason"] != "colour_contour_reaches_roi_edge"
            or observation.get("completion_reason") != "completed_point_outside_original_bbox"):
        return dict(result, audit_reason="no_logged_late_bbox_only_rejection")
    if any(row.get(k) is not False for k in FLAGS) or len(row.get("selected_detector_boxes", [])) != 1:
        raise ValueError("unverified single-box record required")
    if len(contexts) != 3:
        return dict(result, audit_reason="missing_three_lateral_contexts")
    a, b = contexts[-2:]
    ca, cb = a.get("component") or {}, b.get("component") or {}
    sha = ca.get("pixel_sha256")
    if (not isinstance(sha, str) or len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha)
            or cb.get("pixel_sha256") != sha or a.get("observation") != b.get("observation")
            or any(c.get("touches") != dict(left=False, right=False, top=False, bottom=False) for c in (ca, cb))
            or not (4 < a.get("lateral_padding_px", 0) < b.get("lateral_padding_px", 0))):
        return dict(result, audit_reason="closed_pair_identity_not_proven_in_log")
    obs = a.get("observation") or {}
    point = obs.get("point")
    support = obs.get("support")
    if not isinstance(point, list) or not isinstance(support, list) or point not in support:
        return dict(result, audit_reason="candidate_not_in_logged_support")
    relation = bbox_relation(row["selected_detector_boxes"][0], point)
    if relation["inside_strict_float_bbox"]:
        raise ValueError("recorded bbox-only rejection contradicts strict float coordinates")
    return dict(result, audit_reason="logged_closed_pair_rejected_at_float_bbox_only",
                component_sha256=sha, relation=relation, logged_candidate_support=support,
                native_pixels_rechecked=False)


def sha_file(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024*1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    source, output = args.input_dir.resolve(), args.output_dir.resolve()
    if output.exists() or output == source or source in output.parents:
        raise ValueError("new output outside source required")
    previous = json.loads((ROOT/"Experimental_results/2026-11-10/driver_motion_live_analysis_r01/results_r01/analysis.json").read_text())
    path = source/"motion_distance_frames.jsonl"
    expected_sha = previous["input_sha256"][path.name]
    sha = hashlib.sha256()
    all_audits, window, total = [], [], 0
    with path.open("rb") as stream:
        for line in stream:
            sha.update(line)
            row = json.loads(line, parse_constant=reject_constant, object_pairs_hook=unique_object)
            total += 1
            if row["session"] != SESSION:
                raise ValueError("unexpected session")
            if LO <= row["frame"] <= HI:
                window.append({k: row[k] for k in ("frame", "source_time_sec", "completed_time_sec",
                    "distance_available", "horizontal_camera_foot_range_m", "reason")})
            if row["reason"] == "colour_contour_reaches_roi_edge":
                all_audits.append(candidate_audit(row))
    if sha.hexdigest() != expected_sha:
        raise ValueError("input differs from the previously validated run")

    # Reuse the exact existing camera and fixed-floor equations, not a new fit.
    from angular_fisheye_geometry import unproject
    from cone_distance_core import DEFAULT_CONFIG, digest, load_config
    from cone_motion_range import checked_current_support, horizontal_range, load_motion_profile
    settings, camera, _, _ = load_config()
    profile, profile_sha = load_motion_profile(source/"motion_profile_used.json", settings)
    engine = previous["runtime_metadata"]["motion_engine_summary.json"]
    if digest(DEFAULT_CONFIG) != engine["config_sha256"] or profile_sha != engine["profile_sha256"]:
        raise ValueError("original geometry/config required")
    model = next(m for m in profile["models"] if m["id"] == profile["primary_model"])
    valid = [r for r in window if r["distance_available"]]
    keys = [r["frame"] for r in valid]
    motion = [r for r in all_audits if LO <= r["frame"] <= HI]
    for row in motion:
        if "relation" not in row:
            continue
        point, support_reason = checked_current_support(dict(point=row["relation"]["point"],
            support=row["logged_candidate_support"]))
        row["current_spatial_support_valid"] = point is not None
        row["current_spatial_support_reason"] = support_reason
        rays, domain = unproject([point], camera, image_size=(1280, 720)) if point is not None else (None, [False])
        value = horizontal_range(rays[0], model) if domain[0] else None
        row["diagnostic_candidate_range_m_NOT_output_or_ground_truth"] = value
        index = bisect_left(keys, row["frame"])
        neighbors = [valid[i] for i in (index-1, index) if 0 <= i < len(valid)]
        row["neighbor_numeric_results_NOT_ground_truth"] = neighbors

    # Contiguous rejected PROCESSED records, not duration of actual GUI holds.
    runs, active = [], []
    for row in window:
        if not row["distance_available"]:
            active.append(row)
        elif active:
            runs.append(dict(first_frame=active[0]["frame"], last_frame=active[-1]["frame"],
                             processed_rejections=len(active),
                             rejected_completion_span_ms=1000*(active[-1]["completed_time_sec"]-active[0]["completed_time_sec"]),
                             next_numeric_frame=row["frame"]))
            active = []
    if active:
        runs.append(dict(first_frame=active[0]["frame"], last_frame=active[-1]["frame"],
                         processed_rejections=len(active), next_numeric_frame=None))
    def counts(rows):
        pairs = [r for r in rows if "relation" in r]
        return dict(boundary_rejections=len(rows), logged_closed_pair_candidates=len(pairs),
                    half_pixel_overlap_candidates=sum(r["relation"]["pixel_cell_overlaps_bbox"] for r in pairs),
                    outward_inclusive_rounding_candidates=sum(r["relation"]["inside_outward_rounded_inclusive_bbox"] for r in pairs),
                    audit_reasons=dict(Counter(r["audit_reason"] for r in rows)))
    output.mkdir(parents=True, exist_ok=False)
    payload = dict(schema="logged_support_boundary_audit_v1", input_sha256=expected_sha,
        source_records=total, profile_sha256=profile_sha, full_run_counts=counts(all_audits),
        motion_window_counts=counts(motion), motion_rejections=motion, processed_rejection_runs=runs,
        adopted=False, live_distance_unchanged=True, native_pixels_available=False,
        physical_accuracy_improvement_verified=False, gui_withheld_durations_measured=False,
        dependency_sha256={name: sha_file(ROOT/"src"/name) for name in (
            "cone_support_completion_candidate.py", "cone_upper_support_candidate.py",
            "cone_motion_range.py", "cone_distance_core.py", "cone_support_quality.py",
            "angular_fisheye_geometry.py")})
    with (output/"audit.json").open("x") as stream:
        json.dump(payload, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write("\n")
    fields = ["frame", "outside_bottom_px", "half_pixel_overlap", "outward_inclusive_rounding",
              "diagnostic_range_m_NOT_live"]
    with (output/"rounding_candidates.csv").open("x", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in motion:
            if "relation" in row:
                r = row["relation"]
                writer.writerow(dict(frame=row["frame"], outside_bottom_px=r["outside_bottom_px"],
                    half_pixel_overlap=r["pixel_cell_overlaps_bbox"],
                    outward_inclusive_rounding=r["inside_outward_rounded_inclusive_bbox"],
                    diagnostic_range_m_NOT_live=row["diagnostic_candidate_range_m_NOT_output_or_ground_truth"]))
    print(json.dumps({"full_run": counts(all_audits), "motion_window": counts(motion)}, indent=2))


if __name__ == "__main__":
    main()
