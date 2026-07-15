#!/bin/bash
# led_control.sh — Control board LEDs remotely.
#
# Usage:
#   ./bin/led_control.sh set <index> <on|off|blink>
#   ./bin/led_control.sh rgb  <index> <r> <g> <b>
#   ./bin/led_control.sh list
#
# LED1 and LED2 are Linux-side (sysfs), LED3 and LED4 are STM32-side (RPC).
# All four are RGB-capable.
#
# Hermes calls this via --no-agent --script mode.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
VENV_PYTHON="${PROJECT_DIR}/.venv/bin/python"
PYTHON="${VENV_PYTHON}"
[ -x "${PYTHON}" ] || PYTHON="python3"

CMD="${1:-}"
cd "${PROJECT_DIR}"

case "${CMD}" in
    set)
        INDEX="${2:-}"
        STATE="${3:-}"
        if [ -z "${INDEX}" ] || [ -z "${STATE}" ]; then
            echo "Usage: $0 set <index> <on|off|blink>"
            echo "  index: 1, 2 (Linux side) or 3, 4 (STM32 side)"
            exit 1
        fi
        # Validate inputs
        if ! [[ "${INDEX}" =~ ^[1-4]$ ]]; then
            echo "ERROR: Invalid LED index ${INDEX}. Must be 1-4."
            exit 1
        fi
        if ! echo "on off blink" | grep -qw "${STATE}"; then
            echo "ERROR: Invalid state '${STATE}'. Must be on, off, or blink."
            exit 1
        fi
        export LED_INDEX="${INDEX}"
        export LED_STATE="${STATE}"
        export PROJECT_DIR
        exec "${PYTHON}" -c "
import os, sys
sys.path.insert(0, os.environ['PROJECT_DIR'])
from backend.hw import led_set
idx = int(os.environ['LED_INDEX'])
state = os.environ['LED_STATE']
try:
    led_set(idx, state)
    print(f'LED{idx} -> {state}')
except Exception as e:
    print(f'ERROR: {e}', file=sys.stderr)
    sys.exit(1)
"
        ;;

    rgb)
        INDEX="${2:-}"
        R="${3:-}"
        G="${4:-}"
        B="${5:-}"
        if [ -z "${INDEX}" ] || [ -z "${R}" ] || [ -z "${G}" ] || [ -z "${B}" ]; then
            echo "Usage: $0 rgb <index> <r> <g> <b>"
            echo "  index: 1-4,  r/g/b: 0-255 each"
            exit 1
        fi
        # Validate inputs
        if ! [[ "${INDEX}" =~ ^[1-4]$ ]]; then
            echo "ERROR: Invalid LED index ${INDEX}. Must be 1-4."
            exit 1
        fi
        for val in "${R}" "${G}" "${B}"; do
            if ! [[ "${val}" =~ ^[0-9]+$ ]] || [ "${val}" -gt 255 ]; then
                echo "ERROR: RGB values must be 0-255, got ${val}"
                exit 1
            fi
        done
        export LED_INDEX="${INDEX}"
        export LED_R="${R}" LED_G="${G}" LED_B="${B}"
        export PROJECT_DIR
        exec "${PYTHON}" -c "
import os, sys
sys.path.insert(0, os.environ['PROJECT_DIR'])
from backend.hw import led_rgb
idx = int(os.environ['LED_INDEX'])
r = int(os.environ['LED_R'])
g = int(os.environ['LED_G'])
b = int(os.environ['LED_B'])
try:
    led_rgb(idx, r, g, b)
    print(f'LED{idx} -> RGB({r},{g},{b})')
except Exception as e:
    print(f'ERROR: {e}', file=sys.stderr)
    sys.exit(1)
"
        ;;

    list)
        export PROJECT_DIR
        exec "${PYTHON}" -c "
import os, sys
sys.path.insert(0, os.environ['PROJECT_DIR'])
from backend.hw import led_list_all
for info in led_list_all():
    side = info.get('side', '?')
    label = info.get('label', info.get('error', '?'))
    print(f'  LED{info[\"index\"]}: {side} side — {label}')
"
        ;;

    *)
        echo "Usage: $0 <command> [args...]"
        echo ""
        echo "Commands:"
        echo "  set <index> <on|off|blink>   Set LED state"
        echo "  rgb <index> <r> <g> <b>      Set LED RGB color (0-255)"
        echo "  list                         List all LEDs"
        echo ""
        echo "LED index: 1,2 (Linux sysfs) or 3,4 (STM32 RPC)"
        exit 1
        ;;
esac
