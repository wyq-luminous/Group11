"""
sysinfo.py — System information gathering for UNO-Q.

Reads CPU, memory, disk usage, and uptime from the Linux side via
/proc and /sys. This module is shared by the web dashboard, CLI
scripts, and Hermes skills — single source of truth for system state.

All functions return dicts with human-readable keys; get_full_status()
returns the combined snapshot.
"""

import os
import re
import time


# ---------------------------------------------------------------------------
# CPU
# ---------------------------------------------------------------------------

def get_cpu_usage():
    """
    Read CPU usage from /proc/stat.
    Returns a dict with 'percent' (float, 0-100) and 'cores' (int).
    """
    try:
        with open("/proc/stat", "r") as f:
            for line in f:
                if line.startswith("cpu "):
                    parts = line.strip().split()
                    # user, nice, system, idle, iowait, irq, softirq, steal
                    values = [int(x) for x in parts[1:9]]
                    total = sum(values)
                    idle = values[3] + values[4]  # idle + iowait
                    active = total - idle
                    pct = (active / total * 100) if total > 0 else 0.0
                    return {"percent": round(pct, 1), "total": total, "idle": idle}

        return {"percent": 0.0, "error": "Could not read /proc/stat"}
    except Exception as e:
        return {"percent": 0.0, "error": str(e)}


def get_cpu_cores():
    """Return the number of CPU cores from /proc/cpuinfo."""
    try:
        count = 0
        with open("/proc/cpuinfo", "r") as f:
            for line in f:
                if line.startswith("processor"):
                    count += 1
        return max(count, 1)
    except Exception:
        return 1


# ---------------------------------------------------------------------------
# Memory
# ---------------------------------------------------------------------------

def get_memory():
    """
    Read memory info from /proc/meminfo.
    Returns dict with 'total_kb', 'available_kb', 'used_kb', 'percent'.
    """
    try:
        mem = {}
        with open("/proc/meminfo", "r") as f:
            for line in f:
                parts = line.strip().split(":")
                if len(parts) < 2:
                    continue
                key = parts[0].strip()
                value = parts[1].strip().split()[0]
                if key in ("MemTotal", "MemAvailable", "MemFree", "Buffers", "Cached"):
                    mem[key] = int(value)

        total = mem.get("MemTotal", 0)
        available = mem.get("MemAvailable", 0)
        if available == 0:
            # Fallback: MemFree + Buffers + Cached
            available = mem.get("MemFree", 0) + mem.get("Buffers", 0) + mem.get("Cached", 0)

        used = total - available
        pct = (used / total * 100) if total > 0 else 0.0

        return {
            "total_kb": total,
            "available_kb": available,
            "used_kb": used,
            "percent": round(pct, 1),
        }
    except Exception as e:
        return {"total_kb": 0, "available_kb": 0, "used_kb": 0, "percent": 0.0, "error": str(e)}


# ---------------------------------------------------------------------------
# Disk
# ---------------------------------------------------------------------------

def get_disk_usage(path="/"):
    """Return disk usage for the given path using os.statvfs."""
    try:
        stat = os.statvfs(path)
        total = stat.f_blocks * stat.f_frsize
        free = stat.f_bavail * stat.f_frsize
        used = total - free
        pct = (used / total * 100) if total > 0 else 0.0

        return {
            "path": path,
            "total_gb": round(total / (1024 ** 3), 2),
            "used_gb": round(used / (1024 ** 3), 2),
            "free_gb": round(free / (1024 ** 3), 2),
            "percent": round(pct, 1),
        }
    except Exception as e:
        return {"path": path, "percent": 0.0, "error": str(e)}


# ---------------------------------------------------------------------------
# Uptime
# ---------------------------------------------------------------------------

def get_uptime():
    """
    Read system uptime from /proc/uptime.
    Returns dict with 'seconds', 'formatted' (e.g. "2d 3h 15m").
    """
    try:
        with open("/proc/uptime", "r") as f:
            uptime_seconds = float(f.readline().split()[0])

        days = int(uptime_seconds // 86400)
        hours = int((uptime_seconds % 86400) // 3600)
        minutes = int((uptime_seconds % 3600) // 60)

        parts = []
        if days > 0:
            parts.append(f"{days}d")
        if hours > 0:
            parts.append(f"{hours}h")
        parts.append(f"{minutes}m")

        return {
            "seconds": int(uptime_seconds),
            "formatted": " ".join(parts),
        }
    except Exception as e:
        return {"seconds": 0, "formatted": "unknown", "error": str(e)}


# ---------------------------------------------------------------------------
# Temperature (if available)
# ---------------------------------------------------------------------------

def get_temperature():
    """Try to read CPU temperature from /sys/class/thermal."""
    try:
        base = "/sys/class/thermal/thermal_zone0/temp"
        if os.path.exists(base):
            with open(base, "r") as f:
                millideg = int(f.read().strip())
            return {"celsius": round(millideg / 1000.0, 1)}
    except Exception:
        pass
    return {"celsius": None}


# ---------------------------------------------------------------------------
# Combined status
# ---------------------------------------------------------------------------

def get_full_status():
    """Return a complete system status snapshot as a dict."""
    return {
        "timestamp": time.time(),
        "timestamp_iso": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
        "cpu": get_cpu_usage(),
        "cpu_cores": get_cpu_cores(),
        "memory": get_memory(),
        "disk": get_disk_usage("/"),
        "uptime": get_uptime(),
        "temperature": get_temperature(),
    }


# ---------------------------------------------------------------------------
# CLI text formatter (shared by bin/status.sh and web)
# ---------------------------------------------------------------------------

def format_status_text(status=None):
    """Format a status dict as a human-readable text block."""
    if status is None:
        status = get_full_status()

    lines = []
    lines.append("╔══════════════════════════════════╗")
    lines.append("║     UNO-Q System Status         ║")
    lines.append("╠══════════════════════════════════╣")

    cpu = status.get("cpu", {})
    lines.append(f"║ CPU:       {cpu.get('percent', '?'):>5}% "
                 f"({status.get('cpu_cores', '?')} cores)")

    mem = status.get("memory", {})
    total_mb = mem.get("total_kb", 0) // 1024
    used_mb = mem.get("used_kb", 0) // 1024
    lines.append(f"║ Memory:    {mem.get('percent', '?'):>5}% "
                 f"({used_mb}M / {total_mb}M)")

    disk = status.get("disk", {})
    lines.append(f"║ Disk (/):  {disk.get('percent', '?'):>5}% "
                 f"({disk.get('used_gb', '?')}G / {disk.get('total_gb', '?')}G)")

    uptime = status.get("uptime", {})
    lines.append(f"║ Uptime:    {uptime.get('formatted', '?'):>10}")

    temp = status.get("temperature", {})
    tc = temp.get("celsius")
    if tc is not None:
        lines.append(f"║ Temp:      {tc:>7}°C")

    lines.append("╚══════════════════════════════════╝")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Direct run for testing
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import json
    status = get_full_status()
    print(format_status_text(status))
    print()
    print("--- JSON ---")
    print(json.dumps(status, indent=2))
