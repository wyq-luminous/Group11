#!/usr/bin/env python3
"""
monitor.py — Anomaly detection and alerting daemon for UNO-Q.

Periodically samples CPU, memory, and disk usage. When a metric crosses
its configured threshold and stays there for debounce_cycles, the monitor:
  1. Shows the WARNING pattern on the LED matrix.
  2. Writes an alert event to alerts.jsonl.
  3. A separate Hermes cron job (deliver_alerts.sh) picks up the file
     and delivers alerts to WeChat.

Design rationale (recorded in DEVLOG):
  Hermes has no direct "push message" CLI/API. The cleanest event-driven
  approach is:
    - Monitor writes events to a lightweight JSON-lines file (alerts.jsonl).
    - A Hermes script-only cron (every 1 min) reads and delivers pending
      alerts. This gives at most ~60s delay (Hermes gateway tick interval),
      which is acceptable for system monitoring.

  Debounce + cooldown prevent alert storms (every sample cycle bombardment)
  and allow for "recovery" notifications when metrics return to normal.

Usage:
  # Foreground / self-test (Ctrl+C to stop):
  python3 bin/monitor.py

  # Background (daemon):
  nohup python3 bin/monitor.py > /tmp/monitor.log 2>&1 &

  # With custom config:
  python3 bin/monitor.py --config /path/to/thresholds.yaml
"""

import json
import os
import sys
import time
import argparse
from datetime import datetime

# Project root
PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_DIR)

try:
    import yaml
except ImportError:
    print("[monitor] ERROR: PyYAML not installed. Run: pip install PyYAML", file=sys.stderr)
    sys.exit(1)

from backend.sysinfo import get_cpu_usage, get_memory, get_disk_usage


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------
def load_config(path=None):
    """Load thresholds from YAML config file."""
    if path is None:
        path = os.path.join(PROJECT_DIR, "config", "thresholds.yaml")

    if not os.path.exists(path):
        print(f"[monitor] WARNING: config not found at {path}, using defaults.", file=sys.stderr)
        return _default_config()

    with open(path, "r") as f:
        cfg = yaml.safe_load(f)

    m = cfg.get("monitor", {})
    return {
        "interval_sec": m.get("interval_sec", 30),
        "debounce_cycles": m.get("debounce_cycles", 3),
        "cooldown_sec": m.get("cooldown_sec", 600),
        "alert_file": m.get("alert_file", "alerts.jsonl"),
        "cpu_warn": m.get("cpu", {}).get("warn", 70),
        "cpu_critical": m.get("cpu", {}).get("critical", 90),
        "mem_warn": m.get("memory", {}).get("warn", 70),
        "mem_critical": m.get("memory", {}).get("critical", 90),
        "disk_warn": m.get("disk", {}).get("warn", 75),
        "disk_critical": m.get("disk", {}).get("critical", 90),
    }


def _default_config():
    """Built-in fallback defaults."""
    return {
        "interval_sec": 30,
        "debounce_cycles": 3,
        "cooldown_sec": 600,
        "alert_file": "alerts.jsonl",
        "cpu_warn": 70,
        "cpu_critical": 90,
        "mem_warn": 70,
        "mem_critical": 90,
        "disk_warn": 75,
        "disk_critical": 90,
    }


# ---------------------------------------------------------------------------
# Alert event
# ---------------------------------------------------------------------------
class AlertTracker:
    """Tracks per-metric state for debounce and cooldown."""

    def __init__(self):
        # Per-metric: consecutive over-threshold count
        self.debounce = {}   # key → count
        # Per-metric: last alert timestamp (for cooldown)
        self.last_alert = {}  # key → unix timestamp
        # Per-metric: whether currently in alert state
        self.in_alert = {}    # key → bool

    def _key(self, metric, severity):
        return f"{metric}:{severity}"

    def check(self, metric, value, warn_thresh, critical_thresh, now, cfg):
        """
        Check a metric value against thresholds.
        Returns: None (ok), "warn", or "critical" if an alert should fire.
        """
        debounce = cfg["debounce_cycles"]
        cooldown = cfg["cooldown_sec"]

        # Determine severity
        if value >= critical_thresh:
            severity = "critical"
        elif value >= warn_thresh:
            severity = "warn"
        else:
            # Value is normal — clear debounce, check recovery
            severity = None
            for sev in ("warn", "critical"):
                k = self._key(metric, sev)
                self.debounce[k] = 0
                if self.in_alert.get(k):
                    # Was in alert, now recovered
                    self.in_alert[k] = False
                    return "recovered"
            return None

        k = self._key(metric, severity)

        # Cooldown check
        if k in self.last_alert:
            if now - self.last_alert[k] < cooldown:
                return None  # still in cooldown

        # Debounce: increment counter
        self.debounce[k] = self.debounce.get(k, 0) + 1

        if self.debounce[k] >= debounce:
            self.debounce[k] = 0
            self.last_alert[k] = now
            self.in_alert[k] = True
            return severity

        return None


# ---------------------------------------------------------------------------
# Alert queue
# ---------------------------------------------------------------------------
def write_alert(alert_file, event):
    """Append an alert event to the JSON-lines file."""
    path = os.path.join(PROJECT_DIR, alert_file)
    try:
        with open(path, "a") as f:
            f.write(json.dumps(event) + "\n")
    except Exception as e:
        print(f"[monitor] ERROR: cannot write alert file {path}: {e}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Matrix warning (best-effort)
# ---------------------------------------------------------------------------
def show_matrix_warning():
    """Try to show the warning pattern on the matrix. Non-fatal if RPC fails."""
    try:
        from backend.hw import matrix_show_pattern
        matrix_show_pattern("warning")
    except Exception as e:
        print(f"[monitor] WARNING: cannot set matrix warning: {e}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Main monitor loop
# ---------------------------------------------------------------------------
def run_monitor(config_path=None):
    cfg = load_config(config_path)
    tracker = AlertTracker()

    interval = cfg["interval_sec"]
    alert_file = cfg["alert_file"]

    print(f"[monitor] Starting UNO-Q monitor...")
    print(f"[monitor] Interval: {interval}s, Debounce: {cfg['debounce_cycles']} cycles, "
          f"Cooldown: {cfg['cooldown_sec']}s")
    print(f"[monitor] Thresholds — CPU: {cfg['cpu_warn']}/{cfg['cpu_critical']}%, "
          f"Mem: {cfg['mem_warn']}/{cfg['mem_critical']}%, "
          f"Disk: {cfg['disk_warn']}/{cfg['disk_critical']}%")
    print(f"[monitor] Alert file: {os.path.join(PROJECT_DIR, alert_file)}")
    print(f"[monitor] Press Ctrl+C to stop.")

    try:
        while True:
            now = time.time()
            ts = datetime.now().isoformat(timespec="seconds")

            # Sample
            cpu = get_cpu_usage()
            mem = get_memory()
            disk = get_disk_usage("/")

            cpu_pct = cpu.get("percent", 0)
            mem_pct = mem.get("percent", 0)
            disk_pct = disk.get("percent", 0)

            # Check each metric
            checks = [
                ("cpu", cpu_pct, cfg["cpu_warn"], cfg["cpu_critical"]),
                ("memory", mem_pct, cfg["mem_warn"], cfg["mem_critical"]),
                ("disk", disk_pct, cfg["disk_warn"], cfg["disk_critical"]),
            ]

            for metric, value, warn_th, crit_th in checks:
                result = tracker.check(metric, value, warn_th, crit_th, now, cfg)

                if result in ("warn", "critical"):
                    event = {
                        "timestamp": ts,
                        "type": "alert",
                        "metric": metric,
                        "value": value,
                        "severity": result,
                        "threshold_warn": warn_th,
                        "threshold_critical": crit_th,
                    }
                    write_alert(alert_file, event)
                    show_matrix_warning()
                    print(f"[monitor] ALERT [{result.upper()}] {metric}={value}% "
                          f"(thresholds: {warn_th}/{crit_th})")

                elif result == "recovered":
                    event = {
                        "timestamp": ts,
                        "type": "recovery",
                        "metric": metric,
                        "value": value,
                    }
                    write_alert(alert_file, event)
                    # Clear matrix on recovery
                    try:
                        from backend.hw import matrix_clear
                        matrix_clear()
                    except Exception:
                        pass
                    print(f"[monitor] RECOVERED {metric}={value}%")

            # Periodic status log
            print(f"[monitor] {ts} | CPU:{cpu_pct}% Mem:{mem_pct}% Disk:{disk_pct}%")

            time.sleep(interval)

    except KeyboardInterrupt:
        print(f"\n[monitor] Stopped.")


# ---------------------------------------------------------------------------
# Self-test mode: sample once and print what would happen
# ---------------------------------------------------------------------------
def self_test(config_path=None):
    """Run one sample cycle and print results. Does not write alerts."""
    cfg = load_config(config_path)
    print("=== UNO-Q Monitor Self-Test ===\n")

    cpu = get_cpu_usage()
    mem = get_memory()
    disk = get_disk_usage("/")

    print(f"CPU:    {cpu.get('percent', '?'):>5}%  (warn:{cfg['cpu_warn']}, crit:{cfg['cpu_critical']})")
    print(f"Memory: {mem.get('percent', '?'):>5}%  (warn:{cfg['mem_warn']}, crit:{cfg['mem_critical']})")
    print(f"Disk:   {disk.get('percent', '?'):>5}%  (warn:{cfg['disk_warn']}, crit:{cfg['disk_critical']})")

    alerts = []
    for metric, value, warn_th, crit_th in [
        ("cpu", cpu.get("percent", 0), cfg["cpu_warn"], cfg["cpu_critical"]),
        ("memory", mem.get("percent", 0), cfg["mem_warn"], cfg["mem_critical"]),
        ("disk", disk.get("percent", 0), cfg["disk_warn"], cfg["disk_critical"]),
    ]:
        if value >= crit_th:
            alerts.append(f"CRITICAL: {metric} at {value}%")
        elif value >= warn_th:
            alerts.append(f"WARNING: {metric} at {value}%")

    if alerts:
        print(f"\n⚠ Would trigger: {', '.join(alerts)}")
    else:
        print("\n✓ All metrics within normal range.")
    print(f"\nAlert file would be: {os.path.join(PROJECT_DIR, cfg['alert_file'])}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="UNO-Q Anomaly Monitor")
    parser.add_argument("--config", help="Path to thresholds YAML config")
    parser.add_argument("--test", action="store_true", help="Run self-test (one sample, no alerts)")
    args = parser.parse_args()

    if args.test:
        self_test(args.config)
    else:
        run_monitor(args.config)
