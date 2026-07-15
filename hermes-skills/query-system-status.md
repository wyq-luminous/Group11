# Query System Status

## When to use
- User asks "how is the board?", "system status", "check the board", "uptime", "CPU usage", "memory usage", "disk space"
- User says "状态", "系统状态", "查一下板子"

## What to do
1. Run the status script:
   ```
   /home/arduino/ArduinoApps/ws6/bin/status.sh
   ```
2. Read the output (text table with CPU, memory, disk, uptime, temperature).
3. Reply with a 1-2 sentence natural-language summary. Highlight anything concerning:
   - CPU > 80% → warn about high CPU
   - Memory > 80% → warn about low memory
   - Disk > 85% → warn about disk space
   - Otherwise → "all normal"

## Example reply
"UNO-Q is running normally: CPU 12%, memory 34% (180M/512M), disk 22% (1.4G/7.1G), uptime 3d 5h. Temperature 42°C."

## Important
- Do NOT try to read system files directly — always use the script.
- Do NOT run system commands like `top`, `free`, `df` — the script does that.
- If the script fails, tell the user the status check failed and suggest checking if the board is online.
