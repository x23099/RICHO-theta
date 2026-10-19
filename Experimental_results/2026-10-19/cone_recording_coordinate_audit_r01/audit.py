"""Read-only data/code audit, writing only a new experiment output directory."""
import argparse
import ast
from collections import defaultdict
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
OLD = ROOT / "Experimental_results/2026-10-15"
sys.path.insert(0, str(ROOT / "src"))
from cone_dataset import read_csv, sha256, write_csv
from diagnose_box_contact_calibration import project_pixel

GROUPS = ("cone_static_distance_r01", "cone_floor_reference_real_r01", "floor_cone_same_pose_analysis_r01",
          "white_paper_visibility_r01", "paper_reference7_r01")
GEOMETRY_KEYS = ("camera_height", "pitch_deg", "roll_deg", "yaw_deg", "radius_scale", "front_cx_offset",
                 "front_cy_offset", "back_cx_offset", "back_cy_offset")
CAPTURE_KEYS = ("backend", "frame_width", "frame_height", "fps", "fourcc_text")
WRITER_METHODS = ("start_capture", "start_recording", "_open_recording_writers", "record_frames", "update_frame")
HISTORICAL_REVISION = "a77483c"


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def valid_frame_table(rows):
    if not rows or [int(r["frame"]) for r in rows] != list(range(1, len(rows)+1)):
        raise ValueError("complete consecutive one-based frame table required")
    times = [float(r["time_sec"]) for r in rows]
    if any(not math.isfinite(t) or t < 0 for t in times) or any(b <= a for a, b in zip(times, times[1:])):
        raise ValueError("finite strictly increasing original timestamps required")
    return times


def file_hashes(intake, entry):
    session = Path(entry["path"])
    source = entry.get("hashes", intake.get("source_sha256", {}))
    result = {}
    for name in ("raw.avi", "metadata.json", "detections.csv"):
        digest = source.get(name, source.get(str(session / name)))
        if not digest:
            raise ValueError("missing archived session digest")
        result[str(session / name)] = digest
    return result


def collect_inputs():
    sessions, archives, hashes, manifest_rows = [], [], {}, []
    for name in GROUPS:
        group = OLD / name
        path = group / "intake_summary.json"
        intake = json.loads(path.read_text())
        hashes[str(path)] = sha256(path)
        entries = intake.get("inputs", [dict(path=intake.get("session"))])
        for entry in entries:
            root = Path(entry["path"])
            expected = file_hashes(intake, entry)
            for filename, digest in expected.items():
                if not Path(filename).is_file() or Path(filename).is_symlink() or sha256(filename) != digest:
                    raise ValueError("session changed since original intake: " + filename)
            hashes.update(expected)
            sessions.append(dict(group=name, root=root, archive=intake["archive"], hashes=expected))
        archive = Path(intake["archive"])
        digest = intake.get("archive_sha256", intake.get("source_sha256", {}).get(str(archive)))
        if not digest:
            raise ValueError("missing original archive digest")
        present = archive.is_file()
        if present and sha256(archive) != digest:
            raise ValueError("original archive changed: " + str(archive))
        if present:
            hashes[str(archive)] = digest
        archives.append(dict(group=name, archive=str(archive), expected_sha256=digest,
                             present=present, archive_rechecked=present,
                             status="hash_matches_original_intake" if present else "not_available_to_recheck"))
        manifests = sorted(group.glob("*manifest.csv"))
        occlusion = group / "occlusion_diagnosis_r01/raw_manifest.csv"
        if occlusion.exists():
            manifests.append(occlusion)
        for manifest in manifests:
            hashes[str(manifest)] = sha256(manifest)
            for row in read_csv(manifest):
                # Nested occlusion manifest file names are relative to its own folder.
                candidate = group / row["file"]
                if not candidate.exists():
                    candidate = manifest.parent / row["file"]
                manifest_rows.append(dict(row, path=candidate, group=name, manifest=str(manifest)))
                hashes[str(candidate)] = row["png_sha256"]
    names = [s["root"].name for s in sessions]
    if len(sessions) != 10 or len(names) != len(set(names)):
        raise ValueError("ten unique prespecified sessions required")
    for row in manifest_rows:
        if row["session"] not in names or sha256(row["path"]) != row["png_sha256"]:
            raise ValueError("native sample not tied to its frozen session")
    return sessions, archives, manifest_rows, hashes


def video_header(path):
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise ValueError("unreadable video: " + str(path))
    values = [cap.get(k) for k in (cv2.CAP_PROP_FRAME_WIDTH, cv2.CAP_PROP_FRAME_HEIGHT,
                                  cv2.CAP_PROP_FRAME_COUNT, cv2.CAP_PROP_FPS, cv2.CAP_PROP_FOURCC)]
    cap.release()
    if not all(math.isfinite(v) for v in values):
        raise ValueError("nonfinite video header")
    code = int(values[4])
    return dict(width=int(values[0]), height=int(values[1]), header_frames=int(values[2]), fps=values[3],
                codec="".join(chr((code >> 8*i) & 255) for i in range(4)))


def verify_sample(image, sample, source_raw_sha256):
    png = cv2.imread(str(sample["path"]))
    if (sample["source_raw_sha256"] != source_raw_sha256 or image.shape != (720, 1280, 3)
            or png is None or png.shape != image.shape or not np.array_equal(png, image)):
        raise ValueError("sample differs from its one-based raw frame")
    pixels = hashlib.sha256(image.tobytes()).hexdigest()
    if pixels != sample["decoded_bgr_sha256"]:
        raise ValueError("native sample pixel hash mismatch")
    return dict(group=sample["group"], session=sample["session"], frame=int(sample["frame"]),
                file=str(sample["path"]), manifest=sample["manifest"], width=1280, height=720,
                source_raw_sha256=source_raw_sha256, png_sha256=sample["png_sha256"],
                decoded_bgr_sha256=pixels, pixels_equal=True)


def audit_sessions(sessions, samples):
    table, verified, headers = [], [], []
    by_sample = defaultdict(list)
    for s in samples:
        by_sample[s["session"], int(s["frame"])].append(s)
    for s in sessions:
        root = s["root"]
        meta = json.loads((root / "metadata.json").read_text())
        rows = read_csv(root / "detections.csv")
        times = valid_frame_table(rows)
        raw_sha = s["hashes"][str(root / "raw.avi")]
        for name in ("raw", "bev", "detection"):
            path = root / (name + ".avi")
            h = video_header(path)
            headers.append(dict(group=s["group"], session=root.name, view=name, path=str(path), **h))
            if h["header_frames"] != len(rows):
                raise ValueError("video header/CSV frame count mismatch")
            if name == "raw" and (h["width"], h["height"], h["codec"]) != (1280, 720, "MJPG"):
                raise ValueError("native raw dimensions/codec mismatch")
        capture = cv2.VideoCapture(str(root / "raw.avi"))
        decoded = 0
        try:
            for r in rows:
                ok, image = capture.read()
                if not ok or image.shape != (720, 1280, 3):
                    raise ValueError("raw decode/CSV/native frame mismatch")
                decoded += 1
                for sample in by_sample.get((root.name, decoded), []):
                    if float(sample["time_sec"]) != float(r["time_sec"]):
                        raise ValueError("PNG/CSV timestamp mismatch")
                    verified.append(verify_sample(image, sample, raw_sha))
            if capture.read()[0]:
                raise ValueError("extra raw frames")
        finally:
            capture.release()
        parameters, props = meta["parameters"], meta["camera_capture_properties"]
        geometry = {k: parameters[k] for k in GEOMETRY_KEYS}
        cap = {k: props[k] for k in CAPTURE_KEYS}
        table.append(dict(group=s["group"], session=root.name, session_path=str(root), archive=s["archive"],
                          created_at=meta["created_at"], device=meta["device"], odom_topic=meta["odom_topic"],
                          requested_width=meta["requested_camera_width"], requested_height=meta["requested_camera_height"],
                          requested_fps=meta["requested_camera_fps"], decoded_frames=decoded,
                          first_time_sec=times[0], last_time_sec=times[-1],
                          effective_frame_rate=(len(rows)-1)/(times[-1]-times[0]),
                          **cap, geometry_fingerprint=fingerprint(geometry), parameters_fingerprint=fingerprint(parameters),
                          capture_fingerprint=fingerprint(props), geometry=json.dumps(geometry, sort_keys=True),
                          odom_available_frames=sum(r["odom_available"] == "1" for r in rows),
                          max_abs_odom_linear_mps=max(abs(float(r["odom_linear_mps"])) for r in rows if r["odom_linear_mps"]),
                          max_abs_odom_angular_radps=max(abs(float(r["odom_angular_radps"])) for r in rows if r["odom_angular_radps"]),
                          git_revision_recorded=any("git" in k or "commit" in k for k in meta),
                          geometry_per_frame_recorded=all(k in rows[0] for k in GEOMETRY_KEYS),
                          camera_serial_recorded=any("serial" in k for k in meta) or any("serial" in k for k in props),
                          exposure_controls_verified=False, camera_internal_correction_state_recorded=False,
                          usable_for_ffb=False))
        print(f"Audited {root.name}: decoded={decoded}", flush=True)
    if len(verified) != len(samples):
        raise ValueError("some native sample frames were not decoded")
    return table, verified, headers


def methods(code):
    tree = ast.parse(code)
    result = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name in WRITER_METHODS:
            result[node.name] = node
    if set(result) != set(WRITER_METHODS):
        raise ValueError("expected recording methods missing")
    return result


def raw_route_contract(code):
    nodes = methods(code)
    update = nodes["update_frame"]
    calls = [n for n in ast.walk(update) if isinstance(n, ast.Call)]
    record = [n for n in calls if ast.unparse(n.func) == "self.record_frames"]
    capread = [n for n in ast.walk(update) if isinstance(n, ast.Assign)
               and isinstance(n.value, ast.Call) and ast.unparse(n.value.func) == "self.cap.read"]
    writes = [n for n in ast.walk(nodes["record_frames"]) if isinstance(n, ast.Call)
              and ast.unparse(n.func) == "self.recording_writers['raw'].write"]
    other_assigns = []
    for n in ast.walk(update):
        if isinstance(n, (ast.Assign, ast.AugAssign, ast.AnnAssign)) and n not in capread:
            targets = n.targets if isinstance(n, ast.Assign) else [n.target]
            if any(isinstance(t, ast.Name) and t.id == "frame" for target in targets for t in ast.walk(target)):
                other_assigns.append(n)
    return dict(cap_read_assigns_ret_frame=len(capread) == 1 and ast.unparse(capread[0].targets[0]) == "(ret, frame)",
                records_input_frame_not_bev=len(record) == 1 and [ast.unparse(a) for a in record[0].args] == ["frame", "bev_img", "lane_mask_visual"],
                raw_writer_receives_raw_frame=len(writes) == 1 and [ast.unparse(a) for a in writes[0].args] == ["raw_frame"],
                input_frame_not_reassigned=not other_assigns,
                explicit_raw_calibration_overlay_calls=sum(ast.unparse(n.func).endswith("draw_fisheye_calibration_circles") for n in calls),
                scope="AST route check plus manual reader inspection; not execution trace of historical capture")


def bbox_coordinate_audit():
    output = []
    for group in ("cone_static_distance_r01", "floor_cone_same_pose_analysis_r01"):
        path = OLD / group / "inference_r01/predictions.csv"
        rows = read_csv(path)
        valid = all(0 <= float(r["x1"]) < float(r["x2"]) <= 1280
                    and 0 <= float(r["y1"]) < float(r["y2"]) <= 720 for r in rows)
        if not valid:
            raise ValueError("exported bbox outside native image")
        output.append(dict(group=group, predictions=len(rows), native_bounds_valid=valid,
                           x2_larger_than_model_imgsz960=sum(float(r["x2"]) > 960 for r in rows),
                           max_x2=max(float(r["x2"]) for r in rows), max_y2=max(float(r["y2"]) for r in rows),
                           inference_imgsz=960, native_width=1280, native_height=720,
                           interpretation="native coordinate contract consistent; no normalization or imgsz rescaling applied downstream"))
    return output


def audit_code():
    code = (ROOT / "src/bird_eye.py").read_text()
    historical = subprocess.check_output(["git", "show", HISTORICAL_REVISION + ":src/bird_eye.py"], cwd=ROOT, text=True)
    old, current = methods(historical), methods(code)
    rows = [dict(method=k, current_line=current[k].lineno, historical_revision=HISTORICAL_REVISION,
                 ast_equal=ast.dump(old[k], include_attributes=False) == ast.dump(current[k], include_attributes=False))
            for k in WRITER_METHODS]
    revision = subprocess.check_output(["git", "rev-parse", HISTORICAL_REVISION], cwd=ROOT, text=True).strip()
    return dict(current_contract=raw_route_contract(code), historical_contract=raw_route_contract(historical),
                historical_revision=revision, historical_source_sha256=hashlib.sha256(historical.encode()).hexdigest(),
                capture_runtime_revision_proved=False, methods=rows)


def same_video_reference_audit():
    folder = OLD / "floor_cone_same_pose_analysis_r01"
    anchors = read_csv(folder / "contact_candidates.csv")
    geometry = json.loads((HERE.parent / "cone_distance_methods_r01/results_r01/provenance.json").read_text())["geometries"]
    scope = json.loads((folder / "scope.json").read_text())
    confirmation = json.loads((OLD / "floor_visibility_confirmation_r01/confirmation.json").read_text())
    rows = []
    for a in anchors:
        if a["kind"] != "floor":
            continue
        x, y = float(a["pixel_x"]), float(a["pixel_y"])
        cone = next(p for p in anchors if p["kind"] == "cone" and p["point_id"] == a["point_id"])
        for name, p in geometry.items():
            centre = project_pixel((x, y), p)
            probes = [project_pixel((x+dx, y+dy), p) for dx in range(-2, 3) for dy in range(-2, 3)]
            if centre is None or any(q is None for q in probes):
                raise ValueError("prespecified local sensitivity outside projection domain")
            rows.append(dict(point_id=a["point_id"], nominal_z_m=float(a["reference_z_m"]), floor_frame=int(a["frame"]),
                             pixel_x=x, pixel_y=y, model=name, z_m=centre[1],
                             hypothetical_pm2px_z_min_m=min(q[1] for q in probes),
                             hypothetical_pm2px_z_max_m=max(q[1] for q in probes),
                             cone_frame=int(cone["frame"]), cone_candidate_y=float(cone["pixel_y"]),
                             cone_minus_floor_candidate_y_px=float(cone["pixel_y"])-y,
                             pixel_gt_verified=False, fit_eligible=False, usable_for_ffb=False))
    return rows, dict(floor_only_window=[1, 300], cone_130_window=[563, 780], cone_200_window=[1000, 1547],
                      floor_after=scope["floor_after"], user_visibility_confirmation=confirmation,
                      exact_floor_apex_pixels_human_confirmed=False,
                      paper7_contains_cone_reference_pair=False,
                      uncertainty_pm2px_is_assumed_not_measured=True,
                      information_gap="clearly identifiable surveyed floor point and corresponding near base edge in the same camera-state recording",
                      existing_seven_pose_paper_recording_missing=False, full_retake_requested=False,
                      physical_fault_inferred=False, usable_for_ffb=False)


def plot(table, points, output):
    os.environ.setdefault("MPLCONFIGDIR", "/tmp/cone_coordinate_audit_matplotlib")
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(11, 4), layout="constrained")
    ax.bar(range(len(table)), [r["effective_frame_rate"] for r in table], label="CSV monotonic sample rate")
    ax.axhline(30, color="black", ls="--", label="Declared AVI / capture rate")
    ax.set_xticks(range(len(table)), [r["session"].split("_20261015")[0] for r in table], rotation=35, ha="right", fontsize=7)
    ax.set(ylabel="Frames/s", title="Same native geometry does not guarantee same wall-clock frame spacing")
    ax.legend(fontsize=8)
    fig.savefig(output / "recording_rate_audit.png", dpi=150)
    plt.close(fig)
    fig, ax = plt.subplots(figsize=(9, 4), layout="constrained")
    for n, r in enumerate(points):
        ax.plot([n, n], [r["hypothetical_pm2px_z_min_m"], r["hypothetical_pm2px_z_max_m"]], color="C0", lw=3)
        ax.plot(n, r["z_m"], "o", color="C0")
        ax.plot([n-.3, n+.3], [r["nominal_z_m"]]*2, color="black", ls="--")
    ax.set_xticks(range(len(points)), [r["point_id"]+"\n"+r["model"] for r in points], fontsize=8)
    ax.set(ylabel="Conditional floor Z [m]", title="Existing same-video V-apex candidates: assumed +/-2 px sensitivity, NOT a confidence interval")
    ax.grid(axis="y", alpha=.3)
    fig.savefig(output / "same_video_reference_sensitivity.png", dpi=150)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.output_dir.exists():
        raise ValueError("new audit output directory required")
    sessions, archives, samples, hashes = collect_inputs()
    table, verified, headers = audit_sessions(sessions, samples)
    code = audit_code()
    points, reference = same_video_reference_audit()
    bbox = bbox_coordinate_audit()
    paths = [Path(__file__), HERE / "method.md", HERE / "test_audit.py", ROOT / "src/bird_eye.py",
             ROOT / "src/ground_contact.py", ROOT / "src/cone_observation.py", ROOT / "src/run_cone_video.py",
             ROOT / "src/cone_detection_diagnostics.py", ROOT / "src/diagnose_box_contact_calibration.py",
             OLD / "floor_cone_same_pose_analysis_r01/contact_candidates.csv",
             OLD / "floor_cone_same_pose_analysis_r01/scope.json",
             OLD / "floor_visibility_confirmation_r01/confirmation.json",
             OLD / "paper_reference7_r01/analyze.py", OLD / "white_paper_visibility_r01/analyze.py",
             HERE.parent / "cone_support_extent_r01/support.py", HERE.parent / "cone_contact_reuse_r01/contact_pixels.py",
             HERE.parent / "cone_distance_methods_r01/results_r01/provenance.json"]
    for name in ("cone_static_distance_r01", "floor_cone_same_pose_analysis_r01"):
        paths.extend(OLD / name / "inference_r01" / f for f in ("predictions.csv", "frames.csv", "provenance.json"))
    vendor = ROOT / "yolo-env/lib/python3.10/site-packages/ultralytics"
    paths.extend(vendor / p for p in ("models/yolo/detect/predict.py", "utils/ops.py"))
    paths.extend(sorted((ROOT / "src").glob("bird_eye_config*.json")))
    hashes.update({str(p): sha256(p) for p in paths})
    if not all(sha256(p) == digest for p, digest in hashes.items()):
        raise ValueError("inputs changed during audit")
    args.output_dir.mkdir(parents=True)
    for name, rows in (("sessions.csv", table), ("video_headers.csv", headers), ("archives.csv", archives),
                       ("native_samples.csv", verified), ("same_video_floor_sensitivity.csv", points)):
        write_csv(args.output_dir / name, rows)
    (args.output_dir / "code_route_audit.json").write_text(json.dumps(code, indent=2)+"\n")
    (args.output_dir / "floor_correspondence.json").write_text(json.dumps(reference, indent=2, ensure_ascii=False)+"\n")
    write_csv(args.output_dir / "bbox_coordinate_audit.csv", bbox)
    plot(table, points, args.output_dir)
    report = dict(status="RECORDING_COORDINATE_AUDIT_NOT_PHYSICAL_CALIBRATION_APPROVAL", sessions=len(table),
                  raw_frames_decoded=sum(r["decoded_frames"] for r in table), native_pngs_verified=len(verified),
                  distinct_recorded_geometry=len({r["geometry_fingerprint"] for r in table}),
                  distinct_all_parameters=len({r["parameters_fingerprint"] for r in table}),
                  distinct_capture_properties=len({r["capture_fingerprint"] for r in table}),
                  raw_route_contract=code["current_contract"], recording_methods_equal_historical=all(r["ast_equal"] for r in code["methods"]),
                  new_inference_or_fit=False, images_edited_or_created=False, runtime_changes=False,
                  physical_output=False, usable_for_ffb=False, source_sha256=hashes,
                  output_sha256={p.name: sha256(p) for p in args.output_dir.iterdir() if p.is_file()})
    (args.output_dir / "provenance.json").write_text(json.dumps(report, indent=2)+"\n")
    print(json.dumps({k: v for k, v in report.items() if k not in ("source_sha256", "output_sha256")}, indent=2))


if __name__ == "__main__":
    main()
