"""Read-only archive inventory; never extract/execute attached documents."""
import argparse
from collections import Counter
import csv
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))
from cone_distance_core import digest

ARCHIVES = (
    "upper_support_capture_r01 (1).tar.xz", "upper_support_capture_r01.tar.xz",
    "floor_reference_9b7d9a17_r01.tar.xz", "floor_comparison_live_tail_r01.tar.xz",
    "fixed_floor_display_roi_fix_r01.tar.xz")


def safe_member_name(name):
    p = PurePosixPath(name)
    if p.is_absolute() or ".." in p.parts or "\\" in name or not p.parts:
        raise ValueError("unsafe archive member path")
    return p


def classify(name):
    p = safe_member_name(name)
    if p.suffix.lower() in (".avi", ".mp4", ".mkv", ".mov", ".webm", ".mjpeg", ".mjpg"):
        return "video_candidate"
    if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".bmp"):
        if "synthetic" in name.lower():
            return "synthetic_image_NOT_camera_evidence"
        if re.fullmatch(r"decoded_[A-Za-z0-9_-]+_f[0-9]+\.png", p.name):
            return "native_decoded_camera_png_candidate"
        return "other_image_requires_provenance"
    if p.suffix == ".jsonl":
        return "structured_log_NOT_video"
    return "metadata_code_report_or_resource"


def stream_digest(stream):
    h = hashlib.sha256()
    for block in iter(lambda: stream.read(1024*1024), b""):
        h.update(block)
    return h.hexdigest()


def inspect_archive(path, reference_root, cache):
    """Match regular member bytes to an existing local file, not tar headers."""
    rows = []; names = set()
    with tarfile.open(path, mode="r:xz") as archive:
        for member in archive:
            relative = safe_member_name(member.name)
            if member.isdir():
                continue
            if not member.isfile():
                raise ValueError("nonregular archive member refused: " + member.name)
            if member.name in names:
                raise ValueError("duplicate archive member refused: " + member.name)
            names.add(member.name)
            if member.size > 1024*1024*1024:
                raise ValueError("oversized member refused")
            with archive.extractfile(member) as stream:
                sha = stream_digest(stream)
            local = reference_root.joinpath(*relative.parts)
            local.resolve().relative_to(reference_root.resolve())
            if local.is_symlink():
                raise ValueError("local comparison symlink refused")
            if local.is_file():
                if local not in cache:
                    cache[local] = digest(local)
                local_sha = cache[local]
                relation = "same_as_existing_file" if local_sha == sha else "different_from_existing_file"
            else:
                local_sha = None; relation = "not_in_existing_target_folder"
            rows.append(dict(archive=path.name, member=member.name, size=member.size, sha256=sha,
                             kind=classify(member.name), relation=relation,
                             existing_path=str(local.relative_to(ROOT)) if local_sha is not None else None,
                             existing_sha256=local_sha))
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.output_dir.exists():
        raise ValueError("new output directory required")
    paths = [Path("/home/robo25/Downloads") / name for name in ARCHIVES]
    initial = {str(p): digest(p) for p in paths}
    cache = {}; all_rows = []; summaries = []
    for path in paths:
        reference = (ROOT / "recordings/2026-11-04/upper_support_capture_submission_r01"
                     if path.name.startswith("upper_support_capture_r01") else ROOT / "Experimental_results/2026-11-04")
        rows = inspect_archive(path, reference, cache)
        all_rows += rows
        summaries.append(dict(archive=path.name, archive_sha256=initial[str(path)],
                              regular_members=len(rows), member_kinds=dict(Counter(r["kind"] for r in rows)),
                              existing_relations=dict(Counter(r["relation"] for r in rows))))
    upper = [[(r["member"], r["sha256"]) for r in all_rows if r["archive"] == name] for name in ARCHIVES[:2]]
    images = [r for r in all_rows if r["kind"] in ("native_decoded_camera_png_candidate", "other_image_requires_provenance")]
    new_images = [r for r in images if r["relation"] != "same_as_existing_file"]
    checks = dict(archive_bytes_unchanged=all(digest(p) == sha for p, sha in initial.items()),
                  existing_files_unchanged=all(digest(p) == sha for p, sha in cache.items()),
                  no_files_extracted=True, no_attached_code_executed=True, no_images_modified=True)
    if not all(checks.values()):
        raise ValueError("input changed during inspection")
    args.output_dir.mkdir(parents=True, exist_ok=False)
    with (args.output_dir / "archive_members.csv").open("x", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(all_rows[0]), lineterminator="\n")
        writer.writeheader(); writer.writerows(all_rows)
    output = dict(status="COMPLETE_ARCHIVE_REFERENCE_INVENTORY_ONLY", checks=checks,
                  archives=summaries, upper_archives_regular_member_contents_identical=sorted(upper[0]) == sorted(upper[1]),
                  video_candidates=[r for r in all_rows if r["kind"] == "video_candidate"],
                  camera_png_member_occurrences=len(images), unique_camera_png_sha256=len({r["sha256"] for r in images}),
                  new_or_changed_camera_images=new_images, source_sha256=dict(initial, **{str(Path(__file__).relative_to(ROOT)): digest(__file__)}),
                  compared_existing_sha256={str(p.relative_to(ROOT)): sha for p, sha in cache.items()},
                  instructions_in_attachments_followed=False, runtime_changed=False, usable_for_ffb=False)
    with (args.output_dir / "summary.json").open("x") as stream:
        json.dump(output, stream, indent=2, ensure_ascii=False, allow_nan=False); stream.write("\n")
    print(json.dumps({k:v for k,v in output.items() if k not in ("source_sha256", "compared_existing_sha256")}, indent=2))


if __name__ == "__main__":
    main()
