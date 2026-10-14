#!/usr/bin/env bash
set -euo pipefail
CONE_REPO_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
CONE_PYTHON="${CONE_PYTHON:-${CONE_REPO_DIR}/yolo-env/bin/python3}"
if [[ ! -x "$CONE_PYTHON" ]]; then
  echo "YOLO Python not found: $CONE_PYTHON. Run setup_cone_yolo.sh on the GPU PC first." >&2
  exit 2
fi
if [[ "${1:-}" == "video" ]]; then
  exec "$CONE_PYTHON" "$CONE_REPO_DIR/src/run_cone_video.py" "$@"
fi
exec "$CONE_PYTHON" "$CONE_REPO_DIR/src/run_cone_yolo.py" "$@"
