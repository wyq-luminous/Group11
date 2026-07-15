"""
hw.py — Hardware abstraction layer for UNO-Q.

All hardware operations (matrix, LEDs) go through this module.
CLI scripts and monitoring scripts both use it — single implementation.

Matrix:  all operations go through RPC to STM32 firmware.
LEDs:   LED1/LED2 are Linux-side (sysfs), LED3/LED4 are STM32-side (RPC).
        The HW layer routes transparently; callers just use led_set(1, "on").
"""

import os
import sys
from backend.rpc_client import rpc_call, RpcError

# ---------------------------------------------------------------------------
# LED sysfs paths (Linux-side LEDs)
# ---------------------------------------------------------------------------
LED_SYSFS = {
    1: {
        "r": "/sys/class/leds/red:user/brightness",
        "g": "/sys/class/leds/green:user/brightness",
        "b": "/sys/class/leds/blue:user/brightness",
        "label": "LED1 (Linux, RGB)",
    },
    2: {
        "r": "/sys/class/leds/red:panic/brightness",
        "g": "/sys/class/leds/green:wlan/brightness",
        "b": "/sys/class/leds/blue:bt/brightness",
        "label": "LED2 (Linux, RGB, shared with system indicators)",
    },
}

# ---------------------------------------------------------------------------
# Matrix operations (all via RPC to STM32)
# ---------------------------------------------------------------------------

def matrix_scroll_text(text, socket_path=None):
    """
    Start scrolling text on the LED matrix.
    Text scrolls right-to-left and loops continuously.
    Call matrix_clear() or matrix_show_pattern() to stop.
    """
    return rpc_call("matrix.scroll_text", text, socket_path=socket_path)


def matrix_show_pattern(name, socket_path=None):
    """
    Show a named pattern on the matrix.
    Valid names: warning, smiley, heart, cross, clear.
    This stops any active scrolling.
    """
    valid = {"warning", "smiley", "heart", "cross", "clear"}
    if name not in valid:
        raise ValueError(f"Unknown pattern '{name}'. Valid: {', '.join(sorted(valid))}")
    return rpc_call("matrix.show_pattern", name, socket_path=socket_path)


def matrix_show_animation(name, socket_path=None):
    """
    Start an animation on the matrix.
    Valid animations: walker (4-frame walking stick figure).
    Loops continuously until replaced by scroll/pattern/clear.
    """
    return rpc_call("matrix.show_animation", name, socket_path=socket_path)


def matrix_clear(socket_path=None):
    """Clear the LED matrix (all pixels off)."""
    return rpc_call("matrix.clear", socket_path=socket_path)


# ---------------------------------------------------------------------------
# LED operations (routes to sysfs or RPC depending on LED index)
# ---------------------------------------------------------------------------

def _sysfs_write(path, value):
    """Write a value to a sysfs file. Creates if not existing."""
    try:
        with open(path, "w") as f:
            f.write(str(value))
        return True
    except PermissionError:
        print(f"[hw] WARNING: Permission denied writing to {path}. Try sudo.", file=sys.stderr)
        return False
    except FileNotFoundError:
        print(f"[hw] WARNING: sysfs path not found: {path}", file=sys.stderr)
        return False
    except Exception as e:
        print(f"[hw] ERROR writing {path}: {e}", file=sys.stderr)
        return False


def _is_linux_led(index):
    """Return True if this LED index is Linux-side."""
    return index in LED_SYSFS


def _is_stm32_led(index):
    """Return True if this LED index is STM32-side (needs RPC)."""
    return index in (3, 4)


def led_set(index, state, socket_path=None):
    """
    Set LED state: on, off, or blink.

    Args:
        index: LED number (1-4). LED1/2 = Linux sysfs, LED3/4 = STM32 RPC.
        state: "on", "off", or "blink"
    """
    if state not in ("on", "off", "blink"):
        raise ValueError(f"Invalid LED state '{state}'. Use on/off/blink.")

    results = {}

    if _is_linux_led(index):
        # Linux side: write brightness to sysfs
        # For "blink", use sysfs trigger (if available)
        led = LED_SYSFS[index]
        if state == "on":
            r = _sysfs_write(led["r"], "255")
            g = _sysfs_write(led["g"], "255")
            b = _sysfs_write(led["b"], "255")
            results["sysfs"] = all([r, g, b])
        elif state == "off":
            r = _sysfs_write(led["r"], "0")
            g = _sysfs_write(led["g"], "0")
            b = _sysfs_write(led["b"], "0")
            results["sysfs"] = all([r, g, b])
        elif state == "blink":
            # Try to use trigger; fall back to manual note
            for color in ["r", "g", "b"]:
                trigger_path = led[color].replace("brightness", "trigger")
                _sysfs_write(trigger_path, "timer")
            results["sysfs"] = True
            results["note"] = "blink via sysfs timer trigger"

    elif _is_stm32_led(index):
        # STM32 side: RPC call to firmware
        result = rpc_call("led.set", index, state, socket_path=socket_path)
        results["rpc"] = result
    else:
        raise ValueError(f"Invalid LED index {index}. Valid: 1, 2 (Linux) or 3, 4 (STM32).")

    return results


def led_rgb(index, r, g, b, socket_path=None):
    """
    Set LED RGB color. Values 0-255 each.

    Args:
        index: LED number (1-4).
        r, g, b: Red, green, blue intensity (0=off, 255=max).
    """
    # Clamp values
    r, g, b = max(0, min(255, r)), max(0, min(255, g)), max(0, min(255, b))

    results = {}

    if _is_linux_led(index):
        led = LED_SYSFS[index]
        rr = _sysfs_write(led["r"], str(r))
        gg = _sysfs_write(led["g"], str(g))
        bb = _sysfs_write(led["b"], str(b))
        results["sysfs"] = all([rr, gg, bb])
        results["values"] = {"r": r, "g": g, "b": b}

    elif _is_stm32_led(index):
        result = rpc_call("led.rgb", index, r, g, b, socket_path=socket_path)
        results["rpc"] = result
        results["values"] = {"r": r, "g": g, "b": b}
    else:
        raise ValueError(f"Invalid LED index {index}. Valid: 1, 2 (Linux) or 3, 4 (STM32).")

    return results


def led_get_info(index):
    """Return info about a given LED index."""
    if _is_linux_led(index):
        return {
            "index": index,
            "side": "Linux",
            "control": "sysfs",
            "label": LED_SYSFS[index]["label"],
            "rgb": True,
        }
    elif _is_stm32_led(index):
        return {
            "index": index,
            "side": "STM32",
            "control": "RPC",
            "label": f"LED{index} (STM32, RGB, active-low)",
            "rgb": True,
        }
    else:
        return {"index": index, "error": "Unknown LED"}


def led_list_all():
    """List all known LEDs."""
    return [led_get_info(i) for i in (1, 2, 3, 4)]


# ---------------------------------------------------------------------------
# Self-test (run with: python3 -m backend.hw)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("=== UNO-Q Hardware Abstraction Self-Test ===\n")

    print("LED Inventory:")
    for info in led_list_all():
        print(f"  LED{info['index']}: {info.get('label', info.get('error', '?'))}")

    print("\nMatrix operations (requires RPC connection):")
    try:
        result = matrix_clear()
        print(f"  matrix.clear() → {result}")
    except Exception as e:
        print(f"  matrix.clear() → ERROR: {e}")

    print("\nDone.")
