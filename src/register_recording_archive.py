#!/usr/bin/env python3
"""Validate a recording archive and register it in the Git-tracked manifest."""

from __future__ import annotations

import argparse
import csv
import hashlib
import lzma
import re
import tarfile
from datetime import datetime, timezone
from pathlib import Path


REPOSITORY_DIR = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = (
    REPOSITORY_DIR / "Experimental_results" / "recording_archive_manifest.csv"
)
MANIFEST_FIELDS = [
    "dataset_id",
    "captured_date",
    "experiment_stage",
    "archive_filename",
    "size_bytes",
    "sha256",
    "source_host",
    "source_path",
    "drive_path",
    "uploaded_at_utc",
    "download_verified_at_utc",
    "integrity_status",
    "archive_members",
    "notes",
]
DATASET_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


def validate_dataset_id(dataset_id):
    if not DATASET_ID_PATTERN.fullmatch(dataset_id):
        raise ValueError(
            "dataset_id must contain only lowercase ASCII letters, digits, '.', '_' or '-'"
        )


def sha256_file(path, chunk_size=1024 * 1024):
    digest = hashlib.sha256()
    with Path(path).open("rb") as archive_file:
        while chunk := archive_file.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def inspect_tar_xz(path, check_contents=True):
    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Archive does not exist: {path}")
    if not path.name.endswith(".tar.xz"):
        raise ValueError(f"Archive must have a .tar.xz suffix: {path}")

    member_count = ""
    integrity_status = "sha256_only"
    if check_contents:
        try:
            with tarfile.open(path, mode="r:xz") as archive:
                member_count = sum(1 for _ in archive)
        except (tarfile.TarError, lzma.LZMAError, EOFError) as error:
            raise ValueError(f"Invalid or truncated tar.xz archive: {path}: {error}") from error
        integrity_status = "tar_xz_pass"
    return {
        "archive_filename": path.name,
        "size_bytes": path.stat().st_size,
        "sha256": sha256_file(path),
        "source_path": str(path),
        "integrity_status": integrity_status,
        "archive_members": member_count,
    }


def load_manifest(path):
    path = Path(path)
    if not path.exists():
        return []
    with path.open(newline="") as manifest_file:
        reader = csv.DictReader(manifest_file)
        if reader.fieldnames != MANIFEST_FIELDS:
            raise ValueError(
                f"Unexpected manifest columns in {path}: {reader.fieldnames}"
            )
        return list(reader)


def write_manifest(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as manifest_file:
        writer = csv.DictWriter(
            manifest_file, fieldnames=MANIFEST_FIELDS, lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(sorted(rows, key=lambda row: row["dataset_id"]))


def register_archive(
    manifest_path,
    dataset_id,
    archive_path,
    captured_date="",
    experiment_stage="",
    source_host="matsunuc",
    drive_path="",
    notes="",
    check_contents=True,
):
    validate_dataset_id(dataset_id)
    inspected = inspect_tar_xz(archive_path, check_contents=check_contents)
    rows = load_manifest(manifest_path)
    existing = next(
        (row for row in rows if row["dataset_id"] == dataset_id), None
    )
    if existing is not None and existing["archive_filename"] not in {
        "",
        inspected["archive_filename"],
    }:
        raise ValueError(
            f"dataset_id {dataset_id!r} is already assigned to "
            f"{existing['archive_filename']!r}"
        )

    record = dict.fromkeys(MANIFEST_FIELDS, "")
    if existing is not None:
        record.update(existing)
    record.update(inspected)
    record["dataset_id"] = dataset_id
    record["source_host"] = source_host
    for key, value in (
        ("captured_date", captured_date),
        ("experiment_stage", experiment_stage),
        ("drive_path", drive_path),
        ("notes", notes),
    ):
        if value:
            record[key] = value
    if drive_path and not record["uploaded_at_utc"]:
        record["uploaded_at_utc"] = datetime.now(timezone.utc).isoformat(
            timespec="seconds"
        )

    if existing is None:
        rows.append(record)
    else:
        rows[rows.index(existing)] = record
    write_manifest(manifest_path, rows)
    return record


def main():
    parser = argparse.ArgumentParser(
        description="Validate and register an immutable recording tar.xz archive"
    )
    parser.add_argument("--dataset-id", required=True)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--captured-date", default="")
    parser.add_argument("--experiment-stage", default="")
    parser.add_argument("--source-host", default="matsunuc")
    parser.add_argument("--drive-path", default="")
    parser.add_argument("--notes", default="")
    parser.add_argument(
        "--skip-content-check",
        action="store_true",
        help="calculate SHA-256 without fully validating the tar.xz stream",
    )
    args = parser.parse_args()

    record = register_archive(
        args.manifest,
        args.dataset_id,
        args.archive,
        captured_date=args.captured_date,
        experiment_stage=args.experiment_stage,
        source_host=args.source_host,
        drive_path=args.drive_path,
        notes=args.notes,
        check_contents=not args.skip_content_check,
    )
    print(f"Dataset: {record['dataset_id']}")
    print(f"Archive: {record['source_path']}")
    print(f"Size: {record['size_bytes']} bytes")
    print(f"SHA-256: {record['sha256']}")
    print(f"Integrity: {record['integrity_status']}")
    print(f"Manifest: {args.manifest.resolve()}")


if __name__ == "__main__":
    main()
