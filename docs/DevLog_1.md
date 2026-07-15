# DevLog — 慧姿·智能坐姿守护系统 开发记录

**项目**: SmartPosture Guardian  
**平台**: Arduino UNO-Q (Qualcomm QRB2210 + STM32U585)  
**日期**: 2026-07-14 ~ 2026-07-15  

---

## 第1轮 — 项目初始化与历史经验回顾

**目标**: 搭建项目骨架，确定技术栈。

**关键决策**:
- **不引入频域处理**: 所有图像操作严格使用空间域算法（NumPy 向量化 + 1D 扁平化），节省 ARM 算力
- **ONNX Runtime 替代 MediaPipe**: 回溯 DevLog（肘关节测量项目），ARM64 + Python 3.13 下 MediaPipe 无预编译 wheel，最高仅支持 Python 3.12
- **三线程解耦架构**: 回顾 V4L2 4 帧 FIFO 缓冲区积压问题（推理 187ms 期间缓冲 5-6 帧，cap.read() 返回最旧帧，延迟 ~300ms），确定采集-推理-输出分离
- **opencv-python-headless**: UNO-Q 无桌面环境，标准版 opencv-python 依赖 libgtk/libqt 会安装失败

**产物**: `requirements.txt`, `README.md`, `src/config.py`

---

## 第2轮 — AI 模型选型与下载

**问题**: MoveNet Lightning ONNX (69MB) 从 Wasabisys S3 下载极慢（~16KB/s），HuggingFace/ModelScope 均连接超时。

**尝试过程**:

| 方案 | 结果 |
|------|------|
| Wasabisys S3 全量下载 (69MB) | ❌ 两次中断于 11MB |
| HuggingFace Xenova/movenet-singlepose-lightning | ❌ 连接超时 |
| ModelScope 国内镜像 | ❌ 返回空文件 |
| KaggleHub API | ❌ 404 |
| TensorFlow Hub → tf2onnx 转换 | ❌ tensorflow 无 aarch64 wheel |
| 本地 face_landmark.tflite → ONNX | ❌ TFLite FlatBuffers 无法直接转 ONNX |

**解决**: 改用 **OpenCV FaceDetectorYN (YuNet)** — ONNX 模型仅 228KB，2 秒从 GitHub OpenCV Zoo 下载成功。YuNet 直接输出 5 点人脸关键点（含左右眼坐标），比 MoveNet 更轻量且无需全身姿态估计。

**关键教训**: 对于 UNO-Q 受限网络环境，优先选择 GitHub Releases 等 CDN 加速源下载的微小模型。

---

## 第3轮 — LED 点阵驱动调试

**硬件**: UNO-Q 板载 8×13 蓝色 LED 点阵（104 像素），STM32U585 通过 Charlieplexing (PF0-PF10, 11 根 GPIO) 驱动，Linux 端无法直接访问。

**通信架构**:
```
Linux MPU → msgpack RPC → /var/run/arduino-router.sock → STM32 MCU → Charlieplexing → LED Matrix
```

**问题 1 — ArduinoGraphics 不可用**: 
- `#include <ArduinoGraphics.h>` 编译失败
- `arduino-cli lib install ArduinoGraphics` 安装成功但 Zephyr 平台无法识别
- `beginDraw()/set()/endDraw()` API 全部不可用

**解决**: 改用底层 `matrix.draw(frame)` API，直接操作 104 字节帧缓冲，`frame[row * 13 + col] = 0~255`。

**问题 2 — 坐标映射验证**:
- 单像素测试发现逻辑坐标与物理位置不一致
- 列扫描 + 行扫描确认：`draw()` 使用标准行优先映射（row 0=顶部, col 0=左边）

**问题 3 — 三角感叹号图案迭代**:
- V1: 感叹号圆点跑出三角形底部，用户反馈"戳出去了"
- V2: 三角形封底占据 row 7，感叹号完全包含在三角形内，用户确认"可以的"

**产物**: `~/ArduinoApps/posture_alerter/sketch/sketch.ino`

---

## 第4轮 — 蜂鸣器接入

**需求**: 外接蜂鸣器，D2 引脚，低电平触发，报警时间歇鸣叫。

**问题 — GPIO 引脚映射**:
- gpiod v2 API 直接操作 `/dev/gpiochip1` line 3 不响
- 扫描 gpiochip1（127 lines）和 gpiochip2（19 lines）均无反应

**根因**: UNO-Q 的 Arduino 排针 D2 由 STM32 MCU 管理，不直接暴露为 Linux GPIO。

**解决**: 在 MCU sketch 中添加 `buzzer_on()/buzzer_off()` RPC 方法，使用 `digitalWrite(2, LOW/HIGH)` 控制。Python 端通过 Bridge socket 调用。

**蜂鸣器逻辑**:
```
show_warning() → 每 0.15s 切换 on/off → 间歇滴滴声
show_normal()  → buzzer_off → 静音
```

---

## 第5轮 — 调试上位机

**需求**: 浏览器查看实时摄像头画面 + 双眼标注 + 眼距数值。

**问题 1 — 网页无法访问**:
- 初始监听 `127.0.0.1`（仅本机回环）
- LAN 内其他设备无法连接

**解决**: 参考 workshop1 的 Express.js 实现 (`server.js`)，改为 `0.0.0.0` 监听所有网络接口。

**问题 2 — uvicorn 缺失**: 
`ModuleNotFoundError: No module named 'uvicorn'` → `pip3 install uvicorn fastapi`

**问题 3 — `graceful_shutdown` 引用丢失**:
编辑时意外删除了信号处理函数定义 → 补回 `def graceful_shutdown`

**问题 4 — `state` 变量越界**:
`YuNetEngine.detect_eyes()` 内部引用 `state.eye_positions` 但 state 不在作用域内 → 改为 `self.last_eye_positions`，由推理线程读取后写入 state

**最终方案**: 
- FastAPI `/viewer` 内嵌 HTML 页面（仿 workshop1 风格）
- FastAPI `/stream` MJPEG 流（`multipart/x-mixed-replace`）
- 标注内容: 眼睛十字准星 + 连线 + 眼距数值 + 人脸框 + 状态标签

---

## 第6轮 — Git 分支管理

**需求**: 将 workshop1、workshop3、SmartPosture Guardian 分别推送到独立分支。

**操作**:
```
workshop1 ← workshop1-unoq-status-web (Node.js 系统仪表盘)
workshop3 ← pose_detection (MediaPipe + Tkinter 肘关节测量)
main      ← SmartPosture_Guardian (坐姿检测系统)
```

**注意**: main 分支使用 `--force` 推送覆盖旧内容（原 main 已保存到 workshop1 分支）。

---

## 附录: 技术栈总结

| 组件 | 选型 | 替代方案 |
|------|------|----------|
| AI 推理 | OpenCV FaceDetectorYN (YuNet ONNX) | MediaPipe → ONNX Runtime MoveNet |
| 图像采集 | OpenCV V4L2 + MJPG 压缩 | YUYV 未压缩（USB 带宽不足） |
| LED 矩阵 | STM32 Charlieplexing → Bridge RPC | Linux GPIO（不可用） |
| 蜂鸣器 | STM32 digitalWrite → Bridge RPC | gpiod（不可用） |
| Web 上位机 | FastAPI + MJPEG (0.0.0.0:8000) | Tkinter（无桌面环境） |
| 前后端通信 | FastAPI REST `/api/v1/calibration` | — |
| 版本管理 | Git 多分支 (main/workshop1/workshop3) | — |
