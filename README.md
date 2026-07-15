# UNO-Q Remote Control System

> **"一个系统，三张脸"** — One system, three faces: Web Dashboard, CLI Scripts, WeChat Agent.

A remote monitoring and control system for the Arduino UNO-Q board. Check system status, control the LED matrix and onboard RGB LEDs, and receive scheduled reports and anomaly alerts — all from WeChat, anywhere with cellular connectivity. No public IP, no port forwarding required.

---

## What problem does this solve?

Workshop 1's web dashboard only works within the same local network. Once you leave the room, you lose visibility and control of your UNO-Q board. This system bridges that gap: by connecting Hermes Agent to your WeChat, you can query the board status, scroll text on the matrix, control LEDs, and receive automatic alerts — from anywhere, over mobile data.

---

## Features (Phase A + B)

| # | Feature | How you access it |
|---|---------|-------------------|
| A | **Remote status query** — CPU, memory, disk, uptime, temperature | Web dashboard, CLI, or WeChat |
| B1 | **Matrix scrolling text** — custom 5×7 ASCII font, smooth right-to-left scroll | WeChat: "scroll Hello on the matrix" |
| B2 | **Matrix patterns** — warning, smiley, heart, cross, clear | WeChat: "show warning on matrix" |
| B3 | **LED remote control** — on/off/blink/RGB for all 4 RGB LEDs | WeChat: "turn on LED 3" or "set LED 1 to blue" |
| B4 | **Scheduled reports** — periodic system status pushed to WeChat | Hermes cron: every N minutes, zero token cost |
| B5 | **Anomaly alerts** — high CPU/memory/disk triggers warning on matrix + WeChat alert | Monitor daemon + Hermes cron (event-driven, ~60s latency) |

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                     THREE FACES                          │
│                                                         │
│  💻 Web Dashboard     📟 CLI Scripts     💬 WeChat      │
│  (frontend/index.html) (bin/*.sh)        (via Hermes)   │
│         │                   │                 │         │
│         └───────────────────┼─────────────────┘         │
│                             │                           │
│                   ┌─────────▼─────────┐                 │
│                   │  CORE LOGIC       │                 │
│                   │  backend/sysinfo  │ ← shared        │
│                   │  backend/hw       │ ← shared        │
│                   └────────┬──────────┘                 │
│                            │                            │
│         ┌──────────────────┼──────────────────┐         │
│         │                  │                  │         │
│    ┌────▼────┐      ┌──────▼──────┐    ┌─────▼─────┐   │
│    │ /proc   │      │ Linux sysfs │    │ RPC Client│   │
│    │ /sys    │      │ /sys/class  │    │ backend/  │   │
│    │(CPU/Mem │      │ /leds/      │    │ rpc_client│   │
│    │ /Disk)  │      │ (LED1,LED2) │    └─────┬─────┘   │
│    └─────────┘      └─────────────┘          │         │
│                                              │         │
│               arduino-router Unix socket     │         │
│               /var/run/arduino-router.sock   │         │
│                    msgpack-RPC               │         │
│                                              │         │
│         ┌────────────────────────────────────┘         │
│         │                                              │
│    ┌────▼──────────────────────────────────┐           │
│    │        STM32U585 Firmware             │           │
│    │  sketch.ino + matrix_scroll.h         │           │
│    │  + matrix_font.h + matrix_patterns.h  │           │
│    │                                       │           │
│    │  Controls:                            │           │
│    │    • 8×13 LED Matrix (PF0-PF10)       │           │
│    │    • RGB LED3 (PH10/11/12)            │           │
│    │    • RGB LED4 (PH13/14/15)            │           │
│    └───────────────────────────────────────┘           │
└─────────────────────────────────────────────────────────┘

PUSH CHAINS (scheduled + anomaly):
┌─────────────────────────────────────┐
│  B4: Scheduled Report               │
│  Hermes cron (every N min)          │
│    → bin/status.sh (script-only)    │
│    → stdout → delivered to WeChat   │
│  Zero token cost.                   │
├─────────────────────────────────────┤
│  B5: Anomaly Alert                  │
│  bin/monitor.py (daemon, 30s loop)  │
│    → over threshold + debounced     │
│    → matrix: WARNING pattern        │
│    → writes event to alerts.jsonl   │
│                                     │
│  Hermes cron (every 1 min)          │
│    → bin/deliver_alerts.sh          │
│    → reads alerts.jsonl             │
│    → stdout → delivered to WeChat   │
│  ~60s worst-case latency.           │
└─────────────────────────────────────┘
```

### Design rules (iron laws)

1. **Hermes never touches hardware or runs system commands.** It only calls scripts in `bin/`.
2. **Web dashboard and WeChat share the same core Python logic** (`backend/sysinfo.py`, `backend/hw.py`). Never duplicated.
3. **All hardware operations go through `backend/hw.py`.** CLI scripts and the monitor both import it — single abstraction for matrix and LEDs.
4. **LED routing is transparent to callers.** `hw.py` internally routes LED1/LED2 to Linux sysfs and LED3/LED4 to RPC.

---

## Directory Structure

```
ws6/
├── README.md                    ← This file
├── DEVLOG.md                    ← Development log & pitfall records
├── app.yaml                     ← Arduino App metadata
├── requirements.txt             ← Python dependencies (msgpack, PyYAML)
├── config/
│   └── thresholds.yaml          ← Alert thresholds, debounce, cooldown
├── scripts/
│   ├── bootstrap_venv.sh        ← Create venv + install deps (with retries)
│   └── flash.sh                 ← Compile & flash STM32 firmware
├── backend/
│   ├── __init__.py
│   ├── sysinfo.py               ← System status: CPU, memory, disk, uptime
│   ├── hw.py                    ← Hardware abstraction: matrix + LEDs
│   ├── rpc_client.py            ← msgpack-RPC client for arduino-router
│   └── web.py                   ← HTTP dashboard server (port 8080)
├── frontend/
│   └── index.html               ← Web dashboard with auto-refresh
├── sketch/
│   ├── sketch.ino               ← STM32 firmware main program
│   ├── sketch.yaml              ← Arduino build config (FQBN, libraries)
│   ├── matrix_font.h            ← 5×7 ASCII font (95 characters)
│   ├── matrix_patterns.h        ← Named patterns (warning/smiley/heart/cross/clear)
│   └── matrix_scroll.h          ← Non-blocking scroll engine
├── bin/
│   ├── status.sh                ← Print system status (text or JSON)
│   ├── matrix_scroll.sh         ← Start scrolling text on matrix
│   ├── matrix_pattern.sh        ← Show named pattern on matrix
│   ├── matrix_clear.sh          ← Clear matrix
│   ├── led_control.sh           ← LED on/off/blink/RGB
│   ├── monitor.py               ← Anomaly detection daemon
│   └── deliver_alerts.sh        ← Read & deliver pending alerts (Hermes consumer)
└── hermes-skills/
    ├── query-system-status.md   ← Skill: reply to "how's the board?"
    ├── scroll-text.md           ← Skill: scroll text on matrix
    ├── show-pattern.md          ← Skill: show pattern on matrix
    ├── control-led.md           ← Skill: control LEDs
    ├── scheduled-report.md      ← Skill: periodic status report setup
    └── anomaly-alert.md         ← Skill: anomaly alert setup & architecture
```

---

## Dependencies

### Python (Linux side)
- Python 3.x (system python, Debian 13)
- msgpack >= 1.0.0
- PyYAML >= 6.0

Install via bootstrap script:
```bash
chmod +x scripts/bootstrap_venv.sh
./scripts/bootstrap_venv.sh
```

This handles the UNO-Q's PEP 668 constraint: creates a `--without-pip` venv, bootstraps pip via `get-pip.py`, then installs from `requirements.txt`. Every step retries up to 5 times (phone hotspot resilience).

The venv is created at `.venv/` inside the project. All scripts use `.venv/bin/python` as their interpreter.

### Arduino Libraries (STM32 side, declared in sketch/sketch.yaml)
- Arduino_RouterBridge (for RPC between Linux ↔ STM32)
- Arduino_LED_Matrix (for 8×13 matrix control)
- MsgPack (0.4.2)
- DebugLog (0.8.4)
- ArxContainer (0.7.0)
- ArxTypeTraits (0.3.1)

---

## Firmware: Compile & Flash

```bash
# Compile + flash (standard arduino-cli path):
./scripts/flash.sh

# Compile only:
./scripts/flash.sh --compile

# Compile + flash + verify (with OpenOCD fallback if 0x08100000 is blank):
./scripts/flash.sh --verify
```

### Flash fallback details

If `arduino-cli upload` produces a binary that reads back as all 0xFF from the application area (0x08100000), the script falls back to:

```bash
/opt/openocd/bin/openocd \
  -f /opt/openocd/openocd_gpiod.cfg \
  -f /opt/openocd/flash_sketch.cfg
```

- **Config**: swdio=25, swclk=26, srst=38, gpiochip1
- **Target file**: `build/sketch/sketch.ino.elf-zsk.bin` (NOT `bin-zsk.bin`)
- **Bootloader area (0x08000000) verify-failed is NORMAL** — ignore it.
- **Application area (0x08100000)** is what you need to check.

### Verify RPC is working after flash:
```bash
python3 -m backend.rpc_client
```
Expected: `$/version` returns version, `mon/connected` returns True, unknown method returns `[2, 'method ... not available']`.

---

## Running the System

### 1. Web Dashboard
```bash
.venv/bin/python backend/web.py --port 8080
```
Open `http://<board-IP>:8080` in any browser. Dashboard auto-refreshes every 5 seconds.

### 2. CLI Status Check
```bash
./bin/status.sh            # Text format
./bin/status.sh --json     # JSON format
```

### 3. Matrix Control
```bash
./bin/matrix_scroll.sh "Hello from UNO-Q"
./bin/matrix_pattern.sh warning
./bin/matrix_clear.sh
```

### 4. LED Control
```bash
./bin/led_control.sh set 3 on         # Turn on LED3
./bin/led_control.sh set 3 blink      # Blink LED3
./bin/led_control.sh rgb 4 255 0 0    # LED4 red
./bin/led_control.sh list             # List all LEDs
```

### 5. Monitor Daemon
```bash
# Self-test (one sample, no alerts):
.venv/bin/python bin/monitor.py --test

# Foreground:
.venv/bin/python bin/monitor.py

# Background:
nohup .venv/bin/python bin/monitor.py > /tmp/monitor.log 2>&1 &
```

---

## Hermes Integration (Documentation Only — Not Executed)

### Prerequisites
1. [Install Hermes Agent](https://hermes-agent.nousresearch.com/docs) on the UNO-Q Linux side.
2. Configure your preferred LLM model (`hermes model`).
3. Connect WeChat: `hermes gateway` → add the `weixin` platform → scan QR code to pair.
4. Verify connection: send a test message to yourself.

### Loading Skills
Copy or symlink the skills into Hermes' skills directory:
```bash
# Option 1: load directly from project (if Hermes supports custom skill paths)
# Option 2: (not recommended) copy
cp hermes-skills/*.md ~/.hermes/skills/
```
**Better approach**: In a Hermes session, use `/skills` to load individual skill files. The skills reference absolute paths to the project's `bin/` scripts.

### Setting Up Cron Jobs (in Hermes session)

**Scheduled status report (every 30 min):**
```
/cron create "every 30m" --no-agent --script /home/arduino/ArduinoApps/ws6/bin/status.sh --deliver weixin --name "UNO-Q Status"
```

**Anomaly alert delivery (every 1 min):**
```
/cron create "every 1m" --no-agent --script /home/arduino/ArduinoApps/ws6/bin/deliver_alerts.sh --deliver weixin --name "UNO-Q Alerts"
```

**Verify:**
```
/cron list
```

---

## Acceptance Checklist

- [ ] `scripts/bootstrap_venv.sh` creates a working venv with all dependencies
- [ ] `python3 -m backend.rpc_client` passes self-test (3/3)
- [ ] `./bin/status.sh` prints system status text
- [ ] `backend/web.py` serves dashboard on 0.0.0.0:8080
- [ ] Dashboard auto-refreshes and shows CPU, memory, disk, uptime
- [ ] Firmware compiles and flashes without error
- [ ] `matrix.scroll_text("Test")` scrolls text on the LED matrix
- [ ] `matrix.show_pattern("warning")`, `"smiley"`, `"heart"`, `"cross"`, `"clear"` all work
- [ ] `led.set(3, "on")`, `"off"`, `"blink"` work for both LED3 and LED4
- [ ] `led.rgb(3, 255, 0, 0)` sets LED3 to red
- [ ] LED1 and LED2 controllable via sysfs (if not reserved by system)
- [ ] `bin/monitor.py --test` runs without error
- [ ] Manually triggering threshold produces alert in alerts.jsonl
- [ ] `bin/deliver_alerts.sh` reads and outputs pending alerts

---

## Troubleshooting

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| `No module named 'msgpack'` | venv not bootstrapped | Run `scripts/bootstrap_venv.sh` |
| RPC self-test fails to connect | arduino-router not running | Check `ls /var/run/arduino-router.sock` |
| Unknown RPC method `[2, ...]` | Firmware not flashed or old version | Re-flash with `scripts/flash.sh` |
| Matrix shows nothing | Firmware crashed or not flashed | Verify with RPC self-test; re-flash |
| Scrolling text garbled | FLIP_X/FLIP_Y orientation wrong | Set `#define FLIP_X 1` or `FLIP_Y 1` in sketch.ino |
| LED3/LED4 don't respond | STM32 RPC not receiving | Check `led.set` registered in firmware |
| LED1/LED2 sysfs "permission denied" | Need root for sysfs write | Run with `sudo` or adjust udev rules |
| Dashboard not accessible from phone | Listening on 127.0.0.1 | Ensure web.py uses `--host 0.0.0.0` |
| Monitor "No module named 'yaml'" | PyYAML missing in venv | Re-run `scripts/bootstrap_venv.sh` |
| Flash 0x08100000 all 0xFF | arduino-cli upload didn't write | Use OpenOCD fallback (`scripts/flash.sh --verify`) |

---

## Known Limitations

- **LED2** (Linux side) shares pins with system status indicators (panic, WLAN, BT). Colors may be overridden by the system.
- **WeChat group chat** support is limited by the iLink Bot API used by Hermes — DMs work reliably.
- **Blink on LED1/LED2** uses the sysfs timer trigger, which may conflict if another process sets a different trigger.
- **Alert latency**: Worst case ~60 seconds due to Hermes gateway tick interval. Acceptable for system monitoring, but not suitable for hard real-time alerts.
- **No authentication**: The web dashboard has no login. It listens on 0.0.0.0 — anyone on the same network can see it. Keep this in mind on shared networks.
- **Single user**: Designed for one person (you). No multi-user support.

## Security Notes

- The web dashboard has no authentication. If you need access control, put it behind a reverse proxy or only use it on your phone hotspot.
- Hermes skills reference absolute paths — they only work on this specific board.
- Never commit API keys, tokens, or secrets to this repository.
- The monitor writes alert events to a local JSON-lines file — no data leaves the board unless delivered by Hermes.

## Future Extensibility

- **More patterns**: Add entries to `matrix_patterns.h` and register in the `PATTERNS` array.
- **Additional metrics**: Extend `backend/sysinfo.py` with new functions, add thresholds in `config/thresholds.yaml`, and update `bin/monitor.py`.
- **Custom alert rules**: Modify the threshold comparison logic in `bin/monitor.py`.
- **Other IM platforms**: Hermes supports 30+ platforms (WhatsApp, Telegram, Discord, Slack, etc.). Switch `--deliver` in the cron setup.
- **Web dashboard enhancements**: The dashboard is a single static HTML page — add more cards, charts, or control buttons by editing `frontend/index.html`.
