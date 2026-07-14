#!/bin/bash

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR" || exit 1

VENV_PYTHON="${DIR}/theta-env/bin/python"
if [ -f "${VENV_PYTHON}" ]; then
    PYTHON_CMD="${VENV_PYTHON}"
else
    PYTHON_CMD="python3"
fi

echo "[INFO] Starting WebRTC Receiver UI (DataChannel, low-latency layout)..."
echo "[INFO] Running webrtc_receive_ui.py using ${PYTHON_CMD}"

# Run new low-latency receiver UI
${PYTHON_CMD} webrtc_receive_ui.py \
    --cam-width 1920 \
    --cam-height 960 \
    --front-width 1120 \
    --front-height 720 \
    --front-fov 100.0 \
    --rear-width 560 \
    --rear-height 135 \
    --rear-fov 110.0 \
    --mirror-width 210 \
    --mirror-height 250 \
    --mirror-fov 90.0 \
    --left-mirror-yaw -135.0 \
    --right-mirror-yaw 135.0 \
    --front-lens "left" \
    --roll 0.0 \
    --max-speed 120.0 \
    --speed-scale 12.0
