"""Copy four final daily-report assets unchanged; retain all earlier assets."""
import csv
import hashlib
import json
from pathlib import Path
import shutil

HERE = Path(__file__).resolve().parent
DAY = HERE.parent


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    selected = [
        ("paper_cone_2m_validation_r01/raw_samples/paper_cone_f001019.png", "daily_summary_raw_cone_2m_f001019.png",
         "unaltered_native_camera_frame", "paper_cone_2m_validation_r01/raw_sample_manifest.csv"),
        ("paper_cone_2m_validation_r01/analysis_r01/paper_cone_same_column.png", "daily_summary_paper_cone_same_column.png",
         "numeric_plot", "paper_cone_2m_validation_r01/analysis_r01/summary.json"),
        ("cone_support_quality_r01/results_r02/support_occlusion_recovery.png", "daily_summary_support_occlusion_recovery.png",
         "numeric_plot", "cone_support_quality_r01/results_r02/observations.csv"),
        ("cone_virtual_pinhole_r01/presentation_r01/pinhole_geometry_and_rounding.png", "daily_summary_pinhole_comparison.png",
         "numeric_plot", "cone_virtual_pinhole_r01/results_r01/summary.csv"),
    ]
    manifest = HERE/"daily_summary_manifest.json"
    if manifest.exists() or any((HERE/name).exists() for _, name, _, _ in selected):
        raise ValueError("no daily asset overwrite")
    records = []
    for source, name, kind, reference in selected:
        path = DAY/source
        records.append(dict(source=str(path.relative_to(DAY)), file=name, kind=kind,
                            source_sha256=digest(path), reference=reference))
    with (DAY/selected[0][3]).open(newline="") as f:
        original = next(r for r in csv.DictReader(f) if r["frame"] == "1019")
    records[0].update(session=original["session"], frame=int(original["frame"]), time_sec=float(original["time_sec"]),
                      width=int(original["width"]), height=int(original["height"]),
                      decoded_bgr_sha256=original["decoded_bgr_sha256"], source_raw_sha256=original["source_raw_sha256"],
                      edits="none; byte-for-byte file copy, no overlay/crop/resize/color changes")
    for record in records:
        shutil.copy2(DAY/record["source"], HERE/record["file"])
        assert digest(HERE/record["file"]) == record["source_sha256"]
    manifest.write_text(json.dumps(dict(date="2026-10-19", assets=records,
        original_assets_preserved=True, collector_sha256=digest(Path(__file__))), indent=2)+"\n")


if __name__ == "__main__":
    main()
