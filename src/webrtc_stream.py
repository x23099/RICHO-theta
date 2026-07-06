import argparse
import asyncio
import json
import logging
import os
import sys
import aiohttp
from aiortc import RTCPeerConnection, RTCSessionDescription
from aiortc.contrib.media import MediaPlayer

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("webrtc_stream")

async def run(receiver_ip, window_id, display_id, bitrate, video_size):
    # FFmpeg x11grab options.
    options = {
        "video_size": video_size,
        "framerate": "30",
        "draw_mouse": "0"
    }
    if window_id:
        options["window_id"] = str(window_id)

    logger.info(f"Opening x11grab on display {display_id} (Window ID: {window_id}, Size: {video_size})")
    
    # Use PyAV's MediaPlayer to grab the display.
    player = MediaPlayer(display_id, format="x11grab", options=options)

    pc = RTCPeerConnection()
    
    # Add video track and configure maximum bitrate.
    sender = pc.addTrack(player.video)
    
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

    parameters = sender.getParameters()
    for encoding in parameters.encodings:
        encoding.maxBitrate = bitrate_bps
    await sender.setParameters(parameters)
    logger.info(f"Configured WebRTC encoder max bitrate to {bitrate_bps / 1000:.0f} kbps")
    
    # Create SDP Offer.
    offer = await pc.createOffer()
    await pc.setLocalDescription(offer)
    
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
