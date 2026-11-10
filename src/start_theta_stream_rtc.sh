#!/bin/bash

# Opt-in read-only diagnostic path. Normal driver streaming below is unchanged.
if [ "${1:-}" = "--diagnostic" ]; then
    shift
    DIAG_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    DIAG_PYTHON="${THETA_RTC_PYTHON:-python3}"
    exec "$DIAG_PYTHON" "$DIAG_DIR/theta_rtc_diagnostic.py" send "$@"
fi

# Native measurement input WITH the existing driver ROS/control DataChannels.
if [ "${1:-}" = "--motion-native" ]; then
    shift
    MOTION_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    if [ -n "${THETA_RTC_PYTHON:-}" ]; then
        MOTION_STREAM_PYTHON="$THETA_RTC_PYTHON"
    elif [ -x "$MOTION_SCRIPT_DIR/../theta-env/bin/python" ]; then
        MOTION_STREAM_PYTHON="$MOTION_SCRIPT_DIR/../theta-env/bin/python"
    else
        MOTION_STREAM_PYTHON="python3"
    fi
    exec "$MOTION_STREAM_PYTHON" "$MOTION_SCRIPT_DIR/webrtc_stream.py" \
        --cam-width 1280 --cam-height 720 --motion-native "$@"
fi

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
    --cam-width 1920 \
    --cam-height 960 \
    --fps 24 \
    --bitrate "$BITRATE" \
    --telemetry-hz 24 \
    --odom-topic "/odom" \
    --mode-topic "/handle/drive_mode" \
    --page-delta-topic "/handle/page_delta" \
    --battery-topic "/sensors/core" \
    --imu-topic "/sensors/imu_data_raw" \
    --pedal-topic "/cmd_vel"
