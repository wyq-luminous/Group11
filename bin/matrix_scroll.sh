#!/bin/bash
# matrix_scroll.sh — Start scrolling text on the LED matrix.
#
# Usage:
#   ./bin/matrix_scroll.sh "Hello World"
#
# Hermes calls this via --no-agent --script mode.
# Output: confirmation text on stdout (delivered to user via Hermes).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
VENV_PYTHON="${PROJECT_DIR}/.venv/bin/python"
PYTHON="${VENV_PYTHON}"
[ -x "${PYTHON}" ] || PYTHON="python3"

TEXT="${1:-}"

if [ -z "${TEXT}" ]; then
    echo "Usage: $0 <text>"
    echo "Example: $0 \"Hello World\""
    exit 1
fi

# Truncate long text
MAX_LEN=120
if [ ${#TEXT} -gt ${MAX_LEN} ]; then
    TEXT="${TEXT:0:${MAX_LEN}}"
    echo "(text truncated to ${MAX_LEN} chars)" >&2
fi

cd "${PROJECT_DIR}"

# Pass text via environment variable to avoid shell escaping issues
export MATRIX_SCROLL_TEXT="${TEXT}"
export PROJECT_DIR

exec "${PYTHON}" -c "
import os, sys
sys.path.insert(0, os.environ['PROJECT_DIR'])
from backend.hw import matrix_scroll_text
text = os.environ.get('MATRIX_SCROLL_TEXT', '')
try:
    matrix_scroll_text(text)
    print(f'Matrix now scrolling: \"{text}\"')
except Exception as e:
    print(f'ERROR: {e}', file=sys.stderr)
    sys.exit(1)
"
