"""Count offline front detections/hypotheses without inventing visibility GT."""
from collections import defaultdict
import math

from cone_observation import checked_bbox
from run_cone_video import zero_runs


def summarize_stream(frames, predictions, projector):
    """Validate CSV alignment, retain every frame, and count three scopes.

    A zero run is only absence of a model/geometry candidate, never an automatic
    false negative. Another cone or a false detection can mask a target's loss.
    No target identity, safe-clear state, TTC, or FFB demand is generated.
    """
    by_key, last_number, last_time = {}, {}, {}
    for source in frames:
        session = source["session"]
        number, when, count = int(source["frame"]), float(source["time_sec"]), int(source["detections"])
        if (not session or number != last_number.get(session, 0)+1 or count < 0
                or not math.isfinite(when) or when < 0 or when <= last_time.get(session, -1)):
            raise ValueError("contiguous one-based frames, finite increasing times and nonnegative counts required")
        last_number[session], last_time[session] = number, when
        by_key[(session, number)] = (when, count)
    if not by_key:
        raise ValueError("nonempty frame stream required")
    selected, seen = defaultdict(list), set()
    for source in predictions:
        key = (source["session"], int(source["frame"]))
        index, when = int(source["prediction_index"]), float(source["time_sec"])
        if (key not in by_key or index < 0 or (key, index) in seen
                or not math.isfinite(when) or abs(when-by_key[key][0]) > 1e-9):
            raise ValueError("unique prediction index and exact frame/time alignment required")
        seen.add((key, index))
        row = dict(source, prediction_index=index)
        for name in ("confidence", "class_id", "x1", "y1", "x2", "y2"):
            row[name] = float(row[name])
        checked_bbox(row, projector.width, projector.height)
        if (not math.isfinite(row["confidence"]) or not 0 <= row["confidence"] <= 1
                or row["confidence"] < projector.confidence_threshold-1e-7 or row["class_id"] != 0):
            raise ValueError("frozen threshold and single cone class required")
        selected[key].append(row)
    counts, hypotheses = [], []
    for source in frames:
        key = (source["session"], int(source["frame"]))
        current = selected.get(key, [])
        if sorted(row["prediction_index"] for row in current) != list(range(by_key[key][1])):
            raise ValueError("prediction rows differ from recorded frame detection count")
        front_count, projection_count = 0, 0
        for row in current:
            front = projector.centre_in_front_lens(row)
            front_count += front
            result = projector.project(row, frame_width=projector.width, frame_height=projector.height)
            projection_count += result["projection_candidate"]
            hypotheses.append(dict(**row, front_centre=front, **result))
        counts.append(dict(session=key[0], frame=key[1], time_sec=by_key[key][0],
                           all_detections=len(current), front_detections=front_count,
                           projection_candidates=projection_count))
    summaries, runs = [], []
    for session in last_number:
        series = [row for row in counts if row["session"] == session]
        for scope, column in (("all_view", "all_detections"), ("front_centre", "front_detections"),
                              ("projection_hypotheses", "projection_candidates")):
            gaps = zero_runs([dict(row, detections=row[column]) for row in series])
            summaries.append(dict(session=session, scope=scope, frames=len(series),
                                  frames_with_candidates=sum(row[column] > 0 for row in series),
                                  zero_frames=sum(row[column] == 0 for row in series),
                                  multi_candidate_frames=sum(row[column] > 1 for row in series),
                                  zero_runs=len(gaps), internal_zero_runs=sum(r["bounded_by_detection"] for r in gaps),
                                  max_zero_sample_span_sec=max((r["sample_span_sec"] for r in gaps), default=0),
                                  truth="candidate counts only; NOT precision/recall or safety states"))
            runs.extend(dict(scope=scope, **row) for row in gaps)
    return counts, hypotheses, summaries, runs
