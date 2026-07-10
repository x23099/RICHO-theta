import argparse
import asyncio
import json
import logging
import os
import sys
import aiohttp
import socket
import io
import av
from aiortc import RTCPeerConnection, RTCSessionDescription, MediaStreamTrack
from av import VideoFrame

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("webrtc_stream")


class SocketVideoTrack(MediaStreamTrack):
    kind = "video"

    def __init__(self, port=9999):
        super().__init__()
        self.port = port
        self.sock = None
        self.buffer = b""
        self._connect()

    def _connect(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            self.sock.connect(("127.0.0.1", self.port))
            self.sock.setblocking(False)
            logger.info(f"Connected to UI image socket on port {self.port}")
        except Exception as e:
            logger.error(f"Failed to connect to UI socket on port {self.port}: {e}")
            self.sock = None

    async def recv(self):
        pts, time_base = await self.next_timestamp()

        if self.sock is None:
            self._connect()
            if self.sock is None:
                await asyncio.sleep(0.04)
                return self._create_dummy_frame(pts, time_base)

        loop = asyncio.get_event_loop()

        try:
            while len(self.buffer) < 4:
                data = await loop.run_in_executor(None, self._recv_chunk, 4096)
                if not data:
                    raise ConnectionError("Socket closed")
                self.buffer += data

            length = int.from_bytes(self.buffer[:4], byteorder="big")
            self.buffer = self.buffer[4:]

            while len(self.buffer) < length:
                data = await loop.run_in_executor(None, self._recv_chunk, min(4096, length - len(self.buffer)))
                if not data:
                    raise ConnectionError("Socket closed")
                self.buffer += data

            jpeg_data = self.buffer[:length]
            self.buffer = self.buffer[length:]

            # PyAVでJPEGメモリデータを高速デコード
            container = av.open(io.BytesIO(jpeg_data), format="mjpeg")
            frame = next(container.decode(video=0))
            frame.pts = pts
            frame.time_base = time_base
            container.close()
            return frame

        except Exception as e:
            import traceback
            logger.warn(f"Socket receive/decode error: {e}, reconnecting...")
            traceback.print_exc()
            if self.sock:
                try:
                    self.sock.close()
                except Exception:
                    pass
                self.sock = None
            await asyncio.sleep(0.04)
            return self._create_dummy_frame(pts, time_base)

    def _recv_chunk(self, size):
        try:
            self.sock.setblocking(True)
            return self.sock.recv(size)
        except Exception:
            return b""

    def _create_dummy_frame(self, pts, time_base):
        # 接続待ちの間のダミー黒画面フレームを作成
        frame = VideoFrame(width=800, height=450)
        # 黒でクリア(YUV)
        for plane in frame.planes:
            pass
        frame.pts = pts
        frame.time_base = time_base
        return frame


async def run(receiver_ip, window_id, display_id, bitrate, video_size):
    logger.info(f"Setting up WebRTC Stream using Image Socket (Port 9999)...")
    
    # x11grabの代わりにローカルソケットから画像を受け取るカスタムトラックを使用
    video_track = SocketVideoTrack(port=9999)

    from aiortc import RTCRtpSender

    pc = RTCPeerConnection()
    
    # Video トラックをトランスシーバー経由で追加し、VP8 コーデックを優先設定する
    transceiver = pc.addTransceiver(video_track, direction="sendonly")
    capabilities = RTCRtpSender.getCapabilities("video")
    vp8_codecs = [c for c in capabilities.codecs if c.name == "VP8"]
    if vp8_codecs:
        try:
            transceiver.setCodecPreferences(vp8_codecs)
            logger.info("Enforced VP8 codec preference for ultra-low latency")
        except Exception as e:
            logger.warn(f"Failed to set codec preferences: {e}")
    
    # Parse bitrate string (e.g. 1500k, 4M) to integer bps.
    bitrate_bps = 1500000
    try:
        if str(bitrate).endswith("k"):
            bitrate_bps = int(bitrate[:-1]) * 1000
        elif str(bitrate).endswith("M"):
            bitrate_bps = int(bitrate[:-1]) * 1000000
        else:
            bitrate_bps = int(bitrate)
    except Exception:
        logger.warn(f"Failed to parse bitrate '{bitrate}', using default 1.5 Mbps")

    # Define SDP munge function to enforce bitrate.
    def munge_sdp_bitrate(sdp, bps):
        kbps = int(bps / 1000)
        lines = sdp.split("\r\n")
        new_lines = []
        for line in lines:
            new_lines.append(line)
            if line.startswith("m=video"):
                new_lines.append(f"b=AS:{kbps}")
        return "\r\n".join(new_lines)

    # Create SDP Offer.
    offer = await pc.createOffer()
    
    # Apply munged SDP with custom bitrate.
    munged_sdp = munge_sdp_bitrate(offer.sdp, bitrate_bps)
    offer = RTCSessionDescription(sdp=munged_sdp, type=offer.type)
    
    await pc.setLocalDescription(offer)
    logger.info(f"Configured WebRTC offer with max bitrate to {bitrate_bps / 1000:.0f} kbps")
    
    # Wait for ICE gathering to complete so SDP has all local candidates.
    logger.info("Gathering ICE candidates...")
    while pc.iceGatheringState != "complete":
        await asyncio.sleep(0.1)
    
    local_sdp = pc.localDescription
    
    # Post the offer to the receiver's HTTP server.
    receiver_url = f"http://{receiver_ip}:5002/offer"
    logger.info(f"Sending SDP Offer to {receiver_url}...")
    
    payload = {
        "sdp": local_sdp.sdp,
        "type": local_sdp.type
    }
    
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(receiver_url, json=payload) as response:
                if response.status != 200:
                    logger.error(f"Failed to send offer. Receiver returned status {response.status}")
                    return
                
                answer_data = await response.json()
                logger.info("Received SDP Answer from receiver")
                
                answer = RTCSessionDescription(
                    sdp=answer_data["sdp"],
                    type=answer_data["type"]
                )
                
                await pc.setRemoteDescription(answer)
                logger.info("Remote description set successfully. WebRTC connection establishing...")
        except Exception as e:
            logger.error(f"Error during signaling POST: {e}")
            return

    # Keep connection alive.
    try:
        while True:
            if pc.connectionState == "failed":
                logger.error("WebRTC connection failed. Exiting.")
                break
            await asyncio.sleep(1)
    except asyncio.CancelledError:
        pass
    finally:
        logger.info("Closing peer connection...")
        await pc.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="WebRTC Video Streamer")
    parser.add_argument("--receiver-ip", default="127.0.0.1", help="Receiver IP address")
    parser.add_argument("--window-id", help="Window ID to grab")
    parser.add_argument("--display", default=":1.0", help="X11 Display ID")
    parser.add_argument("--bitrate", default="1500k", help="Video Bitrate")
    parser.add_argument("--video-size", default="1280x720", help="Video capture size (e.g., 1450x1080)")
    
    args = parser.parse_args()
    
    display = args.display
    if not display and "DISPLAY" in os.environ:
        display = os.environ["DISPLAY"]
        
    asyncio.run(run(args.receiver_ip, args.window_id, display, args.bitrate, args.video_size))
