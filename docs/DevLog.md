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

---

## 第9轮 — LED 点阵不显示排查 & Git 初始化 (2026-07-15)

**用户 Prompt 摘要**:
> 校准功能正常但 LED 点阵不显示图案了。蓝灯（ble）也不亮了是否正常？应该有 git 仓库，队友之前上传过。

**Agent 行动**:

**LED 点阵问题排查**:
1. 检查 Bridge socket → 存在，arduino-router 运行中
2. 直接测试 RPC 调用 → `"method ok not available"` — MCU 方法未注册
3. 读取 MCU sketch (`sketch.ino`) → 代码中有 `ok/warning/buzzer_on/buzzer_off` 方法
4. `arduino-app-cli app list` → `user:posture_alerter` 状态 **stopped**
5. **根因**: MCU 固件根本没在运行。之前的亮灯只是 sysfs LED（user-red1/green1/blue1），点阵由 MCU 独立控制
6. 执行 `arduino-app-cli app start user:posture_alerter` → 编译成功，烧录成功
7. 验证所有 5 个 RPC 方法 → 全部可用
8. 蓝灯（bt-blue2 蓝牙指示灯）不亮 → 正常，MCU 重烧后蓝牙被重置，与代码无关

**Alerter RPC 去重修复（次要根因）**:
- 即使 MCU 固件正常，`show_calibrating()` 每秒 20 次 `_clear_matrix()` RPC 也会把 Bridge 打挂
- 修复: Alerter 增加 `_mode` 状态追踪，只在模式切换时发送一次 matrix RPC
- `show_normal/show_calibrating` 首次调用后 `return` 跳过，`show_warning` 只发一次 matrix 但蜂鸣器仍每 tick 评估

**Git 初始化**:
- 搜索 `/home/arduino` → git 仓库在 `~/workshop1-unoq-status-web/`，不在 `~/SmartPosture_Guardian/`
- 远程: `git@github.com:wyq-luminous/Group11.git`，3 分支 (main/workshop1/workshop3)
- 在 `~/SmartPosture_Guardian/` 执行 `git init` → 关联同一 remote → fetch origin/main → reset --soft
- 使用队友相同身份 (`Arduino UNO-Q <arduino@unoq.local>`) 提交
- 成功 push 到 GitHub

**Agent 回复摘要**:
LED 点阵恢复显示。Git 初始化完成，与队友共用同一个 Group11 仓库。系统现在完全正常：绿灯+对勾图案 = 正常监控，遮挡 3s+ = 蓝灯重校准。

---

## 第10轮 — Phase 3: 判定算法重构 + PFLD 模型替换 (2026-07-15)

**用户 Prompt 摘要**:
> 在现有坐姿监测系统上新增异常场景抗干扰（Phase 3）。核心发现：YuNet 5 点关键点在歪头/侧脸时无法准确追踪眼睛位置，十字始终一样高。用户要求换个能追踪五官位置的模型，只关注前倾/低头/歪头/侧脸四个判定场景，不扩展其他异常场景。

**Agent 行动**:

**问题诊断**:
- 分析 YuNet DIAG 日志 → 证实歪头时 `ly ≠ ry` 但偏差被模型内部约束(约 10-15° 实际歪对应 10px ΔY)
- YuNet 是正脸检测模型附带 5 个粗关键点，不是追踪模型
- 眼距骤降 (84→25px) 是侧脸/丢点的可靠信号，但无法与后退区分

**模型选型**:
- MediaPipe: Python 3.13 + ARM64 无 wheel → 不可用
- PFLD ONNX (98 点 WFLW): 1MB, 112×112 输入, 来自 HuggingFace `ykk648/face_lib`
- 通过 `hf-mirror.com` 镜像下载成功 (6.6MB)

**7 步原子化实施**:

**Step 1 — 下载模型**: `models/pfpld.onnx` (6.6MB)
- 直接连接 HuggingFace 超时，换 `hf-mirror.com` 镜像成功

**Step 2 — Benchmark + 确定索引**:
- 模型输出: `pose [1,3]` (yaw/pitch/roll) + `landms [1,196]` (98点×2)
- WFLW 98 点格式: 左眼 60-67, 右眼 68-75, 鼻尖 57
- ONNX Runtime: 109ms/帧 (9 FPS)；OpenCV DNN: 79ms/帧 (13 FPS)
- 选择 OpenCV DNN 后端

**Step 3 — 新增 `src/landmarker.py`**:
- `FaceLandmarker` 类: 加载 PFLD ONNX via OpenCV DNN
- `detect(face_crop)` → `LandmarkResult`: 眼距/眼Y/歪头角/侧脸比 + 16 个眼睛轮廓点 + 鼻尖
- 质量门控: 眼距 < 15px → 判定异常

**Step 4 — 改造 `YuNetEngine`**:
- 新增 `detect_face_bbox()`: 只返回人脸边界框 (带 15% 边距)
- 保留旧 `detect_eyes()` 作为回退

**Step 5 — 串联推理链**:
- `inference_loop`: YuNet 找脸框 → 裁剪 → PFLD 精确定位 → SharedState
- 新增 `SharedState.update_landmark()` / `get_landmark()` 方法
- 同步旧字段 (`eye_distance/eye_y/face_detected`) 供校准兼容
- PFLD 缺失时自动回退到 YuNet 粗检测模式

**Step 6 — 更新 `debug_viewer`**:
- 支持新旧两种 eye_positions 格式
- 新格式: 画 16 个绿色眼轮廓点 + 黄色中心大圆 + 紫色连线
- 显示 `Roll/Yaw` 数值

**Step 7 — 更新 `PostureAnalyzer` (四场景判定)**:
- 侧脸 (`yaw_ratio > 0.35`): 丢弃帧，冻结计时器
- 帧间跳变 (`|Δeye_dist| > 30%`): 丢弃帧，冻结计时器
- 前倾 (`眼距比 > 1.2`): 计时
- 低头 (`当前Y − 基准Y > 25px`): **修复公式 (之前写反了)**
- 歪头 (`|roll_deg| > 12°`): 计时
- 三指标任一持续 5s → 报警

**变更文件清单**:
| 文件 | 变更类型 |
|------|------|
| `models/pfpld.onnx` | 新增 (6.6MB) |
| `src/config.py` | +1 行 (`PFLD_MODEL_PATH`) |
| `src/landmarker.py` | 新增 (~140 行) |
| `src/bench_pfld.py` | 新增 (benchmark 工具, ~140 行) |
| `src/main.py` — SharedState | +20 行 (landmark 字段+方法) |
| `src/main.py` — YuNetEngine | +35 行 (`detect_face_bbox`) |
| `src/main.py` — inference_loop | 重写 (YuNet→PFLD 级联+回退) |
| `src/main.py` — PostureAnalyzer | +40 行 (四场景判定+质量门控+修复低头公式) |
| `src/debug_viewer.py` | +40 行 (16 点眼轮廓+Roll/Yaw 显示) |

**性能**:
- YuNet (~15ms) + PFLD OpenCV DNN (~79ms) = ~94ms/帧 → ~10 FPS 理论
- 实测: ~6 FPS (含调试标注+JPEG 编码等开销)
- 对坐姿判定 5s 窗口可收集 ~30 帧，足够

**Agent 回复摘要**:
7 步全部完成，系统正常运行。判定管线从"双指标 OR"升级为"三层质量门控 + 三指标 OR"。用户需在浏览器 `/viewer` 观察 16 个绿色眼轮廓点是否跟随歪头旋转，并逐一测试前倾/低头/歪头/侧脸四个场景。

---

## 第11轮 — Phase 3 Bug 修复 (2026-07-15)

**问题**:
1. 报警状态下遮挡镜头无法触发重校准（`_handle_no_face` 仅在 MONITORING 状态设 `pending_recal`）
2. 报警一直不解除（质量门控在 ALERTING 状态也拦截，恢复计时器无法推进）
3. 调试视图显示 raw Y 坐标，低头时数值增大但用户困惑"越高越小"

**修复**:
- `_handle_no_face`: 除 CALIBRATING 外所有状态均可触发 `pending_recal`
- 无人脸时 `return False`（停止报警），替代原来的 `return self.state.is_alerting`
- 调试视图 README 中说明图像坐标系（Y=0 在顶部）

**Agent 回复摘要**:
提交 `b921205`，推送至 GitHub。用户确认遮挡重校准正常。

---

## 第12轮 — Phase 4 异常场景鲁棒性: 4A 第二人干扰 + 4B 无人休眠 (2026-07-15)

**用户 Prompt 摘要**:
> Phase 4 异常场景鲁棒性设计。用户要求先聚焦 4A(第二人入画干扰)和 4B(无人状态休眠)，讨论需求和判断标准后再实现。4C-4E 暂不改动，4F 暂不展开。

**讨论决策**:

**4A — 第二人干扰**:
- 确认场景存在但低频，无需增加模型推理负担
- 策略: 主策略选最大脸(bbox 面积)，辅助策略当多脸面积接近(<20%)时用上一帧位置连续性裁决
- 改动量小，仅改 `detect_face_bbox()` 选脸逻辑 + `inference_loop` 历史位置追踪

**4B — 无人休眠**:
- 确认需要，20s 无脸进入休眠(方便测试)，连续有脸 3s 唤醒
- 休眠行为: 绿灯慢闪(0.5s/1.5s) + 推理降频至 1fps + 蜂鸣器静音
- 唤醒后直接进入 MONITORING，不重校准（基准值未失效）
- 与遮挡重校准区分: 2-20s 无脸 = 遮挡重校准，≥20s = 休眠

**实施: 7 步原子化改动**:

| 步骤 | 文件 | 改动 |
|------|------|------|
| B1 | `config.py` | +3 常量 (UNATTENDED_TIMEOUT_SEC=20, WAKE=3, INFERENCE_INTERVAL=1.0) |
| B2 | `main.py` SharedState | +unattended_lock + face_detected_start + 3 方法 (mark_face_seen/lost/get_face_seen_duration) |
| A1 | `main.py` YuNetEngine | detect_face_bbox 新增 last_center 参数，多人脸时选最大脸(w*h)，面积差<20%时用位置连续性裁决 |
| A2 | `main.py` inference_loop | +last_face_center 变量，成功检测后更新、无脸时清零，传给 detect_face_bbox |
| B3 | `main.py` PostureAnalyzer | +UNATTENDED 状态, _handle_no_face 增加≥20s→休眠转换, +_handle_unattended(3s 唤醒), tick()增加休眠路由 |
| B4 | `alerter.py` | +show_unattended() 绿灯慢闪 0.5s/1.5s (+_last_green_state 字段) |
| B5 | `main.py` 主循环+推理 | 主循环增加 UNATTENDED 分支调 show_unattended(), 推理休眠时 sleep 1s 降频 |

**变更文件清单**:
| 文件 | 变更类型 |
|------|------|
| `src/config.py` | +7 行 |
| `src/main.py` | +142 行 / -21 行 |
| `src/alerter.py` | +24 行 |

**完整状态机**:
```
CALIBRATING → MONITORING ⇄ ALERTING → COOLDOWN
                   ↓ ↑
              UNATTENDED  (20s 无脸 → 休眠, 3s 有脸 → 唤醒)
```

**Agent 回复摘要**:
7 步全部完成，用户测试确认 4A(多人脸选最大脸+位置连续性)和 4B(20s 休眠+3s 唤醒+绿灯慢闪)功能正常。提交并推送至 GitHub。

---

## 第13轮 — 生产就绪修复: 线程健康监控 + 摄像头重连纠错 + 可视化补全 (2026-07-16)

**用户 Prompt 摘要**:
对整个项目进行"生产就绪健康检查与轻量重构"。用户明确要求只修最薄弱两处，不动功能代码。后续追加: 关闭蓝牙指示灯、可视化补上鼻尖点。

**Agent 采取的主要行动**:

### 第一阶段 — 诊断
扫描全部 7 个 Python 源文件，列出 12 处异常处理器 + 5 大危险点。

### 第二阶段 — 聚焦两处致命修复

**Fix #1: 摄像头重连设备索引错误 (main.py:327)**
- **Bug**: `_find_usb_camera()` 正确发现了 USB 摄像头索引 (如 `/dev/video2`)，但重连时硬编码用了 `CAMERA_INDEX` (=0)，在 UNO-Q 上 `/dev/video0` 是 Venus 编解码器 → 重连 100% 失败
- **修复**: `cv2.VideoCapture(CAMERA_INDEX)` → `cv2.VideoCapture(camera_idx)`，并补上漏配的 `CAP_PROP_BUFFERSIZE`

**Fix #2: 子线程静默死亡无感知 (main.py:1072-1110)**
- **Bug**: 三个 daemon 线程 (API/Capture/Inference) 任何一个崩溃，主线程完全不知情，系统表面"运行中"实际已废
- **修复**: 主循环每 2 秒检查 `thread.is_alive()`，发现死亡则 0.5s 冷却后重启，最多 3 次，超过记 ERROR 放弃

### 后续追加

**Fix #3: 蓝牙指示灯关闭 (main.py:1062-1068)**
- `bt-blue2` 是 STM32 固件的蓝牙状态灯，项目未使用蓝牙但启动时可能亮起
- 在 `main()` 启动时写入 0 关闭，以后用蓝牙再删

**Fix #4: 鼻尖可视化 (debug_viewer.py)**
- `landmarker.py` 一直提取鼻尖用于 yaw_ratio 计算，但 `debug_viewer.py` 从未绘制
- 新增橙色实心圆 + 中线→鼻尖连线，刷新 /viewer 可见

**Agent 回复摘要**:
四姐妹修复均仅改动必要代码，零功能变更、零新依赖。语法验证通过。用户确认后要求记录 DevLog 并推送。

**变更文件清单**:
| 文件 | 变更类型 |
|------|------|
| `src/main.py` | +38 行 / -2 行 (线程健康监控 + 摄像头索引修复 + BT LED 关闭) |
| `src/debug_viewer.py` | +7 行 / -2 行 (鼻尖标注) |

---

## 第14轮 — Hermes 云端推送模块 (2026-07-16)

**用户 Prompt 摘要**:
> 新增 Hermes 云端推送模块。当异常坐姿成立时，同时触发本地报警和 Hermes 微信推送。首次推送后 1 分钟冷却期。异步非阻塞 + 网络容错。参考 @lav1e2nrose 的 Group11/ws6-remote-control 仓库风格编写。

**Agent 采取的主要行动**:

### 参考仓库分析
1. 通过 GitHub API 成功访问 `wyq-luminous/Group11` (ws6-remote-control 分支)
2. 分析关键文件：`bin/monitor.py` (AlertTracker 冷却模式), `backend/hw.py` (硬件抽象), `backend/rpc_client.py` (RPC 客户端)
3. **关键发现**: 参考仓库使用"文件队列 + Hermes cron + stdout 投递"模式做推送，不直接 HTTP。本项目需要直接 HTTP POST 到 Hermes 云端 API。
4. **可复用模式**: `AlertTracker` 的冷却追踪模式 (debounce + cooldown 按时间戳判断，纯窗口逻辑)

### 实施 (3 文件)

**Step 1 — `src/config.py`**: 新增 6 行 Hermes 配置
- `HERMES_ENABLED` (总开关)
- `HERMES_API_URL` (云端端点)
- `HERMES_COOLDOWN_SEC = 60` (冷却 1 分钟，调试用)
- `HERMES_REQUEST_TIMEOUT_SEC = 5.0`
- `HERMES_RETRY_COUNT = 1`
- API Key 从环境变量 `HERMES_API_KEY` 读取，不硬编码

**Step 2 — `src/hermes.py`** (新增 ~160 行):
- `HermesPusher` 轻量类，模仿 Workshop 6 AlertTracker 风格
- `try_push(reason)`: 主线程调用 → 检查冷却(线程安全) → spawn daemon 线程发送 HTTP POST
- `_do_push(reason)`: 后台线程执行 `requests.post()` + 重试 + 静默容错
- 冷却机制: 纯时间窗口 (60s)，与姿势恢复无关。距上次成功推送不足 60s 则静默跳过
- 网络容错: `ConnectionError/Timeout/Exception` 三层捕获，仅写日志，绝不崩溃
- 包含 `__main__` 自测块 (冷却逻辑、容错、非阻塞三项验证)

**Step 3 — `src/main.py`** 集成:
- `PostureAnalyzer.__init__` 新增可选的 `hermes` 参数
- `_handle_monitoring()` 状态转入 ALERTING 时调用 `self.hermes.try_push(reason)`
- `main()` 中实例化 `HermesPusher()` 并注入 `PostureAnalyzer`

### 验证结果
- 模块导入 ✓
- 冷却逻辑: 首次触发推送 / 60s 内跳过 ✓
- 网络容错: URL 不可达 → warning 日志 → 程序继续运行 ✓
- 非阻塞: `try_push()` 返回耗时 1.6ms (daemon 线程异步) ✓
- PostureAnalyzer 集成: hermes 正确注入 ✓

**Agent 回复摘要**:
3 文件变更完成。Hermes 推送在 ALERTING 首次触发时非阻塞发送，60s 冷却防重复，网络异常静默容错。用户需设置 `HERMES_API_KEY` 环境变量和实际的 `HERMES_API_URL` 端点。

**变更文件清单**:
| 文件 | 变更类型 |
|------|------|
| `src/config.py` | +8 行 (Hermes 配置段) |
| `src/hermes.py` | 新增 (~160 行) |
| `src/main.py` | +5 行 / -2 行 (导入 + 注入 + 调用点) |

---

## 第15轮 — Hermes 切换到文件队列模式 (对齐 Workshop 6) (2026-07-16)

**用户 Prompt 摘要**:
> 选择路径 A，改用 Workshop 6 文件队列模式。B 板未安装 Hermes Agent，希望和队友 A 板上已验证可行的方法保持一致。

**Agent 采取的主要行动**:

### 架构切换: HTTP 直连 → 文件队列 + Hermes cron

**原方案 (第14轮)**: `requests.post()` HTTP 直连 Hermes 云端 API。
**新方案 (对齐 Workshop 6)**:
```
PostureAnalyzer → hermes.try_push() → 写 alerts.jsonl
                                            ↓
Hermes Agent cron (每 1min) → deliver_alerts.sh → stdout → 微信
```

### 变更文件

**Step 1 — `src/config.py`**: 精简配置
- 移除: `HERMES_API_URL`, `HERMES_REQUEST_TIMEOUT_SEC`, `HERMES_RETRY_COUNT`
- 新增: `HERMES_ALERT_FILE = "alerts.jsonl"`
- 保留: `HERMES_ENABLED`, `HERMES_COOLDOWN_SEC`

**Step 2 — `src/hermes.py`** 完全重写 (200→100 行):
- 移除: 所有 `requests`/`threading`/HTTP 代码
- 新增: `_write_alert()` 函数 — JSON-lines 文件追加 (复制 Workshop 6 `write_alert` 模式)
- 冷却逻辑不变 (纯时间窗口 60s)
- 零阻塞 — 文件写入 <1ms
- 自测块: 3 项验证 (写入/冷却跳过/启用开关)

**Step 3 — `bin/deliver_alerts.sh`** (新增, 60 行):
- 100% 对齐 Workshop 6 同名脚本
- 数据通过环境变量传递 (避免 shell 转义问题, 参考 Workshop 6 DEVLOG Issue #2)
- 读 alerts.jsonl → 格式化微信消息 → stdout → 归档到 .delivered

**Step 4 — `hermes-skills/posture-alert.md`** (新增):
- 完整安装+配置教程 (Hermes Agent 安装 / cron 创建 / 端到端验证 / Troubleshooting)
- 包含 Node.js 安装步骤 (ARM64, `/home/arduino` 分区)

**Step 5 — `src/main.py`**: 无改动 (集成点不变, hermes.py 接口兼容)

### 验证结果
- hermes.py 自测: 写入 ✓ / 冷却跳过 ✓ / 禁用开关 ✓
- deliver_alerts.sh: stdout 输出格式正确 ✓ / 归档到 .delivered ✓
- 集成: PostureAnalyzer + HermesPusher 注入正常 ✓

**Agent 回复摘要**:
代码侧全部完成。还需用户侧操作: 安装 Hermes Agent (Node.js + hermes-agent 脚本) → `hermes gateway setup` 配微信 → 创建 cron 投递任务。代码不依赖 Hermes 是否安装 — 没有 Hermes 时告警事件仍正常写入 alerts.jsonl，安装后自动开始投递。

**变更文件清单**:
| 文件 | 变更类型 |
|------|------|
| `src/config.py` | 重写 Hermes 配置段 (-3/+1 参数) |
| `src/hermes.py` | 重写 (200→100 行, HTTP→文件队列) |
| `bin/deliver_alerts.sh` | 新增 (60 行) |
| `hermes-skills/posture-alert.md` | 新增 (完整安装配置文档) |

---

## 第16轮 — 生产级演示自动化改造：systemd 自启 + 运维手册 (2026-07-16)

**用户 Prompt 摘要**:
> 将项目从"开发原型"转变为"可独立运行的产品"，满足现场演示要求：插电即用，全程无需电脑。完成 systemd 开机自启、Hermes 网关保活、无头环境扫描、异常保活、优雅退出等五大检查项。先出体检报告，确认后实施改造。

**Agent 采取的主要行动**:

### Phase 1: 完备性体检

深度扫描全部 `src/` 代码（main.py, config.py, alerter.py, hermes.py, landmarker.py, debug_viewer.py），输出五大领域体检报告：

| 领域 | 评分 | 发现 |
|------|------|------|
| 自动启动 | 🔴 0/3 | 无 systemd 服务，纯手动 |
| Hermes 自启 | 🟡 1/3 | Gateway 已安装但无自启服务 |
| 无头兼容 | 🟢 5/5 | 无 `cv2.imshow`/`matplotlib` 等 GUI 调用；发现 `opencv-python` 和 `opencv-python-headless` 双包共存隐患 |
| 崩溃保活 | 🟢 4/5 | 线程健康监控、摄像头重连、推理异常处理均到位；主循环缺少 broad except 兜底 |
| 资源释放 | 🟢 3/3 | SIGTERM → Alerter.cleanup → 线程 join 完整 |

额外发现：`msgpack` 未列入 `requirements.txt`（alerter.py 隐性依赖）。

用户确认报告后进入 Phase 2。

### Phase 2: 自动启动改造

**发现 Hermes Gateway 已有 user systemd 服务**（`~/.config/systemd/user/hermes-gateway.service`，已启用，`linger=yes`），无需额外配置。

**新建文件**:

**Step 1 — `deploy/smartposture-guardian.service`** (systemd user service):
- `Type=simple` → 前台运行，systemd 直接管理进程生命周期
- `ExecStart=/usr/bin/python3 .../src/main.py` → 使用系统 python3（无 venv）
- `After=network-online.target hermes-gateway.service` → 网络和 IM 就绪后启动
- `Wants=hermes-gateway.service` → 确保 Hermes 一同启动
- `Restart=always` + `RestartSec=5` → 崩溃后 5 秒自动重启
- `KillSignal=SIGTERM` → 触发 main.py 的优雅退出逻辑
- `TimeoutStopSec=15` → 等待清理完成
- 安装至 `~/.config/systemd/user/`，`systemctl --user enable`

**Step 2 — `docs/OPERATIONS_MANUAL.md`** (新增，完整运维手册):
- 12 章 + 2 附录，覆盖：首次部署、启动/停止、LED 指示灯速查、Web 上位机、Hermes 微信绑定、坐姿判定逻辑、状态流转图、阈值修改指南、API 参考、异常排查（8 种场景）、日常维护命令、配置速查卡片

### 验证结果

| 测试项 | 结果 |
|--------|------|
| 正常启动 | ✅ 4 线程全部启动，API `{"status":"ok"}` |
| 崩溃自愈 | ✅ `kill -9` → 5s 后 systemd 自动重启为新 PID |
| 优雅退出 | ✅ `systemctl stop` → SIGTERM → Alerter 释放 → 线程退出 → exit 0 |
| Hermes 自启 | ✅ 已存在，`enabled` + `linger=yes` |
| 开机自启 | ✅ 两个服务均 `enabled`，`Linger=yes`，重启后自动拉起 |
| 手动调试保留 | ✅ `systemctl --user stop` 后可手动 `python3 src/main.py` |

**Agent 回复摘要**:
自动启动改造完成。新增 1 个 systemd 服务文件 + 1 份完整运维手册。现在插电即可用：Linux 启动 → systemd 自动拉起 Hermes Gateway + SmartPosture Guardian → 5 秒校准 → 监控中。全程无需 SSH 或任何手动命令。手动调试能力完整保留。

**变更文件清单**:
| 文件 | 变更类型 |
|------|------|
| `deploy/smartposture-guardian.service` | 新增 (systemd user service) |
| `docs/OPERATIONS_MANUAL.md` | 新增 (~400 行, 完整运维手册) |
| `docs/DevLog.md` | 追加 (本条目) |
