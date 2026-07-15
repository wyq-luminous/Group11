#!/bin/bash
# led_chase.sh — LED running/chase effect (流水灯)
#
# Usage:
#   ./bin/led_chase.sh                     # chase mode, default speed
#   ./bin/led_chase.sh --mode rainbow      # rainbow mode
#   ./bin/led_chase.sh --mode breathe      # breathing mode
#   ./bin/led_chase.sh --speed 0.05        # faster
#
# Run in background:
#   nohup ./bin/led_chase.sh --mode rainbow > /tmp/led_chase.log 2>&1 &
#   # To stop: kill $(pgrep -f led_chase)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
VENV_PYTHON="${PROJECT_DIR}/.venv/bin/python"
PYTHON="${VENV_PYTHON}"
[ -x "${PYTHON}" ] || PYTHON="python3"

cd "${PROJECT_DIR}"
exec "${PYTHON}" "${PROJECT_DIR}/bin/led_chase.py" "$@"
