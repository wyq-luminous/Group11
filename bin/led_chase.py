#!/usr/bin/env python3
"""
led_chase.py — LED running/chase effect across all 4 UNO-Q LEDs.

Controls LED1/LED2 via Linux sysfs (smooth 0-255 per channel).
Controls LED3/LED4 via STM32 RPC (digitalWrite, 8 colors).
Cycles through a rainbow hue wheel with per-LED phase offset for flowing effect.

Modes:
  chase   — LEDs light up in sequence (wave effect)
  rainbow — All LEDs show the same color, cycling through rainbow
  breathe — All LEDs fade in/out together

Usage:
  .venv/bin/python bin/led_chase.py                    # chase mode, default speed
  .venv/bin/python bin/led_chase.py --mode rainbow     # rainbow mode
  .venv/bin/python bin/led_chase.py --mode breathe     # breathing effect
  .venv/bin/python bin/led_chase.py --speed 0.05       # faster (50ms per step)
  .venv/bin/python bin/led_chase.py --speed 0.5        # slower (500ms per step)
"""

import os
import sys
import time
import math
import signal
import argparse

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_DIR)

from backend.hw import led_rgb as hw_led_rgb

# Sysfs paths for Linux-side LEDs
LED_SYSFS = {
    1: {"r": "/sys/class/leds/red:user/brightness",
        "g": "/sys/class/leds/green:user/brightness",
        "b": "/sys/class/leds/blue:user/brightness"},
    2: {"r": "/sys/class/leds/red:panic/brightness",
        "g": "/sys/class/leds/green:wlan/brightness",
        "b": "/sys/class/leds/blue:bt/brightness"},
}


def sysfs_write(path, value):
    """Write to sysfs, return True on success."""
    try:
        with open(path, "w") as f:
            f.write(str(int(value)))
        return True
    except Exception:
        return False


def set_led_sysfs(idx, r, g, b):
    """Set LED1 or LED2 via sysfs (full 0-255 PWM)."""
    paths = LED_SYSFS.get(idx)
    if not paths:
        return False
    return all([
        sysfs_write(paths["r"], r),
        sysfs_write(paths["g"], g),
        sysfs_write(paths["b"], b),
    ])


def set_led_rpc(idx, r, g, b):
    """Set LED3 or LED4 via RPC (digitalWrite, >127 = on)."""
    try:
        hw_led_rgb(idx, r, g, b, timeout=3.0)
        return True
    except Exception:
        return False


def set_led(idx, r, g, b):
    """Set any LED. Routes to sysfs (1-2) or RPC (3-4)."""
    if idx in (1, 2):
        return set_led_sysfs(idx, r, g, b)
    elif idx in (3, 4):
        return set_led_rpc(idx, r, g, b)
    return False


def hue_to_rgb(h):
    """
    Convert HSV hue (0-360) to RGB (0-255).
    Assumes full saturation and value.
    """
    h = h % 360
    sector = h / 60.0
    x = 255 * (1 - abs((sector % 2) - 1))
    if sector < 1:
        return (255, int(x), 0)
    elif sector < 2:
        return (int(x), 255, 0)
    elif sector < 3:
        return (0, 255, int(x))
    elif sector < 4:
        return (0, int(x), 255)
    elif sector < 5:
        return (int(x), 0, 255)
    else:
        return (255, 0, int(x))


def all_off():
    """Turn all LEDs off."""
    for i in range(1, 5):
        set_led(i, 0, 0, 0)


def run_chase(speed, step_hue=15):
    """
    Chase mode: LEDs light up in sequence with hue phase offset.
    LED1 phase=0, LED2 phase=90°, LED3 phase=180°, LED4 phase=270°
    """
    base_hue = 0.0
    phase_offsets = {1: 0, 2: 90, 3: 180, 4: 270}
    print(f"[chase] speed={speed}s, step_hue={step_hue}°  Ctrl+C to stop")
    while True:
        for i in (1, 2, 3, 4):
            hue = (base_hue + phase_offsets[i]) % 360
            r, g, b = hue_to_rgb(hue)
            set_led(i, r, g, b)
        base_hue = (base_hue + step_hue) % 360
        time.sleep(speed)


def run_rainbow(speed, step_hue=5):
    """
    Rainbow mode: all 4 LEDs show the same color, cycling through rainbow.
    Smoother than chase because hue steps are smaller.
    """
    hue = 0.0
    print(f"[rainbow] speed={speed}s, step_hue={step_hue}°  Ctrl+C to stop")
    while True:
        r, g, b = hue_to_rgb(hue)
        for i in (1, 2, 3, 4):
            set_led(i, r, g, b)
        hue = (hue + step_hue) % 360
        time.sleep(speed)


def run_breathe(speed, step=0.02):
    """
    Breathe mode: all LEDs fade in/out together using sine wave.
    """
    print(f"[breathe] speed={speed}s  Ctrl+C to stop")
    t = 0.0
    while True:
        # Sine wave 0→1→0 for brightness
        brightness = (math.sin(t) + 1) / 2  # 0.0 to 1.0
        # Use a fixed warm-white hue, just vary brightness
        r = int(255 * brightness)
        g = int(180 * brightness)
        b = int(60 * brightness)
        for i in (1, 2, 3, 4):
            set_led(i, r, g, b)
        t += step
        time.sleep(speed)


def main():
    parser = argparse.ArgumentParser(description="UNO-Q LED Chase / Rainbow Effect")
    parser.add_argument("--mode", choices=["chase", "rainbow", "breathe"],
                        default="chase", help="Effect mode (default: chase)")
    parser.add_argument("--speed", type=float, default=0.15,
                        help="Seconds per frame (default: 0.15)")
    args = parser.parse_args()

    # Cleanup on Ctrl+C
    def handler(sig, frame):
        print("\n[led_chase] Stopping...")
        all_off()
        print("[led_chase] All LEDs off. Done.")
        sys.exit(0)
    signal.signal(signal.SIGINT, handler)
    signal.signal(signal.SIGTERM, handler)

    print(f"[led_chase] Starting {args.mode} mode...")
    try:
        if args.mode == "chase":
            run_chase(args.speed)
        elif args.mode == "rainbow":
            run_rainbow(args.speed)
        elif args.mode == "breathe":
            run_breathe(args.speed)
    except KeyboardInterrupt:
        handler(None, None)


if __name__ == "__main__":
    main()
