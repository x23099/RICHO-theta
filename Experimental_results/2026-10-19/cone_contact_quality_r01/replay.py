"""Replay frozen color pixels through the UNCHANGED offline quality gate."""
from collections import Counter, defaultdict
from dataclasses import asdict
import argparse
import importlib.util
import json
import math
import os
from pathlib import Path
import sys

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
CONTACT = HERE.parent / "cone_contact_reuse_r01"
PREVIOUS = HERE.parent / "cone_distance_methods_r01"
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(PREVIOUS))
from cone_dataset import read_csv, sha256, write_csv
from cone_observation import ConeGroundProjector, checked_bbox
from cone_observation_quality import ConeObservationQualityGate, ConeQualitySettings
from diagnose_box_contact_calibration import project_pixel

spec = importlib.util.spec_from_file_location("frozen_distance_methods", PREVIOUS / "analyze.py")
previous = importlib.util.module_from_spec(spec)
spec.loader.exec_module(previous)

FLOOR_REASONS = {"no_downward_floor_ray", "nonforward_or_nonfinite_intersection", "outside_diagnostic_range"}


def flag(value):
    if value not in ("True", "False"):
        raise ValueError("explicit frozen boolean required")
    return value == "True"


def key(row):
    return row["dataset"], row["session"], int(row["frame"])


class ColourProjector:
    """Offline composition adapter; detection guards remain those of the bbox projector."""
    def __init__(self, bbox_projector):
        self.bbox = bbox_projector

    def project(self, row, *, frame_width, frame_height):
        baseline = self.bbox.project(row, frame_width=frame_width, frame_height=frame_height)
        if not baseline["projection_candidate"] and baseline["reason"] not in FLOOR_REASONS:
            return baseline
        result = dict(baseline, projection_candidate=False, x_m=None, z_m=None,
                      distance_m=None, pixel_x=None, pixel_y=None,
                      floor_contact_verified=False, usable_for_ffb=False)
        colour = row.get("_colour")
        if not isinstance(colour, dict):
            return dict(result, reason="missing_colour_record")
        if not colour["valid"]:
            return dict(result, reason="colour:" + colour["reason"])
        try:
            x, y = float(colour["x"]), float(colour["y"])
        except (KeyError, TypeError, ValueError):
            return dict(result, reason="invalid_colour_pixel")
        x1, y1, x2, y2 = checked_bbox(row, self.bbox.width, self.bbox.height)
        if not (math.isfinite(x) and math.isfinite(y) and 0 <= x < frame_width and 0 <= y < frame_height
                and math.floor(x1)-4 <= x < math.ceil(x2)+4
                and math.floor(y1)-4 <= y < math.ceil(y2)+4):
            return dict(result, reason="invalid_colour_pixel")
        if not self.bbox._in_circle(x, y):
            return dict(result, reason="colour_pixel_outside_front_lens")
        point = project_pixel((x, y), self.bbox.parameters, frame_width, frame_height)
        if point is None:
            return dict(result, reason="colour_floor_intersection_rejected")
        return dict(result, projection_candidate=True, reason="unverified_visible_colour_bottom_floor_assumption",
                    pixel_x=x, pixel_y=y, x_m=point[0], z_m=point[1], distance_m=math.hypot(*point))


def join_colour_pixels(ledger, selected, pixels):
    """Verify one V30 cache per frame and attach image-only evidence, never labels."""
    cache = {}
    for pixel in pixels:
        if int(pixel["v_min"]) != 30:
            continue
        k = key(pixel)
        if k in cache:
            raise ValueError("duplicate V30 source pixel")
        cache[k] = pixel
    if len({key(r) for r in ledger}) != len(ledger) or set(cache) != {key(r) for r in ledger}:
        raise ValueError("pixel/frame coverage mismatch")
    joined = {}
    for frame in ledger:
        k = key(frame)
        pixel, candidates = cache[k], selected[k]
        if float(pixel["time_sec"]) != frame["time_sec"] or int(pixel["candidates"]) != len(candidates):
            raise ValueError("pixel timestamp or candidate count mismatch")
        valid = flag(pixel["colour_candidate"])
        if valid and len(candidates) != 1:
            raise ValueError("color evidence requires one source detection")
        if len(candidates) == 1:
            bbox = candidates[0]
            if (float(pixel["bbox_pixel_x"]) != (float(bbox["x1"])+float(bbox["x2"]))/2
                    or float(pixel["bbox_pixel_y"]) != float(bbox["y2"])):
                raise ValueError("cached pixel and source bbox differ")
        if valid:
            x, y = float(pixel["pixel_x"]), float(pixel["pixel_y"])
            if not all(math.isfinite(v) for v in (x, y)):
                raise ValueError("finite source pixel required")
        else:
            if pixel["pixel_x"] != "" or pixel["pixel_y"] != "":
                raise ValueError("failed color measurement must not contain coordinates")
            x = y = None
        evidence = dict(valid=valid, reason=pixel["colour_reason"], x=x, y=y)
        joined[k] = [dict(candidate, _colour=evidence.copy()) for candidate in candidates]
    return joined


def replay(ledger, candidates, models, settings=None):
    settings = settings or ConeQualitySettings()
    gates, previous_frames, previous_times = {}, {}, {}
    rows = []
    if set(candidates) != {key(r) for r in ledger}:
        raise ValueError("candidate/frame coverage mismatch")
    for frame in ledger:
        k = key(frame)
        session_key = k[:2]
        if (k[2] != previous_frames.get(session_key, 0)+1
                or not math.isfinite(frame["time_sec"])
                or frame["time_sec"] <= previous_times.get(session_key, -math.inf)):
            raise ValueError("complete sequential frames with increasing finite time required")
        previous_frames[session_key], previous_times[session_key] = k[2], frame["time_sec"]
        selected = candidates[k]
        for name, geometry in models.items():
            for method in ("bbox", "colour"):
                gate_key = (*session_key, name, method)
                if gate_key not in gates:
                    projector = ConeGroundProjector(geometry, width=1280, height=720,
                                                     front_lens="left", confidence_threshold=.5)
                    if method == "colour":
                        projector = ColourProjector(projector)
                    gates[gate_key] = ConeObservationQualityGate(projector, settings)
                result = gates[gate_key].update(frame["time_sec"], selected, frame_width=1280, frame_height=720)
                # Evaluation labels are appended AFTER the causal update.
                rows.append(dict(dataset=k[0], session=k[1], frame=k[2], time_sec=frame["time_sec"],
                                 condition=frame["condition"], reference_z_m=frame["reference_z_m"],
                                 reference_x_m=frame["reference_x_m"], candidates=len(selected),
                                 model=name, method=method, **result))
    return rows


def summarize(rows):
    groups = defaultdict(list)
    for row in rows:
        groups[row["dataset"], row["condition"], row["model"], row["method"]].append(row)
    output = []
    for (dataset, condition, model, method), group in sorted(groups.items()):
        ref = group[0]["reference_z_m"]
        result = dict(dataset=dataset, condition=condition, model=model, method=method, frames=len(group),
                      reference_z_m=ref, projection_candidates=sum(r["projection_candidate"] for r in group),
                      quality_accepted=sum(r["quality_accepted"] for r in group),
                      rejected_reasons=json.dumps(dict(Counter(r["reason"] for r in group if not r["quality_accepted"])), sort_keys=True),
                      usable_for_ffb=False)
        for stage, field in (("candidate", "candidate_z_m"), ("accepted", "observed_z_m")):
            values = [r[field] for r in group if r[field] is not None]
            residual = np.asarray(values)-ref if values and ref is not None else None
            result.update({stage+"_z_median_m": float(np.median(values)) if values else None,
                           stage+"_z_bias_m": float(np.median(residual)) if residual is not None else None,
                           stage+"_abs_z_error_p95_m": float(np.percentile(abs(residual), 95)) if residual is not None else None})
        output.append(result)
    return output


def withheld_runs(rows):
    groups = defaultdict(list)
    for row in rows:
        groups[row["dataset"], row["session"], row["model"], row["method"]].append(row)
    output = []
    for (dataset, session, model, method), group in sorted(groups.items()):
        index, last = 0, None
        while index < len(group):
            if group[index]["quality_accepted"]:
                last = group[index]
                index += 1
                continue
            start = index
            while index < len(group) and not group[index]["quality_accepted"]:
                index += 1
            run, following = group[start:index], group[index] if index < len(group) else None
            output.append(dict(dataset=dataset, session=session, model=model, method=method,
                               start_frame=run[0]["frame"], end_frame=run[-1]["frame"], withheld_frames=len(run),
                               reasons=json.dumps(dict(Counter(r["reason"] for r in run)), sort_keys=True),
                               previous_accepted_frame=last["frame"] if last else None,
                               next_accepted_frame=following["frame"] if following else None,
                               start_to_next_accepted_sec=following["time_sec"]-run[0]["time_sec"] if following else None,
                               accepted_gap_sec=following["time_sec"]-last["time_sec"] if following and last else None,
                               usable_for_ffb=False))
    return output


def bbox_regression(rows, path):
    old = {(key(r), r["model"]): r for r in read_csv(path) if r["model"] != "bbox_area"}
    baseline = [r for r in rows if r["method"] == "bbox"]
    if {(key(r), r["model"]) for r in baseline} != set(old):
        raise ValueError("previous bbox replay coverage changed")
    for row in baseline:
        reference = old[key(row), row["model"]]
        if (row["quality_accepted"] != flag(reference["quality_accepted"])
                or row["reason"] != reference["quality_reason"]
                or row["projection_candidate"] != flag(reference["projection_candidate"])):
            raise ValueError("previous bbox quality decisions changed")
        for field, old_field in (("observed_x_m", "quality_x_m"), ("observed_z_m", "quality_z_m")):
            value = float(reference[old_field]) if reference[old_field] != "" else None
            if row[field] != value:
                raise ValueError("previous bbox accepted measurement changed")
    return len(baseline)


def plot(rows, output):
    os.environ.setdefault("MPLCONFIGDIR", "/tmp/cone_contact_quality_matplotlib")
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(3, 2, figsize=(13, 9), sharex=True, sharey=True, layout="constrained")
    for i, model in enumerate(("recorded58", "height_only59", "paper_centre2")):
        for j, method in enumerate(("bbox", "colour")):
            ax = axes[i, j]
            group = [r for r in rows if r["dataset"] == "sequence" and r["model"] == model
                     and r["method"] == method and 1110 <= r["frame"] <= 1155]
            projected = [r for r in group if r["projection_candidate"]]
            accepted = [r for r in group if r["quality_accepted"]]
            ax.plot([r["frame"] for r in projected], [r["candidate_z_m"] for r in projected],
                    ".", color=".65", label="Raw floor hypothesis")
            ax.scatter([r["frame"] for r in accepted], [r["observed_z_m"] for r in accepted],
                       s=16, label="Temporal acceptance (not contact GT)")
            withheld = [r for r in projected if not r["quality_accepted"]]
            ax.scatter([r["frame"] for r in withheld], [r["candidate_z_m"] for r in withheld],
                       marker="x", color="tab:red", label="Withheld")
            ax.axvspan(1125, 1134, color="orange", alpha=.15)
            ax.axhline(2, color="black", lw=.8, ls="--")
            ax.set_title(model+" / "+method)
            ax.grid(alpha=.3)
            ax.set_ylabel("Z hypothesis [m]")
            if i == 2:
                ax.set_xlabel("Original frame; orange = prior reviewed occlusion, evaluation only")
    axes[0, 0].legend(fontsize=7)
    fig.suptitle("UNCHANGED temporal gate: no missing-value fill, no physical FFB approval")
    fig.savefig(output / "occlusion_quality_comparison.png", dpi=150)
    plt.close(fig)
    summary = summarize(rows)
    order = [("static", c) for c in ("center_080", "center_130", "center_200", "left_130", "right_130")]
    order += [("sequence", "cone_130"), ("sequence", "cone_200")]
    fig, axes = plt.subplots(2, 1, figsize=(12, 7), sharex=True, layout="constrained")
    for method in ("bbox", "colour"):
        chosen = [next(r for r in summary if (r["dataset"], r["condition"], r["model"], r["method"])
                       == (d, c, "height_only59", method)) for d, c in order]
        x = np.arange(len(chosen))
        axes[0].plot(x, [r["quality_accepted"]/r["frames"] for r in chosen], "o-", label=method)
        axes[1].plot(x, [r["accepted_z_bias_m"] for r in chosen], "o-", label=method)
    for ax in axes:
        ax.grid(alpha=.3)
        ax.legend()
        ax.set_xticks(range(len(order)), [d+"\n"+c for d, c in order], fontsize=8)
    axes[0].set(ylabel="Temporal accepted / ALL frames", title="Fixed h59: acceptance is NOT metric accuracy or detection recall")
    axes[1].axhline(0, color="black", lw=.8)
    axes[1].set_ylabel("Accepted median Z - nominal reference [m]")
    fig.savefig(output / "coverage_and_remaining_bias.png", dpi=150)
    plt.close(fig)


def load_inputs():
    sources, models, refs, conditions, phases, hashes = previous.load_inputs()
    frozen = json.loads((CONTACT / "full_replay_r01/provenance.json").read_text())
    # Validate every prior consumed source, including unchanged raw/config files.
    for path, digest in frozen["source_sha256"].items():
        if sha256(Path(path)) != digest:
            raise ValueError("frozen image-diagnostic source changed: " + path)
    for name, digest in frozen["output_sha256"].items():
        if sha256(CONTACT / "full_replay_r01" / name) != digest:
            raise ValueError("frozen image-diagnostic output changed: " + name)
    scope = ConeGroundProjector(models["recorded58"], width=1280, height=720,
                                front_lens="left", confidence_threshold=.5)
    ledger, selected = previous.make_ledger(sources, scope, refs, conditions, phases)
    pixels = read_csv(CONTACT / "full_replay_r01/pixels.csv")
    candidates = join_colour_pixels(ledger, selected, pixels)
    hashes.update(frozen["source_sha256"])
    paths = [Path(__file__), HERE / "method.md", HERE / "test_quality_replay.py",
             CONTACT / "full_replay_r01/provenance.json", CONTACT / "full_replay_r01/pixels.csv",
             PREVIOUS / "results_r01/observations.csv", PREVIOUS / "results_r01/provenance.json"]
    hashes.update({str(p): sha256(p) for p in paths})
    return ledger, candidates, models, hashes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.output_dir.exists():
        raise ValueError("new output directory required; frozen output overwrite refused")
    ledger, candidates, models, hashes = load_inputs()
    settings = ConeQualitySettings()
    rows = replay(ledger, candidates, models, settings)
    if len(rows) != 5143*3*2:
        raise ValueError("all 5143 frames required")
    audited = bbox_regression(rows, PREVIOUS / "results_r01/observations.csv")
    focus = [r for r in rows if r["dataset"] == "sequence" and 1110 <= r["frame"] <= 1155]
    evaluation = []
    for model in models:
        for method in ("bbox", "colour"):
            group = [r for r in rows if r["dataset"] == "sequence" and r["model"] == model and r["method"] == method]
            recovery = next((r for r in group if r["frame"] > 1134 and r["quality_accepted"]), None)
            last = next((r for r in reversed(group) if r["frame"] < 1125 and r["quality_accepted"]), None)
            return_start = next(r for r in group if r["frame"] == 1135)
            evaluation.append(dict(model=model, method=method,
                accepted_during_reviewed_interval=[r["frame"] for r in group if 1125 <= r["frame"] <= 1134 and r["quality_accepted"]],
                first_accepted_after_1134=recovery["frame"] if recovery else None,
                time_since_return_candidate_1135_sec=recovery["time_sec"]-return_start["time_sec"] if recovery else None,
                accepted_gap_sec=recovery["time_sec"]-last["time_sec"] if recovery and last else None))
    args.output_dir.mkdir(parents=True)
    write_csv(args.output_dir / "observations.csv", rows)
    write_csv(args.output_dir / "summary.csv", summarize(rows))
    write_csv(args.output_dir / "withheld_runs.csv", withheld_runs(rows))
    write_csv(args.output_dir / "occlusion_rows.csv", focus)
    plot(rows, args.output_dir)
    if not all(sha256(Path(path)) == digest for path, digest in hashes.items()):
        raise ValueError("input changed during replay")
    provenance = dict(status="COMPLETED_OFFLINE_ONLY_NOT_CONTACT_OR_TTC_OR_FFB_APPROVAL",
        source_frames=len(ledger), observation_rows=len(rows), primary_v_min=30,
        settings=asdict(settings), models=models, previous_bbox_quality_rows_verified=audited,
        occlusion_evaluation=evaluation, geometry_refitted=False, thresholds_changed=False,
        runtime_changed=False, new_inference=False, physical_output=False,
        source_images_edited=False, new_camera_images_saved=False, usable_for_ffb=False,
        source_sha256=hashes, output_sha256={p.name: sha256(p) for p in args.output_dir.iterdir() if p.is_file()})
    (args.output_dir / "provenance.json").write_text(json.dumps(provenance, indent=2)+"\n")
    print(json.dumps(dict(observation_rows=len(rows), previous_bbox_quality_rows_verified=audited,
                          occlusion_evaluation=evaluation), indent=2))
    for row in summarize(rows):
        if row["model"] == "height_only59":
            print(row["dataset"], row["condition"], row["method"],
                  row["projection_candidates"], row["quality_accepted"], row["frames"],
                  row["accepted_z_median_m"], row["rejected_reasons"])


if __name__ == "__main__":
    main()
