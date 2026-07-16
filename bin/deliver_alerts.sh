#!/bin/bash
# deliver_alerts.sh — 读取待推送的坐姿告警并输出到 stdout。
#
# 由 Hermes Agent cron 每分钟调用 (script-only mode, 零 token 消耗):
#   /cron create "every 1m" --no-agent --script /home/arduino/SmartPosture_Guardian/bin/deliver_alerts.sh --deliver weixin --name "坐姿告警"
#
# 工作原理 (对齐 Workshop 6 Group11/ws6-remote-control):
#   1. Python 读取 alerts.jsonl 中未投递的告警事件。
#   2. 格式化为微信可读文本 → 输出到 stdout。
#   3. 将已处理事件移动到 alerts.jsonl.delivered。
#
# stdout 空   → Hermes 静默，不推送。
# stdout 非空 → Hermes 将内容投递到家长微信。
#
# 数据通过环境变量传递 (避免 shell 转义问题，参考 Workshop 6 DEVLOG Issue #2)。

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# 尝试使用项目 venv，不存在则用系统 python3
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
            message = event.get('message', '')
            reason = event.get('reason', '')

            # 微信推送格式
            output_lines.append(f'⚠️ 坐姿提醒')
            output_lines.append(f'')
            output_lines.append(f'{message}')
            output_lines.append(f'')
            output_lines.append(f'检测时间: {ts}')
            output_lines.append(f'详情: {reason}')
            output_lines.append(f'---')
        except json.JSONDecodeError:
            pass  # 跳过损坏行

if output_lines:
    for line in output_lines:
        print(line)
    print()  # 末尾空行

# 归档已投递事件 (best-effort)
try:
    with open(delivered_file, 'a') as df:
        with open(alert_file, 'r') as af:
            df.write(af.read())
    os.remove(alert_file)
except Exception:
    pass  # 归档失败不影响主流程
" 2>/dev/null
