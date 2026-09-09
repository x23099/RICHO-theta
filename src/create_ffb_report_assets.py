#!/usr/bin/env python3
"""Create traceable FFB report graphs and one unedited camera frame."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
import tarfile
import tempfile
from pathlib import Path

os.environ.setdefault(
    "MPLCONFIGDIR",
    str(Path(tempfile.gettempdir()) / "richo-theta-matplotlib"),
)

import cv2  # noqa: E402
import matplotlib  # noqa: E402

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402


CADENCE_ORDER = ("continuous", "double", "triple")


def read_csv(path: Path) -> list[dict]:
    """Read one CSV file into dictionaries."""
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def extract_raw_frame(
    archive_path: Path,
    session: str,
    frame_number: int,
    output_path: Path,
) -> dict:
    """Save one decoded raw-video frame without drawing or resizing it."""
    if frame_number < 1:
        raise ValueError("frame_number must be one-based and positive")
    member_name = f"{session}/raw.avi"
    with tempfile.TemporaryDirectory(prefix="raw-frame-") as temp_dir:
        video_path = Path(temp_dir) / "raw.avi"
        with tarfile.open(archive_path, mode="r:xz") as archive:
            try:
                member = archive.getmember(member_name)
            except KeyError as error:
                raise ValueError(
                    f"raw video not found in archive: {member_name}"
                ) from error
            if not member.isfile():
                raise ValueError(
                    f"raw video member is not a file: {member_name}"
                )
            source = archive.extractfile(member)
            if source is None:
                raise ValueError(f"cannot read raw video: {member_name}")
            with video_path.open("wb") as destination:
                shutil.copyfileobj(source, destination)

        capture = cv2.VideoCapture(str(video_path))
        if not capture.isOpened():
            raise RuntimeError(
                f"cannot open extracted raw video: {member_name}"
            )
        source_width = int(round(capture.get(cv2.CAP_PROP_FRAME_WIDTH)))
        source_height = int(round(capture.get(cv2.CAP_PROP_FRAME_HEIGHT)))
        source_fps = float(capture.get(cv2.CAP_PROP_FPS))
        capture.set(cv2.CAP_PROP_POS_FRAMES, frame_number - 1)
        ok, frame = capture.read()
        capture.release()
        if not ok or frame is None:
            raise RuntimeError(
                f"cannot decode frame {frame_number} from {member_name}"
            )
        height, width = frame.shape[:2]
        if width != source_width or height != source_height:
            raise RuntimeError(
                "decoded frame dimensions differ from the source video"
            )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        if not cv2.imwrite(
            str(output_path),
            frame,
            [cv2.IMWRITE_PNG_COMPRESSION, 3],
        ):
            raise RuntimeError(f"failed to write PNG: {output_path}")
    return {
        "archive": str(archive_path.resolve()),
        "member": member_name,
        "session": session,
        "frame": frame_number,
        "video_time_sec": (frame_number - 1) / source_fps,
        "source_width": source_width,
        "source_height": source_height,
        "source_fps": source_fps,
        "output_width": width,
        "output_height": height,
        "output": str(output_path.resolve()),
        "transformations": [],
    }


def plot_cadence(cadence_root: Path, output_path: Path) -> dict:
    """Plot actual command magnitudes for three dry-run cadences."""
    figure, axes = plt.subplots(3, 1, figsize=(10, 6), sharex=True)
    row_counts = {}
    for axis, cadence in zip(axes, CADENCE_ORDER):
        path = cadence_root / cadence / "command_log.csv"
        rows = read_csv(path)
        if not rows:
            raise ValueError(f"empty cadence command log: {path}")
        start = float(rows[0]["send_monotonic_sec"])
        times = [float(row["send_monotonic_sec"]) - start for row in rows]
        magnitudes = [float(row["requested_magnitude"]) for row in rows]
        axis.step(times, magnitudes, where="post", linewidth=2)
        axis.set_ylabel(cadence)
        axis.set_ylim(-0.005, 0.057)
        axis.grid(True, alpha=0.3)
        row_counts[cadence] = len(rows)
    axes[-1].set_xlabel("Elapsed time [s]")
    figure.supylabel("Requested normalized magnitude")
    figure.suptitle("Collision FFB cadence commands (dry-run)")
    figure.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output_path, dpi=160)
    plt.close(figure)
    return {
        "source": str(cadence_root.resolve()),
        "row_counts": row_counts,
        "output": str(output_path.resolve()),
    }


def plot_replay(replay_root: Path, output_path: Path) -> dict:
    """Plot recorded demand and matching dry-run adapter magnitude."""
    commands = read_csv(replay_root / "replayed_commands.csv")
    statuses = read_csv(replay_root / "adapter_status.csv")
    status_by_sequence = {
        int(row["sequence"]): row
        for row in statuses
        if int(row["has_sequence"]) == 1
    }
    plotted = [row for row in commands if row["source_time_sec"] != ""]
    times = [float(row["source_time_sec"]) for row in plotted]
    requested = [
        float(row["collision_ffb_requested_magnitude"])
        for row in plotted
    ]
    applied = [
        float(
            status_by_sequence.get(
                int(row["collision_ffb_sequence"]),
                {"applied_magnitude": 0.0},
            )["applied_magnitude"]
        )
        for row in plotted
    ]
    figure, axis = plt.subplots(figsize=(10, 4.5))
    axis.plot(times, requested, label="Publisher request", linewidth=1.8)
    axis.plot(times, applied, label="Adapter applied (dry-run)", linewidth=1.8)
    axis.set_xlabel("Recorded time [s]")
    axis.set_ylabel("Normalized magnitude")
    axis.set_title("Recorded collision risk to dry-run FFB demand")
    axis.grid(True, alpha=0.3)
    axis.legend()
    figure.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(output_path, dpi=160)
    plt.close(figure)
    return {
        "source": str(replay_root.resolve()),
        "command_rows": len(plotted),
        "status_rows": len(statuses),
        "output": str(output_path.resolve()),
    }


def sha256(path: Path) -> str:
    """Return a streaming SHA-256 digest for one file."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            block = handle.read(1024 * 1024)
            if not block:
                return digest.hexdigest()
            digest.update(block)


def write_manifest(
    output_dir: Path,
    *,
    raw_metadata: dict,
    cadence_metadata: dict,
    replay_metadata: dict,
    archive_sha256: str,
) -> None:
    """Write machine-readable and human-readable asset provenance."""
    payload = {
        "raw_camera_frame": raw_metadata,
        "cadence_graph": cadence_metadata,
        "recorded_risk_graph": replay_metadata,
        "archive_sha256": archive_sha256,
    }
    (output_dir / "assets_manifest.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    raw_name = Path(raw_metadata["output"]).name
    cadence_name = Path(cadence_metadata["output"]).name
    replay_name = Path(replay_metadata["output"]).name
    replay_source = replay_metadata["source"]
    readme = f"""# 2026-09-10 日報用資料

## `{raw_name}`

- 内容: TTC WARNING開始時点付近の360度カメラ生画像
- 元録画: `{raw_metadata['archive']}`
- archive SHA-256: `{archive_sha256}`
- member: `{raw_metadata['member']}`
- frame: {raw_metadata['frame']}（1始まり）
- 動画内時刻: {raw_metadata['video_time_sec']:.3f}秒
- 解像度: {raw_metadata['output_width']}x{raw_metadata['output_height']}
- 編集: なし。注釈、crop、resize、回転、色・明るさ補正を行っていない

## `{cadence_name}`

- 内容: continuous、double、tripleの実送信command比較
- 元データ: `{cadence_metadata['source']}`以下の`command_log.csv`
- 生成: `src/create_ffb_report_assets.py --cadence-root ...`

## `{replay_name}`

- 内容: 録画済み衝突リスクの要求強度とdry-run adapter適用値
- 元データ: `{replay_source}/replayed_commands.csv`
  および`{replay_source}/adapter_status.csv`
- 生成: `src/create_ffb_report_assets.py --replay-root ...`
"""
    (output_dir / "README.md").write_text(readme, encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    """Build the report-asset command-line parser."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--session", required=True)
    parser.add_argument("--frame", type=int, required=True)
    parser.add_argument("--cadence-root", type=Path, required=True)
    parser.add_argument("--replay-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser


def main(args=None) -> int:
    """Generate three traceable assets for one work day."""
    parsed = build_parser().parse_args(args)
    output_dir = parsed.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    raw_path = output_dir / (
        f"raw_{parsed.session}_frame_{parsed.frame:06d}.png"
    )
    raw_metadata = extract_raw_frame(
        parsed.archive,
        parsed.session,
        parsed.frame,
        raw_path,
    )
    cadence_metadata = plot_cadence(
        parsed.cadence_root,
        output_dir / "ffb_cadence_dry_run.png",
    )
    replay_metadata = plot_replay(
        parsed.replay_root,
        output_dir / "recorded_risk_ffb_dry_run.png",
    )
    write_manifest(
        output_dir,
        raw_metadata=raw_metadata,
        cadence_metadata=cadence_metadata,
        replay_metadata=replay_metadata,
        archive_sha256=sha256(parsed.archive),
    )
    print(f"Assets: {output_dir.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
