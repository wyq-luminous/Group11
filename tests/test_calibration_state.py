"""
SharedState 校准数据与遮挡/休眠计时接口测试
==============================================
被测逻辑 (src/main.py SharedState):
  - finalize_calibration: 样本数边界 (CALIBRATION_MIN_SAMPLES=10) + 中位数
  - set_baseline: API 注入覆盖自动校准
  - mark_no_face / mark_face_restored / get_no_face_duration
  - mark_face_seen / mark_face_lost / get_face_seen_duration
"""

import pytest

from config import CALIBRATION_MIN_SAMPLES


@pytest.fixture
def state():
    from main import SharedState
    return SharedState()


# ============================================================
# 校准样本数边界
# ============================================================
class TestFinalizeCalibration:
    def _fill(self, state, n, d=60.0, y=180.0):
        for _ in range(n):
            state.add_calibration_sample(d, y)

    def test_zero_samples_fails(self, state):
        assert state.finalize_calibration() is False
        assert state.is_calibrated is False

    def test_min_minus_one_samples_fails(self, state):
        """边界: 9 个样本 (MIN-1) → 校准失败"""
        self._fill(state, CALIBRATION_MIN_SAMPLES - 1)
        assert state.finalize_calibration() is False
        assert state.is_calibrated is False

    def test_exactly_min_samples_succeeds(self, state):
        """边界: 恰好 10 个样本 → 校准成功"""
        self._fill(state, CALIBRATION_MIN_SAMPLES)
        assert state.finalize_calibration() is True
        assert state.is_calibrated is True
        assert state.D_normal == pytest.approx(60.0)
        assert state.Y_normal == pytest.approx(180.0)

    def test_samples_cleared_after_success(self, state):
        """校准成功后样本列表清空 (为下次重校准准备)"""
        self._fill(state, CALIBRATION_MIN_SAMPLES)
        state.finalize_calibration()
        assert state.calibration_samples == []

    def test_median_even_count(self, state):
        """偶数个样本 → 中位数为中间两值均值"""
        for d in [50.0, 60.0, 70.0, 80.0] * 3:  # 12 个样本
            state.add_calibration_sample(d, 100.0)
        state.finalize_calibration()
        assert state.D_normal == pytest.approx(65.0)

    def test_median_robust_to_extreme_outliers(self, state):
        """10 个样本含 2 个极端野值 (0.1 / 1e6) → 中位数不受影响"""
        for d in [60.0] * 8 + [0.1, 1e6]:
            state.add_calibration_sample(d, 180.0)
        state.finalize_calibration()
        assert state.D_normal == pytest.approx(60.0)

    def test_failed_finalize_keeps_samples(self, state):
        """样本不足时 finalize 失败 → 已有样本保留 (延长采集继续累积)"""
        self._fill(state, 5)
        state.finalize_calibration()
        assert len(state.calibration_samples) == 5


# ============================================================
# API 基准值注入
# ============================================================
class TestSetBaseline:
    def test_injection_overrides_auto_calibration(self, state):
        """API 注入覆盖已有自动校准结果"""
        for _ in range(CALIBRATION_MIN_SAMPLES):
            state.add_calibration_sample(60.0, 180.0)
        state.finalize_calibration()

        state.set_baseline(75.5, 200.0)
        d, y, calibrated = state.get_baseline()
        assert (d, y, calibrated) == (75.5, 200.0, True)

    def test_injection_clears_pending_samples(self, state):
        """注入时清空未完成的采样 (避免旧样本污染后续 finalize)"""
        state.add_calibration_sample(60.0, 180.0)
        state.set_baseline(75.5, 200.0)
        assert state.calibration_samples == []

    def test_injection_before_any_calibration(self, state):
        """冷启动即注入 → 直接进入已校准状态"""
        state.set_baseline(62.5, 180.0)
        _, _, calibrated = state.get_baseline()
        assert calibrated


# ============================================================
# 遮挡计时接口
# ============================================================
class TestCoverTracking:
    def test_mark_no_face_records_only_first(self, state):
        """重复 mark_no_face 不刷新起始时间 (记录的是最早时刻)"""
        state.mark_no_face(100.0)
        state.mark_no_face(105.0)
        assert state.no_face_start == 100.0

    def test_duration_zero_when_face_present(self, state):
        assert state.get_no_face_duration(999.0) == 0.0

    def test_face_restored_returns_duration_and_resets(self, clock, state):
        """恢复时返回遮挡时长, 且计时器复位"""
        state.mark_no_face(clock.t)
        clock.advance(2.5)
        duration = state.mark_face_restored()
        assert duration == pytest.approx(2.5)
        assert state.no_face_start is None

    def test_face_restored_without_cover_returns_none(self, state):
        assert state.mark_face_restored() is None


# ============================================================
# 休眠唤醒计时接口
# ============================================================
class TestWakeTracking:
    def test_mark_face_seen_records_only_first(self, state):
        state.mark_face_seen(100.0)
        state.mark_face_seen(105.0)
        assert state.face_detected_start == 100.0

    def test_face_lost_resets_timer(self, state):
        state.mark_face_seen(100.0)
        state.mark_face_lost()
        assert state.get_face_seen_duration(200.0) == 0.0

    def test_seen_duration(self, state):
        state.mark_face_seen(100.0)
        assert state.get_face_seen_duration(103.0) == pytest.approx(3.0)
