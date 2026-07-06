#!/bin/bash

UI_DIR="$(cd "$(dirname "$0")" && pwd)"
UI_SCRIPT="zc33s_ui.py"

WINDOW_NAME="THETA S Driver View with Classic Analog Cluster"
RECEIVER_IP="${1:-150.89.169.70}"

DISPLAY_ID="${DISPLAY:-:1.0}"
BITRATE="1500k"

UI_ARGS=(
    "--device" "/dev/video0"
    "--cam-width" "1280"
    "--cam-height" "720"
    "--odom-topic" "/odom"
    "--speed-topic" "/cmd_vel"
    "--speed-msg-type" "twist"
)

echo "[INFO] Starting THETA UI..."

cd "$UI_DIR" || {
    echo "[ERROR] UI directory not found: $UI_DIR"
    exit 1
}

python3 "$UI_SCRIPT" "${UI_ARGS[@]}" &
UI_PID=$!

echo "[INFO] UI PID: $UI_PID"
echo "[INFO] Waiting for UI window..."

WINDOW_ID=""

for i in {1..30}; do
    WINDOW_ID=$(xdotool search --name "$WINDOW_NAME" | head -n 1)

    if [ -n "$WINDOW_ID" ]; then
        break
    fi

    sleep 1
done

if [ -z "$WINDOW_ID" ]; then
    echo "[ERROR] UI window not found: $WINDOW_NAME"
    kill "$UI_PID" 2>/dev/null
    exit 1
fi

echo "[INFO] Found window ID: $WINDOW_ID"
echo "[INFO] Streaming via WebRTC to $RECEIVER_IP"

python3 webrtc_stream.py --receiver-ip "$RECEIVER_IP" --window-id "$WINDOW_ID" --display "$DISPLAY_ID" --bitrate "$BITRATE"

echo "[INFO] Stream stopped."
