# Posture Alert — 坐姿异常微信告警推送

## Purpose
当 SmartPosture Guardian 检测到孩子坐姿异常（前倾/低头/歪头）时，
通过 Hermes Agent 自动推送告警到家长微信。

## Architecture (文件队列 + Hermes cron 投递)

```
src/main.py — PostureAnalyzer._handle_monitoring()
    │  首次进入 ALERTING 状态
    │  冷却检查 (60s 窗口防重复)
    ▼
src/hermes.py — HermesPusher.try_push(reason)
    │  写入 JSON 事件到 alerts.jsonl
    ▼
Hermes Agent cron (每 1 分钟, --no-agent --script)
    │  bin/deliver_alerts.sh 读 alerts.jsonl
    │  stdout 非空 → Hermes 投递到微信
    ▼
家长微信收到告警消息
```

## Why this design (aligns with Workshop 6 verified approach)
- Hermes 无直接 "push message" API。`--no-agent --script` 是最简洁的投递方式：
  脚本 stdout 非空 → 自动投递到配置的 IM 平台（微信）。
- 告警通过 JSON-lines 文件 (alerts.jsonl) 作为轻量事件队列 —
  零额外依赖，无需 Redis/MQTT。
- Hermes cron 最快 1 分钟触发 → 告警延迟最多 ~60s，可接受。
- Script-only 模式零 token 消耗，零 LLM 调用。

## Setup

### 1. 安装 Hermes Agent (一次性)

```bash
# 1. 设置环境变量 (避免占满小系统分区)
export HERMES_HOME="/home/arduino/.hermes"
export PATH="/home/arduino/.local/bin:$PATH"
mkdir -p /home/arduino/.local/bin /home/arduino/.hermes

# 2. 安装 Node.js (Hermes 依赖)
cd /home/arduino
curl -fsSL https://nodejs.org/dist/v22.22.2/node-v22.22.2-linux-arm64.tar.xz -o node.tar.xz
tar xJf node.tar.xz
mv node-v22.22.2-linux-arm64 /home/arduino/node
ln -sf /home/arduino/node/bin/node /home/arduino/.local/bin/node
ln -sf /home/arduino/node/bin/npm /home/arduino/.local/bin/npm
ln -sf /home/arduino/node/bin/npx /home/arduino/.local/bin/npx
rm node.tar.xz

# 3. 安装 Hermes Agent
curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.sh | bash -s -- \
  --dir /home/arduino/hermes-agent \
  --skip-setup

# 4. 配置
hermes setup                    # 选择 LLM provider
hermes gateway setup            # 配置微信接入
```

### 2. 验证文件队列工作

```bash
# 启动 SmartPosture Guardian
cd /home/arduino/SmartPosture_Guardian
python3 src/main.py &

# 触发一次坐姿异常 (前倾或低头保持 5s)
# 然后检查告警文件:
cat alerts.jsonl
# 预期输出类似:
# {"timestamp": "2026-07-16T14:32:00", "type": "posture_alert", ...}
```

### 3. 手动测试投递脚本

```bash
# 如果 alerts.jsonl 有内容，手动跑投递脚本看输出:
./bin/deliver_alerts.sh
# 预期看到格式化的告警文本（stdout）
# 执行后 alerts.jsonl 被清空（归档到 alerts.jsonl.delivered）
```

### 4. 创建 Hermes cron 投递任务

在 Hermes Agent 会话中执行:
```
/cron create "every 1m" --no-agent --script /home/arduino/SmartPosture_Guardian/bin/deliver_alerts.sh --deliver weixin --name "坐姿告警"
```

查看 cron 状态:
```
/cron list
```

### 5. 端到端验证

1. 确认 SmartPosture Guardian 运行中
2. 确认 Hermes Agent 运行中且微信已连接
3. 故意前倾 5 秒触发报警
4. 1 分钟内家长微信应收到了告警消息

## Configuration

编辑 `src/config.py`:
```python
HERMES_ENABLED = True          # 总开关
HERMES_COOLDOWN_SEC = 60       # 冷却窗口 (调试用 60s，正式可改为 600s)
HERMES_ALERT_FILE = "alerts.jsonl"  # 告警队列文件
```

## Alert Format

家长微信收到的消息格式:
```
⚠️ 坐姿提醒

孩子当前坐姿前倾(眼距比=1.35) | 低头(高度降=30.2px)，请注意提醒

检测时间: 2026-07-16T14:32:00
详情: 前倾(眼距比=1.35) | 低头(高度降=30.2px)
---
```

## Troubleshooting

1. **alerts.jsonl 不生成**: 检查 `HERMES_ENABLED=True`，确认坐姿确实触发了 ALERTING (持续 5s 不良)
2. **Hermes cron 不工作**: `hermes gateway` 是否在运行？`/cron list` 看 cron 是否 active
3. **微信收不到**: 确认 `hermes gateway setup` 中微信已正确配置并连接
4. **告警风暴 (每 1 分钟都收到)**: 检查 `HERMES_COOLDOWN_SEC`，冷却窗口应大于 cron 间隔
