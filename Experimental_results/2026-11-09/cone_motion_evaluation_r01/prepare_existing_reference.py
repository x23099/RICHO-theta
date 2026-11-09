"""既存の固定4点だけから走行評価プロファイルを準備。Eと距離真値は不使用。"""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT/"src"))
from cone_distance_core import DEFAULT_CONFIG, digest
from prepare_cone_motion_profile import prepare


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image-dir", type=Path, default=Path("/home/robo25/Downloads"))
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.output_dir.exists():
        raise ValueError("new output directory required")
    folder = Path(__file__).parent
    prior = folder.parent/"wide_l_local_support_r01/results_r01"
    verification = folder.parent/"wide_l_local_support_r01/verification_r02/verification.json"
    record = json.loads(verification.read_text())
    inputs = dict(record["results_sha256"])
    inputs.update(record["source_sha256"])
    inputs.update(json.loads((prior/"input_provenance.json").read_text()))
    for name, sha in inputs.items():
        if digest(name) != sha:
            raise ValueError("checked existing source/input changed: "+name)
    # Earliest later-view frame, not selected by E accuracy. P0 had a different view.
    frame, session = 38231, "159c37ad534a4ac0b96ca69791713567"
    image = args.image_dir/f"decoded_{session}_f{frame:06d}.png"
    rows = json.loads((prior/"observations.json").read_text())
    labels = ["near_image_left", "near_image_right", "far_image_left", "far_image_right"]
    coordinates = []
    for label in labels:
        row = next(r for r in rows if r["frame"] == frame and r["label"] == label
            and r["threshold"] == 110 and r["chroma_limit"] == 100
            and r["arm_method"] == "principal_axis" and r["arc_px"] == 4)
        if not row["available"]:
            raise ValueError("all four actual fixed points required; no fallback")
        coordinates.append(row["point"])
    args.output_dir.mkdir(parents=True)
    spec = dict(schema="native_metric_rectangle_points_v1", image_sha256=digest(image),
        corner_order=labels, corners_native_xy=coordinates, width_m=.8, depth_m=.8,
        point_coordinates_human_reviewed=False, physical_metric_verified=False,
        provenance="existing local-support comparator; arbitrary board axes, not vehicle left/right; no E fitting")
    points = args.output_dir/"reference_points.json"
    points.write_text(json.dumps(spec, indent=2)+"\n")
    profile = prepare(image, points, DEFAULT_CONFIG, 0)
    (args.output_dir/"motion_profile_r01.json").write_text(json.dumps(profile, indent=2)+"\n")
    for p in (Path(__file__), ROOT/"src/prepare_cone_motion_profile.py", ROOT/"src/cone_motion_range.py",
              DEFAULT_CONFIG, verification, prior/"observations.json", image, points):
        inputs[str(p)] = digest(p)
    (args.output_dir/"input_provenance.json").write_text(json.dumps(inputs, indent=2)+"\n")
    print(json.dumps(profile, indent=2))


if __name__ == "__main__":
    main()
