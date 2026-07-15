#!/bin/bash
# status.sh — Print UNO-Q system status for Hermes CLI consumption.
#
# Usage:
#   ./bin/status.sh           # Text format (for human / Hermes)
#   ./bin/status.sh --json    # JSON format (for programmatic use)
#
# Hermes calls this via --no-agent --script mode:
#   hermes cron create "every 30m" --no-agent --script /path/to/bin/status.sh --deliver weixin

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
VENV_PYTHON="${PROJECT_DIR}/.venv/bin/python"

# Fallback to system python if venv not yet bootstrapped
if [ -x "${VENV_PYTHON}" ]; then
    PYTHON="${VENV_PYTHON}"
else
    PYTHON="python3"
fi

cd "${PROJECT_DIR}"

if [ "${1:-}" = "--json" ]; then
    exec "${PYTHON}" -c "
import json
from backend.sysinfo import get_full_status
print(json.dumps(get_full_status(), indent=2))
"
else
    exec "${PYTHON}" -c "
from backend.sysinfo import get_full_status, format_status_text
print(format_status_text(get_full_status()))
"
fi
