#!/bin/bash
# led_breath.sh — 呼吸灯效果 on LED1 (Linux side, sysfs)
# Smoothly fades LED1 from off to bright and back, simulating breathing.
# Run in background: nohup ./bin/led_breath.sh > /tmp/led_breath.log 2>&1 &
# To stop: kill $(pgrep -f led_breath)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
VENV_PYTHON="${PROJECT_DIR}/.venv/bin/python"
PYTHON="${VENV_PYTHON}"
[ -x "${PYTHON}" ] || PYTHON="python3"

cd "${PROJECT_DIR}"

# LED1 sysfs paths
LED1_R="/sys/class/leds/red:user/brightness"
LED1_G="/sys/class/leds/green:user/brightness"
LED1_B="/sys/class/leds/blue:user/brightness"

STEP_DELAY=0.02  # 20ms per step
BREATHE_STEPS=50  # steps per ramp (up or down)

cleanup() {
  # Turn LED1 off on exit
  echo 0 > "$LED1_R" 2>/dev/null || true
  echo 0 > "$LED1_G" 2>/dev/null || true
  echo 0 > "$LED1_B" 2>/dev/null || true
  exit 0
}

trap cleanup SIGTERM SIGINT

# Colors to breathe through (R G B)
COLORS=(
  "255 0 0"      # red
  "0 255 0"      # green
  "0 0 255"      # blue
  "255 255 255"  # white
)

NUM_COLORS=${#COLORS[@]}
COLOR_IDX=0

while true; do
  RGB=(${COLORS[$COLOR_IDX]})
  TARGET_R=${RGB[0]}
  TARGET_G=${RGB[1]}
  TARGET_B=${RGB[2]}

  # Breathe in (fade up)
  for step in $(seq 0 $BREATHE_STEPS); do
    val=$(echo "scale=2; $step / $BREATHE_STEPS" | bc)
    r=$(echo "$val * $TARGET_R / 1" | bc 2>/dev/null || echo 0)
    g=$(echo "$val * $TARGET_G / 1" | bc 2>/dev/null || echo 0)
    b=$(echo "$val * $TARGET_B / 1" | bc 2>/dev/null || echo 0)
    echo "$r" > "$LED1_R" 2>/dev/null || true
    echo "$g" > "$LED1_G" 2>/dev/null || true
    echo "$b" > "$LED1_B" 2>/dev/null || true
    sleep "$STEP_DELAY"
  done

  # Breathe out (fade down)
  for step in $(seq $BREATHE_STEPS -1 0); do
    val=$(echo "scale=2; $step / $BREATHE_STEPS" | bc)
    r=$(echo "$val * $TARGET_R / 1" | bc 2>/dev/null || echo 0)
    g=$(echo "$val * $TARGET_G / 1" | bc 2>/dev/null || echo 0)
    b=$(echo "$val * $TARGET_B / 1" | bc 2>/dev/null || echo 0)
    echo "$r" > "$LED1_R" 2>/dev/null || true
    echo "$g" > "$LED1_G" 2>/dev/null || true
    echo "$b" > "$LED1_B" 2>/dev/null || true
    sleep "$STEP_DELAY"
  done

  # Next color
  COLOR_IDX=$(( (COLOR_IDX + 1) % NUM_COLORS ))
done
