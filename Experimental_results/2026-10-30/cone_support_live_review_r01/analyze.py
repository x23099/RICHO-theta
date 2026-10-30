#!/usr/bin/env python3
"""保存r02ログの候補・時系列監査。距離再計算・推論・実機操作なし。"""
import argparse
from collections import Counter
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import sys

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
from cone_distance_core import load_config, observe_support
from cone_colour_support_candidate import observe_separated_support
from cone_support_completion_candidate import observe_lateral_completion
from cone_support_quality import ConeSupportQualityGate
from summarize_cone_distance_live import load_frames, statistics

FLAGS = ("controlling_distance", "floor_contact_verified", "usable_for_ffb")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def partition(old, new):
    if any(c.get(key) is not False for c in (old, new) for key in FLAGS):
        raise ValueError("non-controlling unverified candidates required")
    point = old.get("point")
    if point is not None:
        if new.get("point") != point or new.get("support") != old.get("support") or new["completion_granted"]:
            raise ValueError("existing support changed or falsely counted as completion")
        return "preserved"
    if new.get("point") is not None:
        if not new["completion_granted"] or not new["completion_attempted"]:
            raise ValueError("new point must declare attempted/granted completion")
        return "completed"
    if new["completion_granted"]:
        raise ValueError("grant without point")
    return "withheld"


def check_completion(candidate, box):
    """Check logged context consistency, NOT physical contact or pixel truth."""
    contexts = candidate["contexts"]
    if len(contexts) != 3:
        raise ValueError("three original/narrow/wide context records required")
    original, narrow, wide = contexts
    touches = original["component"]["touches"]
    if touches["top"] or touches["bottom"] or not (touches["left"] or touches["right"]):
        raise ValueError("original contact not lateral-only")
    if any(any(c["component"]["touches"].values()) for c in (narrow, wide)):
        raise ValueError("expanded component is not closed")
    if narrow["component"]["pixel_sha256"] != wide["component"]["pixel_sha256"]:
        raise ValueError("expanded pixel sets differ")
    if narrow["observation"] != wide["observation"]:
        raise ValueError("expanded observations differ")
    if any(candidate[k] != narrow["observation"][k] for k in ("point", "support")):
        raise ValueError("logged final observation differs from context")
    pad = min(16, max(8, math.ceil(.2*(box["x2"]-box["x1"]))))
    for context, padding in zip(contexts, (4, pad, 2*pad)):
        expected = [math.floor(box["x1"])-padding, math.floor(box["y1"])-4,
                    math.ceil(box["x2"])+padding, math.ceil(box["y2"])+4]
        if context["crop_xyxy"] != expected:
            raise ValueError("context does not match frozen crop rule")
    x, y = candidate["point"]
    if not box["x1"] <= x <= box["x2"] or not box["y1"] <= y <= box["y2"]:
        raise ValueError("completion point outside original detector box")
    return dict(original_touches=[k for k, v in touches.items() if v],
        original_and_expanded_component_hash_equal=(original["component"]["pixel_sha256"] == narrow["component"]["pixel_sha256"]),
        narrow_padding=pad, wide_padding=2*pad,
        component_pixels=narrow["component"]["pixel_count"])


def runs(rows, predicate):
    """Inclusive observed runs; an unlogged sequence number breaks a run."""
    output, active = [], []
    for row in rows:
        if active and (row["frame"] != active[-1]["frame"]+1 or not predicate(row)):
            output.append(active)
            active = []
        if predicate(row):
            active.append(row)
    if active:
        output.append(active)
    return [dict(first_frame=group[0]["frame"], last_frame=group[-1]["frame"],
                 logged_frames=len(group), source_first_sec=group[0]["source_time_sec"],
                 source_last_sec=group[-1]["source_time_sec"],
                 observed_sample_span_sec=group[-1]["source_time_sec"]-group[0]["source_time_sec"])
            for group in output]


def adjacent_metrics(rows, prefix):
    distances, dxs, dys, pairs = [], [], [], []
    for a, b in zip(rows, rows[1:]):
        if b["frame"] != a["frame"]+1 or b["source_time_sec"]-a["source_time_sec"] > .2:
            continue
        pa, pb = a[prefix+"_point"], b[prefix+"_point"]
        if pa is None or pb is None:
            continue
        dx, dy = pb[0]-pa[0], pb[1]-pa[1]
        step = math.hypot(dx, dy)
        distances.append(step)
        dxs.append(abs(dx))
        dys.append(abs(dy))
        pairs.append(dict(before_frame=a["frame"], after_frame=b["frame"],
                          dx_px=dx, dy_px=dy, step_px=step))
    return dict(step_px=statistics(distances), abs_dx_px=statistics(dxs), abs_dy_px=statistics(dys),
                largest_steps=sorted(pairs, key=lambda r: -r["step_px"])[:10])


def summarize_rows(rows):
    gates = {key: ConeSupportQualityGate() for key in ("old", "new")}
    flat, checks = [], []
    for row in rows:
        old, new = [row[key]["candidate"] for key in ("colour_support_shadow", "support_completion_shadow")]
        if old is None or new is None or len(row["selected_detector_boxes"]) != 1:
            raise ValueError("one logged associated candidate required for this fixed-scope audit")
        category = partition(old, new)
        box = row["selected_detector_boxes"][0]
        item = dict(frame=row["frame"], session=row["session"], source_time_sec=row["source_time_sec"],
            category=category, selected_colour=new["selected_colour"], old_point=old["point"], new_point=new["point"],
            old_reason=old["reason"], new_reason=new["reason"], completion_reason=new["completion_reason"],
            seed_red_pixels=new["seed_red_pixels"], seed_yellow_pixels=new["seed_yellow_pixels"],
            seed_dominant_fraction=new["seed_dominant_fraction"], seed_xyxy=new["seed_xyxy"],
            bbox=box, frame_age_ms=row["frame_age_ms"], within_500ms=row["frame_age_ms"] <= 500,
            original_distance_available=row["distance_available"], scene_initialized=row["scene_initialized"])
        if category == "completed":
            checks.append(dict(frame=row["frame"], **check_completion(new, box)))
        for prefix, candidate in (("old", old), ("new", new)):
            point = candidate["point"]
            if point is not None and point not in candidate["support"]:
                raise ValueError("point is not observed support")
            item[prefix+"_point_outside_bbox"] = bool(point is not None and
                not (box["x1"] <= point[0] <= box["x2"] and box["y1"] <= point[1] <= box["y2"]))
            item[prefix+"_point_bbox_excess_px"] = (max(0., box["x1"]-point[0], point[0]-box["x2"],
                box["y1"]-point[1], point[1]-box["y2"]) if point is not None else None)
            result = gates[prefix].update(row["source_time_sec"],
                [dict(support=candidate["support"] if point is not None else None,
                      unavailable_reason=candidate["reason"])])
            item[prefix+"_offline_quality"] = result["quality_accepted"]
            item[prefix+"_offline_quality_reason"] = result["reason"]
        flat.append(item)
    groups = dict(Counter(r["category"] for r in flat))
    summary = dict(processed_frames=len(flat), category_counts=groups,
        missing_sequence_numbers=sum(b["frame"]-a["frame"]-1 for a, b in zip(rows, rows[1:])),
        missing_sequence_numbers_are_not_negative_samples=True,
        quality_comparison_scope="separate unchanged IMAGE gate, every processed row, not runtime authority",
        completion_checks=checks,
        only_red_selected=(all(r["selected_colour"] == "red" for r in flat if r["new_point"] is not None)),
        withheld_reasons=dict(Counter(r["new_reason"] for r in flat if r["category"] == "withheld")),
        original_distance_frames=sum(r["original_distance_available"] for r in flat),
        original_scene_initialized_frames=sum(r["scene_initialized"] for r in flat),
        seed_fraction_by_category={key: dict(
            minimum=min(r["seed_dominant_fraction"] for r in flat if r["category"] == key),
            **statistics([r["seed_dominant_fraction"] for r in flat if r["category"] == key]))
            for key in groups},
        new_offline_quality_by_category={key: sum(r["new_offline_quality"] for r in flat if r["category"] == key)
                                         for key in groups},
        model_or_distance_fit_performed=False, physical_metric_verified=False,
        floor_contact_verified=False, usable_for_ffb=False)
    for key in ("old", "new"):
        available = [r for r in flat if r[key+"_point"] is not None]
        summary[key] = dict(point_frames=len(available),
            fraction_of_logged_frames=len(available)/len(flat) if flat else None,
            point_x_px=statistics([r[key+"_point"][0] for r in available]),
            point_y_px=statistics([r[key+"_point"][1] for r in available]),
            adjacent=adjacent_metrics(flat, key),
            offline_quality_accepted=sum(r[key+"_offline_quality"] for r in flat),
            point_outside_bbox_frames=[r["frame"] for r in flat if r[key+"_point_outside_bbox"]],
            point_bbox_excess_px=statistics([r[key+"_point_bbox_excess_px"] for r in flat if r[key+"_point_outside_bbox"]]),
            offline_quality_reasons=dict(Counter(r[key+"_offline_quality_reason"] for r in flat)))
    summary["category_runs"] = {name: runs(flat, lambda r, name=name: r["category"] == name)
                                 for name in ("completed", "withheld")}
    return flat, summary


def write_csv(path, rows):
    if not rows:
        return
    with path.open("x", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows({k: json.dumps(v, separators=(",", ":")) if isinstance(v, (list, dict)) else v
                         for k, v in row.items()} for row in rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    source, output = args.input_dir.resolve(), args.output_dir.resolve()
    if output.exists() or output.is_relative_to(source) or source.is_relative_to(output):
        raise ValueError("new analysis directory outside the original input required")
    rows, truncated, input_hash = load_frames(source / "distance_frames.jsonl")
    if truncated or not rows or len({r["session"] for r in rows}) != 1:
        raise ValueError("one complete nonempty session required")
    flat, summary = summarize_rows(rows)
    config, camera, _, _ = load_config()
    by_frame = {row["frame"]: row for row in rows}
    image_checks = []
    sources = [source / "distance_frames.jsonl", source / "live_summary.json", Path(__file__).resolve()]
    sources += [ROOT / "src" / name for name in ("cone_distance_core.py", "cone_colour_support_candidate.py",
        "cone_support_completion_candidate.py", "cone_support_quality.py", "summarize_cone_distance_live.py",
        "cone_distance_diagnostic_config.json", "angular_fisheye_geometry.py", "theta_rtc_frames.py")]
    sources += [ROOT / config[key+"_candidate"] for key in ("camera", "floor")]
    for path in sorted(source.glob("decoded_*.png")):
        number = int(path.stem.rsplit("_f", 1)[1])
        row = by_frame.get(number)
        if row is None:
            image_checks.append(dict(path=str(path), frame=number, status="no_processed_same_frame_row"))
            continue
        pixels = cv2.imread(str(path))
        if pixels is None or pixels.shape != (720, 1280, 3):
            raise ValueError("native saved image required")
        before = hashlib.sha256(pixels.tobytes()).hexdigest()
        box = row["selected_detector_boxes"][0]
        old = observe_separated_support(pixels, box, camera)
        new = observe_lateral_completion(pixels, box, camera)
        union = observe_support(pixels, box, camera)
        same = {"old_exact": old == row["colour_support_shadow"]["candidate"],
                "new_exact": new == row["support_completion_shadow"]["candidate"],
                "native_pixels_unchanged": before == hashlib.sha256(pixels.tobytes()).hexdigest()}
        if not all(same.values()):
            raise ValueError(f"saved PNG/log recomputation discrepancy at {number}: {same}")
        image_checks.append(dict(path=str(path), frame=number, category=partition(old, new),
            point=new["point"], union_reason=union["reason"], **same,
            physical_contact_review="not independently labelled or measured"))
        sources.append(path)
    summary.update(schema="saved_live_support_candidate_review_v1", session=rows[0]["session"],
        saved_image_checks=image_checks,
        missing_or_completed_images_available=sum(r.get("category") in ("completed", "withheld") for r in image_checks),
        source_sha256={str(p): sha(p) for p in sources},
        source_log_sha256=input_hash,
        yellow_in_latest_live_scope="not evaluated; current selected target is red, yellow outside ROI",
        no_new_inference=True, no_distance_recalculation=True, physical_output=False)
    output.mkdir(parents=True, exist_ok=False)
    write_csv(output / "frame_review.csv", flat)
    write_csv(output / "completed_frames.csv", [r for r in flat if r["category"] == "completed"])
    write_csv(output / "withheld_frames.csv", [r for r in flat if r["category"] == "withheld"])
    (output / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False, allow_nan=False)+"\n")
    os.environ.setdefault("MPLCONFIGDIR", str(output / "matplotlib_config"))
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(3, 1, figsize=(11, 8), sharex=True, layout="constrained")
    origin = flat[0]["source_time_sec"]
    for name, level, colour in (("preserved", 2, "tab:blue"), ("completed", 1, "tab:orange"), ("withheld", 0, "tab:red")):
        group = [r for r in flat if r["category"] == name]
        axes[0].scatter([r["source_time_sec"]-origin for r in group], [level]*len(group), s=7, color=colour, label=name)
    axes[0].set_yticks([0, 1, 2], ["Withheld", "Completed", "Preserved"])
    axes[0].set_title("Saved live r02 image support candidates; NOT contact / distance accuracy")
    for axis, dim, label in ((axes[1], 0, "Candidate native x [px]"), (axes[2], 1, "Candidate native y [px]")):
        for name, colour in (("preserved", "tab:blue"), ("completed", "tab:orange")):
            group = [r for r in flat if r["category"] == name]
            axis.scatter([r["source_time_sec"]-origin for r in group], [r["new_point"][dim] for r in group], s=6, color=colour)
        axis.set_ylabel(label)
    axes[0].legend(loc="upper right")
    axes[-1].set_xlabel("Receiver-local source reception offset [s]; missing points NOT filled")
    fig.savefig(output / "candidate_timeline.png", dpi=140)
    plt.close(fig)
    print(json.dumps({k: summary[k] for k in ("processed_frames", "category_counts", "withheld_reasons", "missing_sequence_numbers")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
