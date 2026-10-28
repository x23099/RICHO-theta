#!/usr/bin/env python3
"""Read-only native WebRTC intake. No ROS, steering, inference, or FFB.

Same HTTP /offer + aiortc VP8 route as the driver stream, but a separate explicit
profile. Both sides must use --diagnostic. Regular driver mode is unchanged.
"""
import argparse
import asyncio
import csv
from fractions import Fraction
import hashlib
import importlib.metadata
import json
import logging
from pathlib import Path
import threading
import time
import uuid

import cv2
import numpy as np

from camera_capture_properties import read_capture_properties
from theta_rtc_frames import PROFILE, LatestNativeFrame, finite_time, native_frame, validate_profile


LOG = logging.getLogger("theta_rtc_diagnostic")
DEFAULT_CAPTURE_TIMEOUT_SEC = 3.0


def capture_timeout(value):
    value = finite_time(value)
    if not 1.0 <= value <= 10.0:
        raise ValueError("capture timeout must be within 1..10 seconds; frame freshness stays 0.2s")
    return value


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_subparsers(dest="role", required=True)
    send = modes.add_parser("send", help="matunuc; video only, no ROS/control channels")
    send.add_argument("--receiver-ip", required=True)
    send.add_argument("--port", type=int, default=5002)
    send.add_argument("--device", default="/dev/video0")
    send.add_argument("--fps", type=int, default=30, choices=(10, 20, 24, 25, 30))
    send.add_argument("--capture-timeout-sec", type=float, default=DEFAULT_CAPTURE_TIMEOUT_SEC,
                      help="continuous capture outage before exit; NOT permitted frame age (still 0.2s)")
    probe_parser = modes.add_parser("probe", help="matunuc; local native preview/snapshots only, no network/ROS/FFB")
    probe_parser.add_argument("--device", default="/dev/video0")
    probe_parser.add_argument("--fps", type=int, default=30, choices=(10, 20, 24, 25, 30))
    probe_parser.add_argument("--capture-timeout-sec", type=float, default=DEFAULT_CAPTURE_TIMEOUT_SEC)
    probe_parser.add_argument("--output-dir", type=Path, required=True)
    probe_parser.add_argument("--duration-sec", type=float, default=5.0)
    probe_parser.add_argument("--headless", action="store_true")
    receive = modes.add_parser("receive", help="GPU PC; native intake only, NOT distance output")
    receive.add_argument("--host", default="0.0.0.0")
    receive.add_argument("--port", type=int, default=5002)
    receive.add_argument("--output-dir", type=Path, required=True)
    receive.add_argument("--headless", action="store_true")
    receive.add_argument("--duration-sec", type=float, help="optional bounded intake duration")
    return parser


def validate_args(args):
    if args.role != "probe" and not 1 <= args.port <= 65535:
        raise ValueError("port must be 1..65535")
    if args.role in ("receive", "probe"):
        if args.output_dir.exists():
            raise ValueError("output directory must be new; no overwrite")
        if args.duration_sec is not None and (finite_time(args.duration_sec) <= 0):
            raise ValueError("positive duration required")
    if args.role in ("send", "probe"):
        capture_timeout(args.capture_timeout_sec)
    if args.role == "probe" and args.duration_sec > 120:
        raise ValueError("local probe duration must not exceed 120 seconds")
    if args.role == "send" and (not args.receiver_ip.strip() or any(c in args.receiver_ip for c in "/ \t\r\n")):
        raise ValueError("receiver IPv4 address or hostname required")
    return args


class CaptureFrames:
    """Camera reader with a one-frame slot, never re-emits an old capture."""
    def __init__(self, capture, *, clock=time.monotonic, timeout_sec=DEFAULT_CAPTURE_TIMEOUT_SEC):
        self.capture, self.clock = capture, clock
        self.timeout_sec = capture_timeout(timeout_sec)
        self.lock = threading.Lock()
        self.stopped = threading.Event()
        self.latest = None
        self.error = None
        self.sequence = 0
        self.started_at = None
        self.last_read_sec = self.max_read_sec = 0.
        self.failed_reads = self.recovered_gaps = 0
        self.thread = threading.Thread(target=self._read, name="native-camera-reader", daemon=True)

    def start(self):
        if self.stopped.is_set():
            raise RuntimeError("closed camera reader cannot be restarted")
        if self.thread.ident is not None:
            raise RuntimeError("camera reader already started")
        self.started_at = self.clock()
        self.thread.start()

    def _read(self):
        try:
            last_good = self.started_at if self.started_at is not None else self.clock()
            while not self.stopped.is_set():
                started = self.clock()
                ok, image = self.capture.read()
                now = self.clock()
                if self.stopped.is_set():
                    break
                gap = now-last_good
                with self.lock:
                    self.last_read_sec = now-started
                    self.max_read_sec = max(self.max_read_sec, self.last_read_sec)
                    if self.error:
                        raise RuntimeError(self.error)
                if gap >= self.timeout_sec:
                    raise RuntimeError(f"camera read failed or stalled for {gap:.3f}s; capture timeout={self.timeout_sec:.3f}s")
                if not ok:
                    with self.lock:
                        self.failed_reads += 1
                    self.stopped.wait(0.01)
                    continue
                native_frame(image)
                owned = image.copy()
                with self.lock:
                    if self.error or self.stopped.is_set():
                        break
                    if self.sequence and gap > 0.5:
                        self.recovered_gaps += 1
                    self.sequence += 1
                    self.latest = (self.sequence, now, owned)
                if gap > 0.5:
                    LOG.warning("Capture returned after %.1f ms; no old frame repeated; freshness limit remains 200 ms", gap*1000)
                last_good = now
        except Exception as exc:
            with self.lock:
                self.error = self.error or str(exc)
                self.latest = None
        finally:
            self.capture.release()

    def _status_locked(self):
        if self.error:
            raise RuntimeError(self.error)
        if self.stopped.is_set():
            raise RuntimeError("camera reader stopped")
        reference = self.latest[1] if self.latest is not None else self.started_at
        if reference is None:
            raise RuntimeError("camera reader not started")
        age = self.clock()-reference
        if age is not None and age >= self.timeout_sec:
            self.error = f"camera capture timeout: no successful read for {age:.3f}s; limit={self.timeout_sec:.3f}s"
            self.latest = None
            raise RuntimeError(self.error)
        return dict(state="capturing" if self.latest is not None and 0 <= age <= PROFILE["max_capture_age_sec"] else "capture_wait",
                    age_sec=age, captured_frames=self.sequence, failed_reads=self.failed_reads,
                    recovered_gaps=self.recovered_gaps, last_read_ms=1000*self.last_read_sec,
                    max_read_ms=1000*self.max_read_sec)

    def status(self):
        with self.lock:
            return self._status_locked()

    def after(self, sequence):
        with self.lock:
            status = self._status_locked()
            if self.latest is None or self.latest[0] <= sequence:
                return None
            value = self.latest
            age = status["age_sec"]
            if age < 0 or age > PROFILE["max_capture_age_sec"]:
                return None
            return value

    def close(self):
        self.stopped.set()
        with self.lock:
            self.latest = None
        if self.thread.ident is not None:
            self.thread.join(timeout=1)
        if self.thread.is_alive():
            LOG.warning("camera read is blocked; reader is daemonized, no stale frame is retransmitted")


async def wait_for_capture(reader, sequence, *, is_live=lambda: True, sleep=asyncio.sleep):
    """Wait WITHOUT fabricating/repeating a frame; reader bounds the outage."""
    while is_live():
        value = reader.after(sequence)
        if value is not None:
            return value
        await sleep(0.005)
    raise RuntimeError("video track ended while waiting for capture")


def make_native_track(reader):
    """Lazy media dependency; independently testable without a camera/socket."""
    import av
    from aiortc import VideoStreamTrack
    from aiortc.mediastreams import MediaStreamError

    class NativeTrack(VideoStreamTrack):
        def __init__(self):
            super().__init__()
            self.reader = reader
            self.sequence = 0
            self.origin = None
            self.last_pts = -1

        async def recv(self):
            try:
                value = await wait_for_capture(self.reader, self.sequence, is_live=lambda: self.readyState == "live")
            except RuntimeError as exc:
                self.stop()
                raise MediaStreamError(str(exc)) from exc
            self.sequence, captured_at, image = value
            if self.origin is None:
                self.origin = captured_at
            # Capture read-return time, NOT a sensor exposure timestamp. RTP
            # origins may be rebased on the receiver: do not subtract PC clocks.
            pts = max(self.last_pts + 1, round((captured_at - self.origin) * 90000))
            self.last_pts = pts
            frame = av.VideoFrame.from_ndarray(image, format="bgr24")
            frame.pts, frame.time_base = pts, Fraction(1, 90000)
            return frame
    return NativeTrack()


def open_native_capture(device, fps):
    """Shared sender/probe settings, matching the native measurement profile."""
    device = int(device) if str(device).isdigit() else str(device)
    capture = cv2.VideoCapture(device, cv2.CAP_V4L2)
    if not capture.isOpened():
        capture.release()
        raise RuntimeError(f"cannot open camera: {device}")
    try:
        capture.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        capture.set(cv2.CAP_PROP_FRAME_WIDTH, PROFILE["width"])
        capture.set(cv2.CAP_PROP_FRAME_HEIGHT, PROFILE["height"])
        capture.set(cv2.CAP_PROP_FPS, fps)
        LOG.info("Capture request=1280x720 MJPG %sfps; reported=%s; every actual frame is checked",
                 fps, read_capture_properties(capture))
        return capture
    except BaseException:
        capture.release()
        raise


async def probe(args):
    """Native local preview before RTC; no network/ROS/GPU imports or remap.

    Snapshots are complete unannotated decoded capture frames. This intentionally
    does not classify a capture card's No Signal screen as valid camera content.
    """
    args.output_dir.mkdir(parents=True, exist_ok=False)
    capture = reader = None
    first = last = None
    started = time.monotonic()
    summary = dict(status="LOCAL_CAPTURE_PROBE_NOT_SIGNAL_OR_DISTANCE_APPROVAL", device=args.device,
        requested_fps=args.fps, image_size=[1280, 720], physical_output=False,
        network_started=False, ros_started=False, cuda_inference_started=False,
        scene_content_verified=False, no_signal_detected=None, observed_frames=0,
        capture_timeout_sec=args.capture_timeout_sec, permitted_frame_age_sec=PROFILE["max_capture_age_sec"],
        source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    try:
        capture = open_native_capture(args.device, args.fps)
        summary["reported_capture_properties"] = read_capture_properties(capture)
        reader = CaptureFrames(capture, timeout_sec=args.capture_timeout_sec)
        reader.start()
        started = time.monotonic()
        sequence, previous_state = 0, None
        with (args.output_dir/"capture_observations.csv").open("x", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=("sequence", "read_return_monotonic_sec",
                "observe_monotonic_sec", "read_return_to_observe_ms", "width", "height"))
            writer.writeheader()
            while time.monotonic()-started < args.duration_sec:
                state = reader.status()
                if state["state"] != previous_state:
                    LOG.info("Local probe state=%s age_sec=%s; max read=%.1f ms",
                             state["state"], state["age_sec"], state["max_read_ms"])
                    previous_state = state["state"]
                value = reader.after(sequence)
                if value is not None:
                    sequence, read_at, image = value
                    observed = time.monotonic()
                    first = first if first is not None else value
                    last = value
                    writer.writerow(dict(sequence=sequence, read_return_monotonic_sec=read_at,
                        observe_monotonic_sec=observed, read_return_to_observe_ms=1000*(observed-read_at),
                        width=image.shape[1], height=image.shape[0]))
                    stream.flush()
                    summary["observed_frames"] += 1
                if not args.headless:
                    # Never hold an old preview during a capture gap.
                    display = (last[2] if last is not None
                        and 0 <= time.monotonic()-last[1] <= PROFILE["max_capture_age_sec"]
                        else np.zeros((720, 1280, 3), np.uint8))
                    cv2.imshow("THETA local capture probe (unannotated)", display)
                    if cv2.waitKey(1) & 0xff in (ord("q"), ord("Q")):
                        break
                await asyncio.sleep(.02)
        summary["capture_state_before_close"] = reader.status()
    except BaseException as exc:
        summary.update(status="LOCAL_CAPTURE_PROBE_FAILED", error=f"{type(exc).__name__}: {exc}")
        raise
    finally:
        # No listeners/media tasks here; a bounded local join is sufficient.
        if reader is not None:
            reader.close()
            summary["reader_stopped"] = not reader.thread.is_alive()
            with reader.lock:
                summary["capture_counters"] = dict(captured_frames=reader.sequence,
                    failed_reads=reader.failed_reads, recovered_gaps=reader.recovered_gaps,
                    max_completed_read_ms=reader.max_read_sec*1000, reader_error=reader.error)
        elif capture is not None:
            capture.release()
        if not args.headless:
            cv2.destroyAllWindows()
        snapshots = []
        for name, value in (("first_frame.png", first), ("last_frame.png", last)):
            if value is None:
                continue
            path = args.output_dir/name
            if not cv2.imwrite(str(path), value[2]):
                summary.update(status="LOCAL_CAPTURE_PROBE_FAILED", snapshot_error=name)
                continue
            snapshots.append(dict(file=name, sequence=value[0], read_return_monotonic_sec=value[1],
                sha256=hashlib.sha256(path.read_bytes()).hexdigest(), source_pixels_edited=False))
        summary.update(elapsed_sec=time.monotonic()-started, snapshots=snapshots,
                       snapshot_kind="native OpenCV decoded capture, not annotated, NOT guaranteed sensor-original")
        if summary["status"] != "LOCAL_CAPTURE_PROBE_FAILED" and not summary["observed_frames"]:
            summary["status"] = "LOCAL_CAPTURE_PROBE_NO_FRAMES"
        if summary.get("reader_stopped") is False:
            summary.update(status="LOCAL_CAPTURE_PROBE_FAILED", shutdown_error="camera reader still blocked")
        (args.output_dir/"probe_summary.json").write_text(json.dumps(summary, indent=2)+"\n")
    if summary["status"] == "LOCAL_CAPTURE_PROBE_FAILED":
        raise RuntimeError("local capture probe save/shutdown incomplete; see probe_summary.json")


async def send(args):
    import aiohttp
    from aiortc import RTCConfiguration, RTCPeerConnection, RTCSessionDescription, RTCRtpSender
    capture = open_native_capture(args.device, args.fps)
    reader = CaptureFrames(capture, timeout_sec=args.capture_timeout_sec)
    pc = None
    try:
        reader.start()
        pc = RTCPeerConnection(RTCConfiguration(iceServers=[]))
        track = make_native_track(reader)
        transceiver = pc.addTransceiver(track, direction="sendonly")
        codecs = [c for c in RTCRtpSender.getCapabilities("video").codecs if c.name == "VP8"]
        if not codecs:
            raise RuntimeError("VP8 codec unavailable")
        transceiver.setCodecPreferences(codecs)
        await pc.setLocalDescription(await pc.createOffer())
        payload = dict(sdp=pc.localDescription.sdp, type=pc.localDescription.type,
                       diagnostic_profile=PROFILE)
        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(f"http://{args.receiver_ip}:{args.port}/offer", json=payload) as response:
                if response.status != 200:
                    raise RuntimeError(f"diagnostic receiver rejected offer: {response.status} {(await response.text())[:300]}")
                answer = await response.json()
                validate_profile(answer.get("diagnostic_profile"))
                await pc.setRemoteDescription(RTCSessionDescription(sdp=answer["sdp"], type=answer["type"]))
        LOG.info("Video-only diagnostic stream; no ROS/control/FFB. Ctrl+C stops.")
        connection_deadline = time.monotonic() + 20
        last_capture_state = None
        while pc.connectionState not in ("closed", "failed", "disconnected"):
            if pc.connectionState != "connected" and time.monotonic() > connection_deadline:
                raise RuntimeError("WebRTC connection timed out")
            # Also catches capture failure when the RTP sender has stopped recv.
            state = reader.status()
            if state["state"] != last_capture_state:
                LOG.info("Capture state=%s age_sec=%s; timeout=%.1fs, frame freshness=0.2s; read_max_ms=%.1f",
                         state["state"], state["age_sec"], reader.timeout_sec, state["max_read_ms"])
                last_capture_state = state["state"]
            if track.readyState != "live":
                raise RuntimeError("video track ended")
            await asyncio.sleep(0.05)
    finally:
        try:
            if pc is not None:
                await pc.close()
        finally:
            if reader.thread.ident is None:
                capture.release()
            else:
                await asyncio.to_thread(reader.close)


class Receiver:
    def __init__(self, slot):
        self.slot = slot
        self.pc = None
        self.tasks = set()
        self.lock = asyncio.Lock()

    async def offer(self, request):
        from aiohttp import web
        from aiortc import RTCConfiguration, RTCPeerConnection, RTCSessionDescription
        try:
            payload = await request.json()
            validate_profile(payload.get("diagnostic_profile"))
            if payload.get("type") != "offer" or not isinstance(payload.get("sdp"), str):
                raise ValueError("SDP offer required")
        except (ValueError, TypeError, AttributeError) as exc:
            return web.json_response(dict(error=str(exc)), status=400)
        async with self.lock:
            if self.pc is not None and self.pc.connectionState != "closed":
                return web.json_response(dict(error="one sender only; stop old sender before reconnect"), status=409)
            pc = RTCPeerConnection(RTCConfiguration(iceServers=[]))
            self.pc = pc
            identity = uuid.uuid4().hex
            self.slot.begin(identity)
            video_count = 0

            @pc.on("datachannel")
            def unexpected_channel(channel):
                # No callback can ever forward a control message.
                channel.close()

            @pc.on("track")
            def on_track(track):
                nonlocal video_count
                video_count += int(track.kind == "video")
                if track.kind != "video" or video_count != 1:
                    track.stop()
                    self.slot.end(identity, "unexpected_media_track")
                    task = asyncio.create_task(pc.close())
                else:
                    task = asyncio.create_task(self.consume(track, identity, pc))
                self.tasks.add(task)
                task.add_done_callback(self.tasks.discard)

            @pc.on("connectionstatechange")
            async def state_changed():
                if pc.connectionState in ("closed", "failed", "disconnected"):
                    self.slot.end(identity, "connection_" + pc.connectionState)
                    if pc.connectionState != "closed":
                        await pc.close()

            try:
                await pc.setRemoteDescription(RTCSessionDescription(sdp=payload["sdp"], type="offer"))
                if video_count != 1:
                    raise ValueError("exactly one native video track required")
                await pc.setLocalDescription(await pc.createAnswer())
                return web.json_response(dict(sdp=pc.localDescription.sdp, type=pc.localDescription.type,
                                              diagnostic_profile=PROFILE))
            except Exception as exc:
                self.slot.end(identity, "offer_failed")
                await pc.close()
                LOG.warning("Offer rejected: %s", exc)
                return web.json_response(dict(error="invalid diagnostic media offer"), status=400)

    async def consume(self, track, identity, pc):
        try:
            while True:
                frame = await track.recv()
                received = time.monotonic()
                if frame.pts is None or frame.time_base is None:
                    raise ValueError("media presentation timestamp missing")
                image = frame.to_ndarray(format="bgr24")
                self.slot.publish(identity, image, float(frame.pts * frame.time_base), received)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            LOG.info("Native intake ended: %s", exc)
            self.slot.end(identity, "invalid_or_ended_video")
            await pc.close()

    async def close(self):
        for task in tuple(self.tasks):
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        if self.pc is not None:
            await self.pc.close()


def save_decoded_frame(output, frame):
    """Unannotated decoded pixels, explicitly NOT lossless camera originals."""
    path = output / f"decoded_{frame.session}_f{frame.sequence:06d}.png"
    if path.exists():
        raise ValueError("snapshot already exists for this frame")
    if not cv2.imwrite(str(path), frame.image):
        raise RuntimeError("PNG write failed")
    return path


async def receive(args):
    from aiohttp import web
    args.output_dir.mkdir(parents=True, exist_ok=False)
    slot = LatestNativeFrame()
    server = Receiver(slot)
    app = web.Application(client_max_size=256 * 1024)
    app.router.add_post("/offer", server.offer)
    runner = web.AppRunner(app, access_log=None)
    started = time.monotonic()
    summary = dict(status="INTAKE_ONLY_NOT_DISTANCE_VALIDATION", profile=PROFILE,
                   physical_output=False, distance_connected=False, camera_originals_saved=False,
                   cross_pc_latency_measured=False, received_frames_consumed=0,
                   packages={n: importlib.metadata.version(n) for n in ("aiortc", "av", "aiohttp", "numpy")},
                   source_sha256={p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                  for p in (Path(__file__), Path(__file__).with_name("theta_rtc_frames.py"))})
    fields = ("session", "sequence", "media_time_sec", "receive_monotonic_sec", "consume_monotonic_sec",
              "receive_to_consume_ms", "overwritten_before_consume", "width", "height", "distance_connected")
    try:
        await runner.setup()
        await web.TCPSite(runner, args.host, args.port).start()
        LOG.info("Intake-only receiver listening on %s:%s; no ROS/FFB; Ctrl+C or Q stops.", args.host, args.port)
        last_key, last_state, last_flush = None, None, started
        with (args.output_dir / "received_frames.csv").open("x", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            while args.duration_sec is None or time.monotonic() - started < args.duration_sec:
                now = time.monotonic()
                frame, state = slot.current(now)
                if state != last_state:
                    LOG.info("Intake state: %s", state)
                    last_state = state
                if frame is not None and (frame.session, frame.sequence) != last_key:
                    last_key = (frame.session, frame.sequence)
                    writer.writerow(dict(session=frame.session, sequence=frame.sequence,
                        media_time_sec=frame.media_time, receive_monotonic_sec=frame.received_at,
                        consume_monotonic_sec=now, receive_to_consume_ms=1000 * (now - frame.received_at),
                        overwritten_before_consume=slot.overwritten, width=1280, height=720,
                        distance_connected=False))
                    summary["received_frames_consumed"] += 1
                if now - last_flush >= 1:
                    stream.flush()
                    last_flush = now
                if not args.headless:
                    # Display is a derived copy; the immutable intake image and
                    # saved decoded PNG remain full-frame and unannotated.
                    display = frame.image.copy() if frame is not None else np.zeros((720, 1280, 3), np.uint8)
                    cv2.rectangle(display, (0, 0), (1280, 85), (0, 0, 0), -1)
                    cv2.putText(display, "INTAKE ONLY | Distance: NOT CONNECTED | NO ROS / FFB", (12, 28),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 255, 255), 1)
                    cv2.putText(display, state, (12, 55), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
                    cv2.putText(display, "Q: quit | S: save unannotated decoded frame (not camera original)", (12, 78),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
                    cv2.imshow("THETA native diagnostic intake", display)
                    key = cv2.waitKey(1) & 0xff
                    if key in (ord("q"), ord("Q")):
                        break
                    if key in (ord("s"), ord("S")) and frame is not None:
                        try:
                            path = await asyncio.to_thread(save_decoded_frame, args.output_dir, frame)
                            LOG.info("Saved decoded frame: %s (see received_frames.csv for identity/time)", path)
                        except ValueError as exc:
                            LOG.info("%s", exc)
                await asyncio.sleep(0.02)
    finally:
        await server.close()
        await runner.cleanup()
        if not args.headless:
            cv2.destroyAllWindows()
        summary["elapsed_sec"] = time.monotonic() - started
        (args.output_dir / "intake_summary.json").write_text(json.dumps(summary, indent=2) + "\n")


def main(argv=None):
    logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
    try:
        args = validate_args(build_parser().parse_args(argv))
        asyncio.run({"send": send, "receive": receive, "probe": probe}[args.role](args))
    except KeyboardInterrupt:
        return 0
    except (ValueError, RuntimeError, OSError, ImportError) as exc:
        LOG.error("%s", exc)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
