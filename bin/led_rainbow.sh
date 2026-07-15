#!/bin/bash
# led_rainbow.sh — 多彩流水灯效果 (Colorful flowing water LED effect)
# Cycles all 4 LEDs through a rainbow with phase shift for flowing effect.
# Run in background: nohup ./bin/led_rainbow.sh > /tmp/led_rainbow.log 2>&1 &
# To stop: kill $(pgrep -f led_rainbow.sh)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
VENV_PYTHON="${PROJECT_DIR}/.venv/bin/python"
PYTHON="${VENV_PYTHON}"
[ -x "${PYTHON}" ] || PYTHON="python3"

cd "${PROJECT_DIR}"

# Rainbow color palette (R G B)
COLORS=(
  "255 0 0"      # red
  "255 128 0"    # orange
  "255 255 0"    # yellow
  "0 255 0"      # green
  "0 255 255"    # cyan
  "0 0 255"      # blue
  "255 0 255"    # magenta
)

NUM_COLORS=${#COLORS[@]}
INTERVAL=0.3  # seconds between shifts

# Phase offset per LED for flowing effect
# LED1 phase 0, LED2 phase 2, LED3 phase 4, LED4 phase 6
# This creates a diagonal rainbow effect that shifts

cleanup() {
  # Turn all LEDs off on exit
  for i in 1 2 3 4; do
    "${PYTHON}" -c "
import sys
sys.path.insert(0, '${PROJECT_DIR}')
from backend.hw import led_set
try:
    led_set($i, 'off')
    print(f'LED${i} off')
except Exception as e:
    pass
" 2>/dev/null || true
  done
  exit 0
}

trap cleanup SIGTERM SIGINT

# Main loop
STEP=0
while true; do
  for i in 1 2 3 4; do
    # Phase offset: LED1=0, LED2=2, LED3=4, LED4=6
    PHASE=$(( (STEP + (i-1)*2) % NUM_COLORS ))
    RGB=(${COLORS[$PHASE]})
    R=${RGB[0]}
    G=${RGB[1]}
    B=${RGB[2]}
    
    "${PYTHON}" -c "
import sys
sys.path.insert(0, '${PROJECT_DIR}')
from backend.hw import led_set
try:
    led_set($i, 'off')
except:
    pass
from backend.hw import led_rgb
try:
    led_rgb($i, $R, $G, $B)
except Exception as e:
    pass
" 2>/dev/null &
  done
  
  wait
  sleep ${INTERVAL}
  STEP=$(( (STEP + 1) % NUM_COLORS ))
done
