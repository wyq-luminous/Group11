#!/bin/bash
# matrix_pattern.sh — Show a named pattern on the LED matrix.
#
# Usage:
#   ./bin/matrix_pattern.sh <pattern_name>
#
# Valid patterns: warning, smiley, heart, cross, clear
#
# Hermes calls this via --no-agent --script mode.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
VENV_PYTHON="${PROJECT_DIR}/.venv/bin/python"
PYTHON="${VENV_PYTHON}"
[ -x "${PYTHON}" ] || PYTHON="python3"

PATTERN="${1:-}"

if [ -z "${PATTERN}" ]; then
    echo "Usage: $0 <pattern>"
    echo "Valid patterns: warning, smiley, heart, cross, clear"
    exit 1
fi

VALID="warning smiley heart cross clear"
if ! echo "${VALID}" | grep -qw "${PATTERN}"; then
    echo "ERROR: Unknown pattern '${PATTERN}'. Valid: ${VALID}"
    exit 1
fi

cd "${PROJECT_DIR}"

export MATRIX_PATTERN="${PATTERN}"
export PROJECT_DIR

exec "${PYTHON}" -c "
import os, sys
sys.path.insert(0, os.environ['PROJECT_DIR'])
from backend.hw import matrix_show_pattern
pattern = os.environ.get('MATRIX_PATTERN', 'clear')
try:
    matrix_show_pattern(pattern)
    print(f'Matrix now showing: {pattern}')
except Exception as e:
    print(f'ERROR: {e}', file=sys.stderr)
    sys.exit(1)
"
