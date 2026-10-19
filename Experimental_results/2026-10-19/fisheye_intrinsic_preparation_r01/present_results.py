"""Legible view of frozen synthetic results; preserve original plot."""
import json
import os
from pathlib import Path
import sys

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT/"src"))
sys.path.insert(0, str(ROOT/"tests"))
from cone_dataset import sha256
from test_fisheye_intrinsic_calibration import synthetic_views


def main():
    output = HERE/"presentation_r01"
    if output.exists():
        raise ValueError("no plot overwrite")
    sources = [HERE/"verification_r01/SYNTHETIC_intrinsics_NOT_FOR_CAMERA.json",
               HERE/"verification_r01/summary.json", ROOT/"tests/test_fisheye_intrinsic_calibration.py", Path(__file__)]
    before = {str(p):sha256(p) for p in sources}
    candidate = json.loads(sources[0].read_text())
    _, _, _, views = synthetic_views()
    assert len(views) == len(candidate["per_view"])
    output.mkdir()
    os.environ.setdefault("MPLCONFIGDIR", str(output/"matplotlib_config"))
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1, 2, figsize=(10, 4), layout="constrained")
    for i, p in enumerate(views):
        held = i in candidate["validation_indices"]
        axes[0].plot(*np.mean(p, axis=0), "x" if held else ".", color="tab:orange" if held else "tab:blue")
    axes[0].set(xlim=(0, 640), ylim=(720, 0), xlabel="Native X [px]", ylabel="Native Y [px]",
                title="Synthetic view coverage\nBlue: train / Orange: validation")
    for split in ("train", "pose_validation_only"):
        rows = [r for r in candidate["per_view"] if r["split"] == split]
        axes[1].semilogy([r["view_index"] for r in rows], [max(r["rms_px"], 1e-14) for r in rows], ".", label=split)
    axes[1].set(xlabel="Synthetic view index", ylabel="Reprojection RMS [px]", title="Exact-model synthetic test\nNOT real camera accuracy")
    axes[1].legend(fontsize=8)
    for axis in axes:
        axis.grid(alpha=.2)
    fig.savefig(output/"synthetic_tool_validation.png", dpi=150)
    plt.close(fig)
    assert all(sha256(Path(p)) == digest for p, digest in before.items())
    (output/"provenance.json").write_text(json.dumps(dict(source_sha256=before,
        original_results_unchanged=True, synthetic_not_real=True,
        output_sha256=sha256(output/"synthetic_tool_validation.png")), indent=2)+"\n")


if __name__ == "__main__":
    main()
