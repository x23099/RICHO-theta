"""Copy four existing report assets byte-for-byte; never edit camera images."""
import csv
import hashlib
import json
from pathlib import Path
import shutil

import cv2

HERE = Path(__file__).resolve().parent
DAY = HERE.parent
ITEMS = [
    ("raw_cone_center1p30_f000217.png", "cone_static_distance_r01/raw_samples/center_130_f000217.png",
     "cone_static_distance_r01/raw_sample_manifest.csv", "raw"),
    ("raw_paper_center2p00_f001481.png", "paper_reference7_r01/raw_samples/paper7_f001481.png",
     "paper_reference7_r01/raw_sample_manifest.csv", "raw"),
    ("cone_occlusion_quality_gate.png", "cone_observation_quality_r01/results_r01/occlusion_gate.png", None, "graph"),
    ("paper_reference_projection_comparison.png", "paper_reference7_r01/analysis_r01/projection_comparison.png", None, "graph"),
]


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    if (HERE/"manifest.json").exists() or any((HERE/i[0]).exists() for i in ITEMS):
        raise ValueError("existing report assets must not be overwritten")
    rows = []
    for name, relative, manifest, kind in ITEMS:
        source, target = DAY/relative, HERE/name
        record = dict(file=name, source=str(source.relative_to(DAY)), kind=kind, source_sha256=sha256(source))
        if manifest:
            with (DAY/manifest).open(newline="") as stream:
                matches = [r for r in csv.DictReader(stream) if (DAY/manifest).parent/r["file"] == source]
            assert len(matches) == 1
            row = matches[0]
            image = cv2.imread(str(source))
            assert image.shape == (720,1280,3)
            assert sha256(source) == row["png_sha256"]
            assert hashlib.sha256(image.tobytes()).hexdigest() == row["decoded_bgr_sha256"]
            record.update(session=row["session"], frame=int(row["frame"]), time_sec=float(row["time_sec"]),
                width=1280, height=720, decoded_bgr_sha256=row["decoded_bgr_sha256"],
                source_raw_sha256=row["source_raw_sha256"], image_edits=False)
        shutil.copyfile(source, target)
        assert sha256(source) == sha256(target) == record["source_sha256"]
        rows.append(record)
    result = dict(date="2026-10-15", assets=rows, camera_images_edited=False,
                  script_sha256=sha256(Path(__file__)))
    (HERE/"manifest.json").write_text(json.dumps(result, indent=2, ensure_ascii=False)+"\n")
    print("Verified four byte-identical report assets, including two native1280x720 raw PNGs.")


if __name__ == "__main__":
    main()
