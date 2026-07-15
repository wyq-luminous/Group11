# 慧姿·智能坐姿守护系统 (SmartPosture_Guardian)

> 🪑 **脱离 PC 的嵌入式智能坐姿监控硬件** — 在 UNO-Q 核心板上独立运行的边缘 AI 护眼助手。

---

## 📌 项目简介

SmartPosture_Guardian 是一款完全运行在 ARM64 边缘设备（Arduino UNO-Q）上的实时坐姿监测系统。通过 USB 摄像头采集图像，利用 YuNet DNN 模型提取人脸关键点，计算双眼像素距离与高度偏移。当检测到不良前倾坐姿并持续 5 秒后，通过板载 8×13 LED 点阵显示三角感叹号 ⚠️ 警告符号，并触发外接蜂鸣器报警。

**核心特点**：
- 🚫 不依赖 PC，不连接云端，完全本地推理
- ⚡ 空间域算法优化，无频域处理，极致省算力
- 🔇 无感自动校准 + **遮挡镜头 2 秒触发重校准**（任意状态可用），无需用户手动标定
- 🎯 PFLD 98 点面部关键点精确定位双眼，支持歪头/侧脸抗干扰
- 🧭 三指标复合判定（前倾 / 低头 / 歪头）+ 侧脸质量门控
- 🌐 内置 Web 调试上位机，浏览器实时查看 16 点眼轮廓标注
- 🔵 四色 LED 状态反馈 (绿=正常 / 红=报警 / 蓝=校准中 / 绿慢闪=无人休眠)
- 👥 多人脸智能选脸（最大脸优先 + 位置连续性防跳变）
- 💤 无人自动休眠（20s 无脸降频省电，人脸恢复 3s 唤醒）

---

## 🧠 核心机制

### 1. 无感基线校准

系统启动后自动采集用户正常坐姿下的双眼参数作为基准值：
- **基准眼距 (D_normal)**: 正常坐姿下的双眼像素距离
- **基准高度 (Y_normal)**: 正常坐姿下的眼睛 Y 轴坐标

**运行时重校准**: 用手掌完全遮挡摄像头 **2 秒以上**，移开后系统自动重新校准。适用于用户更换座位、调整摄像头位置等场景。校准期间板载 LED 显示蓝灯。

### 2. 三指标复合判定

系统通过 YuNet 检测人脸边界框，再由 PFLD ONNX (98 点 WFLW) 精确定位双眼及鼻尖，计算三项坐姿指标：

| 指标 | 计算方法 | 报警阈值 |
|------|----------|----------|
| 前倾 | 当前眼距 / 基准眼距 | > 1.2×（头部靠近屏幕导致眼距放大） |
| 低头 | 当前眼Y − 基准眼Y | > 25px（低头导致眼睛在画面中下移） |
| 歪头 | atan2(右眼Y−左眼Y, 右眼X−左眼X) | > 15°（头部侧倾） |

**质量门控**:
- 侧脸 (鼻尖偏移比 > 0.35) → 丢弃帧，冻结计时器
- 帧间眼距跳变 > 30% → 丢弃帧，冻结计时器
- 双眼间距 < 15px → 判定为检测异常

### 3. 时间滤波防误报

异常状态需**持续 5 秒**才触发报警；姿势恢复需**稳定 3 秒**才解除。避免捡东西、打喷嚏等短暂动作误报。

### 4. 空间域算法优化

- 减少循环嵌套，NumPy 广播替代显式循环
- 图像缩放使用 `cv2.INTER_AREA` 空间域插值
- **不使用 FFT / DCT / 小波变换等任何频域方法**

---

## 🏗 系统架构

```
┌─────────────────────────────────────────────────────┐
│              UNO-Q Linux MPU (Qualcomm QRB2210)      │
│                                                      │
│  线程1: FastAPI (0.0.0.0:8000)                      │
│         ├─ /viewer          调试上位机页面           │
│         ├─ /stream          MJPEG 眼标注流          │
│         ├─ /api/v1/calibration  POST 基准值注入      │
│         ├─ /api/v1/status       GET  系统状态        │
│         └─ /api/v1/health       GET  健康检查        │
│                                                      │
│  线程2: 采集 (V4L2 30fps drain)                     │
│  线程3: 推理 (YuNet 找脸 → PFLD 98点定位 → 姿态指标) │
│  线程4: 主控 (PostureAnalyzer 状态机 + Alerter)     │
│              │                                       │
│              ▼ msgpack RPC                           │
│         /var/run/arduino-router.sock                 │
└─────────────┬───────────────────────────────────────┘
              │
┌─────────────▼───────────────────────────────────────┐
│           STM32U585 MCU (Zephyr RTOS)                │
│                                                      │
│  Arduino_LED_Matrix (Charlieplexing PF0-PF10)       │
│         └─ 8×13 蓝色 LED 点阵                       │
│  digitalWrite(D2) ── 蜂鸣器 (LOW 触发)              │
└─────────────────────────────────────────────────────┘
```

---

## 📡 API 接口文档

Base URL: `http://<UNO-Q-IP>:8000`

### 校准

```
POST /api/v1/calibration
Content-Type: application/json

{
  "user_D_normal": 62.5,
  "user_Y_normal": 180.0
}

Response 200:
{
  "status": "ok",
  "D_normal": 62.5,
  "Y_normal": 180.0
}
```
前端用户登录后发送专属基准值，覆盖自动校准结果。值必须 > 0。

### 系统状态

```
GET /api/v1/status

Response 200:
{
  "is_calibrated": true,
  "D_normal": 62.5,
  "Y_normal": 180.0,
  "is_alerting": false,
  "state": "running",
  "posture_state": "MONITORING"
}
```

### 健康检查

```
GET /api/v1/health

Response 200: {"status": "ok"}
```

### 调试上位机

```
浏览器访问: http://<UNO-Q-IP>:8000/viewer

实时显示:
- 摄像头画面
- 双眼十字准星 (黄色) + 绿色圆圈
- 双眼连线 (紫色)
- 眼距数值 (像素)
- 人脸估算框
- FACE OK / NO FACE 状态
```

---

## 📁 目录结构

```
SmartPosture_Guardian/
├── README.md              # 项目说明（本文件）
├── requirements.txt       # Python 依赖清单
├── src/
│   ├── main.py            # 主入口 (四线程调度 + FastAPI + FSM)
│   ├── config.py          # 全局配置常量
│   ├── alerter.py         # 报警输出 (LED矩阵 + RGB LED + 蜂鸣器)
│   ├── landmarker.py      # PFLD 98点关键点定位 (双眼+鼻尖)
│   ├── debug_viewer.py    # 调试上位机 (MJPEG流 + 16点眼轮廓标注)
│   └── bench_pfld.py      # PFLD 模型 benchmark 工具
├── models/
│   ├── face_detection_yunet.onnx   # YuNet DNN 人脸检测 (228KB)
│   └── pfpld.onnx                  # PFLD 98点面部关键点 (6.6MB)
├── docs/
│   └── DevLog.md          # 开发记录
├── tests/                 # 测试
└── logs/                  # 运行日志
```

`~/ArduinoApps/posture_alerter/` (Arduino App)
```
├── app.yaml
├── python/main.py         # Python 端 (保持 Bridge 存活)
└── sketch/
    ├── sketch.yaml
    └── sketch.ino         # STM32 固件 (LED矩阵 + 蜂鸣器 RPC)
```

---

## 🚀 快速开始

```bash
# 1. 安装系统依赖
pip install --break-system-packages -r requirements.txt

# 2. 确认 MCU sketch 已部署
arduino-app-cli app list | grep posture_alerter
# 若未运行: arduino-app-cli app start user:posture_alerter

# 3. 插入 USB 摄像头

# 4. 启动系统
cd ~/SmartPosture_Guardian
python3 src/main.py

# 5. 浏览器打开调试上位机
# http://<板子IP>:8000/viewer
```

---

## ⚙️ 技术栈

| 组件 | 选型 | 理由 |
|------|------|------|
| 图像采集 | OpenCV headless + V4L2 (MJPG) | 无桌面环境，MJPG 压缩节省 USB 带宽 |
| 人脸检测 | OpenCV FaceDetectorYN (YuNet ONNX) | 228KB 极小人脸检测 |
| 关键点定位 | PFLD ONNX (98 点 WFLW) | 6.6MB，双眼各 8 轮廓点 + 鼻尖，OpenCV DNN 推理 |
| 矩阵运算 | NumPy | 空间域向量化计算 |
| LED 矩阵 | STM32 Charlieplexing → Bridge RPC | 硬件由 MCU 管理，Linux 端不可直接访问 |
| 蜂鸣器 | STM32 digitalWrite(D2) → Bridge RPC | LOW 电平触发，通过 MCU sketch 控制 |
| Web 服务 | FastAPI + uvicorn (0.0.0.0:8000) | 局域网内任意设备可访问 |
| IPC | Unix Socket + MsgPack | Linux ↔ STM32 高效二进制通信 |

---

## 🔧 后续开发

### 短期 (功能完善)

- [x] **无感重校准**: 遮挡镜头 2 秒触发自动重校准，LED 蓝灯反馈 (2026-07-15)
- [x] **Git 版本管理**: 接入 GitHub `wyq-luminous/Group11.git`，DevLog 自动记录 (2026-07-15)
- [ ] **LED 阵列灰度动画**: 利用 8 级硬件灰度实现报警图案呼吸效果
- [ ] **云端告警推送**: `requests` → Hermes 服务触发家长微信通知 (10min 冷却)
- [x] **异常场景抗干扰**: 侧脸丢弃 + 帧间跳变冻结 + 歪头检测 (2026-07-15)
- [x] **PFLD 面部关键点**: 98 点 WFLW 替代 YuNet 5 粗点，精确追踪双眼 (2026-07-15)
- [x] **多人脸选脸**: 最大脸优先 + 位置连续性防跳变 (2026-07-15)
- [x] **无人自动休眠**: 20s 无脸降频 1fps + 3s 唤醒 + 绿灯慢闪 (2026-07-15)
- [ ] **前端校准对接**: 陈朵的 Web 前端通过 `POST /api/v1/calibration` 注入用户专属基准值
- [ ] **日志持久化**: 坐姿异常事件记录到 `logs/events.jsonl`
- [ ] **单元测试**: `tests/` 下补充状态机逻辑和眼距计算的测试用例

### 中期 (模型升级)

- [x] **PFLD 面部关键点**: 98 点 WFLW 替代 YuNet 5 点，精确追踪双眼 (2026-07-15)
- [ ] **模型量化**: INT8 量化加速 PFLD 推理（目标 < 30ms/帧）
- [x] **多人脸处理**: 支持画面中多人时选择主要使用者 (2026-07-15)

### 长期 (产品化)

- [ ] **OTA 更新**: 通过 Arduino Cloud 远程更新模型和代码
- [ ] **历史数据面板**: Web 页面展示坐姿趋势图表
- [ ] **语音提醒**: 替代蜂鸣器，使用语音合成播报"请调整坐姿"

---

## ⚠️ 已知约束

| 约束项 | 说明 |
|--------|------|
| **MediaPipe 不可用** | ARM64 + Python 3.13 无预编译 wheel |
| **V4L2 缓冲区积压** | 必须采集/推理/输出三线程解耦 |
| **headless OpenCV** | 必须用 `opencv-python-headless` 而非标准版 |
| **LED 矩阵不可直接访问** | STM32 Charlieplexing，Linux 端必须通过 Bridge RPC |
| **Arduino 排针 GPIO** | D2 等引脚由 STM32 MCU 管理，gpiod 不可用 |
| **STN32 闪存校验** | Bank 1 (1MB+) 校验持续失败，代码需保持在 Bank 0 内 |
| **网络受限** | 大模型文件需通过 U 盘/scp 离线传输到板子 |

---

*Built for Arduino UNO-Q (Qualcomm QRB2210 + STM32U585) · Debian 13 · Python 3.13*
