"""
Hermes 微信告警文件队列测试
==============================================
被测逻辑 (src/hermes.py HermesPusher):
  - 冷却窗口边界: now - last < 60s → 跳过 (恰好 60s → 推送)
  - HERMES_ENABLED=False → 静默跳过
  - 写入失败容错: 不抛异常, 不更新冷却时间戳
  - JSON-lines 事件格式与中文保留
"""

import json
import time

import pytest

import hermes as hermes_mod
from hermes import HermesPusher
from config import HERMES_COOLDOWN_SEC


@pytest.fixture
def pusher(tmp_path):
    """告警文件重定向到临时目录, 不污染项目根目录"""
    p = HermesPusher()
    p._alert_path = str(tmp_path / "alerts.jsonl")
    return p


def read_lines(pusher):
    try:
        with open(pusher._alert_path, "r", encoding="utf-8") as f:
            return f.readlines()
    except FileNotFoundError:
        return []


# ============================================================
# 基本写入与事件格式
# ============================================================
class TestAlertWrite:
    def test_first_push_writes_event(self, pusher):
        pusher.try_push("前倾(眼距比=1.35)")
        lines = read_lines(pusher)
        assert len(lines) == 1

    def test_event_json_schema(self, pusher):
        """事件字段完整性: deliver_alerts.sh 与微信模板依赖这些字段"""
        pusher.try_push("前倾(眼距比=1.35)")
        event = json.loads(read_lines(pusher)[0])
        assert event["type"] == "posture_alert"
        assert event["device"] == "SmartPosture_Guardian"
        assert event["reason"] == "前倾(眼距比=1.35)"
        assert event["message"] == "孩子当前坐姿前倾(眼距比=1.35)，请注意提醒"
        # ISO 时间戳可被解析
        from datetime import datetime
        datetime.fromisoformat(event["timestamp"])

    def test_chinese_not_escaped(self, pusher):
        """ensure_ascii=False: 文件内容为原始中文 (微信直读, 非 \\uXXXX)"""
        pusher.try_push("低头(高度降=30.2px)")
        raw = read_lines(pusher)[0]
        assert "低头" in raw
        assert "\\u" not in raw

    def test_multiple_events_append_as_lines(self, pusher):
        """跨冷却窗口的多次推送按行追加 (JSON-lines 队列语义)"""
        pusher.try_push("前倾(眼距比=1.30)")
        pusher._last_push_time = 0.0  # 手动解除冷却
        pusher.try_push("歪头(倾角=15.0°)")
        lines = read_lines(pusher)
        assert len(lines) == 2
        assert json.loads(lines[1])["reason"] == "歪头(倾角=15.0°)"


# ============================================================
# 冷却窗口边界
# ============================================================
class TestCooldown:
    def test_within_cooldown_skipped(self, clock, pusher):
        """边界: 距上次 59.999s (< 60) → 跳过"""
        pusher.try_push("第一次")
        assert len(read_lines(pusher)) == 1

        clock.advance(HERMES_COOLDOWN_SEC - 0.001)
        pusher.try_push("冷却期内")
        assert len(read_lines(pusher)) == 1  # 未新增

    def test_exactly_at_cooldown_pushed(self, clock, pusher):
        """边界: 距上次恰好 60.0s → 推送 (条件为严格 <)"""
        pusher.try_push("第一次")
        clock.advance(float(HERMES_COOLDOWN_SEC))
        pusher.try_push("冷却期满")
        assert len(read_lines(pusher)) == 2

    def test_cooldown_independent_of_posture_recovery(self, clock, pusher):
        """冷却为纯时间窗口: 窗口内多次触发 (恢复又变差) 都不重复写"""
        pusher.try_push("A")
        for _ in range(5):
            clock.advance(5.0)
            pusher.try_push("B")
        assert len(read_lines(pusher)) == 1

    def test_successful_push_updates_timestamp(self, clock, pusher):
        pusher.try_push("A")
        assert pusher._last_push_time == pytest.approx(clock.t)


# ============================================================
# 容错与开关
# ============================================================
class TestFaultTolerance:
    def test_disabled_flag_skips_silently(self, monkeypatch, pusher):
        """HERMES_ENABLED=False → 不写文件、不抛异常。
        注意: 必须 patch hermes 模块内的名字 (from-import 值拷贝),
        patch config.HERMES_ENABLED 无效。"""
        monkeypatch.setattr(hermes_mod, "HERMES_ENABLED", False)
        pusher.try_push("被禁用")
        assert read_lines(pusher) == []

    def test_write_failure_does_not_raise(self, tmp_path):
        """告警路径不可写 (目录不存在) → 仅记日志, 绝不崩溃主循环"""
        p = HermesPusher()
        p._alert_path = str(tmp_path / "no_such_dir" / "alerts.jsonl")
        p.try_push("写入失败场景")  # 不应抛异常

    def test_write_failure_keeps_cooldown_open(self, clock, tmp_path):
        """写入失败不更新冷却时间戳 → 下次触发继续尝试 (不丢告警)"""
        p = HermesPusher()
        p._alert_path = str(tmp_path / "no_such_dir" / "alerts.jsonl")
        p.try_push("失败")
        assert p._last_push_time == 0.0

        # 修复路径后立即可推送, 无需等待冷却
        p._alert_path = str(tmp_path / "alerts.jsonl")
        p.try_push("恢复")
        assert len(read_lines(p)) == 1
