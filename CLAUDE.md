# CLAUDE.md — SmartPosture Guardian 项目指令

## 强制规则

### DevLog 自动记录

**每次对话交互必须记录到 `docs/DevLog.md`**，无论任务是分析、编码、调试还是讨论。

记录格式：
- 以 `## 第N轮 — 标题 (日期)` 开头
- 包含：**用户 Prompt 摘要**、**Agent 采取的主要行动**、**Agent 最终回复摘要**
- 每轮追加到文件末尾，不覆盖历史记录

### 平台硬约束

本项目运行在 Arduino UNO-Q (ARM64 + STM32U585) 上：

1. **零 PC 依赖** — 必须使用 `opencv-python-headless`，严禁 `cv2.imshow()` 或任何 GUI 调用
2. **非阻塞 GPIO** — LED 矩阵 / 蜂鸣器由 STM32 MCU 管理，Linux 端必须通过 Bridge RPC (`/var/run/arduino-router.sock` + MsgPack) 通信，禁止直接操作 `/dev/gpiochip*`
3. **异步网络** — 云端推送必须用 `requests` 异步（`asyncio.to_thread` 或线程池），禁止阻塞主循环
4. **无 MediaPipe** — ARM64 + Python 3.13 无预编译 wheel，使用 YuNet ONNX 替代
5. **空间域算法** — 所有图像处理使用 NumPy 向量化 + 空间域插值，严禁 FFT / DCT / 小波等频域方法
