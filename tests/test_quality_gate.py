"""
质量门控 (侧脸 / 帧间跳变) 边界条件测试
==============================================
被测逻辑 (src/main.py PostureAnalyzer.tick):
  - 侧脸门控:   yaw_ratio > 0.35        → 丢弃帧 (严格大于)
  - 跳变门控:   帧间眼距变化 > 30%      → 丢弃帧 (严格大于)
  - 两个门控仅在 MONITORING / ALERTING 状态生效
  - 被丢弃的帧返回当前 is_alerting (维持现状, 不推进判定)
"""

import pytest

from conftest import feed_face, feed_no_face

GOOD = dict(dist=100.0, y=100.0)
BAD = dict(dist=140.0, y=100.0)


# ============================================================
# 侧脸门控 (yaw_ratio 0.35 边界)
# ============================================================
class TestYawGate:
    def test_yaw_exactly_at_threshold_is_processed(self, clock, analyzer_factory):
        """边界: yaw == 0.35 → 不丢弃, 正常参与判定 (严格大于才丢)"""
        state, analyzer = analyzer_factory()
        feed_face(state, **BAD, yaw=0.35)
        analyzer.tick()
        assert state.bad_posture_start is not None  # 判定流程执行了

    def test_yaw_just_above_threshold_is_discarded(self, clock, analyzer_factory):
        """边界: yaw = 0.351 → 丢弃, 不良计时不启动"""
        state, analyzer = analyzer_factory()
        feed_face(state, **BAD, yaw=0.351)
        result = analyzer.tick()
        assert result is False                       # MONITORING 中未报警
        assert state.bad_posture_start is None       # 判定流程被跳过

    def test_yaw_gate_keeps_alarm_during_alerting(self, clock, analyzer_factory):
        """ALERTING 中出现侧脸帧 → 返回 True (维持报警), 不当作恢复"""
        from main import PostureState
        state, analyzer = analyzer_factory()
        feed_face(state, **BAD)
        analyzer.tick()
        clock.t = state.bad_posture_start + 5.0
        feed_face(state, **BAD)
        assert analyzer.tick() is True

        feed_face(state, **GOOD, yaw=0.5)   # 侧脸 + 姿势看似良好
        assert analyzer.tick() is True       # 帧被丢弃 → 报警维持
        assert analyzer.posture == PostureState.ALERTING
        assert state.good_posture_start is None  # 恢复计时未被侧脸帧启动

    def test_yaw_gate_inactive_during_calibration(self, clock, analyzer_factory):
        """校准阶段门控不生效: 侧脸帧仍被收为校准样本 (当前实现行为)"""
        state, analyzer = analyzer_factory(calibrated=False)
        feed_face(state, 60.0, 180.0, yaw=0.9)
        analyzer.tick()
        assert len(state.calibration_samples) == 1

    def test_extreme_yaw_discarded(self, clock, analyzer_factory):
        """完全侧脸 (yaw=2.0) → 丢弃"""
        state, analyzer = analyzer_factory()
        feed_face(state, **BAD, yaw=2.0)
        analyzer.tick()
        assert state.bad_posture_start is None


# ============================================================
# 帧间跳变门控 (30% 边界)
# ============================================================
class TestJumpGate:
    def test_first_frame_never_gated(self, clock, analyzer_factory):
        """第一帧无历史眼距 → 不可能触发跳变门控"""
        state, analyzer = analyzer_factory()
        feed_face(state, **BAD)
        analyzer.tick()
        assert state.bad_posture_start is not None

    def test_jump_exactly_30_percent_is_processed(self, clock, analyzer_factory):
        """边界: |130-100|/100 == 0.30 → 不丢弃 (严格大于才丢)"""
        state, analyzer = analyzer_factory()
        feed_face(state, **GOOD)             # 建立历史眼距 100
        analyzer.tick()
        clock.advance(0.05)

        feed_face(state, dist=130.0, y=100.0)  # 恰好 30% 跳变, ratio=1.3 前倾
        analyzer.tick()
        assert state.bad_posture_start is not None  # 正常参与判定

    def test_jump_above_30_percent_is_discarded(self, clock, analyzer_factory):
        """边界: |131-100|/100 = 0.31 → 丢弃帧"""
        state, analyzer = analyzer_factory()
        feed_face(state, **GOOD)
        analyzer.tick()
        clock.advance(0.05)

        feed_face(state, dist=131.0, y=100.0)
        result = analyzer.tick()
        assert result is False
        assert state.bad_posture_start is None

    def test_downward_jump_also_discarded(self, clock, analyzer_factory):
        """反向跳变 (眼距骤减 40%) 同样丢弃 — abs() 语义"""
        state, analyzer = analyzer_factory()
        feed_face(state, **GOOD)
        analyzer.tick()
        clock.advance(0.05)

        feed_face(state, dist=60.0, y=100.0)  # -40%
        analyzer.tick()
        assert state.bad_posture_start is None

    def test_gated_frame_updates_history(self, clock, analyzer_factory):
        """
        被丢弃的跳变帧会更新历史眼距 (当前实现):
        100 → 140(丢弃, 历史变 140) → 140(相对历史 0% 跳变, 正常处理)。
        含义: 眼距持续停留在新值时, 第二帧起恢复判定 (真实的姿势突变不会被永久屏蔽)。
        """
        state, analyzer = analyzer_factory()
        feed_face(state, **GOOD)
        analyzer.tick()
        clock.advance(0.05)

        feed_face(state, dist=140.0, y=100.0)  # +40% 跳变 → 丢弃
        analyzer.tick()
        assert state.bad_posture_start is None
        clock.advance(0.05)

        feed_face(state, dist=140.0, y=100.0)  # 与新历史一致 → 处理
        analyzer.tick()
        assert state.bad_posture_start is not None  # ratio=1.4 前倾, 开始计时

    def test_no_face_resets_jump_history(self, clock, analyzer_factory):
        """无脸帧后历史眼距清空 → 人脸恢复的第一帧不触发跳变门控"""
        state, analyzer = analyzer_factory()
        feed_face(state, **GOOD)
        analyzer.tick()

        feed_no_face(state)
        analyzer.tick()
        assert analyzer._last_eye_dist is None

        feed_face(state, dist=200.0, y=100.0)  # 相对上帧 +100%, 但历史已清
        analyzer.tick()
        assert state.bad_posture_start is not None  # 正常参与判定

    def test_single_glitch_frame_does_not_alert(self, clock, analyzer_factory):
        """
        典型场景: 检测抖动产生单帧眼距尖峰 (100→180→100)。
        尖峰帧被丢弃; 回落帧相对新历史 180 是 -44% 又被丢弃;
        第三帧起恢复正常 → 全程无报警、无计时污染。
        """
        state, analyzer = analyzer_factory()
        feed_face(state, **GOOD)
        analyzer.tick()
        clock.advance(0.05)

        feed_face(state, dist=180.0, y=100.0)  # 尖峰
        assert analyzer.tick() is False
        clock.advance(0.05)

        feed_face(state, **GOOD)               # 回落
        assert analyzer.tick() is False
        clock.advance(0.05)

        feed_face(state, **GOOD)
        assert analyzer.tick() is False
        assert state.bad_posture_start is None
