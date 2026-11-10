"""Offline driver-range log audit. Standard library only; no camera/ROS/GPU."""
import argparse
from collections import Counter, defaultdict
import csv
import hashlib
import json
import math
from pathlib import Path
import re


FLAGS = ("physical_metric_verified", "floor_contact_verified", "controlling_distance",
         "usable_for_ffb", "published_to_ros")
COMPACT = ("session", "frame", "source_time_sec", "distance_available",
           "horizontal_camera_foot_range_m", "reason", "primary_model", *FLAGS)
FRAME_FIELDS = ("schema", *COMPACT, "media_time_sec", "completed_time_sec", "frame_age_ms",
                "predict_ms", "support_geometry_ms", "inference_source", "profile_sha256")


def number(value, label):
    if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
        raise ValueError("finite nonnegative number required: " + label)
    return value


def reject_constant(value):
    raise ValueError("nonfinite JSON: " + value)


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key: " + key)
        result[key] = value
    return result


def read_jsonl(path, *, fields=None):
    rows, sha = [], hashlib.sha256()
    with Path(path).open("rb") as stream:
        while True:
            line = stream.readline(4 * 1024 * 1024 + 1)
            if not line:
                break
            sha.update(line)
            if len(line) > 4 * 1024 * 1024 or not line.endswith(b"\n"):
                raise ValueError(f"{path}:{len(rows)+1}: oversized or unfinished line; copy closed logs")
            row = json.loads(line, parse_constant=reject_constant, object_pairs_hook=unique_object)
            if not isinstance(row, dict):
                raise ValueError(f"{path}:{len(rows)+1}: JSON object required")
            # Validate JSON for the entire line, but do not retain the large
            # per-pixel support payload when only scalar audit fields are used.
            rows.append(row if fields is None else {k: row[k] for k in fields if k in row})
    if not rows:
        raise ValueError("empty log: " + str(path))
    return rows, sha.hexdigest()


def validate_result(row):
    if not all(k in row for k in COMPACT):
        raise ValueError("missing result fields")
    if not isinstance(row["session"], str) or not re.fullmatch("[0-9a-f]{32}", row["session"]):
        raise ValueError("invalid session")
    if type(row["frame"]) is not int or row["frame"] <= 0:
        raise ValueError("positive integer frame required")
    number(row["source_time_sec"], "source_time_sec")
    if type(row["distance_available"]) is not bool:
        raise ValueError("boolean distance_available required")
    if any(row[k] is not False for k in FLAGS):
        raise ValueError("unexpected verification/control flag; not this experiment's format")
    if not isinstance(row["reason"], str) or not row["reason"]:
        raise ValueError("nonempty reason required")
    value = row["horizontal_camera_foot_range_m"]
    if row["distance_available"]:
        number(value, "horizontal_camera_foot_range_m")
    elif value is not None:
        raise ValueError("withheld result must have null distance")
    return row["session"], row["frame"]


def distribution(values):
    """Nearest-rank P50/P95, not a confidence interval."""
    values = sorted(values)
    if not values:
        return dict(count=0, min=None, p50=None, p95=None, max=None)
    return dict(count=len(values), min=values[0], max=values[-1],
                p50=values[math.ceil(.5 * len(values))-1],
                p95=values[math.ceil(.95 * len(values))-1])


def summarize(frames, events):
    by_key, groups, previous = {}, defaultdict(list), {}
    for row in frames:
        if row.get("schema") != "cone_motion_range_v1":
            raise ValueError("unexpected frame schema")
        key = validate_result(row)
        if key in by_key:
            raise ValueError("duplicate processed frame")
        for field in ("media_time_sec", "completed_time_sec", "frame_age_ms", "predict_ms", "support_geometry_ms"):
            number(row.get(field), field)
        if row["completed_time_sec"] < row["source_time_sec"]:
            raise ValueError("completion precedes source")
        if abs(row["frame_age_ms"] - 1000*(row["completed_time_sec"]-row["source_time_sec"])) > .05:
            raise ValueError("frame age does not match source/completion times")
        if not isinstance(row.get("inference_source"), str) or not row["inference_source"]:
            raise ValueError("explicit inference_source required")
        if not isinstance(row.get("profile_sha256"), str) or not re.fullmatch("[0-9a-f]{64}", row["profile_sha256"]):
            raise ValueError("profile SHA-256 required")
        prior = previous.get(key[0])
        if prior is not None:
            for field in ("frame", "media_time_sec", "source_time_sec", "completed_time_sec"):
                if row[field] <= prior[field]:
                    raise ValueError("nonincreasing per-session " + field)
            if row["profile_sha256"] != prior["profile_sha256"]:
                raise ValueError("profile changed within session")
        previous[key[0]] = row
        by_key[key] = row
        groups[key[0]].append(row)

    accepted = {}
    for event in events:
        result = event.get("result")
        if not isinstance(result, dict):
            raise ValueError("bridge result object required")
        key = validate_result(result)
        if key in accepted:
            raise ValueError("duplicate bridge event")
        if key not in by_key or any(result[k] != by_key[key][k] for k in COMPACT):
            raise ValueError("bridge/frame mismatch; do not mix runs")
        flag = event.get("accepted_current_session_and_age")
        if type(flag) is not bool:
            raise ValueError("boolean bridge acceptance required")
        accepted[key] = flag

    sessions = []
    for session, rows in groups.items():
        n = len(rows)
        valid = sum(row["distance_available"] for row in rows)
        completed = [row["completed_time_sec"] for row in rows]
        gaps = [1000*(b-a) for a, b in zip(completed, completed[1:])]
        distances = [row["horizontal_camera_foot_range_m"] for row in rows if row["distance_available"]]
        sessions.append(dict(
            session=session, profile_sha256=rows[0]["profile_sha256"], processed_frames=n,
            inference_sources=dict(Counter(row["inference_source"] for row in rows)),
            numeric_results=valid, processed_withheld_fraction=(n-valid)/n,
            withheld_reasons=dict(Counter(row["reason"] for row in rows if not row["distance_available"])),
            completion_span_sec=completed[-1]-completed[0],
            processed_result_interval_hz=((n-1)/(completed[-1]-completed[0]) if n > 1 else None),
            completion_gap_ms=distribution(gaps),
            bridge_events=sum((session, row["frame"]) in accepted for row in rows),
            bridge_accepted=sum(accepted.get((session, row["frame"])) is True for row in rows),
            bridge_retired=sum(accepted.get((session, row["frame"])) is False for row in rows),
            bridge_accepted_numeric=sum(row["distance_available"] and
                accepted.get((session, row["frame"])) is True for row in rows),
            frames_without_bridge_event=sum((session, row["frame"]) not in accepted for row in rows),
            distance_m=distribution(distances),
            timing_ms={field: distribution([row[field] for row in rows]) for field in
                       ("frame_age_ms", "predict_ms", "support_geometry_ms")}))
    return dict(schema="driver_motion_offline_report_v1", sessions=sessions,
                physical_accuracy_error_m=None, gui_time_withheld_fraction=None,
                end_to_end_camera_latency_ms=None, physical_metric_verified=False,
                usable_for_control=False), accepted


def report(input_dir, output_dir):
    input_dir, output_dir = Path(input_dir).resolve(), Path(output_dir).resolve()
    if output_dir == input_dir or input_dir in output_dir.parents:
        raise ValueError("output must be a new directory outside input")
    frames, frame_sha = read_jsonl(input_dir / "motion_distance_frames.jsonl", fields=FRAME_FIELDS)
    events, event_sha = read_jsonl(input_dir / "motion_bridge_events.jsonl")
    summary, accepted = summarize(frames, events)
    summary["input_dir"] = str(input_dir)
    summary["input_sha256"] = dict(motion_distance_frames_jsonl=frame_sha, motion_bridge_events_jsonl=event_sha)
    output_dir.mkdir(parents=True, exist_ok=False)
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2, allow_nan=False)+"\n")
    fields = ["session", "frame", "media_time_sec", "source_time_sec", "completed_time_sec",
              "distance_available", "horizontal_camera_foot_range_m", "reason", "frame_age_ms",
              "predict_ms", "support_geometry_ms", "inference_source", "bridge_accepted"]
    with (output_dir / "frames.csv").open("x", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in frames:
            writer.writerow({**{field: row[field] for field in fields[:-1]},
                             "bridge_accepted": accepted.get((row["session"], row["frame"]))})
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    report(args.input_dir, args.output_dir)
    print("Offline summary.json / frames.csv saved. No accuracy/control approval.")


if __name__ == "__main__":
    main()
