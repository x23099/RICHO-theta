"""Inventory the user's completed three-message batch without extraction.

Names repeated in messages are NOT separately available historical uploads;
inspect each current attached path once and state that limit explicitly.
"""
import argparse
from collections import Counter, defaultdict
import csv
import hashlib
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location("archive_intake", Path(__file__).with_name("inspect_archives.py"))
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)

BATCH_ONE = (
    "floor_reference_9b7d9a17_r01", "fixed_floor_display_roi_fix_r01", "floor_comparison_live_tail_r01",
    "floor_reference_b559e424_r01", "upper_support_capture_analysis_r01", "floor_support_final_audit_r01",
    "upper_support_live_r01", "upper_support_comparator_r01", "report_assets", "floor_df33e833_multidistance_r01",
    "floor_df33e833_diagnosis_r01", "floor_reference_df33e833_r01", "floor_comparison_df33e833_live_r01",
    "upper_support_capture_r01")
BATCH_TWO = ("floor_support_final_audit_r01", "upper_support_live_r01", "upper_support_comparator_r01",
             "report_assets", "floor_df33e833_multidistance_r01")
BATCH_THREE = ("floor_df33e833_diagnosis_r01", "floor_reference_df33e833_r01",
               "floor_comparison_df33e833_live_r01", "upper_support_capture_r01")


def image_role(row, native_sha):
    if row["kind"] == "native_decoded_camera_png_candidate":
        return "native_camera_png"
    if row["kind"] == "synthetic_image_NOT_camera_evidence":
        return "synthetic_test_image"
    if row["kind"] != "other_image_requires_provenance":
        return row["kind"]
    if row["member"] == "report_assets/upper_support_b559e424_f035562.png" and row["sha256"] in native_sha:
        return "native_camera_png_byte_copy"
    if row["member"] in ("report_assets/fixed_floor_comparison_gui_df33e833_f019541.png",
                          "report_assets/fixed_floor_comparison_terminal_df33e833.png"):
        return "user_gui_or_terminal_screenshot"
    known_graphs = {
        "upper_support_capture_analysis_r01/detail_r02/live_comparison.png",
        "upper_support_capture_analysis_r01/detail_r02/recovered_event.png",
        "floor_support_final_audit_r01/results_r03/paper_height_consistency.png",
        "floor_support_final_audit_r01/results_r03/session_distances.png",
        "report_assets/upper_support_b559e424_live_comparison.png",
        "report_assets/fixed_floor_df33e833_live_stability.png",
        "report_assets/fixed_floor_df33e833_multidistance.png",
        "floor_df33e833_multidistance_r01/results_r01/distance_comparison.png",
        "floor_df33e833_diagnosis_r01/results_r01/geometry_sensitivity.png",
        "floor_comparison_df33e833_live_r01/results_r01/live_stability.png"}
    return "existing_analysis_graph" if row["member"] in known_graphs else "image_role_unresolved"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.output_dir.exists():
        raise ValueError("new output directory required")
    occurrence_counts = Counter(BATCH_ONE+BATCH_TWO+BATCH_THREE)
    files = [Path("/home/robo25/Downloads")/(name+".tar.xz") for name in BATCH_ONE]
    before = {str(p): audit.digest(p) for p in files}
    cache = {}; rows = []; archive_rows = []; signatures = defaultdict(list)
    for path in files:
        reference = ROOT/("recordings/2026-11-04/upper_support_capture_submission_r01"
                          if path.name == "upper_support_capture_r01.tar.xz" else "Experimental_results/2026-11-04")
        members = audit.inspect_archive(path, reference, cache)
        rows += members
        archive_rows.append(dict(archive=path.name, occurrences_in_messages=occurrence_counts[path.name[:-7]],
                                 archive_sha256=before[str(path)], regular_members=len(members),
                                 same_existing=sum(r["relation"] == "same_as_existing_file" for r in members),
                                 video_candidates=sum(r["kind"] == "video_candidate" for r in members)))
        signature = tuple(sorted((r["member"], r["size"], r["sha256"]) for r in members))
        signatures[hashlib.sha256(json.dumps(signature).encode()).hexdigest()].append(path.name)
    native_sha = {r["sha256"] for r in rows if r["kind"] == "native_decoded_camera_png_candidate"}
    for row in rows:
        row["evidence_role"] = image_role(row, native_sha)
    by_hash = defaultdict(list)
    for row in rows:
        by_hash[row["sha256"]].append(dict(archive=row["archive"], member=row["member"], role=row["evidence_role"]))
    duplicates = [{"sha256": sha, "occurrences": values} for sha, values in by_hash.items() if len(values) > 1]
    inputs = dict(before)
    for path in (Path(__file__).resolve(), Path(SPEC.origin), ROOT/"Experimental_results/2026-11-04/report_assets/README.md"):
        inputs[str(path.relative_to(ROOT))] = audit.digest(path)
    def resolve(path):
        return Path(path) if Path(path).is_absolute() else ROOT/path
    checks = dict(input_archives_and_code_unchanged=all(audit.digest(resolve(p)) == sha for p, sha in inputs.items()),
                  existing_reference_files_unchanged=all(audit.digest(p) == sha for p, sha in cache.items()),
                  every_member_matches_existing=all(r["relation"] == "same_as_existing_file" for r in rows),
                  all_image_roles_resolved=all(r["evidence_role"] != "image_role_unresolved" for r in rows),
                  all_current_batch_paths_inspected=len(archive_rows) == len(occurrence_counts) == 14)
    args.output_dir.mkdir(parents=True, exist_ok=False)
    for filename, data in (("archive_members.csv", rows), ("archive_summary.csv", archive_rows)):
        with (args.output_dir/filename).open("x", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(data[0]), lineterminator="\n")
            writer.writeheader(); writer.writerows(data)
    roles = Counter(r["evidence_role"] for r in rows)
    summary = dict(status="COMPLETE_READ_ONLY_BATCH_AUDIT" if all(checks.values()) else "REQUIRES_FURTHER_REVIEW",
                   checks=checks, attachments_in_messages=sum(occurrence_counts.values()), unique_archive_paths=len(files),
                   repeated_names_in_messages={name+".tar.xz": count for name, count in occurrence_counts.items() if count > 1},
                   historical_upload_versions_separately_accessible=False,
                   archives_with_identical_member_contents=[g for g in signatures.values() if len(g) > 1],
                   regular_member_occurrences=len(rows), member_roles=dict(roles),
                   unique_native_camera_png_contents=len(native_sha),
                   raw_image_copy_matches_native=roles["native_camera_png_byte_copy"] == 1,
                   video_candidates=[r["member"] for r in rows if r["kind"] == "video_candidate"],
                   changed_or_new_members=[r for r in rows if r["relation"] != "same_as_existing_file"],
                   duplicate_member_content_groups=duplicates,
                   source_sha256=inputs, existing_file_sha256={str(p.relative_to(ROOT)): sha for p,sha in cache.items()},
                   archives_extracted=False, attached_code_or_instructions_executed=False,
                   original_images_modified=False, runtime_changed=False,
                   new_independent_physical_reference_found=False, usable_for_ffb=False)
    with (args.output_dir/"summary.json").open("x") as stream:
        json.dump(summary, stream, indent=2, ensure_ascii=False, allow_nan=False); stream.write("\n")
    print(json.dumps({k:v for k,v in summary.items() if k not in
                     ("source_sha256", "existing_file_sha256", "duplicate_member_content_groups")}, indent=2))
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
