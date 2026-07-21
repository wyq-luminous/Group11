# SmartPosture Guardian 测试文档

> 测试策略以**边界条件**为核心特性：每一个数值阈值（时间、比率、像素、置信度）
> 都在"恰好等于 / 刚好小于 / 刚好大于"三个点上验证，明确 `>` 与 `>=` 语义。

---

## 1. 测试分层

| 层级 | 文件 | 依赖 | 运行位置 |
|------|------|------|----------|
| **L1 纯逻辑单元测试** | `test_posture_judgment.py`<br>`test_state_machine.py`<br>`test_quality_gate.py`<br>`test_calibration_state.py`<br>`test_hermes.py`<br>`test_alerter.py`<br>`test_landmarker.py`<br>`test_face_selection.py`<br>`test_api.py` | 仅 Python 包，硬件/模型/时间全部 mock | 任意 PC / 板子 |
| **L2 模型冒烟测试** | `test_models_smoke.py` | 仓库内真实 ONNX 文件 + OpenCV | 任意 PC / 板子 |
| **L3 板上集成测试** | `test_on_device.py` (`@pytest.mark.device`) | UNO-Q 硬件：摄像头、Bridge socket、主服务 | 仅板子 |
| **L4 端到端手动验收** | 见 §5 手动测试清单 | 完整系统 + 真人 | 仅板子 |

**关键设计**：

- **FakeClock 虚拟时钟**（`conftest.py`）：接管全局 `time.time()`，
  20 秒休眠超时、5 秒报警滤波等用例**瞬时完成且边界精确到毫秒**，全套 L1 只需约 3 秒。
- **硬件 mock**：`Alerter` 的 Bridge RPC 与 sysfs 写入被 `HardwareRecorder` 拦截记录，
  可在无板子的环境验证"模式去重 / 蜂鸣节拍"这类硬件驱动逻辑。
- **推理 mock**：`FakeDetector` / `FakeNet` 直接构造 YuNet / PFLD 的原始输出张量，
  精确控制眼睛坐标，从而把"眼距 15px、面积差 20%"这种边界钉死。

---

## 2. 运行方法

### 2.1 PC 上（当前即可运行，无需设备）

```bash
# 一次性安装测试依赖
pip install opencv-python-headless numpy fastapi httpx pytest uvicorn

cd Group11
pytest              # L1 + L2，硬件用例自动跳过 (pytest.ini: -m "not device")
pytest -v           # 显示每个用例名
pytest tests/test_state_machine.py -v   # 只跑状态机
```

### 2.2 板上（设备连接后）

```bash
# 1. 同步代码到板子
scp -r Group11/ arduino@<板子IP>:~/SmartPosture_Guardian/

# 2. 板上安装 pytest
pip install --break-system-packages pytest requests

# 3. 先跑纯逻辑层（确认环境一致性）
cd ~/SmartPosture_Guardian && pytest

# 4. 硬件集成测试（覆盖默认过滤）
pytest tests/test_on_device.py -m device -v
#   - 摄像头用例: 需插入 USB 摄像头
#   - Bridge 用例: 需 arduino-app-cli app start user:posture_alerter
#   - LiveAPI 用例: 需主服务运行 (systemctl start smartposture-guardian)
#   - 蜂鸣器/LED 用例含人工目视/听觉确认环节
```

---

## 3. 边界条件矩阵（本次测试的核心 feature）

| # | 阈值 | 配置值 | 语义 | 边界用例 (恰好等于 → 期望) |
|---|------|--------|------|---------------------------|
| 1 | 前倾眼距比 | 1.2 | 严格 `>` | ratio==1.2 → **不报警** |
| 2 | 低头高度降 | 25px | 严格 `>` | drop==25.0 → **不报警** |
| 3 | 歪头角 | 12° (代码值) | 严格 `>` (abs) | ±12.0° → **不报警** |
| 4 | 侧脸门控 | yaw 0.35 | 严格 `>` | 0.35 → **正常处理**, 0.351 → 丢帧 |
| 5 | 帧间跳变门控 | 30% | 严格 `>` (abs) | 30% → 处理, 31% → 丢帧 |
| 6 | 报警持续滤波 | 5.0s | `>=` | 4.999s 不报 / 5.0s 报警 |
| 7 | 恢复解除滤波 | 3.0s | `>=` | 2.999s 维持 / 3.0s 解除 |
| 8 | 遮挡重校准 | 2.0s | `>=` | 1.999s 不标记 / 2.0s 标记 |
| 9 | 无人休眠 | 20.0s | `>=` | 19.999s 监控 / 20.0s 休眠（并清除重校准标记） |
| 10 | 休眠唤醒 | 3.0s | `>=` | 2.999s 休眠 / 3.0s 唤醒（不重校准） |
| 11 | 校准时长 | 5.0s | `>=` | 4.999s 采集中 / 5.0s 完成 |
| 12 | 校准最少样本 | 10 | `>=` | 9 个失败延长 / 10 个成功 |
| 13 | 最小眼距 | 15px | 严格 `<` 拒绝 | 15.0px 接受 / 14.4px 拒绝 |
| 14 | YuNet 置信度 | 0.6 | `>=` 接受 | 0.6 接受 / 0.599 拒绝 |
| 15 | 多人脸面积差 | 20% | 严格 `<` 走连续性 | 恰 20% → 仍选最大脸 |
| 16 | Hermes 冷却 | 60s | 严格 `<` 跳过 | 59.999s 跳过 / 60.0s 推送 |
| 17 | API 基准值 | >0 | 严格 `>` | 0 拒绝 / 1e-9 接受 |
| 18 | 蜂鸣节拍 | 0.15/0.10s | `>=` 翻转 | 149ms 不切 / 150ms 切换 |
| 19 | 休眠绿闪 | 0.5/1.5s | `>=` 翻转 | 499ms 不切 / 500ms 切换 |
| 20 | Roll 归一化 | [-90°, 90°] | 越界 ±180° 折回 | 165° → -15° |

每条边界均有独立命名的用例，断言两侧行为——回归时能立刻定位是哪个阈值语义被改动。

时序/交互类边界另覆盖：

- 单帧恢复重置不良计时（捡东西不误报）
- 报警中侧脸帧不当作"恢复"（维持报警，恢复计时不启动）
- 检测尖峰帧（100→180→100px）全程零污染
- 休眠期间人脸闪断 → 唤醒计时清零
- 无脸帧后跳变门控历史清空（人脸恢复第一帧不误丢）
- 遮挡重校准在 ALERTING 状态同样可触发
- Hermes 写入失败不更新冷却戳（告警不丢失）、进入 ALERTING 瞬间只推送一次

---

## 4. 测试发现的问题（供后续修复决策）

1. **[已修复] `hermes.py` 未指定文件编码** — `open(path, "a")` 依赖系统 locale，
   非 UTF-8 环境写出乱码。已改为 `encoding="utf-8"`（由 `test_chinese_not_escaped` 发现）。
2. **[xfail 记录] 从 ALERTING 进入遮挡重校准时 `is_alerting` 未清除** —
   重校准期间 `/api/v1/status` 仍报告 `is_alerting=true`
   （`test_recal_from_alerting_clears_alert_flag`，标记 xfail）。
3. **README 与代码不一致**：歪头阈值 README 写 15°，代码为 12°（`main.py _is_bad_posture`）。
4. **多人脸位置连续性的坐标系不匹配**：`detect_face_bbox` 中 `last_center` 是原始帧坐标，
   但与之比较的候选脸中心是模型输入空间 (320×240) 坐标，未乘 scale——通常不改变选脸结果，
   但数学上不严谨。
5. **`PostureState.WAITING_COOLDOWN` 不可达**：无任何转移进入该状态，属死代码。
6. **报警中人脸消失** → `tick()` 返回 False，硬件立即停止报警但 `is_alerting` 标志保持 True，
   状态展示与硬件行为不一致（已用回归用例固定当前行为）。

---

## 5. 板上手动验收清单（L4）

设备连接后按序执行，每项打勾：

| # | 操作 | 期望 |
|---|------|------|
| 1 | 启动 `python3 src/main.py`，正坐 | 蓝灯约 5s（校准）→ 绿灯 + 点阵 ✓ |
| 2 | 浏览器开 `http://<IP>:8000/viewer` | 实时画面 + 16 点眼轮廓 + 眼距数值 |
| 3 | 身体前倾贴近屏幕保持 6s | 第 5s 起红灯 + 点阵 ⚠️ + 蜂鸣器间歇响 |
| 4 | 坐直保持 4s | 第 3s 起恢复绿灯，蜂鸣停止 |
| 5 | 低头看手机 6s | 同 #3 触发报警 |
| 6 | 歪头 >12° 保持 6s | 同 #3 触发报警 |
| 7 | 前倾 3s → 坐直 1s → 再前倾 3s | **不**报警（时间滤波重置） |
| 8 | 手掌遮镜头 3s 后移开 | 蓝灯重校准 5s → 绿灯 |
| 9 | 遮镜头 1s 后移开 | 无反应，直接继续监控 |
| 10 | 侧脸 90° 保持 10s | 不报警（侧脸门控丢帧） |
| 11 | 离开座位 20s+ | 绿灯慢闪（休眠），viewer 显示 NO FACE |
| 12 | 回座 3s | 恢复绿灯常亮监控，**不**重校准 |
| 13 | 触发一次报警 | ≤1 分钟内家长微信收到"孩子当前坐姿…"推送 |
| 14 | 1 分钟内再次触发报警 | 微信**不**重复推送（60s 冷却） |
| 15 | 两人同框 | viewer 标注框锁定大脸/近脸，不跳变 |
| 16 | `curl -X POST <IP>:8000/api/v1/calibration -d '{"user_D_normal":62.5,"user_Y_normal":180}' -H 'Content-Type: application/json'` | 返回 ok，`/api/v1/status` 立即反映新基准 |
| 17 | Ctrl-C 退出 | LED 熄灭、蜂鸣停止、线程全部干净退出 |

---

## 6. 目录速查

```
Group11/
├── pytest.ini                    # testpaths + device marker 过滤
└── tests/
    ├── conftest.py               # FakeClock / 状态机工厂 / 投喂辅助
    ├── test_posture_judgment.py  # 三指标阈值边界 (17 用例)
    ├── test_state_machine.py     # FSM 时间边界与转移 (23 用例)
    ├── test_quality_gate.py      # 侧脸/跳变门控边界 (13 用例)
    ├── test_calibration_state.py # 校准样本/中位数/计时接口 (17 用例)
    ├── test_api.py               # FastAPI 端点边界 (19 用例)
    ├── test_hermes.py            # 冷却窗口/容错/格式 (12 用例)
    ├── test_alerter.py           # RPC 去重/蜂鸣节拍/绿闪 (15 用例)
    ├── test_landmarker.py        # PFLD 派生指标数学 (20 用例)
    ├── test_face_selection.py    # 多人脸选脸/bbox 钳位 (17 用例)
    ├── test_models_smoke.py      # 真实 ONNX 加载冒烟 (10 用例)
    └── test_on_device.py         # 板上集成 (14 用例, -m device)
```
