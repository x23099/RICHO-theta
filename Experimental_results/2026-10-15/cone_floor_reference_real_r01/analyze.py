"""Fixed projection at visible V-tip candidates, no calibration/pixel fitting.

Uses confirmed placements, not inferred image coordinates. Pixel selections
are assistant nonblind candidates; +/-2px is hypothetical, not a measured CI.
Unknown physical placement/height uncertainty is retained as unknown.
"""
import hashlib
import json
import os
from pathlib import Path
import sys

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "src"))
from cone_dataset import read_csv, sha256, write_csv
from diagnose_box_contact_calibration import project_pixel
from run_cone_review_frames import verify_frame


def main():
    output = HERE / "analysis_r01"
    if output.exists():
        raise ValueError("new run required; no previous result overwrite")
    intake = json.loads((HERE / "intake_summary.json").read_text())
    session = Path(intake["session"])
    for name, digest in intake["source_sha256"].items():
        if sha256(session/name) != digest:
            raise ValueError("original recording changed")
    p = intake["metadata"]["parameters"]
    measured_height = .59  # Explicit user statement: floor to lens centre, 59 cm.
    q = dict(p, camera_height=measured_height)
    manifest = read_csv(HERE / "raw_sample_manifest.csv")
    for sample in manifest:
        verify_frame(HERE, sample)
    samples = {int(r["frame"]):r for r in manifest}
    candidates = read_csv(HERE / "point_candidates.csv")
    if len(candidates) != 7 or len({r["point_id"] for r in candidates}) != 7:
        raise ValueError("seven distinct points required")
    cone_summary_path = HERE.parent / "cone_static_distance_r01/analysis_r01/summary.csv"
    cone = {r["condition"]:r for r in read_csv(cone_summary_path)}
    correspondence = dict(C080="center_080", C130="center_130", C200="center_200", L130="left_130", R130="right_130")
    sources = [Path(__file__), HERE / "point_candidates.csv", HERE / "intake_summary.json",
               HERE / "raw_sample_manifest.csv", cone_summary_path,
               ROOT / "src/ground_contact.py", ROOT / "src/diagnose_box_contact_calibration.py"]
    sources.extend(session/name for name in intake["source_sha256"])
    sources.extend(HERE/r["file"] for r in manifest)
    before = {str(f):sha256(f) for f in sources}
    results = []
    for row in candidates:
        sample = samples[int(row["frame"])]
        x, y, rx, rz, margin = (float(row[k]) for k in
            ("pixel_x", "pixel_y", "reference_x_m", "reference_z_m", "assumed_pixel_half_width_px"))
        if row["review_kind"] != "nonblind_visual_candidate" or margin != 2:
            raise ValueError("review and sensitivity assumptions unexpectedly changed")
        raw = project_pixel((x,y), p)
        measured = project_pixel((x,y), q)
        if raw is None or measured is None:
            raise ValueError("candidate is outside floor-ray diagnostic range")
        probe = [project_pixel((x+dx,y+dy), p) for dx in range(-2,3) for dy in range(-2,3)]
        if any(value is None for value in probe):
            raise ValueError("hypothetical pixel probe contains invalid floor ray")
        c = cone.get(correspondence.get(row["point_id"]))
        results.append(dict(row, time_sec=sample["time_sec"], raw_image=sample["file"],
            reference_x_m=rx, reference_z_m=rz, placement_uncertainty_m=None,
            configured_height_m=float(p["camera_height"]), reported_measured_height_m=measured_height,
            reported_height_uncertainty_m=None, raw_x_m=raw[0], raw_z_m=raw[1],
            raw_error_x_m=raw[0]-rx, raw_error_z_m=raw[1]-rz,
            measured_height_only_x_m=measured[0], measured_height_only_z_m=measured[1],
            measured_height_only_error_x_m=measured[0]-rx, measured_height_only_error_z_m=measured[1]-rz,
            hypothetical_2px_x_min_m=min(t[0] for t in probe), hypothetical_2px_x_max_m=max(t[0] for t in probe),
            hypothetical_2px_z_min_m=min(t[1] for t in probe), hypothetical_2px_z_max_m=max(t[1] for t in probe),
            cone_other_session_x_median_m=c["x_m_median"] if c else None,
            cone_other_session_z_median_m=c["z_m_median"] if c else None,
            physical_apex_verified=False, usable_for_ffb=False, fit_eligible=False))
    output.mkdir(exist_ok=False)
    write_csv(output/"floor_candidate_errors.csv", results)
    os.environ.setdefault("MPLCONFIGDIR", str(HERE.parent / "cone_static_distance_r01/.mplconfig"))
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, (ax, side) = plt.subplots(1,2,figsize=(12,5),constrained_layout=True)
    central = sorted([r for r in results if r["reference_x_m"] == 0],key=lambda r:r["reference_z_m"])
    refs = [r["reference_z_m"] for r in central]
    zs = [r["raw_z_m"] for r in central]
    ax.plot([.7,2.4],[.7,2.4],"k--",label="Reference = estimate")
    ax.errorbar(refs,zs,yerr=np.array([[r["raw_z_m"]-r["hypothetical_2px_z_min_m"] for r in central],
        [r["hypothetical_2px_z_max_m"]-r["raw_z_m"] for r in central]]), fmt="o",capsize=4,
        label="Floor V-tip candidate, configured h=0.58m; +/-2px probe")
    ax.plot(refs,[r["measured_height_only_z_m"] for r in central],"x",label="Same candidates, measured h=0.59m only")
    comparable = [r for r in central if r["cone_other_session_z_median_m"] is not None]
    ax.plot([r["reference_z_m"] for r in comparable],
        [float(r["cone_other_session_z_median_m"]) for r in comparable],"s",label="Cone bbox median, different recording")
    ax.set(xlabel="User-confirmed nominal placement Z [m]",ylabel="Estimated Z [m]",title="Centre: fixed geometry; no parameter fit")
    side.scatter([r["reference_x_m"] for r in results],[r["reference_z_m"] for r in results],marker="x",c="black",label="User-confirmed placements")
    side.scatter([r["raw_x_m"] for r in results],[r["raw_z_m"] for r in results],label="V-tip candidate projection, h=0.58m")
    for r in results:
        side.plot([r["reference_x_m"],r["raw_x_m"]],[r["reference_z_m"],r["raw_z_m"]],"k-",alpha=.3)
        side.annotate(r["point_id"],(r["raw_x_m"],r["raw_z_m"]),xytext=(4,3),textcoords="offset points",fontsize=8)
    side.set(xlabel="X right [m]",ylabel="Z forward [m]",title="Reference vs candidate projection; not precision GT")
    for panel in (ax,side):
        panel.grid(alpha=.25)
        panel.legend(fontsize=7)
    fig.savefig(output/"floor_reference_comparison.png",dpi=150)
    plt.close(fig)
    if any(sha256(Path(f)) != digest for f,digest in before.items()):
        raise ValueError("source/code/raw PNG changed during diagnosis")
    summary = dict(status="COMPLETED_FIXED_GEOMETRY_CANDIDATE_DIAGNOSIS_NOT_CALIBRATION_APPROVAL",
        user_reference_confirmation="全テープにおいて指定通りの距離においています",
        user_camera_height_confirmation="床からカメラのレンズ中心までで59cm",
        coordinate_basis="user-confirmed planned coordinates, V-tip reference; no instrumented coordinate table supplied",
        visibility_review_frames=[94,187,280,373], primary_frame=187,
        pixel_selection="assistant visual candidates; planned layout and earlier cone results known; no inverse solve or pixel fitting",
        uncertainty="physical placement/height uncertainty not provided; +/-2px is illustrative sensitivity, NOT confidence interval or measured annotation error",
        unresolved_apex="farther markers only a few native pixels; exact V apex not independently verified",
        real_camera_height_applied_to_production=False, physical_output=False, fitted_parameters=False,
        production_settings_changed=False, fit_points_used=0, coordinate_rows=len(results),
        different_session_comparison="cone medians use their own captures/nominal placement labels, NOT same-frame or paired physical points",
        source_sha256=before, output_sha256={n:sha256(output/n) for n in ("floor_candidate_errors.csv","floor_reference_comparison.png")})
    (output/"summary.json").write_text(json.dumps(summary,indent=2)+"\n")
    for r in results:
        print(f"{r['point_id']}: raw X={r['raw_x_m']:+.4f}, Z={r['raw_z_m']:.4f}; Z error={r['raw_error_z_m']:+.4f}; height0.59 Z={r['measured_height_only_z_m']:.4f}; +/-2px Z=[{r['hypothetical_2px_z_min_m']:.4f},{r['hypothetical_2px_z_max_m']:.4f}]")


if __name__ == "__main__":
    main()
