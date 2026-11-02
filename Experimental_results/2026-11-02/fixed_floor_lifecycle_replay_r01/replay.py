"""Offline model lifecycle over stored observations. Never a live receiver.

Only comparison fields are added. File-read completion uses a declared logical
delay, not GPU/network performance. The REAL production payload validator runs.
"""
from collections import Counter
from concurrent.futures import Future
import copy
import csv
import json
from pathlib import Path
import sys
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT/"src"))
from cone_distance_core import load_config
from cone_fixed_floor_live_load import LocalFloorModelLoader
from cone_fixed_floor_shadow import enforce_freshness
from summarize_cone_distance_live import validate_row


class LogicalFileExecutor:
    """One real file-validation call at a declared virtual completion time."""
    def __init__(self, clock, delay):
        if type(delay) not in (float, int) or not 0 <= delay <= 10:
            raise ValueError("bounded declared logical file-read delay required")
        self.clock, self.delay, self.job = clock, delay, None

    def submit(self, function, *args):
        if self.job is not None:
            raise ValueError("no queued loads")
        future = Future()
        future.set_running_or_notify_cancel()
        self.job = (future, function, args, self.clock[0]+self.delay)
        return future

    def finish(self, now):
        if self.job is None or self.job[3] > now:
            return
        future, function, args, completed = self.job
        self.job = None
        self.clock[0] = completed
        try:
            future.set_result(function(*args))
        except Exception as exc:
            future.set_exception(exc)
        self.clock[0] = now

    def shutdown(self, **kwargs):
        pass


def stored_observation(row, source):
    if source == "baseline":
        return row.get("frame_evidence", {}).get("support_observation")
    return row.get(source, {}).get("candidate")


def audit_rows(original, output):
    if len(original) != len(output):
        raise ValueError("complete original processed-row coverage required")
    previous_source = previous_completion = None
    for before, after in zip(original, output):
        validate_row(after)
        if previous_source is not None and (after["source_time_sec"] <= previous_source
                                           or after["completed_time_sec"] < previous_completion):
            raise ValueError("increasing source/nondecreasing completion times required")
        previous_source, previous_completion = after["source_time_sec"], after["completed_time_sec"]
        stripped = {k: v for k, v in after.items() if k not in ("fixed_floor_load", "fixed_floor_shadow")}
        if stripped != before:
            raise ValueError("original observation/distance/timing changed")
        fixed = after.get("fixed_floor_shadow")
        load = after["fixed_floor_load"]
        if fixed is not None:
            if (load["state"] != "active" or after["frame"] <= max(load["evidence_frames"])
                    or after["source_time_sec"] < load["load_completed_at_sec"]):
                raise ValueError("model leaked to a pre-load/reference frame")
            if after["frame_age_ms"] > 500 and any(m["range_available"] for m in fixed["models"]):
                raise ValueError("stale comparison value released")


def run_case(rows, models, evidence_dir, output_dir, schedule, *, config=None, delay=.06,
             source="support_completion_shadow", kind):
    if not rows or any("fixed_floor_load" in r or "fixed_floor_shadow" in r for r in rows):
        raise ValueError("nonempty original observations without prior comparison fields required")
    for row in rows:
        validate_row(row)
    if len({r["session"] for r in rows}) != 1:
        raise ValueError("one original session required; no renaming")
    frames = [r["frame"] for r in rows]
    if frames != sorted(set(frames)) or any(e["after_frame"] not in frames for e in schedule):
        raise ValueError("ordered actual frame IDs and exact existing action frames required")
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=False)
    settings, camera, transform, _ = load_config() if config is None else load_config(config)
    from cone_distance_core import DEFAULT_CONFIG, digest
    clock = [rows[0]["source_time_sec"]]
    pool = LogicalFileExecutor(clock, delay)
    loader = LocalFloorModelLoader(models, settings, digest(DEFAULT_CONFIG if config is None else config),
        evidence_dir, output_dir/"fixed_floor_model_events.jsonl", source, clock=lambda: clock[0], executor=pool)
    output, actions = [], []
    try:
        for before in rows:
            t = before["source_time_sec"]
            pool.finish(t)
            clock[0] = t
            frame = SimpleNamespace(session=before["session"], sequence=before["frame"], received_at=t)
            adapter = loader.step(frame)
            row = copy.deepcopy(before)
            if adapter is not None:
                row["fixed_floor_shadow"] = adapter.observe(frame, stored_observation(before, source), camera, transform)
                enforce_freshness(row["fixed_floor_shadow"], row["frame_age_ms"])
            row["fixed_floor_load"] = loader.snapshot()
            output.append(row)
            for event in (e for e in schedule if e["after_frame"] == before["frame"]):
                clock[0] = before["completed_time_sec"]
                if event["action"] == "request":
                    loader.path = Path(event.get("models", models))
                    accepted, reason = loader.request(frame)
                elif event["action"] == "disconnect":
                    loader.step(None)
                    accepted, reason = True, "simulated_input_disconnect"
                else:
                    raise ValueError("explicit request/disconnect actions only")
                actions.append(dict(event, logical_time_sec=clock[0], accepted=accepted, reason=reason))
        # Finish I/O, NOT another camera frame. Never invent a final evaluation.
        if pool.job is not None:
            pool.finish(max(clock[0], pool.job[3]))
        loader.step(None)
    finally:
        shutdown = loader.close()
    audit_rows(rows, output)
    flat = []
    for row in output:
        fixed = row.get("fixed_floor_shadow", {})
        ranges = [m["horizontal_camera_foot_range_m"] for m in fixed.get("models", []) if m["range_available"]]
        flat.append(dict(frame=row["frame"], source_time_sec=row["source_time_sec"],
            load_state=row["fixed_floor_load"]["state"], load_reason=row["fixed_floor_load"]["reason"],
            generation=row["fixed_floor_load"]["generation"],
            baseline_available=row["distance_available"], baseline_forward_m=row["distance_forward_m"],
            comparison_available=bool(ranges), models_with_range=len(ranges),
            comparison_min_m=min(ranges) if ranges else None, comparison_max_m=max(ranges) if ranges else None,
            comparison_reason=fixed.get("reason", "no_active_model"), frame_age_ms=row["frame_age_ms"]))
    with (output_dir/"distance_frames.jsonl").open("x") as stream:
        for row in output:
            stream.write(json.dumps(row, allow_nan=False)+"\n")
    with (output_dir/"timeline.csv").open("x", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(flat[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(flat)
    events = [json.loads(line) for line in (output_dir/"fixed_floor_model_events.jsonl").read_text().splitlines()]
    summary = dict(data_kind=kind, session=rows[0]["session"], processed_rows=len(rows),
        original_fields_unchanged=len(rows), actions=actions,
        load_states=dict(Counter(r["load_state"] for r in flat)),
        load_event_counts=dict(Counter(e["action"] for e in events)),
        comparison_available_rows=sum(r["comparison_available"] for r in flat),
        comparison_reason_counts=dict(Counter(r["comparison_reason"] for r in flat)),
        logical_file_read_delay_sec=delay, logical_schedule_is_not_measured_latency=True,
        saved_observations_not_fresh_inference=True, no_fake_live_summary_created=True,
        physical_metric_verified=False, floor_contact_verified=False, usable_for_ffb=False,
        shutdown=shutdown)
    (output_dir/"summary.json").write_text(json.dumps(summary, indent=2)+"\n")
    return output, flat, summary
