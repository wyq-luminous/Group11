#!/bin/bash
# matrix_clear.sh — Clear the LED matrix (all pixels off).
#
# Usage:
#   ./bin/matrix_clear.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
VENV_PYTHON="${PROJECT_DIR}/.venv/bin/python"
PYTHON="${VENV_PYTHON}"
[ -x "${PYTHON}" ] || PYTHON="python3"

cd "${PROJECT_DIR}"

exec "${PYTHON}" -c "
import sys
sys.path.insert(0, '${PROJECT_DIR}')
from backend.hw import matrix_clear
try:
    matrix_clear()
    print('Matrix cleared.')
except Exception as e:
    print(f'ERROR: {e}', file=sys.stderr)
    sys.exit(1)
"
