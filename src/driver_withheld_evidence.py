"""Opt-in bounded native PNG evidence. No file I/O or PNG work in offer()."""
from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import queue
import re
import threading

from driver_motion_protocol import checked_result, compact_result
from theta_rtc_frames import native_frame

TARGET_REASON = "colour_contour_reaches_roi_edge"
MAX_LINE = 1024 * 1024


@dataclass(frozen=True)
class EvidenceLimits:
    max_frames: int = 40
    max_bytes: int = 128 * 1024 * 1024
    interval_sec: float = 1.

    def __post_init__(self):
        if (type(self.max_frames) is not int or not 1 <= self.max_frames <= 100
                or type(self.max_bytes) is not int or not 1024*1024 <= self.max_bytes <= 256*1024*1024
                or type(self.interval_sec) not in (int, float) or not math.isfinite(self.interval_sec)
                or not .1 <= self.interval_sec <= 60):
            raise ValueError("evidence limits: 1..100 frames, 1..256 MiB, .1..60 sec")


def evidence_path(path, repo_root=None):
    root = (Path(repo_root) if repo_root is not None else Path(__file__).resolve().parents[1])/"recordings"
    root, path = root.resolve(), Path(path).expanduser().resolve()
    if path == root or root not in path.parents:
        raise ValueError("evidence requires a new subdirectory under repository recordings/")
    if path.exists():
        raise ValueError("new withheld-evidence directory required")
    return path


def add_evidence_arguments(parser, *, prefix=""):
    parser.add_argument("--"+prefix+"withheld-evidence-dir", type=Path, default=None,
                        help="OFF by default; native support-boundary rejection PNG/JSON under recordings/")
    parser.add_argument("--"+prefix+"withheld-evidence-max-frames", type=int, default=40)
    parser.add_argument("--"+prefix+"withheld-evidence-max-mib", type=int, default=128)
    parser.add_argument("--"+prefix+"withheld-evidence-interval-sec", type=float, default=1.)


def limits_from_args(args, *, prefix=""):
    def value(suffix):
        return getattr(args, prefix+"withheld_evidence_"+suffix)
    mib = value("max_mib")
    if type(mib) is not int:
        raise ValueError("integer evidence MiB required")
    return EvidenceLimits(value("max_frames"), mib*1024*1024, value("interval_sec"))


def _atomic_new(path, data):
    """Publish complete file without overwriting another file; index commits pair."""
    temporary = path.with_name(path.name+".part")
    with temporary.open("xb") as stream:
        stream.write(data)
    os.link(temporary, path)  # Fails rather than replacing an existing target.
    temporary.unlink()      # Only our own completed temporary hardlink.


class WithheldEvidenceRecorder:
    """One pending + one saving frame, owned immutable images from read_frame().

    Caller hands over frame and immutable exact JSONL line, never a reused
    mutable image buffer. No queue waits/copies/encodes/hashes/files in offer.
    Failure only disables evidence, never changes a measurement.
    """
    def __init__(self, directory, result_log, limits=None):
        self.directory, self.result_log = Path(directory), Path(result_log).absolute()
        self.limits = limits or EvidenceLimits()
        self.directory.mkdir(parents=True, exist_ok=False)
        self.lock = threading.Lock()
        self.pending = queue.Queue(maxsize=1)
        self.stop = threading.Event()
        self.accepted = self.saved = self.bytes_saved = 0
        self.skipped_interval = self.skipped_full = self.skipped_quota = self.skipped_other = 0
        self.skipped_budget = 0
        self.busy_drops = 0
        self.error = None
        self.last_source = None
        self.seen = set()
        self.budget_exhausted = False
        self.thread = threading.Thread(target=self._run, name="native-withheld-evidence", daemon=True)
        self.thread.start()

    def offer(self, frame, result, result_line):
        if not self.lock.acquire(blocking=False):
            self.busy_drops += 1
            return False
        try:
            if self.stop.is_set() or self.error:
                return False
            if result.get("distance_available") is not False or result.get("reason") != TARGET_REASON:
                self.skipped_other += 1
                return False
            if self.budget_exhausted or self.accepted >= self.limits.max_frames:
                self.skipped_quota += 1
                return False
            native_frame(frame.image)
            if (not isinstance(frame.session, str) or not re.fullmatch("[0-9a-f]{32}", frame.session)
                    or type(frame.sequence) is not int or frame.sequence < 1):
                raise ValueError("safe native frame identity required")
            if frame.image.flags.writeable:
                raise ValueError("immutable owned native frame required")
            scalar = checked_result(compact_result(result), frame)
            key = frame.session, frame.sequence
            if key in self.seen:
                return False
            if not isinstance(result_line, str) or len(result_line) > MAX_LINE or not result_line.endswith("\n"):
                raise ValueError("bounded exact source JSONL line required")
            if self.last_source is not None and frame.received_at-self.last_source < self.limits.interval_sec:
                self.skipped_interval += 1
                return False
            try:
                self.pending.put_nowait((frame, scalar, result_line))
            except queue.Full:
                self.skipped_full += 1
                return False
            self.seen.add(key)
            self.last_source = frame.received_at
            self.accepted += 1
            return True
        except Exception as error:
            self.error = f"{type(error).__name__}: {error}"[:1000]
            return False
        finally:
            self.lock.release()

    def snapshot(self):
        with self.lock:
            return dict(schema="driver_withheld_evidence_status_v1", enabled=True,
                accepted=self.accepted, saved=self.saved, png_and_sidecar_bytes=self.bytes_saved,
                skipped_interval=self.skipped_interval, skipped_queue_full=self.skipped_full,
                skipped_quota=self.skipped_quota, skipped_other_reason=self.skipped_other,
                skipped_after_encoding_budget=self.skipped_budget,
                tap_busy_drops=self.busy_drops, error=self.error, budget_exhausted=self.budget_exhausted,
                max_frames=self.limits.max_frames, max_png_and_sidecar_bytes=self.limits.max_bytes,
                min_interval_sec=self.limits.interval_sec, target_reason=TARGET_REASON,
                source="native_decoded_1280x720_BGR_NOT_remapped", image_files_written=self.saved > 0,
                control_modified=False, physical_metric_verified=False)

    def _status(self, done=False):
        payload = self.snapshot()
        payload.update(writer_done=done, shutdown_complete=done and payload["error"] is None
                       and payload["saved"]+payload["skipped_after_encoding_budget"] == payload["accepted"])
        temporary = self.directory/"evidence_status.json.part"
        with temporary.open("xb") as stream:
            stream.write((json.dumps(payload, indent=2)+"\n").encode())
        os.replace(temporary, self.directory/"evidence_status.json")

    def _save(self, item, index):
        import cv2
        frame, scalar, line = item
        measurement = json.loads(line)
        if checked_result(compact_result(measurement), frame) != scalar:
            raise ValueError("source JSONL line does not match offered measurement")
        ok, encoded = cv2.imencode(".png", frame.image, [cv2.IMWRITE_PNG_COMPRESSION, 1])
        if not ok:
            raise OSError("native PNG encoding failed")
        png = encoded.tobytes()
        if len(png) > 1280*720*3+65536:
            raise ValueError("unexpected PNG size")
        stem = f"decoded_{frame.session}_f{frame.sequence:06d}"
        png_name, json_name = stem+".png", stem+".json"
        meta = dict(schema="driver_withheld_frame_evidence_v1", session=frame.session, frame=frame.sequence,
            media_time_sec=frame.media_time, source_time_sec=frame.received_at, reason=scalar["reason"],
            image_file=png_name, width=1280, height=720, channels="BGR8",
            layout="dual_fisheye_front_left_unremapped", image_modified=False,
            decoded_bgr_sha256=hashlib.sha256(frame.image.tobytes()).hexdigest(),
            png_sha256=hashlib.sha256(png).hexdigest(),
            source_log_file=str(self.result_log), source_log_line_sha256=hashlib.sha256(line.encode()).hexdigest(),
            measurement=measurement, worker_withheld_NOT_proof_of_GUI_display=True,
            physical_metric_verified=False, controlling_distance=False, usable_for_ffb=False)
        sidecar = (json.dumps(meta, allow_nan=False, separators=(",", ":"))+"\n").encode()
        if len(sidecar) > MAX_LINE+16384:
            raise ValueError("oversized evidence sidecar")
        size = len(png)+len(sidecar)
        with self.lock:
            if self.bytes_saved+size > self.limits.max_bytes:
                self.budget_exhausted = True
                self.skipped_budget += 1
                return
        _atomic_new(self.directory/png_name, png)
        _atomic_new(self.directory/json_name, sidecar)
        record = dict(schema="driver_withheld_evidence_index_v1", session=frame.session,
            frame=frame.sequence, image_file=png_name, sidecar_file=json_name,
            png_sha256=meta["png_sha256"], sidecar_sha256=hashlib.sha256(sidecar).hexdigest(),
            source_log_line_sha256=meta["source_log_line_sha256"], reason=scalar["reason"])
        index.write(json.dumps(record)+"\n")
        index.flush()  # Only an indexed pair counts as committed evidence.
        with self.lock:
            self.saved += 1
            self.bytes_saved += size

    def _run(self):
        try:
            with (self.directory/"evidence_index.jsonl").open("x") as index:
                self._status()
                while not self.stop.is_set() or not self.pending.empty():
                    try:
                        item = self.pending.get(timeout=.05)
                    except queue.Empty:
                        continue
                    try:
                        if self.error:
                            break
                        self._save(item, index)
                        self._status()
                    finally:
                        self.pending.task_done()
        except Exception as error:
            with self.lock:
                self.error = f"{type(error).__name__}: {error}"[:1000]
        finally:
            try:
                self._status(done=True)
            except Exception:
                pass  # Disk failure cannot affect the inference/control process.

    def close(self, timeout=.25):
        self.stop.set()
        self.thread.join(timeout)
        result = self.snapshot()
        result["writer_stopped"] = not self.thread.is_alive()
        return result
