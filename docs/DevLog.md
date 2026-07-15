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

---

## 第7轮 — 二期需求分析与架构审查 (2026-07-15)

**用户 Prompt 摘要**:
> 项目新接手者，需要在现有坐姿监测基础上进行二期开发：
> 1. 增加"无感校准"功能（遮挡镜头 2 秒触发）
> 2. 完善异常场景（无人状态、转头/侧头抗干扰）
> 3. 优化阈值定义（放大系数、滤波秒数等改为全局可调宏）
> 4. 增加 Hermes 云端异步推送（微信告警 + 10分钟冷却机制）
> 要求先做只读分析，输出架构报告，不修改代码。

**Agent 行动**:
- 读取全部核心源文件：`README.md`, `requirements.txt`, `src/config.py`, `src/main.py`, `src/alerter.py`, `src/debug_viewer.py`, `src/convert_tflite_to_onnx.py`
- 检查 `tests/`（空目录）和 `logs/`（仅运行日志）
- 确认项目非 git 仓库，无 CLAUDE.md
- 建立 DevLog 自动记录规则：创建 `CLAUDE.md`，写入强制 DevLog 规则 + 平台硬约束
- 分析 FSM 状态机、校准逻辑、报警链路、阈值分布

**Agent 发现的关键问题**:
1. `WAITING_COOLDOWN` 状态已定义但 `_handle_cooldown()` 方法未实现 — 状态机断链
2. YuNetEngine 内部硬编码 `INPUT_W=320`, `SCORE_THRESHOLD=0.6` 等，未走 config.py
3. 校准仅在启动时执行一次，无运行时"遮挡镜头重新校准"逻辑
4. 无人状态（face_detected=False）直接跳过判定，不区分"无人"与"检测失败"
5. 无转头/侧头抗干扰（单侧眼睛被遮挡时 YuNet 可能返回低置信度或错误关键点）
6. 无 Hermes 云端推送模块
7. 无报警冷却机制（连续报警无间隔限制）
8. `tests/` 目录为空，无任何单元测试

**Agent 回复摘要**:
输出完整架构分析报告（见下方回复正文），含模块清单、现状评估矩阵、硬约束确认、四项新功能的实施计划草案。

---

## 第8轮 — 无感校准功能实现 (2026-07-15)

**用户 Prompt 摘要**:
> 要求按原子化步骤实现无感校准功能（遮挡镜头 2s 触发重校准），每一步可独立测试。

**Agent 行动**:
按 5 个原子步骤实现：

**Step 1 — config.py 新增常量**:
- `CALIBRATION_COVER_SEC = 2.0` — 遮挡触发阈值
- `CALIBRATION_RECAL_FEEDBACK_SEC = 1.0` — 校准完成反馈闪烁秒数
- 同步更新 `main.py` import 列表

**Step 2 — SharedState 新增遮挡追踪**:
- 新增字段: `cover_lock`, `no_face_start: float|None`, `pending_recal: bool`
- 新增方法: `mark_no_face(ts)`, `mark_face_restored() -> float|None`, `get_no_face_duration(now) -> float`
- 特点: `mark_no_face` 幂等（只在首次 None 时记录），`mark_face_restored` 返回遮挡时长并清零

**Step 3 — PostureAnalyzer FSM 核心改动**:
- 修改 `tick()`: 无脸帧不再直接 return，而是调用 `_handle_no_face(now)`
- 有脸帧到达时先检查 `pending_recal` → 若为 True 调用 `_start_recalibration()`
- 新增 `_handle_no_face(now)`: 仅在 MONITORING 状态下累计无脸时长，≥2s 时置 `pending_recal = True`
- 新增 `_start_recalibration(now)`: 清空旧样本、重置 `calibration_start`、切入 CALIBRATING
- 修复潜在 bug: `WAITING_COOLDOWN` 分支原来是调用不存在的 `_handle_cooldown`，改为安全回退到 MONITORING

**Step 4 — Alerter 校准反馈**:
- `alerter.py`: 新增 `show_calibrating()` — 蓝灯 + 清空点阵 + 静音
- `main.py` 主循环: 按 `analyzer.posture` 优先判断，CALIBRATING 时调用 `show_calibrating()`

**Step 5 — API 暴露 + 集成验证**:
- SharedState: 新增 `posture_state: str` 字段
- PostureAnalyzer: 所有 `self.posture = ...` 位置同步更新 `state.posture_state`
- StatusResponse: 新增 `posture_state: str`
- API `/api/v1/status` 返回中包含 `posture_state` 字段

**变更文件清单**:
| 文件 | 变更类型 |
|------|------|
| `src/config.py` | +2 行常量 |
| `src/main.py` — SharedState | +30 行（字段 + 3 方法） |
| `src/main.py` — PostureAnalyzer | +30 行（tick 改动 + 2 新方法 + posture_state 同步） |
| `src/main.py` — 主循环 | +3 行（校准状态分支） |
| `src/main.py` — API | +2 行（StatusResponse + get_status） |
| `src/alerter.py` | +6 行（show_calibrating） |

**Agent 回复摘要**:
5 步全部独立验证通过。核心链路: `MONITORING → (无脸≥2s) → pending_recal=True → (人脸恢复) → CALIBRATING → (校准完成) → MONITORING`。未破坏原有启动校准和 API 注入校准功能。
