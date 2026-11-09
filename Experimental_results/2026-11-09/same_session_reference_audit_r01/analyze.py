"""Inventory same-session PNG evidence and compare two existing paper frames.

No paper relocation inferred from repeated frames. No image export, new
physical measurements, live bundle, session transfer, ROS or FFB.
"""
import argparse
import csv
import hashlib
import importlib.util
from pathlib import Path
import re
import sys
import tarfile

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
from cone_distance_core import DEFAULT_CONFIG, digest, load_config
from derive_fixed_floor_live_bundle import source

SPEC = importlib.util.spec_from_file_location(
    "paper_boundary_stability", Path(__file__).resolve().parent.parent / "paper_boundary_stability_r01/analyze.py")
boundary = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(boundary)
sensitivity = boundary.sensitivity
audit = sensitivity.audit

SESSIONS = ("b559e4240e364166935f9ede9ac3e7ae", "df33e833acdf4e7d8b00d1ec37b7bcae")
ARCHIVE = Path("/home/robo25/Downloads/upper_support_capture_r01.tar.xz")


def identity(path):
    name = Path(path).name
    match = re.fullmatch(r"decoded_([a-z0-9]+)_f([0-9]{6,})\.png", name)
    if match is None or match[1] not in SESSIONS:
        return None
    return match[1], int(match[2])


def group_sources(paths):
    """Never count copied PNG bytes as additional frames or observations."""
    groups = {}
    for path in sorted(paths):
        key = identity(path)
        if key is None:
            continue
        sha = digest(path)
        if key in groups and groups[key]["sha256"] != sha:
            raise ValueError("same session/frame has differing PNG bytes: " + str(key))
        group = groups.setdefault(key, dict(sha256=sha, paths=[]))
        group["paths"].append(path)
    return groups


def observed_content(session, frame):
    """Agent's visual screening of ORIGINAL full frames, not human labeling."""
    if (session.startswith("b559") and frame in (2427, 5755)) or (session.startswith("df33") and frame == 2292):
        return dict(visual_content="floor_paper_visible", same_pose_ground_truth_verified=False,
                    physical_measurements_added=False, reviewed_by="assistant_full_native_image_screening")
    known_absent = ((session == SESSIONS[0] and frame in (32654, 32717, 32976, 33066, 33206, 33271, 35562, 36478))
                    or (session == SESSIONS[1] and frame in (61948, 64232)))
    if not known_absent:
        raise ValueError("additional frame requires explicit native-image visual screening")
    return dict(visual_content="floor_paper_not_visible_in_submitted_frame", same_pose_ground_truth_verified=False,
                physical_measurements_added=False, reviewed_by="assistant_full_native_image_screening")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.output_dir.exists():
        raise ValueError("new output directory required")
    recording_root = ROOT / "recordings/2026-11-04"
    groups = group_sources(recording_root.rglob("decoded_*.png"))
    hashes = {}; inventory = []; duplicates = []; items = {}
    for (session, frame), group in groups.items():
        path = group["paths"][0]
        item = source(path)
        if item["image"].shape != (720, 1280, 3):
            raise ValueError("native decoded size required")
        items[(session, frame)] = item
        inventory.append(dict(session=session, frame=frame, canonical_path=str(path.relative_to(ROOT)),
                              sha256=group["sha256"], copies_in_recordings=len(group["paths"]),
                              **observed_content(session, frame)))
        for copy in group["paths"]:
            relative = str(copy.relative_to(ROOT)); hashes[relative] = group["sha256"]
            duplicates.append(dict(session=session, frame=frame, location="recordings", path=relative,
                                   sha256=group["sha256"], additional_independent_observation=False))
    for path in sorted(Path("/home/robo25/Downloads").glob("decoded_*.png")):
        key = identity(path)
        if key is None:
            continue
        sha = digest(path); hashes[str(path)] = sha
        matched = key in groups and sha == groups[key]["sha256"]
        if not matched:
            raise ValueError("additional or changed same-session PNG needs visual screening: " + str(path))
        duplicates.append(dict(session=key[0], frame=key[1], location="Downloads", path=str(path),
                               sha256=sha, additional_independent_observation=False))
    # Read archive metadata/PNG bytes without extracting or overwriting files.
    hashes[str(ARCHIVE)] = digest(ARCHIVE)
    archive_rows = []
    with tarfile.open(ARCHIVE, mode="r:xz") as tar:
        for member in tar:
            if not member.isfile():
                continue
            ext = Path(member.name).suffix.lower()
            if ext in (".avi", ".mp4", ".mkv", ".mov", ".webm"):
                archive_rows.append(dict(path=member.name, kind="continuous_video", size=member.size))
            key = identity(member.name)
            if key is None:
                continue
            if member.size > 8*1024*1024:
                raise ValueError("bounded native PNG required")
            stream = tar.extractfile(member)
            with stream:
                sha = hashlib.sha256(stream.read()).hexdigest()
            if key not in groups or sha != groups[key]["sha256"]:
                raise ValueError("archive has additional/different source needing review")
            archive_rows.append(dict(path=member.name, kind="decoded_png_copy", size=member.size,
                                     session=key[0], frame=key[1], sha256=sha, additional_independent_observation=False))
    settings, camera, heading, _ = load_config()
    probe_path = Path(__file__).resolve().parent.parent / "reviewed_coordinate_audit_r01/results_r02/colour_pixel_vs_reviewed_edge.csv"
    paths = [Path(__file__), Path(SPEC.origin), Path(sensitivity.__file__), Path(audit.__file__),
             DEFAULT_CONFIG, ROOT/settings["camera_candidate"], ROOT/settings["floor_candidate"], probe_path]
    paths += [ROOT/"src"/name for name in ("derive_fixed_floor_live_bundle.py", "floor_reference_pose.py",
              "angular_fisheye_geometry.py", "cone_fixed_floor_candidate.py", "cone_distance_core.py")]
    review_root = Path(__file__).resolve().parent.parent / "physical_reference_review_r01/prepared_r01"
    review_queue = audit.validate_queue(audit.read_json(review_root / "queue.json"))
    decisions = audit.load_decisions(review_root / "decisions", review_queue, digest(review_root / "queue.json"))
    if len(decisions) != 6 or any(d["status"] != "reviewed" for d in decisions.values()):
        raise ValueError("unchanged complete human review set required")
    paths += [review_root / "queue.json", *[review_root / "decisions" / (item["id"]+".json") for item in review_queue["items"]]]
    for path in paths:
        hashes[str(path.relative_to(ROOT))] = digest(path)
    with probe_path.open() as stream:
        probe = next(row for row in csv.DictReader(stream) if row["session"] == SESSIONS[0] and row["frame"] == "35562")
    if probe["point_role"] != "recorded_upper_point":
        raise ValueError("recorded point, not rejected context, required")
    probe_point = [int(probe["point_x"]), int(probe["point_y"])]
    session = SESSIONS[0]; frame_corners = {}; geometry = []; methods = {}
    for frame in (2427, 5755):
        item = items[(session, frame)]; before = item["image"].copy()
        quad, info = sensitivity.contour_quad(item["image"], (280, 395, 90, 50), 170, .025)
        if quad is None:
            raise ValueError("fixed primary contour missing: " + str(info))
        methods[frame] = info
        gray = cv2.cvtColor(item["image"], cv2.COLOR_BGR2GRAY)
        baseline = sensitivity.fit(quad, item, settings, camera)
        for window in (0, 2, 3, 4):
            corners = quad if window == 0 else boundary.refine(gray, quad, window)
            frame_corners[(frame, window)] = corners
            models = sensitivity.fit(corners, item, settings, camera)
            rows = sensitivity.metrics(corners, models, baseline, [dict(id="fixed_probe", point=probe_point)], camera,
                                       heading, session, settings["diagnostic_range_m"])
            geometry += [dict(session=session, paper_frame=frame, window=window, probe_source_frame=35562,
                               probe_pixel_x=probe_point[0], probe_pixel_y=probe_point[1],
                               probe_is_actual_target_in_this_paper_frame=False,
                               evaluation="fixed_ray_response_only_NOT_current_frame_cone_distance", **row) for row in rows]
        if not np.array_equal(before, item["image"]):
            raise ValueError("input image memory modified")
    paired = []
    for window in (0, 2, 3, 4):
        delta = frame_corners[(5755, window)] - frame_corners[(2427, window)]
        for k in range(4):
            paired.append(dict(session=session, earlier_frame=2427, later_frame=5755, window=window, corner=k,
                               earlier_x=float(frame_corners[(2427, window)][k, 0]), earlier_y=float(frame_corners[(2427, window)][k, 1]),
                               later_x=float(frame_corners[(5755, window)][k, 0]), later_y=float(frame_corners[(5755, window)][k, 1]),
                               dx_px=float(delta[k, 0]), dy_px=float(delta[k, 1]), distance_px=float(np.linalg.norm(delta[k]))))
    # Events/logs establish scope, not new pixel evidence or floor measurements.
    cap_root = recording_root / "upper_support_capture_submission_r01/upper_support_capture_r01"
    live_summary_path = cap_root / "live_summary.json"
    hashes[str(live_summary_path.relative_to(ROOT))] = digest(live_summary_path)
    live_summary = audit.read_json(live_summary_path)
    videos = sorted(str(p.relative_to(ROOT)) for p in recording_root.rglob("*")
                    if p.is_file() and p.suffix.lower() in (".avi", ".mp4", ".mkv", ".mov", ".webm"))
    args.output_dir.mkdir(parents=True, exist_ok=False)
    for filename, rows in (("unique_frame_inventory.csv", inventory), ("duplicate_paths.csv", duplicates),
                           ("archive_image_members.csv", archive_rows), ("paper_frame_corner_differences.csv", paired),
                           ("paper_frame_geometry.csv", geometry)):
        audit.write_csv(args.output_dir / filename, rows)
    fig, axes = audit.plt.subplots(1, 2, figsize=(10, 4), layout="constrained")
    for window in (0, 2, 3, 4):
        data = [r for r in paired if r["window"] == window]
        axes[0].plot(range(4), [r["distance_px"] for r in data], "o-", label=f"half-window {window}" if window else "Old contour")
    axes[0].set_xticks(range(4), ["TL", "TR", "BR", "BL"]); axes[0].set_ylabel("Corner shift between frames [native px]")
    axes[0].set_title("b559 f2427 -> f5755 / existing paper view"); axes[0].legend(fontsize=7)
    for window in (0, 2, 3, 4):
        data = [r for r in geometry if r["window"] == window and r["assignment"] == "as_listed"
                and r["tracked_branch"] == "s0" and r["height_source"] == "image_plane_plus_thickness"]
        axes[1].plot([r["paper_frame"] for r in data], [r["height_mm"] for r in data], "o-", label=f"half-window {window}" if window else "Old contour")
    axes[1].set_xlabel("Saved frame"); axes[1].set_ylabel("Conditional floor height [mm]"); axes[1].set_title("Fixed first-listed family, no method selection")
    fig.suptitle("Repeated image evidence, NOT independent physical accuracy validation")
    fig.savefig(args.output_dir / "same_paper_frame_repeatability.png", dpi=150); audit.plt.close(fig)
    def resolve(path):
        return Path(path) if Path(path).is_absolute() else ROOT/path
    changed = [p for p, sha in hashes.items() if digest(resolve(p)) != sha]
    if changed:
        raise ValueError("source changed during audit: " + str(changed))
    summary = dict(status="COMPLETED_EXISTING_SESSION_EVIDENCE_NOT_PHYSICAL_APPROVAL", sessions=list(SESSIONS),
                   local_unique_frames=len(inventory), local_decoded_paths=sum(len(g["paths"]) for g in groups.values()),
                   visible_paper_frames=sum(r["visual_content"] == "floor_paper_visible" for r in inventory),
                   absent_paper_frames=sum(r["visual_content"] != "floor_paper_visible" for r in inventory),
                   b559_additional_paper_frame=2427, df33_additional_paper_frames_found=0,
                   new_independent_physical_reference_found=False,
                   paired_corner_records=len(paired), all_model_response_records=len(geometry),
                   primary_contours=methods, archive_member_rows=len(archive_rows),
                   continuous_video_in_scoped_local_directory=videos,
                   continuous_video_in_submitted_archive=[r["path"] for r in archive_rows if r["kind"] == "continuous_video"],
                   remote_school_storage_checked=False, original_run_static_camera_flag=live_summary["static_camera_only"],
                   static_floor_pose_independently_verified=False, selected_model=None, selected_method=None,
                   source_sha256=hashes, original_images_modified=False, human_decisions_changed=False,
                   runtime_changed=False, physical_metric_verified=False, usable_for_ffb=False)
    audit.write_json(args.output_dir / "summary.json", summary)
    print({k: v for k, v in summary.items() if k not in ("source_sha256", "primary_contours")})


if __name__ == "__main__":
    main()
