#!/usr/bin/env python3
"""Run registered recording archives as a reproducible regression suite."""

from __future__ import annotations

import argparse
import csv
import json
import sys
import tarfile
from pathlib import Path

from analyze_field_recording import run_analysis
from register_recording_archive import load_manifest, sha256_file


REPOSITORY_DIR = Path(__file__).resolve().parents[1]
DEFAULT_ARCHIVE_MANIFEST = (
    REPOSITORY_DIR / "Experimental_results" / "recording_archive_manifest.csv"
)
DEFAULT_SUITE = (
    REPOSITORY_DIR / "Experimental_results" / "recording_regression_suite.csv"
)
SUITE_FIELDS = [
    "dataset_id",
    "enabled",
    "config_path",
    "labels_path",
    "requirements_path",
    "expected_status",
    "expected_sessions",
    "expected_gate_sessions",
    "expected_gate_pass_sessions",
    "expected_occlusion_events",
    "expected_track_expired_events",
    "expected_reacquired_events",
    "notes",
]
RESULT_FIELDS = [
    "dataset_id",
    "archive_path",
    "sha256_match",
    "expected_status",
    "actual_status",
    "expected_sessions",
    "actual_sessions",
    "expected_gate_sessions",
    "actual_gate_sessions",
    "expected_gate_pass_sessions",
    "actual_gate_pass_sessions",
    "expected_occlusion_events",
    "actual_occlusion_events",
    "expected_track_expired_events",
    "actual_track_expired_events",
    "expected_reacquired_events",
    "actual_reacquired_events",
    "decision",
    "reasons",
    "report_path",
]
VALID_EXPECTED_STATUSES = {"PASS", "FAIL", "DIAGNOSTIC"}


def _write_rows(path: Path, fields, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as output_file:
        writer = csv.DictWriter(output_file, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def load_regression_suite(path: Path) -> list[dict]:
    with Path(path).open(newline="") as input_file:
        reader = csv.DictReader(input_file)
        if reader.fieldnames != SUITE_FIELDS:
            raise ValueError(
                f"Unexpected regression suite columns in {path}: "
                f"{reader.fieldnames}; expected {SUITE_FIELDS}"
            )
        rows = list(reader)

    dataset_ids = [row["dataset_id"].strip() for row in rows]
    if not rows:
        raise ValueError("regression suite contains no datasets")
    if any(not dataset_id for dataset_id in dataset_ids):
        raise ValueError("regression suite contains an empty dataset_id")
    if len(set(dataset_ids)) != len(dataset_ids):
        raise ValueError("regression suite contains duplicate dataset_id values")

    for row in rows:
        row["dataset_id"] = row["dataset_id"].strip()
        row["enabled"] = row["enabled"].strip()
        row["expected_status"] = row["expected_status"].strip().upper()
        if row["enabled"] not in {"0", "1"}:
            raise ValueError(
                f"{row['dataset_id']}: enabled must be 0 or 1"
            )
        if row["expected_status"] not in VALID_EXPECTED_STATUSES:
            raise ValueError(
                f"{row['dataset_id']}: invalid expected_status "
                f"{row['expected_status']!r}"
            )
        integer_fields = (
            "expected_sessions",
            "expected_gate_sessions",
            "expected_gate_pass_sessions",
            "expected_occlusion_events",
            "expected_track_expired_events",
            "expected_reacquired_events",
        )
        for field in integer_fields:
            try:
                value = int(row[field])
            except (TypeError, ValueError) as error:
                raise ValueError(
                    f"{row['dataset_id']}: {field} must be an integer"
                ) from error
            minimum = 1 if field == "expected_sessions" else 0
            if value < minimum:
                raise ValueError(
                    f"{row['dataset_id']}: {field} must be at least {minimum}"
                )
            row[field] = value
    return rows


def select_datasets(rows: list[dict], selected_ids: list[str]) -> list[dict]:
    enabled = [row for row in rows if row["enabled"] == "1"]
    if not selected_ids:
        return enabled
    requested = set(selected_ids)
    known = {row["dataset_id"] for row in rows}
    unknown = sorted(requested - known)
    if unknown:
        raise ValueError(f"unknown dataset_id: {unknown[0]}")
    return [row for row in rows if row["dataset_id"] in requested]


def resolve_repository_path(value: str, field: str, optional: bool = False):
    value = value.strip()
    if not value and optional:
        return None
    if not value:
        raise ValueError(f"{field} is required")
    relative = Path(value)
    if relative.is_absolute():
        raise ValueError(f"{field} must be repository-relative: {value}")
    resolved = (REPOSITORY_DIR / relative).resolve()
    try:
        resolved.relative_to(REPOSITORY_DIR)
    except ValueError as error:
        raise ValueError(f"{field} escapes the repository: {value}") from error
    if not resolved.is_file():
        raise FileNotFoundError(f"{field} does not exist: {resolved}")
    return resolved


def find_archive(filename: str, archive_dirs: list[Path]):
    matches = set()
    for archive_dir in archive_dirs:
        archive_dir = archive_dir.expanduser().resolve()
        if not archive_dir.is_dir():
            raise FileNotFoundError(f"archive directory does not exist: {archive_dir}")
        direct = archive_dir / filename
        if direct.is_file():
            matches.add(direct.resolve())
            continue
        matches.update(path.resolve() for path in archive_dir.rglob(filename))
    if not matches:
        return None
    if len(matches) > 1:
        rendered = ", ".join(str(path) for path in sorted(matches))
        raise ValueError(f"archive filename is ambiguous: {filename}: {rendered}")
    return next(iter(matches))


def _load_csv_rows(path: Path) -> list[dict]:
    with path.open(newline="") as input_file:
        return list(csv.DictReader(input_file))


def _base_result(dataset: dict) -> dict:
    return {
        "dataset_id": dataset["dataset_id"],
        "archive_path": "",
        "sha256_match": "",
        "expected_status": dataset["expected_status"],
        "actual_status": "",
        "expected_sessions": dataset["expected_sessions"],
        "actual_sessions": "",
        "expected_gate_sessions": dataset["expected_gate_sessions"],
        "actual_gate_sessions": "",
        "expected_gate_pass_sessions": dataset["expected_gate_pass_sessions"],
        "actual_gate_pass_sessions": "",
        "expected_occlusion_events": dataset["expected_occlusion_events"],
        "actual_occlusion_events": "",
        "expected_track_expired_events": dataset[
            "expected_track_expired_events"
        ],
        "actual_track_expired_events": "",
        "expected_reacquired_events": dataset["expected_reacquired_events"],
        "actual_reacquired_events": "",
        "decision": "FAIL",
        "reasons": "",
        "report_path": "",
    }


def run_dataset(
    dataset: dict,
    archive_record: dict,
    archive_dirs: list[Path],
    output_dir: Path,
    overwrite: bool,
    allow_missing: bool,
    analysis_runner=run_analysis,
    hash_function=sha256_file,
) -> dict:
    result = _base_result(dataset)
    archive_filename = archive_record["archive_filename"].strip()
    expected_sha256 = archive_record["sha256"].strip().lower()
    if not archive_filename or not expected_sha256:
        result["reasons"] = "archive manifest lacks filename or SHA-256"
        return result

    archive_path = find_archive(archive_filename, archive_dirs)
    if archive_path is None:
        result["decision"] = "SKIP" if allow_missing else "FAIL"
        result["reasons"] = f"archive not found: {archive_filename}"
        return result
    result["archive_path"] = str(archive_path)

    reasons = []
    expected_size = archive_record["size_bytes"].strip()
    if expected_size and archive_path.stat().st_size != int(expected_size):
        reasons.append(
            f"size={archive_path.stat().st_size} != expected={expected_size}"
        )
    actual_sha256 = hash_function(archive_path).lower()
    sha256_match = actual_sha256 == expected_sha256
    result["sha256_match"] = int(sha256_match)
    if not sha256_match:
        reasons.append(
            f"SHA-256={actual_sha256} != expected={expected_sha256}"
        )
    if reasons:
        result["reasons"] = "; ".join(reasons)
        return result

    config_path = resolve_repository_path(dataset["config_path"], "config_path")
    labels_path = resolve_repository_path(
        dataset["labels_path"], "labels_path", optional=True
    )
    requirements_path = resolve_repository_path(
        dataset["requirements_path"], "requirements_path"
    )
    dataset_output = output_dir / dataset["dataset_id"]
    analysis_args = argparse.Namespace(
        input=archive_path,
        output_dir=dataset_output,
        config=config_path,
        labels=labels_path,
        requirements=requirements_path,
        threshold=None,
        moving_threshold_mps=0.03,
        max_extracted_gb=50.0,
        overwrite=overwrite,
    )
    actual_status = analysis_runner(analysis_args)
    result["actual_status"] = actual_status
    result["report_path"] = str(dataset_output / "analysis_report.md")

    inventory_rows = _load_csv_rows(dataset_output / "archive_inventory.csv")
    live_rows = _load_csv_rows(dataset_output / "live_summary.csv")
    gate_rows = _load_csv_rows(dataset_output / "gate_regression.csv")
    with config_path.open() as config_file:
        selected_gate_mode = json.load(config_file).get(
            "blue_observation_area_distance_mode", "forward_z"
        )
    selected_gate_rows = [
        row
        for row in gate_rows
        if row["normalization_mode"] == selected_gate_mode
    ]
    actual_sessions = len(live_rows)
    actual_gate_sessions = len(selected_gate_rows)
    actual_gate_pass_sessions = sum(
        row["decision"] == "PASS" for row in selected_gate_rows
    )
    actual_occlusion_events = sum(
        int(row["occlusion_events"]) for row in selected_gate_rows
    )
    actual_track_expired_events = sum(
        int(row["events_track_expired"]) for row in selected_gate_rows
    )
    actual_reacquired_events = sum(
        int(row["events_reacquired"]) for row in selected_gate_rows
    )
    result["actual_sessions"] = actual_sessions
    result["actual_gate_sessions"] = actual_gate_sessions
    result["actual_gate_pass_sessions"] = actual_gate_pass_sessions
    result["actual_occlusion_events"] = actual_occlusion_events
    result["actual_track_expired_events"] = actual_track_expired_events
    result["actual_reacquired_events"] = actual_reacquired_events
    if len(inventory_rows) != 1:
        reasons.append(f"archive inventory rows={len(inventory_rows)} != 1")
    elif inventory_rows[0]["sha256"].lower() != expected_sha256:
        reasons.append("analysis inventory SHA-256 differs from manifest")
    if actual_status != dataset["expected_status"]:
        reasons.append(
            f"status={actual_status} != expected={dataset['expected_status']}"
        )
    if actual_sessions != dataset["expected_sessions"]:
        reasons.append(
            f"sessions={actual_sessions} != expected={dataset['expected_sessions']}"
        )
    comparisons = (
        ("gate_sessions", actual_gate_sessions, dataset["expected_gate_sessions"]),
        (
            "gate_pass_sessions",
            actual_gate_pass_sessions,
            dataset["expected_gate_pass_sessions"],
        ),
        (
            "occlusion_events",
            actual_occlusion_events,
            dataset["expected_occlusion_events"],
        ),
        (
            "track_expired_events",
            actual_track_expired_events,
            dataset["expected_track_expired_events"],
        ),
        (
            "reacquired_events",
            actual_reacquired_events,
            dataset["expected_reacquired_events"],
        ),
    )
    for name, actual, expected in comparisons:
        if actual != expected:
            reasons.append(f"{name}={actual} != expected={expected}")
    result["decision"] = "FAIL" if reasons else "PASS"
    result["reasons"] = "; ".join(reasons)
    return result


def build_report(results: list[dict]) -> str:
    failed = [row for row in results if row["decision"] == "FAIL"]
    skipped = [row for row in results if row["decision"] == "SKIP"]
    overall = "FAIL" if failed else "INCOMPLETE" if skipped else "PASS"
    lines = [
        "# 録画回帰試験レポート",
        "",
        f"総合判定: **{overall}**",
        "",
        f"- 登録データセット: {len(results)}",
        f"- PASS: {sum(row['decision'] == 'PASS' for row in results)}",
        f"- FAIL: {len(failed)}",
        f"- SKIP: {len(skipped)}",
        "",
        "| dataset | SHA-256 | 解析判定 | session | gate PASS | 遮蔽失効/再捕捉 | 回帰 |",
        "|---|---|---|---:|---:|---:|---|",
    ]
    for row in results:
        sha = "PASS" if str(row["sha256_match"]) == "1" else "―"
        sessions = row["actual_sessions"] if row["actual_sessions"] != "" else "―"
        gate_pass = (
            f"{row['actual_gate_pass_sessions']}/{row['actual_gate_sessions']}"
            if row["actual_gate_sessions"] != ""
            else "―"
        )
        events = (
            f"{row['actual_track_expired_events']}/"
            f"{row['actual_reacquired_events']}"
            if row["actual_track_expired_events"] != ""
            else "―"
        )
        lines.append(
            f"| {row['dataset_id']} | {sha} | "
            f"{row['actual_status'] or '―'} | {sessions} | {gate_pass} | "
            f"{events} | {row['decision']} |"
        )
    differences = [row for row in results if row["reasons"]]
    if differences:
        lines.extend(["", "## 差分または未実行", ""])
    for row in differences:
        if row["reasons"]:
            lines.append(f"- `{row['dataset_id']}`: {row['reasons']}")
    lines.append("")
    return "\n".join(lines)


def run_suite(args: argparse.Namespace) -> list[dict]:
    suite_rows = select_datasets(
        load_regression_suite(args.suite), args.dataset_id
    )
    if not suite_rows:
        raise ValueError("no regression datasets selected")
    archive_rows = {
        row["dataset_id"]: row for row in load_manifest(args.archive_manifest)
    }
    output_dir = args.output_dir.expanduser().resolve()
    summary_path = output_dir / "regression_summary.csv"
    report_path = output_dir / "recording_regression_report.md"
    if not args.overwrite:
        existing = next(
            (path for path in (summary_path, report_path) if path.exists()), None
        )
        if existing:
            raise FileExistsError(
                f"regression output already exists; use --overwrite: {existing}"
            )
    output_dir.mkdir(parents=True, exist_ok=True)

    results = []
    for index, dataset in enumerate(suite_rows, start=1):
        dataset_id = dataset["dataset_id"]
        print(f"[{index}/{len(suite_rows)}] {dataset_id}", flush=True)
        archive_record = archive_rows.get(dataset_id)
        if archive_record is None:
            result = _base_result(dataset)
            result["reasons"] = "dataset is absent from archive manifest"
        else:
            try:
                result = run_dataset(
                    dataset,
                    archive_record,
                    args.archive_dir,
                    output_dir,
                    args.overwrite,
                    args.allow_missing,
                )
            except (
                FileNotFoundError,
                OSError,
                ValueError,
                KeyError,
                tarfile.TarError,
            ) as error:
                result = _base_result(dataset)
                result["reasons"] = str(error)
        results.append(result)
        print(f"  {result['decision']}: {result['reasons'] or 'matched'}", flush=True)

    _write_rows(summary_path, RESULT_FIELDS, results)
    report_path.write_text(build_report(results), encoding="utf-8")
    print(f"Summary saved: {summary_path}")
    print(f"Report saved: {report_path}")
    return results


def list_suite(args: argparse.Namespace) -> None:
    suite_rows = select_datasets(
        load_regression_suite(args.suite), args.dataset_id
    )
    archive_rows = {
        row["dataset_id"]: row for row in load_manifest(args.archive_manifest)
    }
    for dataset in suite_rows:
        archive = archive_rows.get(dataset["dataset_id"], {})
        print(
            f"{dataset['dataset_id']}\t"
            f"{archive.get('archive_filename', 'UNREGISTERED')}\t"
            f"expected={dataset['expected_status']}\t"
            f"sessions={dataset['expected_sessions']}\t"
            f"gate={dataset['expected_gate_pass_sessions']}/"
            f"{dataset['expected_gate_sessions']}"
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run Git-registered recording archives as a regression suite"
    )
    parser.add_argument("--archive-dir", type=Path, action="append", default=[])
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--suite", type=Path, default=DEFAULT_SUITE)
    parser.add_argument(
        "--archive-manifest", type=Path, default=DEFAULT_ARCHIVE_MANIFEST
    )
    parser.add_argument("--dataset-id", action="append", default=[])
    parser.add_argument("--allow-missing", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--list", action="store_true")
    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.list:
            list_suite(args)
            return 0
        if not args.archive_dir:
            parser.error("--archive-dir is required unless --list is used")
        if args.output_dir is None:
            parser.error("--output-dir is required unless --list is used")
        results = run_suite(args)
    except (FileNotFoundError, OSError, ValueError, KeyError) as error:
        parser.error(str(error))
    return 1 if any(row["decision"] == "FAIL" for row in results) else 0


if __name__ == "__main__":
    sys.exit(main())
