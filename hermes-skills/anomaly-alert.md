# Anomaly Alert (Event-Driven Monitoring)

## Purpose
Automatically detect and alert you when the UNO-Q board is under stress — high CPU, low memory, or disk nearly full. The alert arrives on your WeChat within ~1 minute of detection.

## Architecture (event-driven, not polling)

```
bin/monitor.py  (daemon, samples every 30s)
    │
    ├─ Over threshold + debounced? → matrix shows WARNING pattern
    │                              → writes JSON event to alerts.jsonl
    │
    └─ Metric returns to normal?  → matrix cleared
                                   → writes "recovery" event to alerts.jsonl

Hermes cron (every 1 min, --no-agent --script)
    │
    └─ bin/deliver_alerts.sh reads alerts.jsonl
        → stdout non-empty → Hermes delivers to WeChat
        → marks alerts as delivered
```

## Why this design (see DEVLOG for full rationale)
- Hermes has no direct "push message" API. The script-only cron mode (--no-agent --script) is the closest: non-empty stdout is delivered to the configured IM platform.
- Alerts flow through a lightweight JSON-lines file (alerts.jsonl) as an event queue — no Redis, no MQTT, zero extra dependencies.
- Hermes gateway ticks every 60s → worst-case alert delay ~1 minute. Acceptable for system monitoring.
- Debounce (3 consecutive samples) + cooldown (10 min between repeats) prevent alert storms.

## Setup

### 1. Start the monitor daemon
```bash
# Foreground test (see output, Ctrl+C to stop):
/home/arduino/ArduinoApps/ws6/bin/monitor.py --test

# Foreground run:
/home/arduino/ArduinoApps/ws6/bin/monitor.py

# Background (survives terminal close):
nohup /home/arduino/ArduinoApps/ws6/.venv/bin/python /home/arduino/ArduinoApps/ws6/bin/monitor.py > /tmp/monitor.log 2>&1 &
```

### 2. Create the Hermes cron job (do this in your Hermes session)
```
/cron create "every 1m" --no-agent --script /home/arduino/ArduinoApps/ws6/bin/deliver_alerts.sh --deliver weixin --name "UNO-Q Alerts"
```

This runs every minute, reads alerts.jsonl, and delivers any pending alerts to your WeChat. Zero token cost (script-only mode).

### 3. Verify
Force an alert by temporarily lowering the threshold in config/thresholds.yaml, or just wait for a real anomaly.

## Configuration
Edit `config/thresholds.yaml` to adjust:
- `interval_sec`: How often the monitor samples (default: 30s)
- `debounce_cycles`: How many consecutive over-threshold samples before alerting (default: 3, so ~90s)
- `cooldown_sec`: Minimum seconds between repeated alerts for the same metric (default: 600s = 10 min)
- `cpu.warn / cpu.critical`: CPU percent thresholds
- `memory.warn / memory.critical`: Memory percent thresholds
- `disk.warn / disk.critical`: Disk percent thresholds

## Alert Format
When a threshold is breached and debounce is satisfied, you receive:
```
🔴 [CRITICAL] memory: 93% at 2026-07-09T14:32:00
```

When the metric returns to normal:
```
🟢 [RECOVERED] memory: back to 45% at 2026-07-09T14:38:00
```

## Troubleshooting
1. **No alerts arriving**: Check `hermes gateway` is running, cron job exists (`/cron list`), and monitor daemon is running (`ps aux | grep monitor`).
2. **Alerts every cycle (storm)**: Check debounce_cycles and cooldown_sec in config/thresholds.yaml.
3. **Matrix not showing warning**: The monitor will try to set the matrix via RPC. Verify the board is accessible and the firmware is flashed.
4. **Monitor crashes on startup**: Run `python3 bin/monitor.py --test` to check for import errors or missing dependencies.
