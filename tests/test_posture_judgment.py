"""
三指标复合判定 (_is_bad_posture) 边界条件测试
==============================================
被测逻辑 (src/main.py PostureAnalyzer._is_bad_posture):
  - 前倾: 眼距比率 ratio = d / D_normal  >  1.2   (严格大于)
  - 低头: 高度降  drop  = y - Y_normal   >  25px  (严格大于)
  - 歪头: |roll_deg|                     >  12°   (严格大于)
  - 未校准 → 一律不判为不良坐姿

基准值统一取 D_normal=100, Y_normal=100，便于心算边界。

注意: README 中歪头阈值写的是 15°，代码实际是 12°
(main.py `abs(roll_deg) > 12.0`)。本文件按代码实际值测试。
"""

import pytest

D_N = 100.0
Y_N = 100.0


@pytest.fixture
def judge(analyzer_factory):
    """返回已校准 (D=100, Y=100) 的 _is_bad_posture 可调用对象"""
    state, analyzer = analyzer_factory(calibrated=True, D=D_N, Y=Y_N)
    return analyzer._is_bad_posture


# ============================================================
# 前倾 (眼距比率) 边界
# ============================================================
class TestForwardLean:
    def test_ratio_exactly_at_threshold_is_ok(self, judge):
        """ratio == 1.2 精确落在阈值上 → 不报警 (严格大于)"""
        is_bad, reason = judge(d=120.0, y=Y_N)
        assert not is_bad
        assert reason == ""

    def test_ratio_just_above_threshold_is_bad(self, judge):
        """ratio = 1.201 刚过阈值 → 判定前倾"""
        is_bad, reason = judge(d=120.1, y=Y_N)
        assert is_bad
        assert "前倾" in reason

    def test_ratio_just_below_threshold_is_ok(self, judge):
        """ratio = 1.199 → 正常"""
        is_bad, _ = judge(d=119.9, y=Y_N)
        assert not is_bad

    def test_ratio_far_above_is_bad(self, judge):
        """极端前倾 (脸贴近镜头, ratio=3.0) → 报警"""
        is_bad, reason = judge(d=300.0, y=Y_N)
        assert is_bad
        assert "前倾" in reason

    def test_ratio_below_one_is_ok(self, judge):
        """后仰远离屏幕 (ratio=0.5) → 不属于前倾"""
        is_bad, _ = judge(d=50.0, y=Y_N)
        assert not is_bad

    def test_tiny_positive_distance_is_ok(self, judge):
        """极小眼距 (接近 0) → ratio 远小于 1.2, 不误报前倾"""
        is_bad, _ = judge(d=0.001, y=Y_N)
        assert not is_bad


# ============================================================
# 低头 (高度降) 边界
# ============================================================
class TestHeadDrop:
    def test_drop_exactly_at_threshold_is_ok(self, judge):
        """drop == 25.0px 精确落在阈值 → 不报警 (严格大于)"""
        is_bad, _ = judge(d=D_N, y=Y_N + 25.0)
        assert not is_bad

    def test_drop_just_above_threshold_is_bad(self, judge):
        """drop = 25.1px → 判定低头"""
        is_bad, reason = judge(d=D_N, y=Y_N + 25.1)
        assert is_bad
        assert "低头" in reason

    def test_drop_just_below_threshold_is_ok(self, judge):
        """drop = 24.9px → 正常"""
        is_bad, _ = judge(d=D_N, y=Y_N + 24.9)
        assert not is_bad

    def test_negative_drop_head_up_is_ok(self, judge):
        """抬头 (眼睛比基准高 50px, drop=-50) → 不报警"""
        is_bad, _ = judge(d=D_N, y=Y_N - 50.0)
        assert not is_bad

    def test_zero_drop_is_ok(self, judge):
        """与基准完全一致 → 正常"""
        is_bad, _ = judge(d=D_N, y=Y_N)
        assert not is_bad


# ============================================================
# 歪头 (Roll 角) 边界
# ============================================================
class TestHeadRoll:
    def test_roll_exactly_at_threshold_is_ok(self, judge):
        """roll == 12.0° 精确落在阈值 → 不报警 (严格大于)"""
        is_bad, _ = judge(d=D_N, y=Y_N, roll_deg=12.0)
        assert not is_bad

    def test_roll_just_above_threshold_is_bad(self, judge):
        """roll = 12.1° → 判定歪头"""
        is_bad, reason = judge(d=D_N, y=Y_N, roll_deg=12.1)
        assert is_bad
        assert "歪头" in reason

    def test_negative_roll_uses_absolute_value(self, judge):
        """向另一侧歪头 roll = -12.1° → 同样判定歪头 (取绝对值)"""
        is_bad, reason = judge(d=D_N, y=Y_N, roll_deg=-12.1)
        assert is_bad
        assert "歪头" in reason

    def test_negative_roll_at_threshold_is_ok(self, judge):
        """roll = -12.0° 边界 → 不报警"""
        is_bad, _ = judge(d=D_N, y=Y_N, roll_deg=-12.0)
        assert not is_bad

    def test_default_roll_zero_is_ok(self, judge):
        """未传 roll (默认 0) → 正常"""
        is_bad, _ = judge(d=D_N, y=Y_N)
        assert not is_bad


# ============================================================
# 复合与特殊情形
# ============================================================
class TestCompound:
    def test_all_three_indicators_bad(self, judge):
        """三项同时超标 → 报警且 reason 包含全部三项"""
        is_bad, reason = judge(d=150.0, y=Y_N + 40.0, roll_deg=20.0)
        assert is_bad
        assert "前倾" in reason
        assert "低头" in reason
        assert "歪头" in reason

    def test_two_indicators_bad(self, judge):
        """前倾 + 低头同时超标, 歪头正常"""
        is_bad, reason = judge(d=130.0, y=Y_N + 30.0, roll_deg=0.0)
        assert is_bad
        assert "前倾" in reason
        assert "低头" in reason
        assert "歪头" not in reason

    def test_uncalibrated_never_bad(self, analyzer_factory):
        """未校准状态下, 任意极端输入都不判为不良坐姿"""
        state, analyzer = analyzer_factory(calibrated=False)
        is_bad, reason = analyzer._is_bad_posture(d=999.0, y=999.0, roll_deg=90.0)
        assert not is_bad
        assert reason == ""

    def test_reason_string_format(self, judge):
        """reason 字符串包含量化数值, 供 Hermes 推送与日志使用"""
        is_bad, reason = judge(d=135.0, y=Y_N)
        assert is_bad
        assert "1.35" in reason  # 眼距比精确到两位小数
