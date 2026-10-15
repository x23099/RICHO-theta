"""Independent conservation/hash/statistic checks plus exact causal replays."""
from collections import Counter
from dataclasses import asdict
import json
from pathlib import Path
import statistics

from replay import (HERE, ROOT, read_csv, sha256, replay_frames,
                    ConeGroundProjector, ConeQualitySettings)


def main():
    output = HERE/"verification.json"
    if output.exists():
        raise ValueError("no verification overwrite")
    result = HERE/"results_r01"
    provenance = json.loads((result/"provenance.json").read_text())
    for path, digest in provenance["source_sha256"].items():
        assert sha256(Path(path)) == digest, path
    for name, digest in provenance["output_sha256"].items():
        assert sha256(result/name) == digest, name
    previous = HERE.parent/"floor_cone_same_pose_analysis_r01/analysis_r01/summary.json"
    # Includes frozen projector/geometry, raw camera video, native images and every
    # production config snapshotted before this offline implementation.
    for path, digest in json.loads(previous.read_text())["source_sha256"].items():
        assert sha256(Path(path)) == digest, path
    rows = read_csv(result/"observations.csv")
    summary = read_csv(result/"summary.csv")
    assert len(rows) == 15429
    assert asdict(ConeQualitySettings()) == provenance["settings"]
    for row in rows:
        accepted = row["quality_accepted"] == "True"
        assert row["usable_for_ffb"] == row["floor_contact_verified"] == "False"
        assert accepted == bool(row["observed_z_m"])
        if not accepted:
            assert not row["observed_x_m"] and not row["filtered_z_m"] and not row["filtered_x_m"]
    for s in summary:
        group = [r for r in rows if r["model"] == s["model"] and r["dataset"] == s["dataset"]
                 and (r["phase"] if r["dataset"] == "same_pose" else r["session"]) == s["group"]]
        accepted = [r for r in group if r["quality_accepted"] == "True"]
        assert len(group) == int(s["frames"])
        assert len(accepted) == int(s["quality_accepted"])
        assert dict(Counter(r["reason"] for r in group if r not in accepted)) == json.loads(s["rejected_reasons"])
        if accepted:
            zs = [float(r["observed_z_m"]) for r in accepted]
            assert abs(statistics.median(zs)-float(s["z_median_m"])) < 1e-12
            assert abs(statistics.pstdev(zs)-float(s["z_std_m"])) < 1e-12
    for dataset, folder, central in (("same_pose", "floor_cone_same_pose_analysis_r01", True),
                                      ("historical_static", "cone_static_distance_r01", False)):
        base = HERE.parent/folder/"inference_r01"
        frames, predictions = read_csv(base/"frames.csv"), read_csv(base/"predictions.csv")
        for name, geometry in provenance["models"].items():
            projector = ConeGroundProjector(geometry, width=1280, height=720, front_lens="left",
                                             confidence_threshold=.5)
            expected = [r for r in rows if r["dataset"] == dataset and r["model"] == name]
            actual = replay_frames(frames, predictions, projector, central, ConeQualitySettings())
            assert len(expected) == len(actual)
            for saved, fresh in zip(expected, actual):
                for key, value in fresh.items():
                    assert saved[key] == ("" if value is None else str(value)), (key, saved, fresh)
    focus = [r for r in rows if r["dataset"] == "same_pose" and int(r["frame"]) in (1133, 1134)]
    assert len(focus) == 6 and all(r["quality_accepted"] == "False" for r in focus)
    report = dict(status="PASS_OFFLINE_INTEGRITY_AND_CAUSAL_REPLAY_NOT_HARDWARE_APPROVAL",
                  observations_checked=len(rows), model_dataset_replays=6,
                  all_frames_preserved=True, withheld_observations_not_filled=True,
                  prior_frozen_sources_native_images_and_production_configs_unchanged=True,
                  all_partial_failure_rows_withheld=True, physical_output=False,
                  verification_script_sha256=sha256(Path(__file__)),
                  bookkeeping_test_sha256=sha256(HERE/"test_replay_quality.py"),
                  provenance_sha256=sha256(result/"provenance.json"))
    output.write_text(json.dumps(report, indent=2)+"\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
