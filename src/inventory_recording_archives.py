#!/usr/bin/env python3
"""Inventory recording tar.xz archives without extracting them."""

from __future__ import annotations

import argparse
import csv
import hashlib
import lzma
import tarfile
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path, PurePosixPath


OUTPUT_FIELDS = [
    "archive_filename",
    "archive_path",
    "size_bytes",
    "sha256",
    "tar_xz_status",
    "archive_members",
    "recording_sessions",
    "metadata_sessions",
    "detections_sessions",
    "raw_video_sessions",
    "complete_core_sessions",
    "session_names",
    "error",
]
CORE_FILES = {"metadata.json", "detections.csv", "raw.avi"}
RECORDING_FILES = CORE_FILES | {"bev.avi", "detection.avi"}


def sha256_file(path, chunk_size=1024 * 1024):
    digest = hashlib.sha256()
    with Path(path).open("rb") as input_file:
        while chunk := input_file.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def inspect_archive(path):
    path = Path(path).resolve()
    row = dict.fromkeys(OUTPUT_FIELDS, "")
    row.update(
        {
            "archive_filename": path.name,
            "archive_path": str(path),
            "size_bytes": path.stat().st_size,
            "sha256": sha256_file(path),
            "tar_xz_status": "FAIL",
        }
    )
    session_files = defaultdict(set)
    try:
        with tarfile.open(path, mode="r:xz") as archive:
            member_count = 0
            for member in archive:
                member_count += 1
                if not member.isfile():
                    continue
                member_path = PurePosixPath(member.name)
                if member_path.name in RECORDING_FILES:
                    session_files[member_path.parent].add(member_path.name)
    except (tarfile.TarError, lzma.LZMAError, EOFError, OSError) as error:
        row["error"] = str(error)
        return row

    recording_sessions = sorted(
        (session for session, files in session_files.items() if "raw.avi" in files),
        key=str,
    )
    row.update(
        {
            "tar_xz_status": "PASS",
            "archive_members": member_count,
            "recording_sessions": len(recording_sessions),
            "metadata_sessions": sum(
                "metadata.json" in session_files[session]
                for session in recording_sessions
            ),
            "detections_sessions": sum(
                "detections.csv" in session_files[session]
                for session in recording_sessions
            ),
            "raw_video_sessions": len(recording_sessions),
            "complete_core_sessions": sum(
                CORE_FILES <= session_files[session] for session in recording_sessions
            ),
            "session_names": ";".join(session.name for session in recording_sessions),
        }
    )
    return row


def discover_archives(inputs):
    archives = []
    for input_path in inputs:
        input_path = Path(input_path)
        if input_path.is_dir():
            archives.extend(input_path.glob("*.tar.xz"))
        elif input_path.is_file():
            archives.append(input_path)
        else:
            raise FileNotFoundError(f"Input does not exist: {input_path}")
    return sorted(set(path.resolve() for path in archives), key=lambda path: path.name)


def main():
    parser = argparse.ArgumentParser(
        description="Inventory recording tar.xz archives without extraction"
    )
    parser.add_argument("--input", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()

    archives = discover_archives(args.input)
    if not archives:
        parser.error("no .tar.xz archive was found")
    if args.workers < 1:
        parser.error("--workers must be at least 1")
    completed_rows = {}
    with ThreadPoolExecutor(max_workers=min(args.workers, len(archives))) as executor:
        futures = {
            executor.submit(inspect_archive, archive): archive for archive in archives
        }
        for index, future in enumerate(as_completed(futures), start=1):
            archive = futures[future]
            completed_rows[archive] = future.result()
            print(f"[{index}/{len(archives)}] {archive.name}", flush=True)
    rows = [completed_rows[archive] for archive in archives]

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", newline="") as output_file:
        writer = csv.DictWriter(
            output_file, fieldnames=OUTPUT_FIELDS, lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(rows)

    passed = sum(row["tar_xz_status"] == "PASS" for row in rows)
    print(f"Archives: {len(rows)}, tar.xz PASS: {passed}, FAIL: {len(rows) - passed}")
    print(f"CSV saved: {args.output.resolve()}")


if __name__ == "__main__":
    main()
