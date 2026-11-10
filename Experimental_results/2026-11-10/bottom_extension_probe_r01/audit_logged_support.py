"""今回15保留の保存済み下辺を集計。画素外挿や支持点の選び直しはしない。"""
import argparse
import csv
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    source, output = args.input_dir.resolve(), args.output_dir.resolve()
    if output == source or source in output.parents:
        raise ValueError("output must be outside source")
    previous = json.loads((ROOT/"Experimental_results/2026-11-10/driver_motion_live_analysis_r01/results_r01/analysis.json").read_text())
    old_cases = json.loads((ROOT/"Experimental_results/2026-11-10/driver_motion_live_analysis_r01/results_r01/motion_window_rejections.json").read_text())
    expected = {r["frame"] for r in old_cases if r["touches"]["bottom"]}
    rows, sha = [], hashlib.sha256()
    with (source/"motion_distance_frames.jsonl").open("rb") as stream:
        for line in stream:
            sha.update(line)
            r = json.loads(line)
            if r["frame"] not in expected:
                continue
            if r["session"] != "7f33c225af3948c2aa61d66d52765c2e" or r["distance_available"]:
                raise ValueError("unexpected session or result")
            context = r["support_observation"]["upper_contexts"][0]
            support = context["component"]["observed_lower_support"]
            box = r["selected_detector_boxes"][0]
            edge = context["crop_xyxy"][3]-1
            rows.append(dict(frame=r["frame"], observed_columns=len(support), crop_last_y=edge,
                lower_columns_on_crop_edge=sum(y == edge for x, y in support),
                lower_y_min=min(y for x, y in support), lower_y_max=max(y for x, y in support),
                bbox_y2=box["y2"], lower_columns_inside_float_bbox=sum(
                    box["x1"] <= x <= box["x2"] and box["y1"] <= y <= box["y2"] for x, y in support)))
    if sha.hexdigest() != previous["input_sha256"]["motion_distance_frames.jsonl"] or {r["frame"] for r in rows} != expected:
        raise ValueError("input or expected 15 frames changed")
    output.mkdir(parents=True, exist_ok=True)
    with (output/"logged_lower_support.csv").open("x", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    summary = dict(records=len(rows), without_central_lower_edge_contact=sum(r["lower_columns_on_crop_edge"] == 0 for r in rows),
        with_central_lower_edge_contact=sum(r["lower_columns_on_crop_edge"] > 0 for r in rows),
        input_sha256=sha.hexdigest(), new_point_selected=False, native_pixels_available=False,
        lower_support_stable_after_extension_verified=False, adoption_authorized=False)
    with (output/"logged_lower_support_summary.json").open("x") as stream:
        json.dump(summary, stream, indent=2)
        stream.write("\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
