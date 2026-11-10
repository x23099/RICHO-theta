"""Opt-in read-only driver tap. GPU/pipe waits never run in the RTC/UI loop."""
import json
import os
from pathlib import Path
import re
import subprocess
import threading
import time

from driver_motion_protocol import checked_result, profile_matches, read_message, write_frame
from theta_rtc_frames import NativeFrame, finite_time, native_frame

_SHUTDOWN_GRACE_SEC = 2.
_SHUTDOWN_FORCE_SEC = 1.


def add_motion_arguments(parser):
    group=parser.add_argument_group("experimental non-controlling motion range")
    group.add_argument("--motion-distance",action="store_true")
    group.add_argument("--motion-python",type=Path,help="GPU Python; independent of the ROS/Qt UI Python")
    group.add_argument("--motion-weights",type=Path)
    group.add_argument("--motion-profile",type=Path)
    group.add_argument("--motion-output-dir",type=Path)
    group.add_argument("--motion-config",type=Path)
    group.add_argument("--motion-device",type=int,default=0)
    group.add_argument("--motion-target-roi",type=int,nargs=4)
    group.add_argument("--motion-experimental-rigid-mount",action="store_true")
    from driver_withheld_evidence import add_evidence_arguments
    add_evidence_arguments(group, prefix="motion-")


def bridge_from_args(args):
    from driver_withheld_evidence import EvidenceLimits, evidence_path, limits_from_args
    evidence_dir = args.motion_withheld_evidence_dir
    limits = limits_from_args(args, prefix="motion_")
    if not args.motion_distance:
        if evidence_dir is not None or limits != EvidenceLimits():
            raise ValueError("withheld evidence requires --motion-distance")
        return None
    if evidence_dir is None and limits != EvidenceLimits():
        raise ValueError("evidence limits require --motion-withheld-evidence-dir")
    if not args.motion_experimental_rigid_mount:
        raise ValueError("--motion-experimental-rigid-mount required; NOT accuracy approval")
    if (args.cam_width,args.cam_height) != (1280,720) or args.front_lens != "left" or args.mock_camera:
        raise ValueError("motion range requires real native 1280x720/front-left; no resizing fallback")
    if args.motion_device < 0 or args.motion_output_dir is None:
        raise ValueError("new --motion-output-dir and nonnegative CUDA device required")
    for name in ("motion_python","motion_weights","motion_profile"):
        path=getattr(args,name)
        if path is None or not path.expanduser().is_file():
            raise ValueError("explicit local file required: --"+name.replace("_","-"))
    if not os.access(args.motion_python.expanduser(),os.X_OK):
        raise ValueError("GPU Python is not executable")
    if args.motion_target_roi is not None:
        x1,y1,x2,y2=args.motion_target_roi
        if not 0 <= x1 < x2 <= 640 or not 0 <= y1 < y2 <= 720:
            raise ValueError("native front ROI x1 y1 x2 y2 required")
    if evidence_dir is not None:
        evidence_dir = evidence_path(evidence_dir)
        output = args.motion_output_dir.resolve()
        if evidence_dir == output or output in evidence_dir.parents or evidence_dir in output.parents:
            raise ValueError("evidence directory and motion output must be separate")
    command=[str(args.motion_python.expanduser().absolute()),"-u",
        str(Path(__file__).with_name("driver_motion_process.py")),
        "--weights",str(args.motion_weights.expanduser().resolve()),
        "--profile",str(args.motion_profile.expanduser().resolve()),
        "--output-dir",str(args.motion_output_dir.absolute()),
        "--device",str(args.motion_device),"--experimental-rigid-mount"]
    if args.motion_config is not None:
        command.extend(["--config",str(args.motion_config.resolve())])
    if args.motion_target_roi is not None:
        command.extend(["--target-roi",*map(str,args.motion_target_roi)])
    if evidence_dir is not None:
        command.extend(["--withheld-evidence-dir", str(evidence_dir),
            "--withheld-evidence-max-frames", str(limits.max_frames),
            "--withheld-evidence-max-mib", str(limits.max_bytes//(1024*1024)),
            "--withheld-evidence-interval-sec", str(limits.interval_sec)])
    return DriverMotionBridge(command,args.motion_output_dir,evidence_dir=evidence_dir)


class DriverMotionBridge:
    """Capacity-one borrowed immutable native frame; dedicated pull IPC thread.

    The caller transfers a read-only owned decoded ndarray, never a view into a
    mutable capture buffer. UI remapping/annotation must continue to use copies.
    No image copy, file write, GPU call or pipe I/O occurs in publish().
    """
    def __init__(self,command,output_dir,*,clock=time.monotonic,evidence_dir=None):
        self.command,self.output_dir,self.clock=list(command),Path(output_dir),clock
        self.evidence_dir=Path(evidence_dir) if evidence_dir is not None else None
        self.output_dir.mkdir(parents=True,exist_ok=False)
        self.lock=threading.Lock();self.stop_event=threading.Event();self.ready=threading.Event()
        self.process=None;self.error=None;self.latest=None;self.result=None
        self.session=None;self.valid_source=False;self.sequence=0;self.last_media=self.last_received=None
        self.reason="waiting_for_motion_native_sender";self.sent=self.returned=self.retired=self.dropped=0
        self.used_sessions=set()
        self.max_publish_ms=0.;self.shutdown=None
        self.forced_worker_kill=False;self.shutdown_error=None
        self.thread=threading.Thread(target=self._io_loop,name="driver-range-pipe-io",daemon=True)

    def start(self):
        if self.stop_event.is_set():
            raise RuntimeError("closed driver range tap cannot start")
        self.thread.start()

    def begin(self,session,profile):
        if not isinstance(session,str) or not re.fullmatch("[0-9a-f]{32}",session):
            raise ValueError("unique driver peer session required")
        with self.lock:
            if session in self.used_sessions:raise ValueError("reconnect requires a new driver session")
            self.used_sessions.add(session)
            self.session=session;self.sequence=0;self.last_media=self.last_received=None
            self.latest=self.result=None;self.valid_source=profile_matches(profile)
            self.reason="waiting_for_native_frame" if self.valid_source else "motion_native_sender_profile_missing_or_mismatch"

    def end(self,session,reason="driver_video_disconnected"):
        with self.lock:
            if session == self.session:
                self.valid_source=False;self.latest=self.result=None;self.reason=reason

    def fail(self,reason):
        with self.lock:
            self.error=str(reason)[:1000];self.result=self.latest=None;self.valid_source=False

    def publish(self,session,image,media_time,received_at):
        started=time.perf_counter()
        if not self.lock.acquire(blocking=False):
            self.dropped+=1
            return False
        try:
            if self.stop_event.is_set() or session != self.session or not self.valid_source:
                return False
            try:
                native_frame(image)
                media_time,received_at=finite_time(media_time),finite_time(received_at)
                if received_at > self.clock():raise ValueError("future_native_frame_time")
                if image.flags.writeable:
                    raise ValueError("immutable owned decoded frame required")
                if (self.last_media is not None and media_time <= self.last_media
                        or self.last_received is not None and received_at <= self.last_received):
                    raise ValueError("nonincreasing_native_frame_time")
            except ValueError as error:
                self.valid_source=False;self.latest=self.result=None;self.reason=str(error)
                return False
            self.sequence+=1;self.last_media=media_time;self.last_received=received_at
            self.latest=NativeFrame(session,self.sequence,media_time,received_at,image)
            self.reason="waiting_for_current_motion_range"
            return True
        finally:
            self.lock.release()
            self.max_publish_ms=max(self.max_publish_ms,1000*(time.perf_counter()-started))

    def snapshot(self,now=None):
        now=self.clock() if now is None else finite_time(now)
        if not self.lock.acquire(blocking=False):
            return dict(available=False,reason="motion_tap_busy")
        try:
            reason=self.reason
            if self.stop_event.is_set():reason="motion_tap_stopped"
            elif self.error:reason="motion_worker_failed: "+self.error
            elif self.process is not None and self.process.poll() is not None:reason="motion_worker_exited"
            elif self.valid_source and self.latest is not None:
                if not 0 <= now-self.latest.received_at <= .5:reason="motion_input_stale"
                elif self.result is not None:
                    value=self.result
                    if value["session"] != self.session:reason="motion_session_changed"
                    elif not 0 <= now-value["source_time_sec"] <= .5:reason="motion_result_stale"
                    else:
                        return dict(available=value["distance_available"],reason=value["reason"],
                            result=dict(value),age_ms=1000*(now-value["source_time_sec"]))
            return dict(available=False,reason=reason)
        finally:self.lock.release()

    def _next_frame(self,last_key):
        while not self.stop_event.is_set():
            if self.process is not None and self.process.poll() is not None:
                raise EOFError("motion process exited while awaiting input")
            with self.lock:
                if self.error:return None
                frame=self.latest if self.valid_source else None
                if (frame is not None and (frame.session,frame.sequence) != last_key
                        and 0 <= self.clock()-frame.received_at <= .5):
                    return frame
            self.stop_event.wait(.005)
        return None

    def _io_loop(self):
        try:
            with (self.output_dir/"motion_worker_stderr.log").open("xb") as stderr, \
                 (self.output_dir/"motion_bridge_events.jsonl").open("x") as events:
                self.process=subprocess.Popen(self.command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,
                    stderr=stderr,shell=False,close_fds=True)
                if self.stop_event.is_set():
                    self.process.terminate();return
                last_key=None;inflight=None
                while not self.stop_event.is_set():
                    message=read_message(self.process.stdout)
                    if message == dict(type="request"):
                        self.ready.set()
                        if inflight is not None:raise ValueError("duplicate worker request")
                        frame=self._next_frame(last_key)
                        if frame is None:break
                        write_frame(self.process.stdin,frame)
                        inflight=frame;last_key=frame.session,frame.sequence;self.sent+=1
                    elif message.get("type") == "result" and set(message) == {"type","result"} and inflight is not None:
                        value=checked_result(message["result"],inflight)
                        with self.lock:
                            accepted=(not self.stop_event.is_set() and self.valid_source
                                and value["session"] == self.session
                                and 0 <= self.clock()-value["source_time_sec"] <= .5)
                            if accepted:self.result=value
                            else:self.retired+=1
                        self.returned+=1
                        events.write(json.dumps(dict(result=value,accepted_current_session_and_age=accepted))+"\n")
                        events.flush();inflight=None
                    elif message.get("type") == "error":
                        raise RuntimeError(str(message.get("error","unknown motion worker failure"))[:1000])
                    else:raise ValueError("unexpected motion worker message")
        except Exception as error:
            if not self.stop_event.is_set():
                with self.lock:self.error=f"{type(error).__name__}: {error}";self.result=None
        finally:
            if self.process is not None:
                if self.process.poll() is None:self.process.terminate()
                # This background thread may wait; never join it in RTC.
                try:self.process.wait(timeout=1.)
                except subprocess.TimeoutExpired:
                    self.process.kill();self.process.wait(timeout=1.)
                self.process.stdin.close();self.process.stdout.close()

    def request_stop(self):
        self.stop_event.set()
        with self.lock:self.latest=self.result=None
        if self.process is not None and self.process.poll() is None:
            try:self.process.terminate()
            except ProcessLookupError:pass

    def close(self):
        started=time.monotonic()
        self.request_stop()
        if self.thread.ident is not None:self.thread.join(_SHUTDOWN_GRACE_SEC)
        if self.thread.is_alive():
            # read_message may be blocked while a child ignores SIGTERM or is
            # slow to exit. Its I/O-thread finally cannot enforce a timeout
            # until that read returns. Bound this wait independently, outside
            # the RTC/UI loop, and signal ONLY our exact inference child.
            process=self.process
            if process is not None and process.poll() is None:
                try:
                    process.kill()
                    self.forced_worker_kill=True
                except ProcessLookupError:
                    pass
                except OSError as error:
                    self.shutdown_error=f"{type(error).__name__}: {error}"[:1000]
            self.thread.join(_SHUTDOWN_FORCE_SEC)
        io_stopped=not self.thread.is_alive()
        child_stopped=self.process is None or self.process.poll() is not None
        self.shutdown=dict(schema="driver_motion_bridge_summary_v1",sent=self.sent,returned=self.returned,
            retired_results=self.retired,tap_lock_drops=self.dropped,max_publish_ms=self.max_publish_ms,
            worker_error=self.error,child_exitcode=self.process.poll() if self.process is not None else None,
            io_thread_stopped=io_stopped, child_stopped=child_stopped,
            shutdown_complete=io_stopped and child_stopped,
            shutdown_reason=("complete_after_forced_worker_kill" if self.forced_worker_kill else "complete")
                if io_stopped and child_stopped else "shutdown_incomplete",
            forced_worker_kill=self.forced_worker_kill,shutdown_error=self.shutdown_error,
            shutdown_wait_ms=1000*(time.monotonic()-started),
            image_files_written=None if self.evidence_dir is not None else False,
            withheld_evidence_requested=self.evidence_dir is not None,
            withheld_evidence_status_file=str(self.evidence_dir/"evidence_status.json") if self.evidence_dir else None,
            physical_metric_verified=False,usable_for_ffb=False,
            distance_published_to_ros=False,control_channel_modified=False,
            metric="horizontal_camera_foot_range_m_NOT_base_link_or_contact")
        (self.output_dir/"driver_motion_summary.json").write_text(json.dumps(self.shutdown,indent=2)+"\n")
        return self.shutdown


def panel_text(snapshot):
    if snapshot.get("available"):
        result=snapshot["result"]
        value=f"{result['horizontal_camera_foot_range_m']:.3f} m"
        detail=f"source {result['session'][:8]} frame {result['frame']} | receive-age {snapshot['age_ms']:.0f} ms"
    else:
        value="WITHHELD";detail=snapshot.get("reason","unknown")[:200]
    return (f"RANGE EXPERIMENT: {value} | camera-foot horizontal, NOT base_link/contact\n"
        +detail+"\nFixed mount + planar floor assumed; no tilt compensation. Distance NOT used for control/FFB.")
