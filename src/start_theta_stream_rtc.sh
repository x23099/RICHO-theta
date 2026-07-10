#!/bin/bash

# IP address of the receiver PC
RECEIVER_IP="${1:-150.89.169.70}"
# Camera device file
CAMERA_DEVICE="${2:-/dev/video0}"
# Transmission bitrate
BITRATE="${3:-15M}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR" || exit 1

VENV_PYTHON="${SCRIPT_DIR}/../theta-env/bin/python"
if [ -f "${VENV_PYTHON}" ]; then
    PYTHON_CMD="${VENV_PYTHON}"
else
    PYTHON_CMD="python3"
fi

echo "[INFO] Starting WebRTC Zero-copy Streamer..."
echo "[INFO] Receiver IP: $RECEIVER_IP"
echo "[INFO] Camera Device: $CAMERA_DEVICE"
echo "[INFO] Bitrate: $BITRATE"

# Run new low-latency integrated streamer
${PYTHON_CMD} webrtc_stream.py \
    --receiver-ip "$RECEIVER_IP" \
    --device "$CAMERA_DEVICE" \
    --cam-width 1280 \
    --cam-height 720 \
    --fps 24 \
    --bitrate "$BITRATE" \
    --telemetry-hz 24 \
    --odom-topic "/odom" \
    --mode-topic "/handle/drive_mode" \
    --page-delta-topic "/handle/page_delta" \
    --battery-topic "/sensors/core" \
    --imu-topic "/sensors/imu_data_raw" \
    --pedal-topic "/cmd_vel"
