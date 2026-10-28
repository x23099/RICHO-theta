#!/bin/bash
# Read-only cone diagnostics; never starts ROS / a robot / FFB.
set -euo pipefail
DISTANCE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DISTANCE_PYTHON="${THETA_DISTANCE_PYTHON:-python3}"
DISTANCE_MODE="${1:---help}"
case "$DISTANCE_MODE" in
  replay)
    shift
    exec "$DISTANCE_PYTHON" "$DISTANCE_DIR/src/run_cone_distance_replay.py" "$@"
    ;;
  receive)
    shift
    exec "$DISTANCE_PYTHON" "$DISTANCE_DIR/src/run_cone_distance_live.py" "$@"
    ;;
  report)
    shift
    exec "$DISTANCE_PYTHON" "$DISTANCE_DIR/src/summarize_cone_distance_live.py" "$@"
    ;;
  *)
    echo "Usage: bash start_cone_distance.sh {replay|receive|report} --help"
    if [ "$DISTANCE_MODE" != "--help" ]; then exit 2; fi
    ;;
esac
