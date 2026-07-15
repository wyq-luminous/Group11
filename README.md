# 慧姿·智能坐姿守护系统 (SmartPosture_Guardian)

> 🪑 **脱离 PC 的嵌入式智能坐姿监控硬件** — 在 UNO-Q 核心板上独立运行的边缘 AI 护眼助手。

---

## 📌 项目简介

SmartPosture_Guardian 是一款完全运行在 ARM64 边缘设备（UNO-Q）上的实时坐姿监测系统。通过 USB 摄像头采集图像，利用轻量级 AI 姿态估计模型提取人脸关键点，计算双眼像素距离与高度偏移，当检测到不良前倾坐姿并持续 5 秒后，触发本地蜂鸣器/LED 报警，提醒用户纠正坐姿。

**核心特点**：
- 🚫 不依赖 PC，不连接云端，完全本地推理
- ⚡ 空间域算法优化，无频域处理，极致省算力
- 🔇 无感自动校准，无需用户手动标定

---

## 🧠 核心机制

### 1. 无感基线校准

系统启动后自动采集用户正常坐姿下的双眼参数作为基准值：
- **基准眼距**：正常坐姿下的双眼像素距离
- **基准高度**：正常坐姿下的眼睛 Y 轴坐标

无需用户点击"校准"按钮 — 系统在最初若干秒内自动完成。

### 2. 双指标复合判定

| 指标 | 计算方法 | 报警阈值 |
|------|----------|----------|
| 眼距比率 | 当前眼距 / 基准眼距 | > 1.2×（头部前倾导致眼距放大） |
| 高度偏移 | 基准 Y 坐标 − 当前 Y 坐标 | > 阈值（低头导致眼睛位置下移） |

两个指标可独立触发，也可组合判定，有效区分"正常靠近屏幕"与"不良前倾"。

### 3. 时间滤波防误报

单帧异常可能是短暂动作（如捡东西、打喷嚏）。系统要求**异常状态持续 5 秒**才触发报警，避免误报干扰。

### 4. 空间域算法优化

严格遵守以下原则，杜绝频域处理：
- 减少循环嵌套，能用 NumPy 广播替代的不写显式循环
- 2D 图像数组优先展平为 1D 做逐元素运算
- 所有图像处理（缩放、裁剪、遮挡检测）均在空间域完成
- **不使用 FFT、DCT、小波变换等任何频域方法**

---

## 📁 目录结构

```
SmartPosture_Guardian/
├── README.md             # 项目说明文档（本文件）
├── requirements.txt      # Python 依赖清单
├── src/                  # 源代码
│   ├── main.py           # 主入口（系统启动、线程调度）
│   ├── capture.py        # 摄像头采集模块（V4L2 采集线程）
│   ├── inference.py      # AI 推理模块（ONNX Runtime + MoveNet）
│   ├── posture_analyzer.py # 姿态分析（眼距/高度计算 + 状态机）
│   └── alerter.py        # 报警模块（GPIO 蜂鸣器/LED 控制）
├── models/               # AI 模型文件（MoveNet Lightning ONNX）
├── docs/                 # 项目文档
├── tests/                # 单元测试与集成测试
└── logs/                 # 运行日志
```

---

## ⚙️ 技术栈

| 组件 | 选型 | 理由 |
|------|------|------|
| 图像采集 | OpenCV (headless) + V4L2 | 无桌面环境、体积小 |
| AI 推理 | ONNX Runtime + MoveNet Lightning | ARM64 可用，~13MB 轻量模型 |
| 矩阵运算 | NumPy | 空间域向量化计算 |
| GPIO 控制 | gpiod (libgpiod) | Linux 标准 GPIO，兼容 Qualcomm SoC |
| 架构 | 三线程解耦 | 采集—推理—输出分离，避免 V4L2 缓冲区积压 |

---

## 🚀 快速开始

```bash
# 1. 安装系统依赖
sudo apt update
sudo apt install -y cmake libopenblas-dev libv4l-dev

# 2. 安装 Python 依赖
pip install --break-system-packages -r requirements.txt

# 3. 放置模型文件
# 将 MoveNet Lightning ONNX 模型放入 models/ 目录

# 4. 启动系统
cd ~/SmartPosture_Guardian
python3 src/main.py
```

---

## ⚠️ 已知约束（历史经验）

| 约束项 | 说明 |
|--------|------|
| **MediaPipe 不可用** | ARM64 + Python 3.13 下无预编译 wheel，需用 ONNX Runtime 替代 |
| **V4L2 缓冲区积压** | 驱动 FIFO 缓冲区会在推理期间积压旧帧，必须用采集-推理-输出三线程解耦 |
| **headless OpenCV** | UNO-Q 无桌面环境，必须用 `opencv-python-headless` 而非标准版 |
| **USB 带宽共享** | 摄像头与以太网可能共用 USB Root Hub，推荐使用 MJPG 压缩格式 |

---

*Built for UNO-Q (Qualcomm ARM SoC) · Debian 13 · Python 3.13*
