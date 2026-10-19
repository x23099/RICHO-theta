"""Fixed-geometry, same-column support projection audit; no inference or ROS."""
import argparse
from collections import defaultdict
from itertools import combinations
import json
import os
from pathlib import Path
import sys

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
QUALITY = HERE.parent / "cone_support_quality_r01"
DISTANCE = HERE.parent / "cone_distance_methods_r01/results_r01"
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(QUALITY))
from cone_dataset import read_csv, sha256, write_csv
import replay as quality
from metric_support import RANGE_FIELDS, bounds, compare_columns, project_columns

MODELS = ("recorded58", "height_only59", "paper_centre2")
POPULATIONS = ("all_input", "time_accepted", "common_time_accepted")
EXAMPLES = (("static", "center_080", 241), ("static", "center_130", 217),
            ("static", "center_200", 211), ("static", "left_130", 210),
            ("static", "right_130", 211), ("sequence", "cone_130", 563),
            ("sequence", "cone_200", 1265), ("sequence", "cone_200", 1134))


def check_hashes(hashes):
    for name, digest in hashes.items():
        if sha256(Path(name)) != digest:
            raise ValueError("frozen input changed: " + name)


def load_inputs():
    source, curves, hashes = quality.load_inputs()
    provenance_path = QUALITY / "results_r02/provenance.json"
    provenance = json.loads(provenance_path.read_text())
    check_hashes(provenance["source_sha256"])
    for name, digest in provenance["output_sha256"].items():
        path = QUALITY / "results_r02" / name
        if sha256(path) != digest:
            raise ValueError("frozen time-quality result changed: " + name)
        hashes[str(path)] = digest
    hashes.update(provenance["source_sha256"])
    status = {quality.key(r): r for r in read_csv(QUALITY / "results_r02/observations.csv")}
    if len(status) != len(source) or set(status) != {quality.key(r) for r in source}:
        raise ValueError("complete one-to-one time-quality ledger required")
    for r in source:
        q = status[quality.key(r)]
        if (q["condition"] != r["condition"] or float(q["time_sec"]) != r["time_sec"]
                or q["input_envelope_available"] != str(r["envelope_available"])
                or q["floor_contact_verified"] != "False" or q["usable_for_ffb"] != "False"):
            raise ValueError("quality ledger/source/safety mismatch")
        if q["quality_accepted"] == "True" and int(q["observed_columns"]) != len(curves[quality.key(r)]):
            raise ValueError("accepted support must contain exactly the observed columns")
    geometry_path = DISTANCE / "provenance.json"
    if sha256(geometry_path) != hashes[str(geometry_path)]:
        raise ValueError("frozen geometry provenance changed")
    models = json.loads(geometry_path.read_text())["geometries"]
    if set(models) != set(MODELS):
        raise ValueError("three prespecified fixed geometries required")
    references = {}
    for r in read_csv(DISTANCE / "summary.csv"):
        if r["model"] == "recorded58":
            references[r["dataset"], r["condition"]] = {
                k: float(r[k]) if r[k] else None for k in ("reference_x_m", "reference_z_m")}
    # Summary labels are consumed only after projection, never by geometry/quality.
    old = json.loads(geometry_path.read_text())
    if sha256(DISTANCE / "summary.csv") != old["output_sha256"]["summary.csv"]:
        raise ValueError("frozen reference summary changed")
    paths = [Path(__file__), HERE / "metric_support.py", HERE / "method.md", HERE / "test_projection.py",
             provenance_path, DISTANCE / "summary.csv", ROOT / "src/cone_dataset.py"]
    hashes.update({str(p): sha256(p) for p in paths})
    return source, curves, status, models, references, hashes


def project_frames(source, curves, status, models):
    records, differences, samples = [], [], []
    if set(curves) - {quality.key(r) for r in source}:
        raise ValueError("orphan curve")
    seen = set()
    for r in source:
        key = quality.key(r)
        if key in seen:
            raise ValueError("duplicate frame")
        seen.add(key)
        columns = curves.get(key, [])
        if bool(columns) != r["envelope_available"]:
            raise ValueError("frame/curve mismatch")
        q = status[key]
        accepted = q["quality_accepted"] == "True"
        if accepted and not columns:
            raise ValueError("cannot accept missing support")
        projected = {name: project_columns(columns, p) for name, p in models.items()}
        ranges = {name: bounds(points) for name, points in projected.items()}
        common = all(b["projection_complete"] for b in ranges.values())
        base = dict(dataset=key[0], session=key[1], frame=key[2], time_sec=r["time_sec"],
                    condition=r["condition"], quality_accepted=accepted, quality_reason=q["reason"],
                    common_projection_complete=common, floor_contact_verified=False, usable_for_ffb=False)
        for name, b in ranges.items():
            complete = accepted and b["projection_complete"]
            row = dict(base, model=name, **{k: v for k, v in b.items() if k not in RANGE_FIELDS},
                       metric_observation_available=complete)
            row["invalid_reasons"] = json.dumps(b["invalid_reasons"], sort_keys=True)
            for field in RANGE_FIELDS:
                row["candidate_" + field] = b[field]
                row["observed_" + field] = b[field] if complete else None
            records.append(row)
            if (r["dataset"], r["condition"], r["frame"]) in EXAMPLES:
                for p in projected[name]:
                    samples.append(dict(base, model=name, **{k: v for k, v in p.items() if k not in base}))
        for first, second in combinations(MODELS, 2):
            differences.append(dict(base, model_first=first, model_second=second,
                                    **{k: v for k, v in compare_columns(projected[first], projected[second]).items()
                                       if k not in base}))
    return records, differences, samples


def eligible(row, population):
    return (population == "all_input" or row["quality_accepted"]) and (
        population != "common_time_accepted" or row["common_projection_complete"])


def median(values):
    return float(np.median(values)) if values else None


def summarize(records, references):
    groups = defaultdict(list)
    for r in records:
        groups[r["dataset"], r["condition"], r["model"]].append(r)
    result = []
    for (dataset, condition, model), group in sorted(groups.items()):
        for population in POPULATIONS:
            selected = [r for r in group if eligible(r, population)]
            good = [r for r in selected if r["projection_complete"]]
            ref = references[dataset, condition]
            record = dict(dataset=dataset, condition=condition, model=model, population=population,
                          total_frames=len(group), population_frames=len(selected),
                          complete_projection_frames=len(good),
                          no_curve_frames=sum(r["input_columns"] == 0 for r in selected),
                          incomplete_projection_frames=sum(r["invalid_columns"] > 0 for r in selected),
                          input_columns=sum(r["input_columns"] for r in selected),
                          invalid_columns=sum(r["invalid_columns"] for r in selected),
                          **ref, floor_contact_verified=False, usable_for_ffb=False)
            for field in RANGE_FIELDS:
                values = [r["candidate_" + field] for r in good]
                record[field + "_frame_median"] = median(values)
            spans = [r["candidate_z_span_m"] for r in good]
            record["z_span_m_frame_p95"] = float(np.percentile(spans, 95)) if spans else None
            result.append(record)
    return result


def summarize_differences(records):
    groups = defaultdict(list)
    for r in records:
        groups[r["dataset"], r["condition"], r["model_first"], r["model_second"]].append(r)
    result = []
    for (dataset, condition, first, second), group in sorted(groups.items()):
        for population in POPULATIONS:
            selected = [r for r in group if eligible(r, population)]
            good = [r for r in selected if r["comparison_complete"]]
            result.append(dict(dataset=dataset, condition=condition, model_first=first, model_second=second,
                               population=population, total_frames=len(group), population_frames=len(selected),
                               compared_frames=len(good), compared_columns=sum(r["compared_columns"] for r in good),
                               **{field + "_frame_median": median([r[field] for r in good]) for field in
                                  ("dx_median_m", "dz_median_m", "dx_abs_max_m", "dz_abs_max_m")},
                               floor_contact_verified=False, usable_for_ffb=False))
    return result


def compare_sessions(summary):
    output = []
    index = {(r["dataset"], r["condition"], r["model"], r["population"]): r for r in summary}
    for distance in ("130", "200"):
        for model in MODELS:
            for population in POPULATIONS:
                a = index["static", "center_" + distance, model, population]
                b = index["sequence", "cone_" + distance, model, population]
                row = dict(nominal_z_m=a["reference_z_m"], model=model, population=population,
                           static_frames=a["complete_projection_frames"], sequence_frames=b["complete_projection_frames"],
                           interpretation="unpaired_observed_ranges_not_identical_physical_point_correspondence",
                           floor_contact_verified=False, usable_for_ffb=False)
                for field in ("z_min_m", "z_max_m", "z_median_m", "z_span_m"):
                    k = field + "_frame_median"
                    row["static_" + field] = a[k]
                    row["sequence_" + field] = b[k]
                    row["sequence_minus_static_" + field] = b[k]-a[k] if a[k] is not None and b[k] is not None else None
                output.append(row)
    return output


def plot(summary, samples, references, output):
    os.environ.setdefault("MPLCONFIGDIR", "/tmp/cone_support_projection_matplotlib")
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    order = [("static", c) for c in ("center_080", "center_130", "center_200", "left_130", "right_130")]
    order += [("sequence", "cone_130"), ("sequence", "cone_200")]
    colors = dict(zip(MODELS, ("C0", "C1", "C2")))
    fig, ax = plt.subplots(figsize=(12, 5), layout="constrained")
    index = {(r["dataset"], r["condition"], r["model"]): r for r in summary if r["population"] == "common_time_accepted"}
    for i, (dataset, condition) in enumerate(order):
        ax.plot([i-.36, i+.36], [references[dataset, condition]["reference_z_m"]]*2, color="black", ls="--")
        for shift, model in zip((-.22, 0, .22), MODELS):
            r = index[dataset, condition, model]
            low, high, centre = (r[k + "_frame_median"] for k in ("z_min_m", "z_max_m", "z_median_m"))
            ax.plot([i+shift]*2, [low, high], color=colors[model], lw=3)
            ax.plot(i+shift, centre, "o", color=colors[model], label=model if i == 0 else None, ms=4)
    ax.plot([], [], "k--", label="Declared near-edge Z; NOT every column's true Z")
    ax.set_xticks(range(len(order)), [a+"\n"+b for a, b in order], fontsize=8)
    ax.set(ylabel="Conditional floor Z [m]", title="Same accepted frames: median of each curve's min/max; NOT confidence intervals or footprints")
    ax.legend(fontsize=8)
    ax.grid(axis="y", alpha=.3)
    fig.savefig(output / "conditional_support_ranges.png", dpi=150)
    plt.close(fig)
    fig, axes = plt.subplots(1, 3, figsize=(14, 4.5), layout="constrained")
    examples = (("static", "center_200", 211), ("sequence", "cone_200", 1265), ("sequence", "cone_200", 1134))
    for ax, (dataset, condition, frame) in zip(axes, examples):
        selected = [r for r in samples if (r["dataset"], r["condition"], r["frame"]) == (dataset, condition, frame)]
        for model in MODELS:
            group = [r for r in selected if r["model"] == model]
            if group and all(r["reason"] == "valid" for r in group):
                ax.plot([r["x_m"] for r in group], [r["z_m"] for r in group], ".-", color=colors[model], label=model, ms=2)
        ax.axhline(references[dataset, condition]["reference_z_m"], color="black", ls="--", lw=1)
        ax.set(title=f"{dataset} frame {frame}\nImage gate accepted: {selected[0]['quality_accepted']}",
               xlabel="Conditional floor X [m]", ylabel="Conditional floor Z [m]")
        ax.grid(alpha=.3)
        ax.legend(fontsize=7)
    fig.suptitle("Actual corresponding image columns; candidate curves only. Occlusion may project but remains withheld.", fontsize=10)
    fig.savefig(output / "same_columns_different_geometries.png", dpi=150)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.output_dir.exists():
        raise ValueError("new output directory required; archived results cannot be overwritten")
    source, curves, status, models, refs, hashes = load_inputs()
    records, differences, samples = project_frames(source, curves, status, models)
    summary = summarize(records, refs)
    pair_summary = summarize_differences(differences)
    sessions = compare_sessions(summary)
    check_hashes(hashes)
    args.output_dir.mkdir(parents=True)
    for name, rows in (("projected_ranges.csv", records), ("summary.csv", summary),
                       ("same_column_geometry_differences.csv", differences), ("geometry_difference_summary.csv", pair_summary),
                       ("unpaired_session_comparison.csv", sessions), ("representative_columns.csv", samples)):
        write_csv(args.output_dir / name, rows)
    plot(summary, samples, refs, args.output_dir)
    check_hashes(hashes)
    report = dict(status="CONDITIONAL_SUPPORT_PROJECTION_ONLY_NOT_DISTANCE_OR_FFB_APPROVAL",
                  source_frames=len(source), model_rows=len(records), model_pair_rows=len(differences),
                  source_observed_columns=sum(map(len, curves.values())), geometries=models,
                  quality_accepted_source_frames=sum(q["quality_accepted"] == "True" for q in status.values()),
                  incomplete_projection_rows=sum(r["invalid_columns"] > 0 for r in records),
                  geometry_refitted=False, physical_contact_inferred=False, floor_contact_verified=False,
                  usable_for_ffb=False, runtime_integration_performed=False, physical_output=False,
                  new_camera_images_saved=False, source_sha256=hashes,
                  output_sha256={p.name: sha256(p) for p in args.output_dir.iterdir() if p.is_file()})
    (args.output_dir / "provenance.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: v for k, v in report.items() if k not in ("geometries", "source_sha256", "output_sha256")}, indent=2))


if __name__ == "__main__":
    main()
