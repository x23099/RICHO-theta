#!/usr/bin/env bash

set -u
set -o pipefail

usage() {
    cat <<'EOF'
Usage:
  ./start_recording_analysis.sh INPUT.tar.xz [OUTPUT_DIR] [ANALYZER_OPTIONS...]

Examples:
  ./start_recording_analysis.sh ~/Downloads/recoding/recording.tar.xz

  ./start_recording_analysis.sh ~/Downloads/recoding/recording.tar.xz \
    Experimental_results/2026-09-03/example \
    --config src/bird_eye_config_ttc_conservative_candidate_20260903.json \
    --dynamic-ttc-profile src/dynamic_ttc_evaluation_profile_v5_candidate.json

The output directory defaults to:
  Experimental_results/YYYY-MM-DD/<archive-name>_analysis

Options after OUTPUT_DIR are passed to src/analyze_field_recording.py.
Set PYTHON_BIN to select a Python interpreter. The script never accesses a
camera, ROS, Kobuki, or a steering-wheel device.
EOF
}

if [[ ${1:-} == "-h" || ${1:-} == "--help" ]]; then
    usage
    exit 0
fi

if [[ $# -lt 1 ]]; then
    usage >&2
    exit 2
fi

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$script_dir" || exit 2

input_path="$1"
shift

archive_name="$(basename "$input_path")"
archive_stem="${archive_name%.tar.xz}"
if [[ "$archive_stem" == "$archive_name" ]]; then
    echo "[ERROR] INPUT must have a .tar.xz extension: $input_path" >&2
    exit 2
fi

if [[ $# -gt 0 && ${1:0:1} != "-" ]]; then
    output_dir="$1"
    shift
else
    output_dir="Experimental_results/$(date +%F)/${archive_stem}_analysis"
fi

python_bin="${PYTHON_BIN:-python3}"
if ! command -v "$python_bin" >/dev/null 2>&1; then
    echo "[ERROR] Python interpreter not found: $python_bin" >&2
    exit 2
fi

echo "[INFO] Input: $input_path"
echo "[INFO] Output: $output_dir"
echo "[INFO] Running standard recording analysis..."

"$python_bin" src/analyze_field_recording.py \
    --input "$input_path" \
    --output-dir "$output_dir" \
    "$@"
analysis_status=$?

if [[ $analysis_status -gt 1 ]]; then
    echo "[ERROR] Standard analysis could not be completed." >&2
    exit "$analysis_status"
fi

echo "[INFO] Replaying collision states as virtual FFB demand..."
"$python_bin" src/virtual_ffb.py \
    --input "$input_path" \
    --output "$output_dir/virtual_ffb_replay.csv"
ffb_status=$?

if [[ $ffb_status -ne 0 ]]; then
    exit "$ffb_status"
fi

echo "[INFO] Analysis finished: $output_dir"
exit "$analysis_status"
