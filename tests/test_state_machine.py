"""
PostureAnalyzer 状态机时间边界测试
==============================================
使用 FakeClock 虚拟时钟, 精确验证所有时间阈值的边界行为:

  | 阈值                        | 值    | 边界语义 (>=)        |
  |-----------------------------|-------|----------------------|
  | CALIBRATION_DURATION_SEC    | 5.0s  | elapsed >= 5.0 完成  |
  | ALERT_PERSIST_SEC           | 5.0s  | 不良 >= 5.0 触发报警 |
  | ALERT_COOLDOWN_SEC          | 3.0s  | 恢复 >= 3.0 解除     |
  | CALIBRATION_COVER_SEC       | 2.0s  | 遮挡 >= 2.0 标记重校 |
  | UNATTENDED_TIMEOUT_SEC      | 20.0s | 无脸 >= 20 休眠      |
  | UNATTENDED_WAKE_SEC         | 3.0s  | 有脸 >= 3.0 唤醒     |

状态转移图:
  CALIBRATING → MONITORING → ALERTING → (恢复) → MONITORING
  任意监控态 --无脸2~20s+人脸恢复--> CALIBRATING (重校准)
  任意监控态 --无脸>=20s--> UNATTENDED --有脸3s--> MONITORING
"""

import pytest

from conftest import feed_face, feed_no_face

# 良好/不良坐姿样本值 (基准 D=100, Y=100)
GOOD = dict(dist=100.0, y=100.0)
BAD = dict(dist=140.0, y=100.0)   # ratio=1.4 前倾

EPS = 0.001  # 边界两侧的最小时间步


# ============================================================
# 自动校准阶段
# ============================================================
class TestCalibrationPhase:
    def test_initial_state_is_calibrating(self, analyzer_factory):
        from main import PostureState
        state, analyzer = analyzer_factory(calibrated=False)
        assert analyzer.posture == PostureState.CALIBRATING
        assert state.posture_state == PostureState.CALIBRATING

    def test_calibration_completes_exactly_at_5s(self, clock, analyzer_factory):
        """边界: elapsed == 5.0s 且样本充足 → 立即完成校准"""
        from main import PostureState
        state, analyzer = analyzer_factory(calibrated=False)

        # 前 4.999 秒内投喂 12 个样本 (> 最少 10 个)
        for _ in range(12):
            feed_face(state, 60.0, 180.0)
            analyzer.tick()
            clock.advance(4.999 / 12)

        assert analyzer.posture == PostureState.CALIBRATING  # 4.999s < 5.0s

        clock.t = analyzer.calibration_start + 5.0  # 精确推到 5.0s 边界
        feed_face(state, 60.0, 180.0)
        analyzer.tick()

        assert analyzer.posture == PostureState.MONITORING
        d, y, calibrated = state.get_baseline()
        assert calibrated
        assert d == pytest.approx(60.0)
        assert y == pytest.approx(180.0)

    def test_calibration_extends_when_samples_insufficient(self, clock, analyzer_factory):
        """样本 < 10 个时到达 5s → 不完成, 重置计时延长采集"""
        from main import PostureState
        state, analyzer = analyzer_factory(calibrated=False)

        # 只投喂 8 帧有效样本 (最后一次 tick 会加入第 9 个, 仍 < 10)
        for _ in range(8):
            feed_face(state, 60.0, 180.0)
            analyzer.tick()
            clock.advance(0.5)

        clock.t = analyzer.calibration_start + 5.0
        feed_face(state, 60.0, 180.0)
        analyzer.tick()

        assert analyzer.posture == PostureState.CALIBRATING
        _, _, calibrated = state.get_baseline()
        assert not calibrated
        # 计时被重置 (延长采集)
        assert analyzer.calibration_start == clock.t

    def test_calibration_uses_median_against_outliers(self, clock, analyzer_factory):
        """校准取中位数: 个别野值帧 (检测抖动) 不应污染基准"""
        state, analyzer = analyzer_factory(calibrated=False)

        samples = [60.0] * 9 + [300.0, 5.0]  # 2 个极端野值
        for d in samples:
            feed_face(state, d, 180.0)
            analyzer.tick()
            clock.advance(0.2)

        clock.t = analyzer.calibration_start + 5.0
        feed_face(state, 60.0, 180.0)
        analyzer.tick()

        d, _, calibrated = state.get_baseline()
        assert calibrated
        assert d == pytest.approx(60.0)  # 中位数不受野值影响

    def test_no_alert_during_calibration(self, clock, analyzer_factory):
        """校准期间即使姿势极端, 也不触发报警"""
        state, analyzer = analyzer_factory(calibrated=False)
        for _ in range(20):
            feed_face(state, 500.0, 500.0)  # 极端值
            assert analyzer.tick() is False
            clock.advance(0.2)

    def test_no_face_during_calibration_does_nothing(self, clock, analyzer_factory):
        """校准中无脸帧: 不触发重校准/休眠, 状态保持 CALIBRATING"""
        from main import PostureState
        state, analyzer = analyzer_factory(calibrated=False)
        for _ in range(10):
            feed_no_face(state)
            assert analyzer.tick() is False
            clock.advance(3.0)  # 累计 30s 无脸
        assert analyzer.posture == PostureState.CALIBRATING
        assert not state.pending_recal


# ============================================================
# 报警触发 (5 秒时间滤波)
# ============================================================
class TestAlertTrigger:
    def _run_bad_for(self, clock, state, analyzer, seconds, step=0.05):
        """持续投喂不良姿势帧 seconds 秒, 返回最后一次 tick 结果"""
        t_end = clock.t + seconds
        result = False
        while clock.t < t_end:
            feed_face(state, **BAD)
            result = analyzer.tick()
            clock.advance(step)
        return result

    def test_bad_posture_below_5s_no_alert(self, clock, analyzer_factory):
        """边界: 不良持续 4.999s → 不报警"""
        from main import PostureState
        state, analyzer = analyzer_factory()

        feed_face(state, **BAD)
        analyzer.tick()          # t0: 记录 bad_posture_start
        t0 = state.bad_posture_start

        clock.t = t0 + 5.0 - EPS
        feed_face(state, **BAD)
        assert analyzer.tick() is False
        assert analyzer.posture == PostureState.MONITORING

    def test_bad_posture_exactly_5s_alerts(self, clock, analyzer_factory):
        """边界: 不良持续 == 5.0s → 触发报警 (>= 语义)"""
        from main import PostureState
        state, analyzer = analyzer_factory()

        feed_face(state, **BAD)
        analyzer.tick()
        t0 = state.bad_posture_start

        clock.t = t0 + 5.0
        feed_face(state, **BAD)
        assert analyzer.tick() is True
        assert analyzer.posture == PostureState.ALERTING
        assert state.is_alerting is True

    def test_brief_recovery_resets_bad_timer(self, clock, analyzer_factory):
        """时间滤波核心: 4s 不良 → 1 帧恢复 → 再 4s 不良 → 不报警 (计时被重置)"""
        from main import PostureState
        state, analyzer = analyzer_factory()

        self._run_bad_for(clock, state, analyzer, 4.0)
        assert analyzer.posture == PostureState.MONITORING

        feed_face(state, **GOOD)   # 单帧恢复 (如捡东西后坐直)
        analyzer.tick()
        assert state.bad_posture_start is None  # 计时清零

        result = self._run_bad_for(clock, state, analyzer, 4.0)
        assert result is False
        assert analyzer.posture == PostureState.MONITORING

    def test_good_posture_never_alerts(self, clock, analyzer_factory):
        """长时间良好坐姿 → 永不报警"""
        state, analyzer = analyzer_factory()
        for _ in range(100):
            feed_face(state, **GOOD)
            assert analyzer.tick() is False
            clock.advance(0.5)

    def test_hermes_pushed_once_on_alert_transition(self, clock, analyzer_factory):
        """进入 ALERTING 的瞬间推送一次 Hermes; 持续报警期间不重复调用 try_push"""
        calls = []

        class StubHermes:
            def try_push(self, reason):
                calls.append(reason)

        state, analyzer = analyzer_factory(hermes=StubHermes())
        self._run_bad_for(clock, state, analyzer, 5.1)
        assert len(calls) == 1
        assert "前倾" in calls[0]

        # 已在 ALERTING, 继续投喂不良帧 → 状态机不再调用 try_push
        self._run_bad_for(clock, state, analyzer, 3.0)
        assert len(calls) == 1


# ============================================================
# 报警解除 (3 秒恢复滤波)
# ============================================================
class TestAlertRecovery:
    @pytest.fixture
    def alerting(self, clock, analyzer_factory):
        """构造一个已处于 ALERTING 状态的状态机"""
        from main import PostureState
        state, analyzer = analyzer_factory()
        feed_face(state, **BAD)
        analyzer.tick()
        clock.t = state.bad_posture_start + 5.0
        feed_face(state, **BAD)
        analyzer.tick()
        assert analyzer.posture == PostureState.ALERTING
        return state, analyzer

    def test_recovery_below_3s_still_alerting(self, clock, alerting):
        """边界: 恢复 2.999s → 仍在报警"""
        from main import PostureState
        state, analyzer = alerting

        feed_face(state, **GOOD)
        analyzer.tick()            # 记录 good_posture_start
        t0 = state.good_posture_start

        clock.t = t0 + 3.0 - EPS
        feed_face(state, **GOOD)
        assert analyzer.tick() is True
        assert analyzer.posture == PostureState.ALERTING

    def test_recovery_exactly_3s_clears_alert(self, clock, alerting):
        """边界: 恢复 == 3.0s → 解除报警, 回到 MONITORING, 计时器全部清零"""
        from main import PostureState
        state, analyzer = alerting

        feed_face(state, **GOOD)
        analyzer.tick()
        t0 = state.good_posture_start

        clock.t = t0 + 3.0
        feed_face(state, **GOOD)
        assert analyzer.tick() is False
        assert analyzer.posture == PostureState.MONITORING
        assert state.is_alerting is False
        assert state.bad_posture_start is None
        assert state.good_posture_start is None

    def test_relapse_during_recovery_resets_good_timer(self, clock, alerting):
        """恢复 2s 后又变坏 1 帧 → 恢复计时清零, 需重新累计 3s"""
        from main import PostureState
        state, analyzer = alerting

        feed_face(state, **GOOD)
        analyzer.tick()
        clock.advance(2.0)
        feed_face(state, **GOOD)
        assert analyzer.tick() is True   # 2s < 3s, 仍报警

        # 复发帧眼距取 125: ratio=1.25 超阈值, 且相对上帧 100 仅 +25%
        # 跳变 (< 30%), 不会被质量门控丢弃
        feed_face(state, dist=125.0, y=100.0)
        analyzer.tick()
        assert state.good_posture_start is None

        # 再良好 2.9s 仍不解除
        feed_face(state, **GOOD)
        analyzer.tick()
        clock.advance(3.0 - EPS)
        feed_face(state, **GOOD)
        assert analyzer.tick() is True
        assert analyzer.posture == PostureState.ALERTING


# ============================================================
# 遮挡重校准 (2 秒边界)
# ============================================================
class TestCoverRecalibration:
    def test_cover_below_2s_no_recal(self, clock, analyzer_factory):
        """边界: 遮挡 1.999s 后恢复 → 不重校准, 继续监控"""
        from main import PostureState
        state, analyzer = analyzer_factory()

        feed_no_face(state)
        analyzer.tick()                    # 记录 no_face_start
        clock.advance(2.0 - EPS)
        feed_no_face(state)
        analyzer.tick()
        assert not state.pending_recal

        feed_face(state, **GOOD)
        analyzer.tick()
        assert analyzer.posture == PostureState.MONITORING

    def test_cover_exactly_2s_marks_recal(self, clock, analyzer_factory):
        """边界: 遮挡 == 2.0s → 标记 pending_recal"""
        state, analyzer = analyzer_factory()

        feed_no_face(state)
        analyzer.tick()
        clock.advance(2.0)
        feed_no_face(state)
        analyzer.tick()
        assert state.pending_recal is True

    def test_face_restored_after_cover_enters_calibrating(self, clock, analyzer_factory):
        """遮挡 3s → 人脸恢复 → 立即切入 CALIBRATING, 旧样本清空"""
        from main import PostureState
        state, analyzer = analyzer_factory()

        feed_no_face(state)
        analyzer.tick()
        clock.advance(3.0)
        feed_no_face(state)
        analyzer.tick()
        assert state.pending_recal

        feed_face(state, **GOOD)
        analyzer.tick()
        assert analyzer.posture == PostureState.CALIBRATING
        assert state.pending_recal is False
        assert analyzer.calibration_start == clock.t

    def test_recal_available_from_alerting_state(self, clock, analyzer_factory):
        """ALERTING 状态下遮挡 2s+ 恢复 → 同样触发重校准 (任意状态可用)"""
        from main import PostureState
        state, analyzer = analyzer_factory()

        # 进入 ALERTING
        feed_face(state, **BAD)
        analyzer.tick()
        clock.t = state.bad_posture_start + 5.0
        feed_face(state, **BAD)
        analyzer.tick()
        assert analyzer.posture == PostureState.ALERTING

        # 遮挡 2.5s → 恢复
        feed_no_face(state)
        analyzer.tick()
        clock.advance(2.5)
        feed_no_face(state)
        analyzer.tick()
        feed_face(state, **GOOD)
        analyzer.tick()
        assert analyzer.posture == PostureState.CALIBRATING

    @pytest.mark.xfail(reason="已知问题: 从 ALERTING 进入重校准时 is_alerting 标志未清除, "
                              "API /status 在重校准期间仍报告 is_alerting=true")
    def test_recal_from_alerting_clears_alert_flag(self, clock, analyzer_factory):
        state, analyzer = analyzer_factory()
        feed_face(state, **BAD)
        analyzer.tick()
        clock.t = state.bad_posture_start + 5.0
        feed_face(state, **BAD)
        analyzer.tick()

        feed_no_face(state)
        analyzer.tick()
        clock.advance(2.5)
        feed_no_face(state)
        analyzer.tick()
        feed_face(state, **GOOD)
        analyzer.tick()

        assert state.is_alerting is False


# ============================================================
# 无人休眠 (20s 进入 / 3s 唤醒)
# ============================================================
class TestUnattendedSleep:
    def _make_sleeping(self, clock, analyzer_factory):
        """构造已进入 UNATTENDED 的状态机"""
        from main import PostureState
        state, analyzer = analyzer_factory()
        feed_no_face(state)
        analyzer.tick()
        clock.advance(20.0)
        feed_no_face(state)
        analyzer.tick()
        assert analyzer.posture == PostureState.UNATTENDED
        return state, analyzer

    def test_no_face_below_20s_not_sleeping(self, clock, analyzer_factory):
        """边界: 无脸 19.999s → 未进入休眠 (但已标记 pending_recal)"""
        from main import PostureState
        state, analyzer = analyzer_factory()

        feed_no_face(state)
        analyzer.tick()
        clock.advance(20.0 - EPS)
        feed_no_face(state)
        analyzer.tick()
        assert analyzer.posture == PostureState.MONITORING
        assert state.pending_recal  # 2s < 19.999s, 重校准标记已置位

    def test_no_face_exactly_20s_enters_sleep(self, clock, analyzer_factory):
        """边界: 无脸 == 20.0s → 进入 UNATTENDED, 且清除 pending_recal (休眠优先)"""
        from main import PostureState
        state, analyzer = self._make_sleeping(clock, analyzer_factory)
        assert analyzer.posture == PostureState.UNATTENDED
        assert state.pending_recal is False

    def test_wake_below_3s_stays_sleeping(self, clock, analyzer_factory):
        """边界: 休眠中连续有脸 2.999s → 仍休眠"""
        from main import PostureState
        state, analyzer = self._make_sleeping(clock, analyzer_factory)

        feed_face(state, **GOOD)
        analyzer.tick()
        clock.advance(3.0 - EPS)
        feed_face(state, **GOOD)
        analyzer.tick()
        assert analyzer.posture == PostureState.UNATTENDED

    def test_wake_exactly_3s_returns_to_monitoring(self, clock, analyzer_factory):
        """边界: 连续有脸 == 3.0s → 唤醒回 MONITORING, 不重校准 (基准仍有效)"""
        from main import PostureState
        state, analyzer = self._make_sleeping(clock, analyzer_factory)

        feed_face(state, **GOOD)
        analyzer.tick()
        clock.advance(3.0)
        feed_face(state, **GOOD)
        analyzer.tick()
        assert analyzer.posture == PostureState.MONITORING
        _, _, calibrated = state.get_baseline()
        assert calibrated                      # 基准未失效
        assert state.no_face_start is None     # 遮挡计时已清, 不会误触重校准
        assert state.pending_recal is False

        # 唤醒后的下一帧: 正常监控, 不进入 CALIBRATING
        feed_face(state, **GOOD)
        analyzer.tick()
        assert analyzer.posture == PostureState.MONITORING

    def test_face_flicker_resets_wake_timer(self, clock, analyzer_factory):
        """休眠中: 有脸 2s → 丢失 1 帧 → 唤醒计时清零, 需重新累计 3s"""
        from main import PostureState
        state, analyzer = self._make_sleeping(clock, analyzer_factory)

        feed_face(state, **GOOD)
        analyzer.tick()
        clock.advance(2.0)
        feed_face(state, **GOOD)
        analyzer.tick()
        assert analyzer.posture == PostureState.UNATTENDED

        feed_no_face(state)         # 人脸闪断 (路过误检结束)
        analyzer.tick()
        assert state.face_detected_start is None

        clock.advance(0.1)
        feed_face(state, **GOOD)
        analyzer.tick()
        clock.advance(3.0 - EPS)
        feed_face(state, **GOOD)
        analyzer.tick()
        assert analyzer.posture == PostureState.UNATTENDED  # 2.999s 不够

    def test_sleep_never_alerts(self, clock, analyzer_factory):
        """休眠状态下 tick 永远返回 False (不驱动报警硬件)"""
        state, analyzer = self._make_sleeping(clock, analyzer_factory)
        feed_face(state, **BAD)     # 即使检测到不良姿势帧
        assert analyzer.tick() is False


# ============================================================
# 无脸帧与报警的交互
# ============================================================
class TestNoFaceDuringAlert:
    def test_no_face_during_alerting_returns_false(self, clock, analyzer_factory):
        """
        当前行为: ALERTING 中人脸消失 → tick 返回 False (硬件停止报警),
        但 posture 仍为 ALERTING、is_alerting 标志保持 True。
        此用例固定该行为作为回归基线; 若未来改为"无脸时维持报警"需同步更新。
        """
        from main import PostureState
        state, analyzer = analyzer_factory()
        feed_face(state, **BAD)
        analyzer.tick()
        clock.t = state.bad_posture_start + 5.0
        feed_face(state, **BAD)
        assert analyzer.tick() is True

        feed_no_face(state)
        assert analyzer.tick() is False
        assert analyzer.posture == PostureState.ALERTING
        assert state.is_alerting is True
