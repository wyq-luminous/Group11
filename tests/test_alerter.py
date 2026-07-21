"""
Alerter 报警输出逻辑测试 (硬件 RPC 全部 mock)
==============================================
被测逻辑 (src/alerter.py Alerter):
  - 模式去重: 相同模式重复调用不重发 RPC (Bridge 带宽保护)
  - 蜂鸣器间歇节拍: 0.15s 响 / 0.10s 停, >= 边界切换
  - 休眠绿灯慢闪: 0.5s 亮 / 1.5s 灭
  - clear() 复位

通过 monkeypatch 替换 _rpc_call / _sysfs_write, 记录所有硬件调用,
无需 Bridge socket / sysfs, 可在任意 PC 上运行。
"""

import pytest

import alerter as alerter_mod
from alerter import Alerter


class HardwareRecorder:
    """记录所有到达"硬件层"的调用"""

    def __init__(self):
        self.rpc_calls = []      # [(method, params)]
        self.sysfs_writes = []   # [(path, value)]

    def rpc(self, method, params=None, timeout=3.0):
        self.rpc_calls.append((method, params))
        return {"ok": True, "response": None}

    def sysfs(self, path, value):
        self.sysfs_writes.append((path, value))
        return True

    def reset(self):
        self.rpc_calls.clear()
        self.sysfs_writes.clear()

    def rpc_methods(self):
        return [m for m, _ in self.rpc_calls]


@pytest.fixture
def hw(monkeypatch):
    rec = HardwareRecorder()
    monkeypatch.setattr(alerter_mod, "_rpc_call", rec.rpc)
    monkeypatch.setattr(alerter_mod, "_sysfs_write", rec.sysfs)
    return rec


@pytest.fixture
def alerter(hw, clock):
    a = Alerter()   # __init__ 会调用 clear()
    hw.reset()      # 只关注测试期间的调用
    return a


# ============================================================
# 模式去重 (RPC 带宽保护)
# ============================================================
class TestModeDedup:
    def test_show_normal_sends_rpc_once(self, alerter, hw):
        """连续 100 次 show_normal → 点阵 RPC 仅发送 1 次"""
        for _ in range(100):
            alerter.show_normal()
        assert hw.rpc_methods().count("ok") == 1

    def test_show_calibrating_sends_rpc_once(self, alerter, hw):
        for _ in range(50):
            alerter.show_calibrating()
        assert hw.rpc_methods().count("clear") == 1

    def test_mode_switch_resends_rpc(self, alerter, hw):
        """normal → warning → normal 每次切换都重发对应图案"""
        alerter.show_normal()
        alerter.show_warning()
        alerter.show_normal()
        methods = hw.rpc_methods()
        assert methods.count("ok") == 2
        assert methods.count("warning") == 1

    def test_clear_forces_next_rpc(self, alerter, hw):
        """clear() 后 _mode 复位 → 下一次 show_normal 必须重发"""
        alerter.show_normal()
        alerter.clear()
        hw.reset()
        alerter.show_normal()
        assert "ok" in hw.rpc_methods()


# ============================================================
# 蜂鸣器间歇节拍 (0.15s 响 / 0.10s 停)
# ============================================================
class TestBuzzerPattern:
    def _buzzer_calls(self, hw):
        return [m for m in hw.rpc_methods() if m in ("buzzer_on", "buzzer_off")]

    def test_warning_starts_buzzer(self, alerter, hw, clock):
        """进入报警后首个节拍边界 → buzzer_on"""
        alerter.show_warning()   # _last_buzzer_toggle 初始 0 → 立即翻转为 on
        assert "buzzer_on" in self._buzzer_calls(hw)

    def test_buzzer_stays_on_before_150ms(self, alerter, hw, clock):
        """边界: 响 149ms (< 0.15s) → 不切换"""
        alerter.show_warning()   # buzzer on, toggle 时刻 = clock.t
        hw.reset()
        clock.advance(0.15 - 0.001)
        alerter.show_warning()
        assert self._buzzer_calls(hw) == []

    def test_buzzer_toggles_off_exactly_at_150ms(self, alerter, hw, clock):
        """边界: 响满 == 0.15s → 切换为 off (>= 语义)"""
        alerter.show_warning()
        hw.reset()
        clock.advance(0.15)
        alerter.show_warning()
        assert self._buzzer_calls(hw) == ["buzzer_off"]

    def test_buzzer_toggles_on_after_100ms_off(self, alerter, hw, clock):
        """停满 0.10s → 再次响起 (完整周期: on 0.15 → off 0.10 → on)"""
        alerter.show_warning()           # on
        clock.advance(0.15)
        alerter.show_warning()           # off
        hw.reset()
        clock.advance(0.10 - 0.001)
        alerter.show_warning()
        assert self._buzzer_calls(hw) == []   # 99ms 不切换
        clock.advance(0.001)
        alerter.show_warning()
        assert self._buzzer_calls(hw) == ["buzzer_on"]

    def test_normal_mode_silences_buzzer(self, alerter, hw, clock):
        """报警解除 → show_normal 立即发送 buzzer_off"""
        alerter.show_warning()
        hw.reset()
        alerter.show_normal()
        assert "buzzer_off" in self._buzzer_calls(hw)


# ============================================================
# 休眠绿灯慢闪 (0.5s 亮 / 1.5s 灭)
# ============================================================
class TestUnattendedBlink:
    def _green_writes(self, hw):
        """提取绿灯通道的写入序列"""
        return [v for p, v in hw.sysfs_writes if "green" in p]

    def test_first_call_clears_matrix_and_buzzer(self, alerter, hw, clock):
        alerter.show_unattended()
        assert "clear" in hw.rpc_methods()
        assert "buzzer_off" in hw.rpc_methods()

    def test_blink_off_exactly_at_500ms(self, alerter, hw, clock):
        """边界: 亮满 0.5s → 熄灭"""
        alerter.show_unattended()     # 触发一次翻转, 记录时刻
        clock.advance(2.0)
        alerter.show_unattended()     # 稳定进入某一相位
        hw.reset()

        phase_on = alerter._last_green_state
        threshold = 0.5 if phase_on else 1.5
        clock.advance(threshold - 0.001)
        alerter.show_unattended()
        assert self._green_writes(hw) == []       # 未到边界不翻转

        clock.advance(0.001)
        alerter.show_unattended()
        assert len(self._green_writes(hw)) == 1   # 恰到边界翻转
        assert alerter._last_green_state != phase_on

    def test_no_buzzer_during_sleep(self, alerter, hw, clock):
        """休眠期间长时间运行 → 除首次静音外不再有蜂鸣器调用"""
        alerter.show_unattended()
        hw.reset()
        for _ in range(20):
            clock.advance(0.5)
            alerter.show_unattended()
        buzzer = [m for m in hw.rpc_methods() if m.startswith("buzzer")]
        assert buzzer == []


# ============================================================
# clear / cleanup
# ============================================================
class TestClear:
    def test_clear_silences_and_greens(self, alerter, hw):
        alerter.show_warning()
        hw.reset()
        alerter.clear()
        assert "clear" in hw.rpc_methods()
        assert "buzzer_off" in hw.rpc_methods()
        assert alerter._is_alerting is False

    def test_rpc_failure_does_not_raise(self, monkeypatch, clock):
        """Bridge 不可用 (socket 缺失) → Alerter 全部方法不抛异常, 仅记日志"""
        monkeypatch.setattr(alerter_mod, "_rpc_call",
                            lambda m, p=None, timeout=3.0: {"ok": False, "error": "no socket"})
        monkeypatch.setattr(alerter_mod, "_sysfs_write", lambda p, v: False)
        a = Alerter()
        a.show_normal()
        a.show_warning()
        a.show_calibrating()
        a.show_unattended()
        a.clear()
        a.cleanup()
