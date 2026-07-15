# Scheduled Status Report (Timer-Based Push)

## Purpose
Periodically send a system status summary to your WeChat, so you always know how the UNO-Q board is doing — without having to ask.

## How it works
1. A Hermes cron job fires every N minutes.
2. It runs the status script in **script-only mode** (--no-agent): zero tokens, zero LLM cost.
3. The script prints system status to stdout.
4. Non-empty stdout → Hermes delivers it to your WeChat automatically.

## Prerequisites
- Hermes gateway must be running (`hermes gateway start`).
- The WeChat (weixin) platform must be connected and paired.
- The status script must be executable and working:
  ```
  /home/arduino/ArduinoApps/ws6/bin/status.sh
  ```

## Setup (do this in your Hermes session)

### Option A: Every 30 minutes (recommended)
```
/cron create "every 30m" --no-agent --script /home/arduino/ArduinoApps/ws6/bin/status.sh --deliver weixin --name "UNO-Q Status Report"
```

### Option B: Custom schedule (cron syntax)
```
/cron create "0 */2 * * *" --no-agent --script /home/arduino/ArduinoApps/ws6/bin/status.sh --deliver weixin --name "UNO-Q Status Report"
```
This runs every 2 hours.

### Option C: Every N minutes
```
/cron create "every 15m" --no-agent --script /home/arduino/ArduinoApps/ws6/bin/status.sh --deliver weixin --name "UNO-Q Status Report"
```

## What you'll receive
A text block like this delivered to your WeChat:
```
╔══════════════════════════════════╗
║     UNO-Q System Status         ║
╠══════════════════════════════════╣
║ CPU:       12% (4 cores)
║ Memory:    34% (180M / 512M)
║ Disk (/):  22% (1.4G / 7.1G)
║ Uptime:    3d 5h
║ Temp:      42°C
╚══════════════════════════════════╝
```

## Management commands (in Hermes session)
```
/cron list                              — See all cron jobs
/cron pause <job_id>                    — Pause a job
/cron resume <job_id>                   — Resume a job
/cron remove <job_id>                   — Delete a job
/cron edit <job_id> --schedule "..."    — Change the schedule
```

## How the trigger works (Hermes internals)
- Hermes gateway daemon ticks every **60 seconds**.
- On each tick, it checks if any cron job is due.
- Due jobs run in an isolated agent session (or script-only, no agent for --no-agent mode).
- Script stdout → delivered via the configured platform (here: weixin).
- Script exit code ≠ 0 → error alert delivered.
- Empty stdout → silent tick, no message sent.

## Troubleshooting
1. **No messages arriving**: Check `hermes gateway` is running. Run `/cron list` to verify the job exists and is not paused.
2. **Script fails**: Run `/home/arduino/ArduinoApps/ws6/bin/status.sh` manually on the board to verify it works.
3. **WeChat not receiving**: Verify the weixin platform is connected in Hermes (`/platforms`).
4. **Wrong timing**: Hermes cron uses your **local timezone**. Verify with `date` on the board.

## Important
- This skill only documents HOW to set up the cron job. The actual setup is done by you in a Hermes session.
- Do NOT modify /etc/crontab or install system cron — Hermes manages its own scheduler.
- The script path MUST be absolute: `/home/arduino/ArduinoApps/ws6/bin/status.sh`
