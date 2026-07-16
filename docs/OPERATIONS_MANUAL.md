# SmartPosture Guardian — 使用与测试手册

> 适用版本：v0.1.0 | 目标硬件：Arduino UNO-Q (ARM64 + STM32U585) | 最后更新：2026-07-16

---

## 目录

1. [系统概述](#1-系统概述)
2. [首次部署](#2-首次部署)
3. [启动与停止](#3-启动与停止)
4. [LED 指示灯与蜂鸣器速查](#4-led-指示灯与蜂鸣器速查)
5. [Web 调试上位机](#5-web-调试上位机)
6. [Hermes 微信告警绑定](#6-hermes-微信告警绑定)
7. [坐姿判定逻辑详解](#7-坐姿判定逻辑详解)
8. [系统状态流转图](#8-系统状态流转图)
9. [阈值修改指南（给测试人员）](#9-阈值修改指南给测试人员)
10. [API 接口参考](#10-api-接口参考)
11. [异常场景与排查](#11-异常场景与排查)
12. [日常维护命令](#12-日常维护命令)

---

## 1. 系统概述

SmartPosture Guardian 是一款完全运行在 Arduino UNO-Q 边缘设备上的**实时坐姿监测系统**。

```
┌──────────────┐     USB Camera      ┌─────────────────────┐
│  8×13 LED    │ ←── Bridge RPC ──   │                     │
│  点阵 + RGB  │                      │   UNO-Q Linux MPU   │─── WiFi ─── 家长微信
│  + 蜂鸣器    │                      │   (QRB2210 ARM64)   │
└──────────────┘                      └─────────────────────┘
```

**核心能力**：
- 插电即用，无需连接电脑，无需任何手动命令
- 自动校准（启动后 5 秒采集基准值）
- 三指标复合判定：前倾 / 低头 / 歪头
- 声光报警：红色 LED + 三角感叹号点阵 + 间歇蜂鸣
- 微信远程告警（可选，需配置 Hermes）
- Web 调试上位机：浏览器实时查看摄像头标注画面

---

## 2. 首次部署

### 2.1 前提条件

UNO-Q 上已具备：
- Python 3.13 + 依赖包（`opencv-python-headless`, `numpy`, `onnxruntime`, `fastapi`, `uvicorn`, `msgpack`, `gpiod`）
- systemd 257 + `linger` 已为用户 `arduino` 开启
- STM32 MCU sketch (`posture_alerter`) 已部署并运行
- Hermes Agent 已安装（可选，仅微信告警需要）

### 2.2 一次性配置

```bash
# 1. 确认 MCU sketch 正在运行
arduino-app-cli app list | grep posture_alerter
# 预期输出包含 "posture_alerter" 且状态为 running

# 2. 确认两个 systemd 服务已启用
systemctl --user is-enabled hermes-gateway.service
systemctl --user is-enabled smartposture-guardian.service
# 预期均输出 "enabled"

# 3. 确认 linger 已开启
loginctl show-user arduino | grep Linger
# 预期输出 "Linger=yes"
```

如果某服务未启用：

```bash
# 启用 Guardian
systemctl --user enable --now smartposture-guardian.service

# 启用 Hermes Gateway
systemctl --user enable --now hermes-gateway.service
```

### 2.3 确认摄像头

```bash
v4l2-ctl --list-devices
# 确认 USB Camera 出现在列表中（非 "qcom-venus" 设备）
```

---

## 3. 启动与停止

### 3.1 自动启动（正常使用）

> **插上电源即可。** 无需键盘、显示器、SSH。

UNO-Q 通电后：
1. Debian Linux 启动（~15 秒）
2. systemd 自动拉起 `hermes-gateway.service`（IM 消息通道就绪）
3. systemd 自动拉起 `smartposture-guardian.service`
4. Guardian 启动 → 5 秒校准 → 进入监控 → 蓝色 LED 变绿色

**全程约 20-30 秒**，之后板载 LED 和点阵会显示当前状态。

### 3.2 手动启动（调试用）

```bash
# 先停掉 systemd 管理的实例（避免端口冲突）
systemctl --user stop smartposture-guardian.service

# 手动启动（可看实时日志）
cd ~/SmartPosture_Guardian
python3 src/main.py
```

按 `Ctrl+C` 退出，之后可恢复自动管理：

```bash
systemctl --user start smartposture-guardian.service
```

### 3.3 停止

```bash
systemctl --user stop smartposture-guardian.service
```

### 3.4 查看运行状态

```bash
# Guardian 状态
systemctl --user status smartposture-guardian.service

# Hermes Gateway 状态
systemctl --user status hermes-gateway.service

# 实时日志
journalctl --user -u smartposture-guardian.service -f
```

### 3.5 崩溃自愈

如果 Guardian 进程意外崩溃，systemd 会在 **5 秒后自动重启**。 连续崩溃不会影响重启策略。

```bash
# 查看重启历史
journalctl --user -u smartposture-guardian.service --since "1 hour ago" | grep -E "Started|Stopped"
```

---

## 4. LED 指示灯与蜂鸣器速查

UNO-Q 板载两颗 RGB LED 和一块 8×13 蓝色 LED 点阵。

### 4.1 LED1 颜色速查

| LED 颜色 | 含义 | 点阵图案 | 蜂鸣器 |
|----------|------|----------|--------|
| 🔵 蓝色常亮 | **校准中** — 正在采集基准值（5 秒） | 清空 | 静音 |
| 🟢 绿色常亮 | **正常监控** — 坐姿良好 | ✓ 对勾 | 静音 |
| 🔴 红色常亮 | **报警中** — 检测到不良坐姿 | ⚠️ 三角感叹号 | 间歇鸣叫 |
| 🟢 绿色慢闪 | **无人休眠** — 超过 20 秒未检测到人脸 | 清空 | 静音 |

### 4.2 蜂鸣器模式

| 场景 | 行为 |
|------|------|
| 正常监控 | 静音 |
| 报警中 | 间歇鸣叫（响 0.15s / 停 0.10s 循环） |
| 校准中 | 静音 |
| 无人休眠 | 静音 |

### 4.3 状态变迁的可视化提示

- **校准 → 监控**：蓝色 LED 突然变绿 + 点阵显示对勾 ✓
- **监控 → 报警**：绿色 LED 突然变红 + 点阵切换为三角感叹号 ⚠️ + 蜂鸣器开始间歇响
- **报警 → 监控**：红色 LED 变回绿 + 点阵切回对勾 + 蜂鸣器停止
- **监控 → 休眠**：绿色 LED 开始慢闪（0.5s 亮 / 1.5s 灭）
- **遮挡 2 秒触发重校准**：LED 变蓝，人脸恢复后重新采集基准值

---

## 5. Web 调试上位机

### 5.1 访问方式

在**同一局域网**内，任意设备（电脑、手机、平板）的浏览器打开：

```
http://<UNO-Q-IP地址>:8000/viewer
```

> 查看 UNO-Q IP 地址：在 UNO-Q 终端执行 `ip addr show wlan0` 或 `hostname -I`

### 5.2 画面内容

| 标注元素 | 颜色 | 说明 |
|----------|------|------|
| 左眼轮廓 8 点 | 🟢 绿色小圆点 | PFLD 模型定位的左眼关键点 |
| 右眼轮廓 8 点 | 🟢 绿色小圆点 | PFLD 模型定位的右眼关键点 |
| 双眼中心 | 🟡 黄色大圆 | 眼睛轮廓均值中心 |
| 双眼连线 | 🟣 紫色线 | 用于计算 Roll（歪头角） |
| 人脸估算框 | 🟢 绿色矩形 | YuNet 检测的人脸边界框 |
| 鼻尖 | 🟠 橙色实心圆 | PFLD 鼻尖关键点 + 中点到鼻尖连线 |
| 状态标签 | 绿/红色文字 | FACE OK 或 NO FACE |
| 眼距数值 | 🟡 黄色文字 | 当前双眼像素距离 |
| Eye Y | 白色文字 | 当前眼睛 Y 轴坐标 |
| Roll / Yaw | 🟡 黄色文字 | 歪头角度 + 侧脸比例 |

### 5.3 调试用途

- **校准验证**：校准完成后，正常坐姿下眼距数值应稳定在基准值附近
- **触发测试**：故意前倾，观察眼距数值是否变大（>1.2× 基准值触发报警）
- **低头测试**：故意低头，观察 Eye Y 数值是否明显上升
- **歪头测试**：倾斜头部，观察 Roll 角度是否超过 ±12°

---

## 6. Hermes 微信告警绑定

### 6.1 架构说明

```
异常坐姿 5s 持续
    │
    ▼
Guardian 写 alerts.jsonl (文件队列)
    │
    ▼
Hermes cron (每 1 分钟)
    │  bin/deliver_alerts.sh 读取
    ▼
家长微信收到 ⚠️ 坐姿提醒
```

告警延迟：最多 1 分钟。冷却窗口：60 秒内不重复推送（可在 config.py 调整）。

### 6.2 绑定微信（一次性）

在 UNO-Q 终端执行：

```bash
# 1. 确认 Hermes Gateway 正在运行
systemctl --user status hermes-gateway.service

# 2. 进入 Hermes 配置微信平台
hermes gateway setup

# 3. 按提示选择 weixin，扫码绑定
# 扫码后微信会收到一条确认消息，回复确认即完成绑定
```

### 6.3 配置用户授权

编辑 `~/.hermes/.env`，添加微信用户白名单：

```bash
# 查看最近的未授权用户日志，获取微信用户 ID
journalctl --user -u hermes-gateway.service | grep "Unauthorized user"

# 在 ~/.hermes/.env 中添加：
WEIXIN_ALLOWED_USERS=o9cq80-xxxxxxxxxxxxxxxxxxxxxxxx
```

### 6.4 验证告警链路

```bash
# 1. 确认 cron 已存在
hermes cron list
# 预期看到 "坐姿告警" (every 1m, active)

# 2. 如果 cron 不存在，创建它：
hermes cron create "every 1m" \
  --no-agent \
  --script /home/arduino/SmartPosture_Guardian/bin/deliver_alerts.sh \
  --deliver weixin \
  --name "坐姿告警"

# 3. 手动测试投递脚本
cd ~/SmartPosture_Guardian
echo '{"timestamp":"2026-07-16T12:00:00","type":"posture_alert","message":"测试消息","reason":"手动测试"}' > alerts.jsonl
./bin/deliver_alerts.sh
# 预期 stdout 输出格式化告警文本，执行后 alerts.jsonl 被清空
```

### 6.5 微信收到的消息格式

```
⚠️ 坐姿提醒

孩子当前坐姿前倾(眼距比=1.35) | 低头(高度降=30.2px)，请注意提醒

检测时间: 2026-07-16T14:32:00
详情: 前倾(眼距比=1.35) | 低头(高度降=30.2px)
---
```

### 6.6 关闭微信告警

编辑 `src/config.py`：

```python
HERMES_ENABLED = False   # 设为 False 则静默跳过所有告警
```

修改后重启 Guardian：

```bash
systemctl --user restart smartposture-guardian.service
```

---

## 7. 坐姿判定逻辑详解

### 7.1 三指标判定

系统使用 PFLD (98 点 WFLW) 面部关键点模型，精确提取双眼各 8 个轮廓点和鼻尖，计算三项指标：

| 指标 | 计算方式 | 阈值 | 触发条件 |
|------|----------|------|----------|
| **前倾** (Lean Forward) | 当前眼距 ÷ 基准眼距 | **> 1.2** | 头部靠近屏幕 → 眼距放大 |
| **低头** (Head Drop) | 当前眼Y − 基准眼Y | **> 25 px** | 低头 → 眼睛在画面中下移 |
| **歪头** (Head Tilt) | 眼线偏离水平面的角度 (Roll) | **> 12°** | 头部侧倾 |

> 三个指标为 **OR 关系**：任一触发即判定为不良坐姿。告警消息中会列出所有触发项。

### 7.2 时间滤波（防误报）

```
不良坐姿需持续 ≥ 5 秒 → 触发 ALERTING（红色 LED + 蜂鸣器）
坐姿恢复正常需稳定 ≥ 3 秒 → 解除报警
```

短暂的前倾（如捡东西、打喷嚏）不会误报。

### 7.3 质量门控（防误判）

以下帧会被**丢弃，且不更新计时器**：

| 门控条件 | 阈值 | 目的 |
|----------|------|------|
| 侧脸 | 鼻尖偏移比 (yaw_ratio) > 0.35 | 侧脸时眼睛位置不准 |
| 帧间跳变 | 眼距变化 > 30% | 检测异常（如遮挡、快速移动） |
| 最小眼距 | < 15 px | 人脸太小或检测失败 |

### 7.4 多人脸选脸策略

当画面中出现多人时：
1. **主策略**：选人脸框面积**最大**的（距离摄像头最近的人）
2. **辅助策略**：两张脸面积接近（差距 <20%）时，用**位置连续性**裁决，选择与上一帧位置最近的人脸，防止跳变

### 7.5 无感重校准

**遮挡镜头 ≥ 2 秒** → 人脸恢复后自动重新校准（LED 变蓝，采集 5 秒新基准值）。

适用场景：
- 用户调整了座椅位置
- 摄像头被移动
- 更换了使用者

---

## 8. 系统状态流转图

```
                    ┌─────────┐
                    │ 开机启动 │
                    └────┬────┘
                         │
                         ▼
                  ┌──────────────┐
                  │  CALIBRATING │  🔵 蓝色 LED
                  │  (采集 5 秒)  │
                  └──────┬───────┘
                         │ 校准完成
                         ▼
                  ┌──────────────┐
         ┌───────│  MONITORING  │  🟢 绿色 LED + ✓ 对勾
         │       └──┬───┬───┬───┘
         │          │   │   │
         │   不良 5s │   │   │ 无脸≥20s
         │          │   │   │
         │          ▼   │   │
         │   ┌──────────┐ │   │
         │   │ ALERTING │ │   │  🔴 红色 LED + ⚠️ + 蜂鸣器
         │   └────┬─────┘ │   │        + 微信推送
         │        │       │   │
         │  恢复 3s│       │   │
         │        ▼       │   │
         │   ┌──────────┐ │   │
         │   │ COOLDOWN │ │   │  (瞬间，内部状态)
         │   └────┬─────┘ │   │
         │        │       │   │
         └────────┘       │   │
                          │   │
                          │   ▼
                          │  ┌──────────────┐
                          │  │  UNATTENDED  │  🟢 绿色慢闪
                          │  │  (休眠降频)   │
                          │  └──────┬───────┘
                          │         │ 连续有脸 ≥3s
                          └─────────┘
                         (唤醒回 MONITORING)

        任意状态 (MONITORING/ALERTING/COOLDOWN):
              遮挡镜头 ≥2s → 标记待重校准
              人脸恢复后 → 返回 CALIBRATING
```

---

## 9. 阈值修改指南（给测试人员）

所有可调参数集中在 **`src/config.py`**。修改后需重启服务生效：

```bash
systemctl --user restart smartposture-guardian.service
```

### 9.1 坐姿灵敏度

```python
# src/config.py

# 前倾灵敏度：值越小越敏感
# 例如改为 1.15：稍微前倾就触发
# 例如改为 1.30：只有明显前倾才触发
EYE_DISTANCE_RATIO_THRESHOLD = 1.2

# 低头灵敏度：值越小越敏感
# 例如改为 15：轻微低头就触发
# 例如改为 40：只有明显低头才触发
HEIGHT_DROP_THRESHOLD_PX = 25.0
```

### 9.2 时间窗口

```python
# 不良坐姿需持续多久才报警（防误报）
# 例如改为 3.0：更快触发，但容易误报
# 例如改为 10.0：更宽容，但响应慢
ALERT_PERSIST_SEC = 5.0

# 报警后姿势恢复需稳定多久才解除
ALERT_COOLDOWN_SEC = 3.0

# 启动后自动校准采集秒数
CALIBRATION_DURATION_SEC = 5.0
```

### 9.3 休眠与唤醒

```python
# 连续无脸多久进入休眠
UNATTENDED_TIMEOUT_SEC = 20.0

# 连续有脸多久从休眠唤醒
UNATTENDED_WAKE_SEC = 3.0
```

### 9.4 微信告警

```python
# 告警冷却窗口（两次推送的最小间隔）
# 调试时用 60s，正式使用建议 600s（10 分钟）
HERMES_COOLDOWN_SEC = 60

# 总开关：False = 关闭微信推送
HERMES_ENABLED = True
```

### 9.5 当前硬编码值（不在 config.py 中）

以下阈值当前**写死在代码逻辑中**，后续会迁移到 config.py：

| 参数 | 位置 | 当前值 | 含义 |
|------|------|--------|------|
| 歪头角阈值 | `main.py:794` | `12.0°` | 头倾斜超过此角度触发歪头判定 |
| 侧脸门控 | `main.py:730` | `0.35` | 鼻尖偏移比超过此值丢弃帧 |
| 帧间跳变门控 | `main.py:736` | `0.30` | 眼距跳变超过 30% 丢弃帧 |
| 最小眼距 | `landmarker.py:34` | `15.0 px` | 眼距低于此值判定为异常 |

> 如需修改这些值，直接编辑对应 `.py` 文件后重启服务。

### 9.6 基准值手动注入

如果不使用自动校准，可以通过 API 手动设置用户专属基准值：

```bash
curl -X POST http://localhost:8000/api/v1/calibration \
  -H "Content-Type: application/json" \
  -d '{"user_D_normal": 62.5, "user_Y_normal": 180.0}'
```

> 基准值获取方法：在 Web 上位机中保持正确坐姿，记录稳定状态下的眼距和 Eye Y 值。

---

## 10. API 接口参考

Base URL: `http://<UNO-Q-IP>:8000`

### 10.1 健康检查

```bash
GET /api/v1/health

# 响应
{"status": "ok"}
```

### 10.2 系统状态

```bash
GET /api/v1/status

# 响应
{
  "is_calibrated": true,       # 是否已完成校准
  "D_normal": 54.73,           # 基准眼距 (px)
  "Y_normal": 84.81,           # 基准眼睛高度 (px)
  "is_alerting": false,        # 是否正在报警
  "state": "running",          # 系统运行状态
  "posture_state": "MONITORING"  # 当前 FSM 状态
}
```

`posture_state` 可能的取值：
- `CALIBRATING` — 校准中
- `MONITORING` — 正常监控
- `ALERTING` — 报警中
- `COOLDOWN` — 报警后冷却
- `UNATTENDED` — 无人休眠

### 10.3 注入基准值

```bash
POST /api/v1/calibration
Content-Type: application/json

{
  "user_D_normal": 62.5,
  "user_Y_normal": 180.0
}

# 成功响应 (200)
{"status": "ok", "D_normal": 62.5, "Y_normal": 180.0}

# 失败响应 (200)
{"status": "error", "message": "基准值必须大于 0"}
```

### 10.4 调试上位机

| 路径 | 类型 | 说明 |
|------|------|------|
| `/viewer` | HTML 页面 | 实时摄像头 + 16 点眼轮廓标注 |
| `/stream` | MJPEG 流 | 原始视频流（~20 fps, JPEG quality 55） |

---

## 11. 异常场景与排查

### 11.1 Guardian 启动失败

```bash
# 查看详细错误
journalctl --user -u smartposture-guardian.service -n 50 --no-pager
```

常见原因：

| 日志关键词 | 原因 | 解决方法 |
|-----------|------|----------|
| `无法打开摄像头` | USB 摄像头未插入或设备索引错误 | 检查 USB 连接；运行 `v4l2-ctl --list-devices` 确认设备 |
| `YuNet 模型不存在` | ONNX 模型文件缺失 | 确认 `models/face_detection_yunet.onnx` 和 `models/pfpld.onnx` 存在 |
| `PFLD 初始化失败` | ONNX Runtime 版本不兼容 | 检查 `onnxruntime` 版本 |
| `Bridge socket 不存在` | STM32 MCU sketch 未运行 | 运行 `arduino-app-cli app start user:posture_alerter` |
| `Address already in use` | 端口 8000 被占用 | 已有一个 Guardian 实例在运行；先 `systemctl --user stop` |

### 11.2 摄像头异常

系统有自动重连机制：**连续 30 帧读取失败 → 自动释放并重新打开摄像头**。

如果重连也失败：
```bash
# 检查摄像头设备
ls /dev/video*
v4l2-ctl -d /dev/video2 --all  # 替换为实际设备号

# 重启 Guardian
systemctl --user restart smartposture-guardian.service
```

### 11.3 蜂鸣器不响

1. 确认 MCU sketch 运行中：`arduino-app-cli app list | grep posture_alerter`
2. 确认 Bridge Socket 存在：`ls -la /var/run/arduino-router.sock`
3. 查看日志中是否有 RPC 错误：`journalctl --user -u smartposture-guardian.service | grep "RPC 失败"`

### 11.4 LED 点阵不显示

同上排查步骤。点阵和蜂鸣器均通过 STM32 MCU 控制。

### 11.5 微信收不到告警

排查链路：

```bash
# Step 1: 确认 Hermes Gateway 运行中
systemctl --user status hermes-gateway.service

# Step 2: 确认微信已连接
hermes gateway status

# Step 3: 确认 cron 存在且 active
hermes cron list

# Step 4: 确认 alerts.jsonl 有内容
cat ~/SmartPosture_Guardian/alerts.jsonl

# Step 5: 手动触发投递
cd ~/SmartPosture_Guardian && ./bin/deliver_alerts.sh

# Step 6: 检查未授权用户
journalctl --user -u hermes-gateway.service | grep "Unauthorized user"
# 如果看到你的微信 ID，需要加到 ~/.hermes/.env 白名单
```

### 11.6 校准异常

**现象**：LED 长时间保持蓝色，不进入绿色监控状态。

**原因**：校准期间未检测到足够的人脸样本（需 ≥10 个有效帧）。

**解决**：
- 确认人脸在摄像头画面中清晰可见
- 打开 Web 上位机查看 FACE OK / NO FACE 状态
- 检查光照是否充足

### 11.7 误报警频繁

1. **光照变化大**：眼距检测可能波动。调高 `ALERT_PERSIST_SEC`（如改为 8 秒）
2. **摄像头位置不稳**：重新校准（遮挡镜头 2 秒）
3. **阈值过敏感**：调高 `EYE_DISTANCE_RATIO_THRESHOLD`（如改为 1.3）或 `HEIGHT_DROP_THRESHOLD_PX`（如改为 35）

### 11.8 报警不触发

1. **阈值过宽**：调低 `EYE_DISTANCE_RATIO_THRESHOLD`（如改为 1.15）或 `HEIGHT_DROP_THRESHOLD_PX`（如改为 15）
2. **时间窗口过长**：减少 `ALERT_PERSIST_SEC`（如改为 3 秒）
3. **质量门控过滤**：检查是否因为侧脸或帧间跳变导致帧被丢弃。在 Web 上位机中观察 Roll/Yaw 数值

---

## 12. 日常维护命令

```bash
# === 服务管理 ===
systemctl --user status smartposture-guardian.service   # 查看状态
systemctl --user restart smartposture-guardian.service  # 重启
systemctl --user stop smartposture-guardian.service     # 停止
systemctl --user start smartposture-guardian.service    # 启动

# === 日志查看 ===
journalctl --user -u smartposture-guardian.service -f              # 实时跟踪
journalctl --user -u smartposture-guardian.service -n 50           # 最近 50 行
journalctl --user -u smartposture-guardian.service --since today   # 今日日志

# === 硬件检查 ===
v4l2-ctl --list-devices                              # 摄像头列表
arduino-app-cli app list                              # MCU app 状态
ls -la /var/run/arduino-router.sock                   # Bridge socket

# === API 检查 ===
curl -s http://localhost:8000/api/v1/health           # 健康检查
curl -s http://localhost:8000/api/v1/status | python3 -m json.tool  # 系统状态

# === 告警文件 ===
cat ~/SmartPosture_Guardian/alerts.jsonl              # 待投递告警
cat ~/SmartPosture_Guardian/alerts.jsonl.delivered    # 已投递告警

# === 进程检查 ===
ps aux | grep "src/main.py"                           # Guardian 进程
```

---

## 附录 A：目录结构

```
~/SmartPosture_Guardian/
├── src/
│   ├── main.py            # 主入口（四线程 + 状态机 + FastAPI）
│   ├── config.py          # ⚙️ 所有可调参数集中于此
│   ├── alerter.py         # LED 点阵 + RGB LED + 蜂鸣器控制
│   ├── hermes.py          # 微信告警文件队列
│   ├── landmarker.py      # PFLD 98 点关键点定位
│   └── debug_viewer.py    # MJPEG 调试流 + 画面标注
├── bin/
│   └── deliver_alerts.sh  # Hermes cron 投递脚本
├── models/
│   ├── face_detection_yunet.onnx   # 人脸检测 (228KB)
│   └── pfpld.onnx                  # 关键点定位 (6.6MB)
├── logs/                  # 运行日志
├── docs/
│   ├── OPERATIONS_MANUAL.md  # 📖 本文件
│   └── DevLog.md             # 开发记录
└── alerts.jsonl           # 告警事件队列（自动生成）
```

## 附录 B：配置速查卡片

| 想实现的效果 | 改哪个参数 | 推荐值 |
|-------------|-----------|--------|
| 更敏感的前倾检测 | `EYE_DISTANCE_RATIO_THRESHOLD` | 1.15 |
| 更宽容的前倾检测 | `EYE_DISTANCE_RATIO_THRESHOLD` | 1.30 |
| 更敏感的低头检测 | `HEIGHT_DROP_THRESHOLD_PX` | 15 |
| 更宽容的低头检测 | `HEIGHT_DROP_THRESHOLD_PX` | 40 |
| 更快的报警响应 | `ALERT_PERSIST_SEC` | 3.0 |
| 减少误报 | `ALERT_PERSIST_SEC` | 8.0 |
| 更快的报警解除 | `ALERT_COOLDOWN_SEC` | 1.5 |
| 微信不推送了 | `HERMES_ENABLED` | False |
| 微信少推些 | `HERMES_COOLDOWN_SEC` | 600 |

---

*Built for Arduino UNO-Q · Debian 13 · Python 3.13 · systemd 257*
