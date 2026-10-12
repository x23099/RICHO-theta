#!/usr/bin/env bash
set -euo pipefail
CONE_REPO_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
CONE_VENV_DIR="${CONE_REPO_DIR}/yolo-env"
CONE_TORCH_INDEX=""
if [[ -L "$CONE_VENV_DIR" ]]; then
  echo "Refusing a symlinked yolo-env; keep the training environment separate from ROS." >&2
  exit 2
fi
if [[ $# -gt 0 ]]; then
  if [[ $# -ne 2 || "$1" != "--torch-index-url" ]]; then
    echo "Usage: $0 [--torch-index-url https://download.pytorch.org/whl/cuXXX]" >&2
    exit 2
  fi
  CONE_TORCH_INDEX="$2"
  if [[ ! "$CONE_TORCH_INDEX" =~ ^https://download\.pytorch\.org/whl/cu[0-9]+$ ]]; then
    echo "Use an official CUDA wheel URL selected from pytorch.org; CPU-only URL is not accepted." >&2
    exit 2
  fi
fi
if [[ -e "$CONE_VENV_DIR" && ! -f "$CONE_VENV_DIR/pyvenv.cfg" ]]; then
  echo "Target exists but is not a virtual environment: $CONE_VENV_DIR" >&2
  exit 2
fi
python3 -m venv "$CONE_VENV_DIR"
CONE_PYTHON="$CONE_VENV_DIR/bin/python3"
"$CONE_PYTHON" -m pip install --upgrade pip
if [[ -n "$CONE_TORCH_INDEX" ]]; then
  "$CONE_PYTHON" -m pip install --upgrade torch torchvision --index-url "$CONE_TORCH_INDEX"
else
  "$CONE_PYTHON" -m pip install --upgrade torch torchvision
fi
"$CONE_PYTHON" -m pip install -r "$CONE_REPO_DIR/requirements-yolo.txt"
echo "[INFO] Environment prepared. Run start_cone_yolo.sh env on the GPU PC to verify CUDA and model loading."
