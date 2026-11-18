#!/bin/bash

# Opt-in native intake; does not import the driver UI / ROS control bridge.
if [ "${1:-}" = "--diagnostic" ]; then
    shift
    DIAG_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    DIAG_PYTHON="${THETA_RTC_PYTHON:-python3}"
    exec "$DIAG_PYTHON" "$DIAG_DIR/theta_rtc_diagnostic.py" receive "$@"
fi

# Opt-in driver UI + independent GPU subprocess. NOT the diagnostic receiver.
if [ "${1:-}" = "--motion-distance" ]; then
    shift
    MOTION_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    MOTION_UI_PYTHON="${THETA_UI_PYTHON:-python3}"
    if [ -n "${THETA_UI_PYTHON:-}" ]; then
        # Respect an explicitly selected ROS/Qt Python instead of the UI's
        # legacy src/theta-env auto-reexec. The old launcher is unchanged.
        export THETA_UI_NO_VENV=1
    fi
    exec "$MOTION_UI_PYTHON" "$MOTION_SCRIPT_DIR/webrtc_receive_ui.py" \
        --cam-width 1280 --cam-height 720 --motion-distance "$@"
fi

# Opt-in transport-only PNG packet probe (no inference/ROS/FFB output).
if [ "${1:-}" = "--frame-packet-probe" ]; then
    shift
    PROBE_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    PROBE_DIR="${1:?existing probe output directory required}"
    shift
    PROBE_VENV="${PROBE_SCRIPT_DIR}/theta-env/bin/python"
    if [ -n "${THETA_UI_PYTHON:-}" ]; then
        PROBE_PYTHON="${THETA_UI_PYTHON}"
        export THETA_UI_NO_VENV=1
    elif [ -x "${PROBE_VENV}" ]; then
        PROBE_PYTHON="${PROBE_VENV}"
    else
        PROBE_PYTHON="python3"
    fi
    exec "$PROBE_PYTHON" "$PROBE_SCRIPT_DIR/webrtc_receive_ui.py" \
        --cam-width 1280 --cam-height 720 \
        --frame-packet-probe-dir "$PROBE_DIR" "$@"
fi

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
