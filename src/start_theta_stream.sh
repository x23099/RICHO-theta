#!/bin/bash

UI_DIR="$HOME/theta_ws/src"
UI_SCRIPT="zc33s_ui.py"

WINDOW_NAME="THETA S Driver View with Classic Analog Cluster"
RECEIVER_IP="${1:-150.89.169.70}"
PORT="5000"

DISPLAY_ID="${DISPLAY:-:1.0}"

BITRATE="1500k"
MAXRATE="1500k"
BUFSIZE="300k"

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
echo "[INFO] Streaming to udp://$RECEIVER_IP:$PORT"

ffmpeg -f x11grab -framerate 30 -window_id "$WINDOW_ID" -i "$DISPLAY_ID" \
-vcodec libx264 -preset ultrafast -tune zerolatency \
-pix_fmt yuv420p \
-b:v "$BITRATE" -maxrate "$MAXRATE" -bufsize "$BUFSIZE" \
-g 30 -bf 0 -f mpegts udp://$RECEIVER_IP:$PORT

echo "[INFO] Stream stopped."