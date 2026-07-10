#!/bin/bash

UI_DIR="$(cd "$(dirname "$0")" && pwd)"
UI_SCRIPT="zc33s_ui.py"

WINDOW_NAME="THETA S Driver View with Classic Analog Cluster"
RECEIVER_IP="${1:-150.89.169.70}"
CAMERA_DEVICE="${2:-/dev/video0}"
SCREEN_SIZE="${3:-large}"  # standard (large) or small (1024x768 optimized)

DISPLAY_ID="${DISPLAY:-:1.0}"
BITRATE="${4:-30M}"

UI_ARGS=(
    "--device" "$CAMERA_DEVICE"
    "--cam-width" "1280"
    "--cam-height" "720"
    "--odom-topic" "/odom"
    "--speed-topic" "/cmd_vel"
    "--speed-msg-type" "twist"
)

# 1024x768の小さなモニター用に解像度を縮小するオプション
if [ "$SCREEN_SIZE" = "small" ] || [ "$SCREEN_SIZE" = "1024" ]; then
    echo "[INFO] Applying small monitor optimization (800x450 front view)"
    UI_ARGS+=(
        "--front-width" "800"
        "--front-height" "450"
        "--rear-width" "400"
        "--rear-height" "95"
    )
else
    echo "[INFO] Applying standard large monitor layout (default sizes)"
fi

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

# Get the actual size of the window dynamically.
WINDOW_SIZE=$(xdotool getwindowgeometry "$WINDOW_ID" | grep Geometry | awk '{print $2}')
if [ -z "$WINDOW_SIZE" ]; then
    WINDOW_SIZE="1280x720"
fi

echo "[INFO] Window Size: $WINDOW_SIZE"
echo "[INFO] Streaming via WebRTC to $RECEIVER_IP"

python3 webrtc_stream.py --receiver-ip "$RECEIVER_IP" --window-id "$WINDOW_ID" --display "$DISPLAY_ID" --bitrate "$BITRATE" --video-size "$WINDOW_SIZE"

echo "[INFO] Stream stopped."
