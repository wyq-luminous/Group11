#!/bin/bash
# matrix_animation.sh — Start an animation on the LED matrix.
#
# Usage:
#   ./bin/matrix_animation.sh <animation_name>
#
# Valid animations: walker (4-frame walking stick figure)
#
# Hermes calls this via --no-agent --script mode.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
VENV_PYTHON="${PROJECT_DIR}/.venv/bin/python"
PYTHON="${VENV_PYTHON}"
[ -x "${PYTHON}" ] || PYTHON="python3"

ANIM="${1:-}"

if [ -z "${ANIM}" ]; then
    echo "Usage: $0 <animation>"
    echo "Valid animations: walker"
    exit 1
fi

cd "${PROJECT_DIR}"

export MATRIX_ANIM="${ANIM}"
export PROJECT_DIR

exec "${PYTHON}" -c "
import os, sys
sys.path.insert(0, os.environ['PROJECT_DIR'])
from backend.hw import matrix_show_animation
anim = os.environ.get('MATRIX_ANIM', '')
try:
    matrix_show_animation(anim)
    print(f'Animation started: {anim}')
except Exception as e:
    print(f'ERROR: {e}', file=sys.stderr)
    sys.exit(1)
"
