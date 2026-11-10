"""処理済みrecordの状態遷移。GUI保留時間や物理運動を推定しない。"""
from collections import Counter
import math

CONFLICT = {"numeric_body_boundary_conflict", "boundary_withheld_body_boundary_conflict"}


def brief(row):
    if row is None:
        return None
    return {k: row[k] for k in ("frame", "source_time_sec", "completed_time_sec", "state", "range_m")}


def summarize(rows, *, gap_limit_sec=.2):
    if type(gap_limit_sec) not in (int, float) or not math.isfinite(gap_limit_sec) or gap_limit_sec <= 0:
        raise ValueError("positive finite gap limit required")
    previous = None
    transitions, episodes, runs = Counter(), [], []
    episode_start = run_start = None
    for i, row in enumerate(rows):
        if (not isinstance(row.get("state"), str) or not row["state"]
                or type(row.get("frame")) is not int or row["frame"] < 1
                or any(type(row.get(k)) not in (int, float) or not math.isfinite(row[k])
                       for k in ("source_time_sec", "completed_time_sec"))
                or row["completed_time_sec"] < row["source_time_sec"]):
            raise ValueError("finite ordered record required")
        if previous is not None and (row["session"] != previous["session"]
                or row["frame"] <= previous["frame"]
                or row["source_time_sec"] <= previous["source_time_sec"]
                or row["completed_time_sec"] <= previous["completed_time_sec"]):
            raise ValueError("single session with increasing frame/source/completion required")
        continuous = previous is not None and row["source_time_sec"] - previous["source_time_sec"] <= gap_limit_sec
        if continuous:
            transitions[previous["state"] + " -> " + row["state"]] += 1
        if run_start is not None and (not continuous or row["state"] != previous["state"]):
            runs.append(dict(first_index=run_start, last_index=i-1,
                             state=rows[run_start]["state"], count=i-run_start))
            run_start = None
        if run_start is None:
            run_start = i
        if episode_start is not None and (not continuous or row["state"] not in CONFLICT):
            episodes.append((episode_start, i-1))
            episode_start = None
        if row["state"] in CONFLICT and episode_start is None:
            episode_start = i
        previous = row
    if run_start is not None:
        runs.append(dict(first_index=run_start, last_index=len(rows)-1,
                         state=rows[run_start]["state"], count=len(rows)-run_start))
    if episode_start is not None:
        episodes.append((episode_start, len(rows)-1))
    details = []
    for start, end in episodes:
        group = rows[start:end+1]
        clear = next((r for r in rows[end+1:] if r["state"] == "numeric_clear_of_body_boundary"), None)
        values = [r["range_m"] for r in group if r["range_m"] is not None]
        details.append(dict(first_frame=group[0]["frame"], last_frame=group[-1]["frame"],
            count=len(group), state_counts=dict(Counter(r["state"] for r in group)),
            source_span_ms=1000*(group[-1]["source_time_sec"]-group[0]["source_time_sec"]),
            completion_span_ms=1000*(group[-1]["completed_time_sec"]-group[0]["completed_time_sec"]),
            numeric_min_m=min(values) if values else None, numeric_max_m=max(values) if values else None,
            previous_processed=brief(rows[start-1] if start else None),
            next_processed=brief(rows[end+1] if end+1 < len(rows) else None),
            next_clear_numeric=brief(clear),
            next_clear_source_gap_ms=1000*(clear["source_time_sec"]-group[-1]["source_time_sec"]) if clear else None))
    return dict(processed_records=len(rows), state_counts=dict(Counter(r["state"] for r in rows)),
        transitions=dict(transitions), conflict_episodes=details, state_runs=runs,
        gap_limit_sec=gap_limit_sec, gui_hold_duration_measured=False, physical_motion_measured=False)
