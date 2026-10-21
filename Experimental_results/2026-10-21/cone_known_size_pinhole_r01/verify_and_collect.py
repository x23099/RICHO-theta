"""Save bounded validation and unchanged report assets. No Git or physical I/O."""
import io
import json
from pathlib import Path
import shutil
import sys
import unittest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT/"src"))
sys.path.insert(0, str(HERE))
from cone_dataset import sha256


def main():
    output = HERE/"verification_r01"
    if output.exists():
        raise ValueError("no verification overwrite")
    suite = unittest.TestSuite()
    suite.addTests(unittest.defaultTestLoader.discover(str(HERE), pattern="test_known_width.py"))
    for name in ("test_fisheye_floor_geometry.py", "test_ground_contact.py"):
        suite.addTests(unittest.defaultTestLoader.discover(str(ROOT/"tests"), pattern=name, top_level_dir=str(ROOT/"tests")))
    log = io.StringIO()
    result = unittest.TextTestRunner(stream=log, verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise AssertionError(log.getvalue())
    provenance = json.loads((HERE/"results_r01/provenance.json").read_text())
    output.mkdir()
    (output/"test_log.txt").write_text(log.getvalue())
    summary = dict(tests=result.testsRun, failures=len(result.failures), errors=len(result.errors),
        results_unchanged=True, source_hashes_verified=True, all_frames=provenance["frames"],
        known_width_geometry_fitted=False, live_output=False, calibration_approved=False,
        tests_sha256=sha256(HERE/"test_known_width.py"), verifier_sha256=sha256(Path(__file__)),
        test_log_sha256=sha256(output/"test_log.txt"))
    (output/"summary.json").write_text(json.dumps(summary, indent=2)+"\n")
    assets = HERE.parent/"report_assets"
    assets.mkdir(exist_ok=True)
    selections = [
        (HERE/"results_r01/known_width_vs_floor.png", "known_width_vs_floor.png", "numeric graph"),
        (HERE/"results_r01/occlusion_and_square_yaw.png", "known_width_occlusion_and_yaw.png", "numeric graph, right panel synthetic"),
        (ROOT/"Experimental_results/2026-10-19/paper_cone_2m_validation_r01/raw_samples/paper_cone_f001019.png",
         "raw_paper_cone_2m_f001019.png", "unedited native1280x720 camera frame"),
    ]
    if (assets/"known_width_manifest.json").exists() or any((assets/name).exists() for _,name,_ in selections):
        raise ValueError("no report asset overwrite")
    records = []
    for source, name, kind in selections:
        digest = sha256(source)
        shutil.copy2(source, assets/name)
        assert sha256(assets/name) == digest
        records.append(dict(source=str(source), file=name, kind=kind, source_sha256=digest))
    (assets/"known_width_manifest.json").write_text(json.dumps(dict(assets=records, byte_identical_copies=True,
        raw_session="paper_cone_center_z2p00_r01_20261019_180411_245", raw_frame=1019,
        raw_manifest="../../2026-10-19/paper_cone_2m_validation_r01/raw_sample_manifest.csv",
        result_provenance="../cone_known_size_pinhole_r01/results_r01/provenance.json"), indent=2)+"\n")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
