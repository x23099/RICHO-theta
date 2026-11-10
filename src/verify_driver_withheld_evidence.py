"""Offline validation of indexed native evidence; never follows recorded paths."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import struct
from types import SimpleNamespace

from driver_motion_protocol import checked_result, compact_result
from driver_withheld_evidence import MAX_LINE, TARGET_REASON
from report_driver_motion_logs import reject_constant, unique_object


def parse_json(payload):
    return json.loads(payload, parse_constant=reject_constant, object_pairs_hook=unique_object)


def read_regular(path, maximum, *, empty=False):
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    with os.fdopen(fd, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > maximum:
            raise ValueError("bounded regular evidence file required")
        data = stream.read(maximum+1)
    if len(data) > maximum or not empty and not data:
        raise ValueError("invalid evidence file size")
    return data


def verify(directory, source_log=None):
    import cv2
    import numpy as np
    directory = Path(directory)
    index_bytes = read_regular(directory/"evidence_index.jsonl", 256*1024, empty=True)
    lines = index_bytes.splitlines(keepends=True)
    truncated = bool(lines and not lines[-1].endswith(b"\n"))
    if truncated:
        lines.pop()  # Uncommitted final index line is never used as evidence.
    if len(lines) > 100:
        raise ValueError("too many evidence records")
    seen, hashes, indexed_files = set(), {}, set()
    verified_bytes = 0
    for line in lines:
        item = parse_json(line)
        session, number = item.get("session"), item.get("frame")
        if (item.get("schema") != "driver_withheld_evidence_index_v1"
                or not isinstance(session, str) or not re.fullmatch("[0-9a-f]{32}", session)
                or type(number) is not int or number < 1 or (session, number) in seen):
            raise ValueError("invalid or duplicate indexed frame")
        seen.add((session, number))
        stem = f"decoded_{session}_f{number:06d}"
        if item.get("image_file") != stem+".png" or item.get("sidecar_file") != stem+".json":
            raise ValueError("evidence filename must match session/frame")
        png = read_regular(directory/item["image_file"], 1280*720*3+65536)
        sidecar_bytes = read_regular(directory/item["sidecar_file"], MAX_LINE+16384)
        if (hashlib.sha256(png).hexdigest() != item.get("png_sha256")
                or hashlib.sha256(sidecar_bytes).hexdigest() != item.get("sidecar_sha256")):
            raise ValueError("PNG or sidecar SHA mismatch")
        meta = parse_json(sidecar_bytes)
        if (meta.get("schema") != "driver_withheld_frame_evidence_v1"
                or meta.get("session") != session or meta.get("frame") != number
                or meta.get("image_file") != item["image_file"] or meta.get("image_modified") is not False
                or meta.get("width") != 1280 or meta.get("height") != 720
                or meta.get("channels") != "BGR8"
                or meta.get("layout") != "dual_fisheye_front_left_unremapped"
                or any(meta.get(k) is not False for k in ("physical_metric_verified", "controlling_distance", "usable_for_ffb"))
                or meta.get("png_sha256") != item["png_sha256"]
                or meta.get("source_log_line_sha256") != item.get("source_log_line_sha256")):
            raise ValueError("native sidecar metadata mismatch")
        measurement = meta["measurement"]
        identity = SimpleNamespace(session=session, sequence=number, received_at=meta["source_time_sec"])
        checked_result(compact_result(measurement), identity)
        if (measurement["distance_available"] or measurement["reason"] != TARGET_REASON
                or meta.get("reason") != TARGET_REASON or item.get("reason") != TARGET_REASON):
            raise ValueError("not an eligible withheld frame")
        if png[:8] != b"\x89PNG\r\n\x1a\n" or len(png) < 24 or struct.unpack(">II", png[16:24]) != (1280, 720):
            raise ValueError("native PNG dimensions required")
        pixels = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_COLOR)
        if pixels is None or pixels.shape != (720, 1280, 3) or hashlib.sha256(pixels.tobytes()).hexdigest() != meta.get("decoded_bgr_sha256"):
            raise ValueError("decoded native BGR pixels mismatch")
        sha = item["source_log_line_sha256"]
        if not isinstance(sha, str) or not re.fullmatch("[0-9a-f]{64}", sha) or sha in hashes:
            raise ValueError("unique exact source log line SHA required")
        hashes[sha] = measurement
        verified_bytes += len(png)+len(sidecar_bytes)
        indexed_files.update((item["image_file"], item["sidecar_file"]))
    matched = set()
    if source_log is not None:
        # Only the user-supplied path is read, never meta['source_log_file'].
        fd = os.open(source_log, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
        with os.fdopen(fd, "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise ValueError("regular source log required")
            while True:
                line = stream.readline(MAX_LINE+1)
                if not line:
                    break
                if len(line) > MAX_LINE or not line.endswith(b"\n"):
                    raise ValueError("bounded complete source log lines required")
                sha = hashlib.sha256(line).hexdigest()
                if sha in hashes:
                    if parse_json(line) != hashes[sha]:
                        raise ValueError("source log content mismatch")
                    matched.add(sha)
        if matched != set(hashes):
            raise ValueError("indexed evidence not found in specified measurement log")
    status_path = directory/"evidence_status.json"
    status = parse_json(read_regular(status_path, 16384)) if status_path.exists() else None
    complete = (status is not None and status.get("shutdown_complete") is True and not truncated
                and status.get("saved") == len(seen) and status.get("png_and_sidecar_bytes") == verified_bytes)
    ignored = sorted(p.name for p in directory.iterdir() if p.name not in indexed_files
                     and p.name not in ("evidence_index.jsonl", "evidence_status.json"))
    complete = complete and not ignored
    return dict(schema="driver_withheld_evidence_verification_v1", verified_pairs=len(seen),
        source_log_checked=source_log is not None, source_log_matched_pairs=len(matched),
        capture_shutdown_complete=complete, incomplete_index_tail_ignored=truncated,
        nonindexed_files_NOT_verified=ignored, recorder_status=status,
        physical_metric_verified=False, usable_for_control=False)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--source-log", type=Path)
    args = parser.parse_args(argv)
    print(json.dumps(verify(args.input_dir, args.source_log), indent=2))


if __name__ == "__main__":
    main()
