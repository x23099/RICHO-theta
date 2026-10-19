"""Record reproducible tool validation; synthetic K/D are NEVER real intrinsics."""
import io
import json
import os
from pathlib import Path
import sys
import unittest

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT/"src"))
sys.path.insert(0, str(ROOT/"tests"))
from cone_dataset import sha256
from fisheye_intrinsic_calibration import fit_candidate
from test_fisheye_intrinsic_calibration import synthetic_views


def main():
    output = HERE/"verification_r01"
    if output.exists():
        raise ValueError("no verification overwrite")
    paths = [Path(__file__), HERE/"method.md", HERE/"target_a3/board_spec.json", HERE/"target_a3/checkerboard.pdf",
             HERE/"target_a3/checkerboard.svg", HERE/"negative_real_video_r01/observations.json",
             ROOT/"src/fisheye_intrinsic_calibration.py", ROOT/"src/prepare_fisheye_calibration.py",
             ROOT/"tests/test_fisheye_intrinsic_calibration.py", ROOT/"src/fisheye_floor_geometry.py",
             ROOT/"src/ground_contact.py", ROOT/"src/bird_eye.py"]
    paths.extend(ROOT.glob("src/bird_eye_config*.json"))
    sources = {str(p):sha256(p) for p in paths}
    negative = json.loads(paths[5].read_text())
    assert negative["frames_decoded"] == 1733 and len(negative["attempts"]) == 3 and not negative["retained_views"]
    for path, digest in negative["source_sha256"].items():
        assert sha256(Path(path)) == digest
    suite = unittest.TestSuite()
    for pattern in ("test_fisheye_intrinsic_calibration.py", "test_fisheye_floor_geometry.py", "test_ground_contact.py"):
        suite.addTests(unittest.defaultTestLoader.discover(str(ROOT/"tests"), pattern=pattern))
    log = io.StringIO()
    run = unittest.TextTestRunner(stream=log, verbosity=2).run(suite)
    assert run.wasSuccessful(), log.getvalue()
    board, K, D, views = synthetic_views()
    candidate = fit_candidate(views, board)
    assert candidate["decision"] == "CANDIDATE_ONLY" and not candidate["usable_for_ffb"]
    assert all(sha256(Path(p)) == digest for p, digest in sources.items())
    output.mkdir()
    (output/"test_log.txt").write_text(log.getvalue())
    (output/"SYNTHETIC_intrinsics_NOT_FOR_CAMERA.json").write_text(json.dumps(candidate, indent=2)+"\n")
    plot(views, candidate, output)
    result = dict(status="PASS_TOOLING_AND_SYNTHETIC_TESTS_NOT_REAL_CAMERA_CALIBRATION", tests=run.testsRun,
        failures=len(run.failures), errors=len(run.errors), synthetic_views=len(views), synthetic_train=len(candidate["train_indices"]),
        synthetic_validation=len(candidate["validation_indices"]),
        synthetic_K_abs_max_error=float(np.max(np.abs(np.asarray(candidate["K"])-K))),
        synthetic_D_abs_max_error=float(np.max(np.abs(np.asarray(candidate["D"])-D))),
        synthetic_train_rms_px=candidate["calibration_rms_px"], synthetic_validation_rms_px=candidate["pose_validation_rms_px"],
        real_video_negative_sampled_frames=[r["frame"] for r in negative["attempts"]], real_video_negative_found=0,
        real_camera_calibrated=False, production_settings_changed=False, source_sha256=sources,
        dependencies_installed=False, gpu_required=False, physical_output=False,
        output_sha256={p.name:sha256(p) for p in output.iterdir() if p.is_file()})
    (output/"summary.json").write_text(json.dumps(result, indent=2)+"\n")
    print(json.dumps({k:v for k,v in result.items() if k not in ("source_sha256", "output_sha256")}, indent=2))


def plot(views, candidate, output):
    os.environ.setdefault("MPLCONFIGDIR", str(output/"matplotlib_config"))
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1, 2, figsize=(10, 4), layout="constrained")
    for i, p in enumerate(views):
        held = i in candidate["validation_indices"]
        axes[0].plot(*np.mean(p, axis=0), "x" if held else ".", color="tab:orange" if held else "tab:blue")
    axes[0].set(xlim=(0, 640), ylim=(720, 0), xlabel="Native X [px]", ylabel="Native Y [px]", title="SYNTHETIC board centres: blue=train, orange=validation")
    for split in ("train", "pose_validation_only"):
        rows = [r for r in candidate["per_view"] if r["split"] == split]
        axes[1].semilogy([r["view_index"] for r in rows], [max(r["rms_px"], 1e-14) for r in rows], ".", label=split)
    axes[1].set(xlabel="Synthetic view index", ylabel="Reprojection RMS [px]", title="SYNTHETIC exact-model recovery, NOT real accuracy")
    axes[1].legend(fontsize=8)
    for axis in axes:
        axis.grid(alpha=.2)
    fig.savefig(output/"synthetic_tool_validation.png", dpi=150)
    plt.close(fig)


if __name__ == "__main__":
    main()
