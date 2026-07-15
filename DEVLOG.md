# DEVLOG — UNO-Q Remote Control System

Development log for the ws6 project. Chronological record of prompts, actions, decisions, and pitfalls.

---

## 2026-07-09 — Session 1: Architecture & Full Implementation

### Prompt Summary
User provided an extremely detailed specification for building a "UNO-Q Remote Control System" from scratch. The system has three interfaces (web dashboard, CLI scripts, WeChat via Hermes Agent) sharing a single core logic layer. Features span system status querying (Phase A) and five Phase B features: matrix scrolling text, matrix patterns, LED remote control, scheduled status reports, and anomaly alerts.

### Key Actions

1. **Project Discovery**: Located ws6 at `/home/arduino/ArduinoApps/ws6` — a bare Arduino App template (app.yaml, sketch/sketch.ino, sketch/sketch.yaml, python/main.py).

2. **Architecture Presentation**: Presented a detailed architecture understanding, directory structure, and 8-phase implementation plan. User approved without changes.

3. **Hermes Research**: Searched for Hermes Agent documentation to understand scheduling and push capabilities. Key findings:
   - Hermes has built-in cron with `--no-agent --script` mode (zero token, zero LLM cost)
   - Non-empty script stdout → automatically delivered to configured IM platform (including WeChat)
   - Gateway ticks every 60 seconds
   - No direct "push message" CLI/API — the script-only cron pattern is the recommended approach for programmatic push

4. **UNO-Q LED Research**: Confirmed the UNO-Q LED architecture:
   - LED1 (RGB): Linux side — `/sys/class/leds/red:user`, `green:user`, `blue:user`
   - LED2 (RGB): Linux side — `/sys/class/leds/red:panic`, `green:wlan`, `blue:bt`
   - LED3 (RGB): STM32 side — PH10(R), PH11(G), PH12(B)
   - LED4 (RGB): STM32 side — PH13(R), PH14(G), PH15(B)
   - All LEDs are active-low
   - 8×13 LED matrix: STM32 side, PF0-PF10, charlieplexed

5. **Full Implementation** (8 phases, ~25 files created):
   - P0: `scripts/bootstrap_venv.sh`, `requirements.txt`, updated `.gitignore`
   - P1: `backend/rpc_client.py` — msgpack.Unpacker streaming, first-message-return
   - P2: `backend/sysinfo.py`, `backend/web.py`, `frontend/index.html`, `bin/status.sh`, `hermes-skills/query-system-status.md`
   - P3: `matrix_font.h` (95 glyphs), `matrix_patterns.h` (5 patterns), `matrix_scroll.h` (non-blocking engine), `sketch.ino` (5 RPC callbacks, LED blink machine), `scripts/flash.sh` (arduino-cli + OpenOCD fallback)
   - P4: `backend/hw.py` (matrix portion), `bin/matrix_scroll.sh`, `bin/matrix_pattern.sh`, `bin/matrix_clear.sh`, `hermes-skills/scroll-text.md`, `hermes-skills/show-pattern.md`
   - P5: `backend/hw.py` (LED portion — sysfs + RPC routing), `bin/led_control.sh`, `hermes-skills/control-led.md`
   - P6: `hermes-skills/scheduled-report.md`
   - P7: `config/thresholds.yaml`, `bin/monitor.py`, `bin/deliver_alerts.sh`, `hermes-skills/anomaly-alert.md`
   - P8: `README.md`, `DEVLOG.md`

---

## Technical Decision Records

### B3: LED Control — Linux sysfs vs STM32 RPC
**Decision**: Hybrid approach. `backend/hw.py` routes transparently:
- LED1 & LED2 → Linux sysfs (`/sys/class/leds/*/brightness`)
- LED3 & LED4 → STM32 RPC (`led.set` / `led.rgb`)

**Rationale**: LED1 and LED2 are physically wired to the Linux-side QRB2210 GPIOs. There's no RPC path to control them — they must be driven via sysfs. LED3 and LED4 are on STM32 GPIOs (PH10-PH15) and go through RPC. The `hw.py` abstraction makes this invisible to callers — `led_set(1, "on")` and `led_set(3, "on")` have the same interface.

### B4: Scheduled Reports — Hermes Cron vs System Cron
**Decision**: Use Hermes built-in cron with `--no-agent --script` mode.

**Rationale**: Hermes cron is managed within the agent ecosystem — no need to touch system crontab (which may require sudo). The `--no-agent --script` mode means zero token cost and zero LLM invocation for simple status scripts. The `--deliver weixin` flag routes stdout directly to WeChat.

### B5: Anomaly Alerts — Push Mechanism
**Decision**: Event-driven via file queue (alerts.jsonl) + Hermes script-only cron consumer.

**Rationale**: Hermes has no direct "push message from external process" CLI or API. The options were:

1. **Pure polling**: Hermes cron runs status.sh, parses output, decides if it's alert-worthy. Requires LLM invocation (token cost per check) and duplicates threshold logic from monitor.py.

2. **Webhook trigger**: POST to Hermes webhook port 8644 to trigger an agent session. Requires the webhook platform to be configured, an agent prompt to be crafted, and LLM invocation per alert.

3. **File queue + script-only cron** (CHOSEN): The monitor daemon writes alert events to `alerts.jsonl`. A separate Hermes cron (every 1 min, script-only, no LLM) runs `deliver_alerts.sh` which reads the file and outputs pending alerts. Non-empty stdout → delivered. Empty stdout → silent.

Option 3 was chosen because:
- Zero token cost (script-only mode)
- No additional dependencies (just a JSON-lines file)
- ~60s worst-case latency (gateway tick interval) — acceptable for system monitoring
- Monitor logic stays in Python (testable, debuggable) rather than in LLM prompts
- Clean separation: monitor detects, Hermes delivers

**Difference from pure polling**: In pure polling, Hermes would invoke an LLM every N minutes to check status output and decide if it looks bad. That burns tokens, adds LLM latency, and duplicates the threshold logic that monitor.py already implements precisely. The file queue approach keeps the detection logic in Python (deterministic, testable) and uses Hermes only as a dumb delivery pipe (script-only mode).

### Bluetooth on LED1/LED2
- LED1 (red:user, green:user, blue:user): full user control, no system reservation
- LED2 (red:panic, green:wlan, blue:bt): shared with system — WLAN and BT indicators may override user settings

### Matrix Scrolling — Custom Font vs Library
**Decision**: Custom 5×7 ASCII font with non-blocking millis() state machine.

**Rationale**: The user explicitly noted that `Arduino_LED_Matrix.text()` and `.textScroll()` are unreliable on UNO-Q. The custom implementation:
- Builds a column buffer from the font glyphs
- Slides a 13-column window across the buffer one column per frame
- Uses `matrix.renderBitmap()` for raw frame submission
- All timing via `millis()`, no `delay()` in `loop()`

---

---
## 2026-07-09 — Session 2: Bugfix Round (Hermes IM Integration)

### Issue 1: msgpack.Unpacker socket error

**Phenomenon**: Hermes called `matrix_scroll.sh` → Python crashed with:
> `AttributeError: 'socket' object has no attribute 'read'`

**Misdiagnosis**: None — immediately clear.

**Real cause**: Python `socket.socket` objects have `.recv()` but NOT `.read()`. `msgpack.Unpacker` expects a file-like object with a `.read()` method. Passing the raw socket directly causes an AttributeError.

**Fix**: In `backend/rpc_client.py`, wrap the socket with `sock.makefile('rb')` before passing to `msgpack.Unpacker`. `makefile('rb')` returns a `BufferedReader` with proper `.read()` and `.read1()` methods. Changed:
```python
# Before (broken):
unpacker = msgpack.Unpacker(sock, raw=False)

# After (fixed):
sf = sock.makefile('rb')
unpacker = msgpack.Unpacker(sf, raw=False)
```

### Issue 2: Shell escaping vulnerability in CLI scripts

**Phenomenon**: `matrix_scroll.sh`, `matrix_pattern.sh`, `led_control.sh`, and `deliver_alerts.sh` all used inline Python with `${variable}` bash interpolation. If user-supplied text contained single quotes, backslashes, or other special characters, it would break the Python string syntax.

**Real cause**: Bash `${TEXT//\'/\\\'}` only handles single quotes — backticks, dollar signs, double quotes, and backslashes still pass through unescaped into the Python `-c` string.

**Fix**: Rewrote all four scripts to pass data via environment variables (`export VAR=...`) and read them in Python via `os.environ['VAR']`. This eliminates all shell escaping concerns — the variable content never appears inside the Python code string.

### Files modified this session
- `backend/rpc_client.py` — socket makefile fix
- `bin/matrix_scroll.sh` — env var passing (was: inline Python with bash interpolation)
- `bin/matrix_pattern.sh` — env var passing + input validation
- `bin/led_control.sh` — env var passing + regex input validation
- `bin/deliver_alerts.sh` — env var passing + entire logic moved into single Python invocation (was: bash loop calling python per line)

---

## Current State (End of Session 1)

**Completed**: All 8 phases implemented. ~25 files written covering:
- Infrastructure (venv bootstrap, requirements)
- Core logic (sysinfo, hardware abstraction, RPC client)
- Web dashboard (Python HTTP server + HTML frontend)
- CLI scripts (7 scripts in bin/)
- Firmware (sketch + 3 headers, 95-glyph font, 5 patterns, scroll engine)
- Flash script (arduino-cli + OpenOCD fallback)
- Hermes skills (6 skills in hermes-skills/)
- Config (thresholds.yaml)
- Documentation (README.md, DEVLOG.md)

**Next Steps** (for the user):
1. Run `scripts/bootstrap_venv.sh` to set up the Python environment
2. Run `python3 -m backend.rpc_client` to verify RPC connectivity
3. Compile and flash firmware: `scripts/flash.sh`
4. Test each CLI script manually
5. Start the web dashboard: `.venv/bin/python backend/web.py --port 8080`
6. Load Hermes skills and set up cron jobs per the skill instructions
7. Run `bin/monitor.py --test` to verify monitoring

**Unresolved**: Hardware testing — all code is written but none has been tested on the physical UNO-Q board yet.
