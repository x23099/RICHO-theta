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


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_subparsers(dest="role", required=True)
    send = modes.add_parser("send", help="matunuc; video only, no ROS/control channels")
    send.add_argument("--receiver-ip", required=True)
    send.add_argument("--port", type=int, default=5002)
    send.add_argument("--device", default="/dev/video0")
    send.add_argument("--fps", type=int, default=30, choices=(10, 20, 24, 25, 30))
    receive = modes.add_parser("receive", help="GPU PC; native intake only, NOT distance output")
    receive.add_argument("--host", default="0.0.0.0")
    receive.add_argument("--port", type=int, default=5002)
    receive.add_argument("--output-dir", type=Path, required=True)
    receive.add_argument("--headless", action="store_true")
    receive.add_argument("--duration-sec", type=float, help="optional bounded intake duration")
    return parser


def validate_args(args):
    if not 1 <= args.port <= 65535:
        raise ValueError("port must be 1..65535")
    if args.role == "receive":
        if args.output_dir.exists():
            raise ValueError("output directory must be new; no overwrite")
        if args.duration_sec is not None and (finite_time(args.duration_sec) <= 0):
            raise ValueError("positive duration required")
    elif not args.receiver_ip.strip() or any(c in args.receiver_ip for c in "/ \t\r\n"):
        raise ValueError("receiver IPv4 address or hostname required")
    return args


class CaptureFrames:
    """Camera reader with a one-frame slot, never re-emits an old capture."""
    def __init__(self, capture, *, clock=time.monotonic):
        self.capture, self.clock = capture, clock
        self.lock = threading.Lock()
        self.stopped = threading.Event()
        self.latest = None
        self.error = None
        self.sequence = 0
        self.thread = threading.Thread(target=self._read, name="native-camera-reader", daemon=True)

    def start(self):
        self.thread.start()

    def _read(self):
        try:
            last_good = self.clock()
            while not self.stopped.is_set():
                ok, image = self.capture.read()
                now = self.clock()
                if not ok:
                    if now - last_good > 0.5:
                        raise RuntimeError("camera read failed for over 0.5s")
                    self.stopped.wait(0.01)
                    continue
                native_frame(image)
                with self.lock:
                    self.sequence += 1
                    self.latest = (self.sequence, now, image.copy())
                last_good = now
        except Exception as exc:
            with self.lock:
                self.error = str(exc)
                self.latest = None
        finally:
            self.capture.release()

    def after(self, sequence):
        with self.lock:
            if self.error:
                raise RuntimeError(self.error)
            if self.latest is None or self.latest[0] <= sequence:
                return None
            value = self.latest
            age = self.clock() - value[1]
            if age < 0 or age > PROFILE["max_capture_age_sec"]:
                return None
            return value

    def close(self):
        self.stopped.set()
        self.thread.join(timeout=1)
        if self.thread.is_alive():
            LOG.warning("camera read is blocked; reader is daemonized, no stale frame is retransmitted")


async def send(args):
    import aiohttp
    import av
    from aiortc import RTCConfiguration, RTCPeerConnection, RTCSessionDescription, RTCRtpSender, VideoStreamTrack
    from aiortc.mediastreams import MediaStreamError

    class NativeTrack(VideoStreamTrack):
        def __init__(self, reader):
            super().__init__()
            self.reader = reader
            self.sequence = 0
            self.origin = None
            self.last_pts = -1

        async def recv(self):
            deadline = time.monotonic() + 0.5
            value = None
            while self.readyState == "live" and time.monotonic() < deadline:
                value = self.reader.after(self.sequence)
                if value is not None:
                    break
                await asyncio.sleep(0.005)
            if value is None:
                self.stop()
                raise MediaStreamError("no fresh new camera frame")
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

    device = int(args.device) if args.device.isdigit() else args.device
    capture = cv2.VideoCapture(device, cv2.CAP_V4L2)
    if not capture.isOpened():
        capture.release()
        raise RuntimeError(f"cannot open camera: {args.device}")
    reader = CaptureFrames(capture)
    pc = None
    try:
        capture.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*"MJPG"))
        capture.set(cv2.CAP_PROP_FRAME_WIDTH, PROFILE["width"])
        capture.set(cv2.CAP_PROP_FRAME_HEIGHT, PROFILE["height"])
        capture.set(cv2.CAP_PROP_FPS, args.fps)
        LOG.info("Capture request=1280x720 MJPG %sfps; reported=%s; every actual frame is checked",
                 args.fps, read_capture_properties(capture))
        reader.start()
        pc = RTCPeerConnection(RTCConfiguration(iceServers=[]))
        track = NativeTrack(reader)
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
        while pc.connectionState not in ("closed", "failed", "disconnected"):
            if pc.connectionState != "connected" and time.monotonic() > connection_deadline:
                raise RuntimeError("WebRTC connection timed out")
            # Also catches capture failure when the RTP sender has stopped recv.
            with reader.lock:
                error, latest = reader.error, reader.latest
            if error:
                raise RuntimeError(error)
            if latest is not None and time.monotonic() - latest[1] > 0.5:
                raise RuntimeError("camera stopped returning fresh frames")
            if track.readyState != "live":
                raise RuntimeError("video track ended")
            await asyncio.sleep(0.05)
    finally:
        if pc is not None:
            await pc.close()
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
        asyncio.run(send(args) if args.role == "send" else receive(args))
    except KeyboardInterrupt:
        return 0
    except (ValueError, RuntimeError, OSError, ImportError) as exc:
        LOG.error("%s", exc)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
