"""Independent bounded channel adapters; NOT wired into live RTC/ROS/FFB.

Use an explicitly scoped new channel object, not lookup by a non-unique label.
No sockets are created here. Only sender pump/close touch the provided channel.
Producer submit and receiver take/close are NOT RTC message callbacks.
"""
from collections import deque
import re
import threading
import time

from driver_frame_packet import checked_candidate, encode_packet, FramePacketReceiver
from driver_frame_packet_flow import (message_limit, age_limit, fragment_plan,
    LatestPacketSender, PacketReassembler)
from driver_odometry_observation import clock_time
from theta_rtc_frames import native_frame

PROTOCOL = 'theta-frame-motion-v1'


def negotiated_message_bytes(remote_sdp, *, mid, local_max_message_size, app_cap=16384):
    """Conservative modern SCTP SDP subset, not a replacement SDP stack.

    remote_sdp must be the applied remote description for this connection.
    Missing max-message-size is 65536; zero means unlimited, NOT zero bytes.
    Unsupported/ambiguous syntax fails closed rather than guessing capabilities.
    """
    message_limit(app_cap)
    if (type(local_max_message_size) is not int or not 0 <= local_max_message_size < 2**63
            or type(remote_sdp) is not str or len(remote_sdp) > 65536
            or type(mid) is not str or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', mid)):
        raise ValueError('explicit bounded remote SDP, MID and local capability required')
    if any(c not in '\r\n' and not 32 <= ord(c) <= 126 for c in remote_sdp):
        raise ValueError('printable ASCII SDP with CR/LF required')
    sections, current = [], None
    lines = remote_sdp.splitlines()
    if not lines or len(lines) > 1024:
        raise ValueError('bounded SDP required')
    for line in lines:
        if not line or len(line) > 4096 or any(ord(c) < 32 or ord(c) > 126 for c in line):
            raise ValueError('bounded printable SDP subset required')
        if line.startswith('m='):
            current = dict(media=line[2:].split(), mids=[], sizes=[], ports=[], inactive=False)
            sections.append(current)
        elif line == 'a=inactive' and current is not None:
            current['inactive'] = True
        elif line.startswith(('a=mid:', 'a=max-message-size:', 'a=sctp-port:')):
            if current is None:
                raise ValueError('media-level SCTP attributes required')
            key, val = line[2:].split(':', 1)
            current[{'mid':'mids', 'max-message-size':'sizes', 'sctp-port':'ports'}[key]].append(val)
    seen, selected = set(), None
    for section in sections:
        mids = section['mids']
        if len(mids) != 1 or mids[0] in seen:
            raise ValueError('unique explicit media MID required')
        seen.add(mids[0])
        if mids[0] == mid:
            selected = section
    if selected is None:
        raise ValueError('selected application MID not present')
    media, ports, sizes = (selected[k] for k in ('media', 'ports', 'sizes'))
    def integer(value):
        if not re.fullmatch(r'0|[1-9][0-9]{0,18}', value):
            raise ValueError('canonical bounded SDP integer required')
        return int(value)
    if (selected['inactive'] or len(media) != 4 or media[0] != 'application'
            or media[2] not in ('UDP/DTLS/SCTP', 'TCP/DTLS/SCTP')
            or media[3] != 'webrtc-datachannel' or not 0 < integer(media[1]) <= 65535
            or len(ports) != 1 or not 0 < integer(ports[0]) <= 65535 or len(sizes) > 1):
        raise ValueError('active modern SCTP application section required')
    remote = integer(sizes[0]) if sizes else 65536
    limit = min([app_cap]+[v for v in (remote, local_max_message_size) if v != 0])
    return message_limit(limit)


class _InboxWorker:
    """Short locks never cover codec/JSON/copies/IO; daemon is not killable."""
    def __init__(self, capacity, name):
        self.capacity, self.queue = capacity, deque()
        self.lock, self.wake = threading.Lock(), threading.Event()
        self.retired, self.done = threading.Event(), threading.Event()
        self.output = self.error = None
        self.replaced = self.peak_queued = 0
        self.thread = threading.Thread(target=self._run, name=name, daemon=True)

    def _retire(self, reason):
        self.error = self.error or reason
        self.retired.set()
        self.wake.set()

    def _offer(self, item, *, latest=False):
        if self.retired.is_set():
            return False
        if not self.lock.acquire(blocking=False):
            self._retire('inbox_busy')
            return False
        try:
            if self.retired.is_set():
                return False
            self.output = None
            if len(self.queue) >= self.capacity:
                if not latest:
                    self.queue.clear()
                    self._retire('inbox_overflow')
                    return False
                self.queue.clear()
                self.replaced += 1
            self.queue.append(item)
            self.peak_queued = max(self.peak_queued, len(self.queue))
            self.wake.set()
            return True
        finally:
            self.lock.release()

    def _run(self):
        try:
            while not self.retired.is_set():
                self.wake.wait()
                with self.lock:
                    self.wake.clear()
                    if self.retired.is_set():
                        break
                    item = self.queue.popleft() if self.queue else None
                    if self.queue:
                        self.wake.set()
                if item is None:
                    continue
                result = self._process(item)
                with self.lock:
                    # No late result after close, overflow or newer queued input.
                    if not self.retired.is_set() and not self.queue:
                        self.output = result
        except Exception as error:
            self._retire(type(error).__name__+': '+str(error)[:160])
        finally:
            self._cleanup()
            with self.lock:
                self.queue.clear()
                self.output = None
            self.done.set()

    def _take(self):
        if self.retired.is_set():
            return None
        if not self.lock.acquire(blocking=False):
            return None
        try:
            value, self.output = self.output, None
            return None if self.retired.is_set() else value
        finally:
            self.lock.release()

    def close(self, timeout_sec=.1):
        if type(timeout_sec) not in (int, float) or not 0 <= timeout_sec <= 1:
            raise ValueError('finite close timeout within [0,1] required')
        self._retire('closed')
        if self.lock.acquire(blocking=False):
            try:
                self.queue.clear()
                self.output = None
            finally:
                self.lock.release()
        self.thread.join(timeout_sec)
        # Hung codec may still own one bounded job. Never claim it stopped.
        return self.done.is_set()

    def _cleanup(self):
        pass


class _EncodeWorker(_InboxWorker):
    def __init__(self, message_bytes):
        super().__init__(1, 'frame-packet-encode')
        self.message_bytes = message_limit(message_bytes)
        self.thread.start()

    def submit(self, image, candidate):
        """Producer-only: bounded copy/check, NOT a camera/RTC event callback."""
        if self.retired.is_set():
            return False
        try:
            native_frame(image)
            value = checked_candidate(candidate)
        except (ValueError, TypeError, KeyError, OverflowError):
            self._retire('invalid_source_submission')
            return False
        return self._offer((image.copy(), value), latest=True)

    def _process(self, item):
        return fragment_plan(encode_packet(*item), message_bytes=self.message_bytes)


class FramePacketChannelSender:
    """Single channel-owner pump + one independent bounded codec worker.

    Call pump periodically on the channel's event-loop thread (bounded budget).
    No timer, executor, automatic reconnect, ROS output or existing channel edit.
    """
    def __init__(self, channel, *, sender_id, stream_id, message_bytes,
                 max_capture_age_sec, max_buffered_bytes, clock=time.monotonic):
        if (channel.label != PROTOCOL or channel.protocol != PROTOCOL
                or channel.ordered is not False or type(channel.maxRetransmits) is not int
                or channel.maxRetransmits != 0
                or channel.maxPacketLifeTime is not None):
            raise ValueError('explicit independent unordered no-retry packet channel required')
        self.owner, self.channel, self.clock = threading.get_ident(), channel, clock
        self.scheduler = LatestPacketSender(sender_id=sender_id, stream_id=stream_id,
            message_bytes=message_bytes, max_capture_age_sec=max_capture_age_sec,
            max_buffered_bytes=max_buffered_bytes)
        self.worker = _EncodeWorker(message_bytes)
        self.closed = False
        self.error = None
        self.messages_sent = 0

    def _owner(self):
        if threading.get_ident() != self.owner:
            raise RuntimeError('channel operations must stay on their owner thread')

    def submit(self, image, candidate):
        return False if self.closed else self.worker.submit(image, candidate)

    def pump(self, *, budget=8):
        self._owner()
        if type(budget) is not int or not 1 <= budget <= 32:
            raise ValueError('bounded pump budget required')
        if self.closed:
            return 0
        if self.worker.retired.is_set():
            self.error = self.worker.error
            self.close(timeout_sec=0)
            return 0
        sent = 0
        try:
            state = self.channel.readyState
            if state == 'connecting':
                return 0
            if state != 'open':
                raise ValueError('packet channel unavailable')
            now = self.clock()
            plan = self.worker._take()
            if plan is not None:
                self.scheduler._offer_prepared(plan, now=now)
            for _ in range(budget):
                if self.channel.readyState != 'open':
                    raise ValueError('packet channel closed during pump')
                amount = self.channel.bufferedAmount
                if type(amount) is not int or not 0 <= amount < 2**63:
                    raise ValueError('invalid packet channel buffer amount')
                message = self.scheduler.next_fragment(now=self.clock(),
                    buffered_amount=amount, channel_open=self.channel.readyState == 'open')
                if self.scheduler.closed:
                    raise ValueError('sender clock retired')
                if message is None:
                    break
                self.channel.send(message)
                sent += 1
                self.messages_sent += 1
        except Exception as error:
            self.error = type(error).__name__+': '+str(error)[:160]
            self.close(timeout_sec=0)
        return sent

    def close(self, timeout_sec=.1):
        self._owner()
        self.closed = True
        self.scheduler.close()
        done = self.worker.close(timeout_sec)
        try:
            self.channel.close()  # Only this explicitly supplied channel, never peer/control.
        except Exception as error:
            self.error = self.error or type(error).__name__+': channel close failed'
        return done


class FramePacketReceiveWorker(_InboxWorker):
    """Non-waiting binary ingress; all assembly/codec state belongs to worker.

    Consumer take() is one-shot and checks the FIRST-fragment local deadline.
    It does not prove source observation freshness or compare PC clocks.
    """
    def __init__(self, *, sender_id, stream_id, message_bytes, timeout_sec,
                 inbox_capacity=128, clock=time.monotonic):
        if type(inbox_capacity) is not int or not 1 <= inbox_capacity <= 128:
            raise ValueError('bounded message inbox required')
        super().__init__(inbox_capacity, 'frame-packet-decode')
        self.message_bytes, self.timeout = message_limit(message_bytes), age_limit(timeout_sec)
        self.clock, self.last_ingress, self.last_take = clock, None, None
        self.last_processing = None
        self.assembler = PacketReassembler(sender_id=sender_id, stream_id=stream_id,
            message_bytes=message_bytes, timeout_sec=timeout_sec)
        self.decoder = FramePacketReceiver(sender_id=sender_id, stream_id=stream_id,
            max_receive_age_sec=timeout_sec)
        self.thread.start()

    def offer_message(self, message):
        """RTC callback entry: bounded bytes/clock/queue only, no parsing/copy/IO."""
        if self.retired.is_set():
            return False
        try:
            now = self.clock()
        except Exception:
            self._retire('ingress_clock_failed')
            return False
        if (type(message) is not bytes or not 0 < len(message) <= self.message_bytes
                or not clock_time(now) or self.last_ingress is not None and now < self.last_ingress):
            self._retire('invalid_ingress_or_clock')
            return False
        self.last_ingress = now  # Exactly one channel-owner ingress producer.
        return self._offer((message, now))

    def _process(self, item):
        message, received = item
        self.assembler.accept(message, received_at_sec=received)
        # Assembly order uses ARRIVAL times, not alternating old queued arrival
        # and current processing time (which would invent clock reversal).
        packet = self.assembler.take(received)
        if self.assembler.closed:
            raise ValueError('receiver clock retired')
        before = self._processing_now()
        if before < received:
            raise ValueError('receiver clock reversed before decode')
        if packet is None:
            return None
        if before > packet.deadline_sec:
            return None
        decoded = self.decoder.accept(packet.wire, received_at_sec=packet.first_received_at_sec)
        now = self._processing_now()
        if now > packet.deadline_sec:
            self.decoder.latest = None
            return None
        return decoded, packet.deadline_sec, now

    def _processing_now(self):
        now = self.clock()
        if (not clock_time(now) or self.last_processing is not None and now < self.last_processing):
            raise ValueError('receiver processing clock reversed')
        self.last_processing = now
        return now

    def take(self):
        result = self._take()
        try:
            now = self.clock()  # Sample AFTER handoff, not before a racing decode.
        except Exception:
            self._retire('consumer_clock_failed')
            return None
        if not clock_time(now) or self.last_take is not None and now < self.last_take:
            self._retire('consumer_clock_reversed')
            return None
        self.last_take = now
        if result is None:
            return None
        decoded, deadline, completed = result
        if now < completed:
            self._retire('consumer_clock_before_decode_completion')
            return None
        if now > deadline:
            return None
        return decoded

    def _cleanup(self):
        self.assembler.close()
        self.decoder.close()
