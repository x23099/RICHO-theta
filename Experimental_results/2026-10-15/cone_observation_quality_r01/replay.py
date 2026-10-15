"""Replay frozen cone predictions, never a camera/ROS/hardware source."""
import argparse
from collections import Counter, defaultdict
from dataclasses import asdict
import json
from pathlib import Path
import statistics
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT/"src"))
from cone_dataset import read_csv, sha256, write_csv
from cone_observation import ConeGroundProjector, checked_bbox
from cone_observation_quality import ConeObservationQualityGate, ConeQualitySettings


def scoped_candidates(predictions, projector, central):
    selected = []
    for row in predictions:
        # Scope is experimental association only, never score-based best-box selection.
        # Invalid boxes remain candidates so malformed input is not silently dropped.
        try:
            x1, _, x2, _ = checked_bbox(row, 1280, 720)
            inside = (270 <= (x1+x2)/2 <= 350) if central else projector.centre_in_front_lens(row)
        except ValueError:
            inside = True
        if inside:
            selected.append(row)
    return selected


def replay_frames(frames, predictions, projector, central, settings):
    index = defaultdict(list)
    for p in predictions:
        index[p["session"], int(p["frame"])].append(p)
    keys = [(r["session"], int(r["frame"])) for r in frames]
    if len(keys) != len(set(keys)) or set(index)-set(keys):
        raise ValueError("duplicate frames or predictions without source frame")
    gates, previous_frame = {}, {}
    output = []
    for row in frames:
        session, frame = row["session"], int(row["frame"])
        if frame != previous_frame.get(session, 0)+1:
            raise ValueError("all original consecutive frames required")
        previous_frame[session] = frame
        gate = gates.setdefault(session, ConeObservationQualityGate(projector, settings))
        all_predictions = index[session, frame]
        if int(row["detections"]) != len(all_predictions):
            raise ValueError("frame prediction count differs from frozen export")
        selected = scoped_candidates(all_predictions, projector, central)
        result = gate.update(float(row["time_sec"]), selected,
                             frame_width=1280, frame_height=720)
        output.append(dict(session=session, frame=frame, time_sec=row["time_sec"],
                           all_view_predictions=len(all_predictions), candidates=len(selected), **result))
    return output


def summarize(rows, **labels):
    observed = [float(r["observed_z_m"]) for r in rows if r["quality_accepted"]]
    return dict(**labels, frames=len(rows), projection_candidates=sum(r["projection_candidate"] for r in rows),
                quality_accepted=len(observed), no_candidates=sum(r["candidates"] == 0 for r in rows),
                ambiguous=sum(r["candidates"] > 1 for r in rows),
                z_median_m=statistics.median(observed) if observed else None,
                z_std_m=statistics.pstdev(observed) if observed else None,
                rejected_reasons=json.dumps(dict(Counter(r["reason"] for r in rows if not r["quality_accepted"])),
                                           sort_keys=True))


def plot(rows, output):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    figure, axes = plt.subplots(3, 1, figsize=(11, 8), sharex=True)
    for axis, name in zip(axes, ("recorded58", "measured59", "frozen_centre2")):
        section = [r for r in rows if r["dataset"] == "same_pose" and r["model"] == name
                   and 1110 <= r["frame"] <= 1155]
        candidates = [r for r in section if r["candidate_z_m"] is not None]
        accepted = [r for r in section if r["quality_accepted"]]
        rejected = [r for r in candidates if not r["quality_accepted"]]
        axis.plot([r["frame"] for r in candidates], [r["candidate_z_m"] for r in candidates],
                  ".", color="0.6", label="Geometric hypothesis (not contact verified)")
        axis.scatter([r["frame"] for r in accepted], [r["observed_z_m"] for r in accepted],
                     s=18, color="tab:blue", label="Temporal gate accepted")
        axis.scatter([r["frame"] for r in rejected], [r["candidate_z_m"] for r in rejected],
                     marker="x", color="tab:red", label="Temporal gate withheld")
        axis.axvspan(1125, 1134, color="orange", alpha=.15, label="Reviewed occlusion interval (evaluation only)")
        axis.set_ylabel("Z hypothesis [m]")
        axis.set_title(name+(" (failed calibration transfer; stress test only)" if name == "frozen_centre2" else ""))
        axis.grid(alpha=.3)
    axes[0].legend(fontsize=8, loc="upper left")
    axes[-1].set_xlabel("Original frame number; missing observations are NOT filled")
    figure.tight_layout()
    figure.savefig(output, dpi=150)
    plt.close(figure)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.output_dir.exists():
        raise ValueError("no frozen result overwrite")
    same = HERE.parent/"floor_cone_same_pose_analysis_r01"
    historical = HERE.parent/"cone_static_distance_r01"
    model_file = same/"analysis_r01/summary.json"
    scope_file = same/"scope.json"
    models = json.loads(model_file.read_text())["models"]
    phases = json.loads(scope_file.read_text())["phase_windows"]
    settings = ConeQualitySettings()
    sources = [Path(__file__), HERE/"method.md", model_file, scope_file,
               ROOT/"src/cone_observation_quality.py", ROOT/"src/cone_observation.py",
               ROOT/"src/obstacle_tracking.py", ROOT/"src/ground_contact.py",
               ROOT/"tests/test_cone_observation_quality.py"]
    all_rows, summary, focus = [], [], []
    recovery = {}
    for dataset, base, central in (("same_pose", same, True), ("historical_static", historical, False)):
        frame_file, prediction_file = base/"inference_r01/frames.csv", base/"inference_r01/predictions.csv"
        sources.extend([frame_file, prediction_file])
        frames, predictions = read_csv(frame_file), read_csv(prediction_file)
        assert len(frames) == (1547 if central else 3596)
        for name, geometry in models.items():
            projector = ConeGroundProjector(geometry, width=1280, height=720, front_lens="left",
                                             confidence_threshold=.5)
            replay = replay_frames(frames, predictions, projector, central, settings)
            for row in replay:
                row.update(dataset=dataset, model=name,
                           phase=next(p["name"] for p in phases if p["start_frame"] <= row["frame"] <= p["end_frame"])
                           if central else "historical_static")
            all_rows.extend(replay)
            groups = defaultdict(list)
            for row in replay:
                groups[row["phase"] if central else row["session"]].append(row)
            for label, group in groups.items():
                summary.append(summarize(group, dataset=dataset, model=name, group=label))
            if central:
                focus.extend(r for r in replay if 1110 <= r["frame"] <= 1155)
                # Known failure frames are evaluation assertions, NOT gate inputs.
                assert all(not r["quality_accepted"] for r in replay if r["frame"] in (1133, 1134))
                next_accepted = next((r for r in replay if r["frame"] > 1134 and r["quality_accepted"]), None)
                recovery[name] = None if next_accepted is None else dict(
                    first_accepted_frame=next_accepted["frame"], time_sec=next_accepted["time_sec"])
    assert len(all_rows) == (1547+3596)*3
    assert all(not r["usable_for_ffb"] and not r["floor_contact_verified"] for r in all_rows)
    assert all(r["observed_z_m"] is None for r in all_rows if not r["quality_accepted"])
    args.output_dir.mkdir(parents=True)
    write_csv(args.output_dir/"observations.csv", all_rows)
    write_csv(args.output_dir/"summary.csv", summary)
    write_csv(args.output_dir/"occlusion_rows.csv", focus)
    plot(all_rows, args.output_dir/"occlusion_gate.png")
    manifest = dict(status="COMPLETED_OFFLINE_QUALITY_REPLAY_NOT_CONTACT_TTC_OR_FFB_APPROVAL",
                    settings=asdict(settings), models=models, observation_rows=len(all_rows),
                    no_threshold_search=True, same_pose_roi_is_evaluation_association_only=True,
                    dynamic_cone_recording_tested=False, physical_output=False,
                    production_settings_changed=False, ground_truth_used_by_gate=False,
                    known_partial_bbox_frames_1133_1134_withheld_all_models=True,
                    recovery_after_1134=recovery,
                    source_sha256={str(p): sha256(p) for p in sources},
                    output_sha256={p.name: sha256(p) for p in args.output_dir.iterdir() if p.is_file()})
    (args.output_dir/"provenance.json").write_text(json.dumps(manifest, indent=2)+"\n")
    print(json.dumps({"observation_rows": len(all_rows), "recovery": recovery}, indent=2))


if __name__ == "__main__":
    main()
