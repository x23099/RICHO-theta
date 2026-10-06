"""Offline-only metrics for a complete visual review of old occlusion labels.

Labels must be reviewed independently of detector output. No ROS, runtime
configuration, calibration, or detector thresholds are changed here.
"""
from collections import Counter


PHASES = ("partial_occlusion", "fully_occluded", "uncertain")


def positive_frame(value):
    frame = int(value)
    if str(frame) != str(value) or frame < 1:
        raise ValueError(f"expected a positive one-based frame: {value}")
    return frame


def flag(row, name):
    value = str(row[name])
    if value not in ("0", "1"):
        raise ValueError(f"invalid binary flag {name}: {value}")
    return int(value)


def join_reviews(reviews, labelled, results, variants):
    """Require every old fully-labelled frame, including frames with no detection.

    Unreviewed phases remain outside this review; they are never inferred visible.
    Frozen variant sets must cover exactly the same old fully-labelled frames.
    """
    variants = tuple(variants)
    if not variants or len(set(variants)) != len(variants):
        raise ValueError("variants must be nonempty and unique")
    old = {}
    for row in labelled:
        if row["variant"] not in variants or row["phase_label"] != "fully_occluded":
            continue
        frame = positive_frame(row["frame"])
        if int(row["video_index_zero_based"]) != frame - 1:
            raise ValueError("old frame/index mismatch")
        key = (row["session"], row["variant"], frame)
        if key in old:
            raise ValueError("duplicate old label")
        old[key] = row
    target = {(session, frame) for session, variant, frame in old if variant == variants[0]}
    if not target:
        raise ValueError("no old fully_occluded frames to review")
    for variant in variants:
        if {(s, f) for s, v, f in old if v == variant} != target:
            raise ValueError("old review target differs between variants")
    manual = {}
    for row in reviews:
        frame = positive_frame(row["frame_one_based"])
        key = (row["session"], frame)
        if key in manual:
            raise ValueError("duplicate manual review")
        if row["reviewed_phase"] not in PHASES:
            raise ValueError("unknown reviewed phase")
        if row["review_method"] != "whole_raw_frame_visual_review" or not row["visible_evidence"]:
            raise ValueError("missing independent visual review evidence")
        manual[key] = row
    if set(manual) != target:
        raise ValueError("manual review must cover exactly ALL old fully_occluded frames")
    lookup = {}
    for row in results:
        if row["variant"] not in variants:
            continue
        frame = positive_frame(row["frame"])
        if (row["session"], frame) not in target:
            continue
        key = (row["session"], row["variant"], frame)
        if key in lookup:
            raise ValueError("duplicate frozen result")
        lookup[key] = row
    if set(lookup) != set(old):
        raise ValueError("missing frozen result for reviewed frame/variant")
    joined = []
    for session, frame in sorted(target):
        review = manual[session, frame]
        for variant in variants:
            key = (session, variant, frame)
            result, label = lookup[key], old[key]
            for field in ("detected", "measurement_accepted", "track_available", "track_predicted"):
                if flag(result, field) != flag(label, field):
                    raise ValueError("frozen result differs from original labelled result")
            if float(result["time_sec"]) != float(label["time_sec"]):
                raise ValueError("frozen timestamp mismatch")
            if flag(result, "measurement_accepted") and not flag(result, "detected"):
                raise ValueError("accepted measurement without detection")
            joined.append(dict(result, original_phase=label["phase_label"],
                               occlusion_event=label["occlusion_event"],
                               reviewed_phase=review["reviewed_phase"],
                               visible_evidence=review["visible_evidence"],
                               review_method=review["review_method"],
                               video_index_zero_based=frame - 1))
    return joined


def phase_metrics(rows, variant, phase):
    selected = [r for r in rows if r["variant"] == variant and r["reviewed_phase"] == phase]
    count = len(selected)
    metrics = dict(variant=variant, reviewed_phase=phase, frames=count,
                   assessment="OBSERVED_NOT_CERTIFIED" if count else "NOT_EVALUATED")
    for field in ("detected", "measurement_accepted", "track_available", "track_predicted"):
        total = sum(flag(r, field) for r in selected)
        metrics[field] = total if count else None
        metrics[field + "_rate"] = total / count if count else None
    return metrics


def review_summary(rows, variants):
    phases = [phase_metrics(rows, variant, phase) for variant in variants for phase in PHASES]
    events = []
    keys = sorted({(r["session"], r["occlusion_event"], r["variant"]) for r in rows})
    for session, event, variant in keys:
        selected = [r for r in rows if (r["session"], r["occlusion_event"], r["variant"]) ==
                    (session, event, variant)]
        counts = Counter(r["reviewed_phase"] for r in selected)
        events.append(dict(session=session, occlusion_event=event, variant=variant,
                           reviewed_frames=len(selected),
                           start_frame=min(int(r["frame"]) for r in selected),
                           end_frame=max(int(r["frame"]) for r in selected),
                           **{phase + "_frames": counts[phase] for phase in PHASES},
                           detected=sum(flag(r, "detected") for r in selected),
                           measurement_accepted=sum(flag(r, "measurement_accepted") for r in selected)))
    return phases, events
