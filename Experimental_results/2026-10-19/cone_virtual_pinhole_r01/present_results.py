"""Readable numeric presentation of frozen results; no camera image editing."""
import argparse
import json
import os
from pathlib import Path
import sys

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "src"))
from cone_dataset import read_csv, sha256


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.output_dir.exists():
        raise ValueError("new presentation output required")
    source = HERE / "results_r01/summary.csv"
    hashes = {str(p): sha256(p) for p in (source, Path(__file__))}
    rows = [r for r in read_csv(source) if r["population"] == "time_accepted" and r["condition"] in ("center_200", "cone_200")]
    rows.sort(key=lambda r: (r["dataset"], ("recorded58", "height_only59", "paper_centre2").index(r["model"])))
    os.environ.setdefault("MPLCONFIGDIR", "/tmp/cone_virtual_pinhole_matplotlib")
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1, 2, figsize=(12, 5), layout="constrained")
    x = np.arange(len(rows))
    for method, label, marker in (("direct", "Direct fisheye", "o"), ("pinhole_float", "Pinhole / unrounded", "x"),
                                   ("pinhole_rounded", "Nearest virtual pixel", "+")):
        axes[0].plot(x, [float(r[method+"_z_median_m_frame_median"]) for r in rows], marker, label=label)
    axes[0].axhline(2., color="black", ls="--", label="Nominal near-edge Z")
    axes[0].set(title="Fixed-ray geometry comparison\nSame calibration, not a new calibration", ylabel="Conditional Z [m]")
    axes[0].legend(fontsize=8)
    axes[1].bar(x, [1000*float(r["rounded_dz_abs_max_m"]) for r in rows])
    axes[1].set(title="Virtual pixel rounding\nSensitivity only, not measurement accuracy", ylabel="Max paired-column |delta Z| [mm]")
    for ax in axes:
        ax.set_xticks(x, [r["dataset"]+"\n"+r["model"] for r in rows], fontsize=7, rotation=15)
        ax.grid(axis="y", alpha=.3)
    fig.suptitle("Central 2m examples: image-quality-accepted frames only", fontsize=11)
    args.output_dir.mkdir(parents=True)
    target = args.output_dir / "pinhole_geometry_and_rounding.png"
    fig.savefig(target, dpi=150)
    plt.close(fig)
    if not all(sha256(p) == digest for p, digest in hashes.items()):
        raise ValueError("presentation source changed")
    (args.output_dir / "provenance.json").write_text(json.dumps(dict(source_sha256=hashes,
        output_sha256={target.name: sha256(target)}, numeric_data_changed=False, camera_images_edited=False), indent=2)+"\n")


if __name__ == "__main__":
    main()
