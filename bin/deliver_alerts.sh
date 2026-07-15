#!/bin/bash
# deliver_alerts.sh — Read pending alerts from alerts.jsonl and output them.
#
# This is called by a Hermes script-only cron job every 1 minute:
#   /cron create "every 1m" --no-agent --script /home/arduino/ArduinoApps/ws6/bin/deliver_alerts.sh --deliver weixin
#
# How it works:
#   1. Calls a Python script that reads alerts.jsonl.
#   2. Python outputs formatted alerts to stdout.
#   3. Python moves processed alerts to alerts.jsonl.delivered.
#
# Empty stdout = no new alerts = Hermes stays silent.
# Non-empty stdout = Hermes delivers the output to WeChat.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
VENV_PYTHON="${PROJECT_DIR}/.venv/bin/python"
PYTHON="${VENV_PYTHON}"
[ -x "${PYTHON}" ] || PYTHON="python3"

export PROJECT_DIR

exec "${PYTHON}" -c "
import os, sys, json

project_dir = os.environ['PROJECT_DIR']
alert_file = os.path.join(project_dir, 'alerts.jsonl')
delivered_file = os.path.join(project_dir, 'alerts.jsonl.delivered')

if not os.path.exists(alert_file):
    sys.exit(0)

output_lines = []

with open(alert_file, 'r') as f:
    for line in f:
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
            ts = event.get('timestamp', '?')
            typ = event.get('type', '?')
            metric = event.get('metric', '?')
            value = event.get('value', '?')
            severity = event.get('severity', '?')

            if typ == 'alert':
                emoji = '\U0001F534' if severity == 'critical' else '\U0001F7E1'
                output_lines.append(f'{emoji} [{severity.upper()}] {metric}: {value}% at {ts}')
            elif typ == 'recovery':
                output_lines.append(f'\U0001F7E2 [RECOVERED] {metric}: back to {value}% at {ts}')
            else:
                output_lines.append(f'? {typ}: {metric}={value}% at {ts}')
        except json.JSONDecodeError:
            pass  # skip corrupt lines

if output_lines:
    for line in output_lines:
        print(line)
    print()  # blank line separator

# Move to delivered
try:
    with open(delivered_file, 'a') as df:
        with open(alert_file, 'r') as af:
            df.write(af.read())
    os.remove(alert_file)
except Exception:
    pass  # best-effort
" 2>/dev/null
