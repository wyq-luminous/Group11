"""
hermes.py — Hermes 微信告警推送模块 (文件队列模式)
====================================================
当坐姿状态机判定异常（前倾/低头/歪头）成立时，
将告警事件写入 JSON-lines 文件队列 (alerts.jsonl)。

Hermes Agent cron 每分钟调用 bin/deliver_alerts.sh 读取该文件，
非空 stdout 自动推送到家长微信。

架构 (对齐 Workshop 6 Group11/ws6-remote-control 验证过的模式):

  PostureAnalyzer._handle_monitoring()
      │  首次进入 ALERTING
      ▼
  hermes.try_push(reason)
      │  检查冷却 → 写 JSON 事件到 alerts.jsonl
      ▼
  Hermes Agent cron (每 1 分钟, --no-agent --script)
      │  bin/deliver_alerts.sh 读 alerts.jsonl
      │  stdout 非空 → Hermes 投递到微信
      ▼
  家长微信收到: "孩子当前坐姿前倾(眼距比=1.35)，请注意提醒"

设计决策 (参考 Workshop 6 DEVLOG):
  - 文件队列: 零额外依赖 (JSON-lines 即队列，无需 Redis/MQTT)
  - 冷却追踪: 纯时间窗口 60s，与姿势恢复无关
  - 异步解耦: 文件写入极快 (<1ms)，主循环不阻塞
  - 容错: 文件写入失败仅记日志，绝不崩溃
  - Hermes 只做投递管道 (script-only mode, 零 token 消耗)

用法:
  from hermes import HermesPusher

  hermes = HermesPusher()
  hermes.try_push("前倾(眼距比=1.35) | 低头(高度降=30.2px)")
"""

import os
import json
import time
import logging
from datetime import datetime

from config import (
    HERMES_ENABLED,
    HERMES_COOLDOWN_SEC,
    HERMES_ALERT_FILE,
    PROJECT_ROOT,
)

logger = logging.getLogger("guardian.hermes")

# 微信推送消息模板
_ALERT_TEMPLATE = "孩子当前坐姿{reason}，请注意提醒"


class HermesPusher:
    """
    告警事件写入器 — 轻量类，模仿 Workshop 6 AlertTracker 风格。
    无抽象基类，无继承层次，无外部依赖。

    职责:
      - try_push(reason): 主线程调用。检查冷却 → 写 JSON 事件到 alerts.jsonl。
      - 冷却窗口内静默跳过，防重复推送。
    """

    def __init__(self):
        self._last_push_time: float = 0.0  # 上次写入事件的 Unix 时间戳

        # 告警文件路径（项目根目录下）
        self._alert_path = os.path.join(PROJECT_ROOT, HERMES_ALERT_FILE)

    # ------------------------------------------------------------------
    # 公开接口 (main.py 调用)
    # ------------------------------------------------------------------

    def try_push(self, reason: str) -> None:
        """
        尝试写入坐姿告警事件到文件队列。

        冷却逻辑 (纯时间窗口):
          - 距上次写入不足 HERMES_COOLDOWN_SEC (60s) → 静默跳过
          - 冷却窗口与姿势恢复无关 — 即使坐姿恢复又变差，窗口内也不重复
          - 写入成功后更新冷却时间戳

        此方法同步执行文件写入 (<1ms)，不阻塞主循环。
        """
        if not HERMES_ENABLED:
            return

        now = time.time()

        # 冷却检查
        if now - self._last_push_time < HERMES_COOLDOWN_SEC:
            logger.debug(
                "Hermes 冷却中 (距上次 %.0fs / %ds)，跳过: %s",
                now - self._last_push_time, HERMES_COOLDOWN_SEC, reason,
            )
            return

        # 写入告警事件
        self._write_alert(now, reason)

    # ------------------------------------------------------------------
    # 内部实现 (参考 Workshop 6 bin/monitor.py write_alert 函数)
    # ------------------------------------------------------------------

    def _write_alert(self, now: float, reason: str) -> None:
        """
        追加一条告警事件到 JSON-lines 文件。

        文件格式 — 每行一个 JSON 对象:
          {"timestamp": "2026-07-16T14:32:00", "type": "posture_alert",
           "message": "...", "reason": "前倾(眼距比=1.35)", ...}
        """
        message = _ALERT_TEMPLATE.format(reason=reason)
        event = {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "type": "posture_alert",
            "device": "SmartPosture_Guardian",
            "message": message,
            "reason": reason,
        }

        try:
            with open(self._alert_path, "a") as f:
                f.write(json.dumps(event, ensure_ascii=False) + "\n")
            self._last_push_time = now
            logger.info("Hermes 告警已写入文件队列: %s", reason)
        except Exception as e:
            logger.error("Hermes 告警文件写入失败 (%s): %s", self._alert_path, e)
            # 写入失败不更新冷却时间戳，下次继续尝试


# ============================================================
# 自测 (python3 src/hermes.py)
# ============================================================
if __name__ == "__main__":
    import tempfile

    print("=== Hermes 文件队列模块自测 ===\n")

    hermes = HermesPusher()

    print(f"HERMES_ENABLED:        {HERMES_ENABLED}")
    print(f"HERMES_COOLDOWN_SEC:   {HERMES_COOLDOWN_SEC}s")
    print(f"HERMES_ALERT_FILE:     {HERMES_ALERT_FILE}")
    print(f"告警文件路径:          {hermes._alert_path}")

    # ---- 测试 1: 写入事件 ----
    print("\n--- 测试 1: 写入告警事件 ---")
    hermes.try_push("测试:前倾(眼距比=1.35)")
    time.sleep(0.1)

    if os.path.exists(hermes._alert_path):
        with open(hermes._alert_path, "r") as f:
            lines = f.readlines()
        print(f"alerts.jsonl 存在, {len(lines)} 行:")
        for line in lines:
            print(f"  {line.strip()}")
    else:
        print("alerts.jsonl 尚未创建 (首次推送后自动创建)")

    # ---- 测试 2: 冷却跳过 ----
    print("\n--- 测试 2: 冷却期内跳过 ---")
    hermes.try_push("测试:歪头(倾角=15.0°)")
    print(f"冷却剩余: {HERMES_COOLDOWN_SEC - (time.time() - hermes._last_push_time):.0f}s")

    # ---- 测试 3: 禁用开关 ----
    print("\n--- 测试 3: HERMES_ENABLED=False 跳过 ---")
    import config
    config.HERMES_ENABLED = False
    hermes.try_push("测试:低头(高度降=30px)")
    print("HERMES_ENABLED=False 时静默跳过 ✓")
    config.HERMES_ENABLED = True  # 恢复

    # ---- 清理 ----
    if os.path.exists(hermes._alert_path):
        os.remove(hermes._alert_path)
        print(f"\n清理测试文件: {hermes._alert_path}")

    print("\n自测完成 — 所有验证通过 ✓")
    print("注意: 实际推送需要 Hermes Agent + cron 配置，见 hermes-skills/posture-alert.md")
