#!/usr/bin/env bash

set -o pipefail

usage() {
    cat <<'EOF'
Usage:
  FFB_INSTALL_SETUP=/path/to/yopi_ws/install/setup.bash \
    ./start_phase5_ffb_replay_dry_run.sh INPUT.tar.xz SESSION [OUTPUT_DIR]

Replays one recorded detections.csv through the same CollisionFfbPublisherBridge
used by bird_eye.py and an explicitly dry-run adapter. It never opens G923.
EOF
}

if [[ ${1:-} == "-h" || ${1:-} == "--help" ]]; then
    usage
    exit 0
fi
if [[ $# -lt 2 || $# -gt 3 ]]; then
    usage >&2
    exit 2
fi

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$script_dir" || exit 2

input_path="$1"
session="$2"
output_dir="${3:-Experimental_results/$(date +%F)/phase5_replay_$(date +%H%M%S)}"

if [[ ! -f /opt/ros/humble/setup.bash ]]; then
    echo "[ERROR] ROS 2 Humble setup not found" >&2
    exit 2
fi
source /opt/ros/humble/setup.bash

if ! ros2 pkg prefix oit_interfaces >/dev/null 2>&1 \
    || ! ros2 pkg prefix oit >/dev/null 2>&1; then
    if [[ -z ${FFB_INSTALL_SETUP:-} || ! -f ${FFB_INSTALL_SETUP:-} ]]; then
        echo "[ERROR] FFB packages are not sourced." >&2
        echo "Set FFB_INSTALL_SETUP to the FFB workspace install/setup.bash." >&2
        exit 2
    fi
    source "$FFB_INSTALL_SETUP"
fi
set -u

mkdir -p "$output_dir/ros_logs"
export ROS_LOG_DIR="$(cd "$output_dir/ros_logs" && pwd)"
adapter_log="$output_dir/adapter.log"

adapter_pid=""
stop_adapter() {
    if [[ -n "$adapter_pid" ]] && kill -0 "$adapter_pid" 2>/dev/null; then
        kill -INT "$adapter_pid" 2>/dev/null || true
        for _index in {1..20}; do
            kill -0 "$adapter_pid" 2>/dev/null || break
            sleep 0.05
        done
        if kill -0 "$adapter_pid" 2>/dev/null; then
            kill -TERM "$adapter_pid" 2>/dev/null || true
        fi
        wait "$adapter_pid" 2>/dev/null || true
    fi
    adapter_pid=""
}
trap stop_adapter EXIT INT TERM

echo "[INFO] Starting adapter with output_mode=dry_run"
bash -c 'trap - INT; exec ros2 run oit collision_ffb_node --ros-args \
    -p output_mode:=dry_run -p max_magnitude:=0.05' \
    >"$adapter_log" 2>&1 &
adapter_pid=$!
sleep 1

if ! kill -0 "$adapter_pid" 2>/dev/null; then
    echo "[ERROR] dry-run adapter exited during startup" >&2
    sed -n '1,160p' "$adapter_log" >&2
    exit 2
fi

python3 src/replay_collision_ffb_commands.py \
    --input "$input_path" \
    --session "$session" \
    --output-dir "$output_dir/replay" \
    --rate 30 \
    --expect-output-mode dry_run
replay_status=$?

stop_adapter
trap - EXIT INT TERM

echo "[INFO] Adapter log: $adapter_log"
echo "[INFO] Replay output: $output_dir/replay"
exit "$replay_status"
