"""
pytest 公共夹具 (fixtures)
==============================================
- 将 src/ 加入 sys.path，使测试可直接 import main / config / hermes 等模块
- FakeClock: 虚拟时钟，接管 time.time()，使时间边界测试确定且瞬时完成
- 各类状态机构造辅助函数
"""

import sys
import os
from pathlib import Path

import pytest

# ---- 路径注入: 保证 import main / config 等可用 ----
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_DIR))


# ============================================================
# 虚拟时钟
# ============================================================
class FakeClock:
    """
    可手动推进的虚拟时钟。
    通过 monkeypatch 替换全局 time.time，所有业务模块
    (main / hermes / alerter) 内的 time.time() 调用均受控。
    时间边界测试因此可以做到:
      - 精确 (4.999s vs 5.000s 这种边界可严格区分)
      - 瞬时 (无需真实 sleep 等待 20 秒休眠超时)
    """

    def __init__(self, start: float = 1_000_000.0):
        self.t = start

    def time(self) -> float:
        return self.t

    def advance(self, dt: float) -> float:
        """推进 dt 秒，返回当前时间"""
        self.t += dt
        return self.t


@pytest.fixture
def clock(monkeypatch):
    """接管全局 time.time 的虚拟时钟"""
    import time as _time
    fc = FakeClock()
    monkeypatch.setattr(_time, "time", fc.time)
    return fc


# ============================================================
# 状态机构造辅助
# ============================================================
def make_landmark(dist=None, y=None, roll=0.0, yaw=0.0, detected=True):
    """构造一个 LandmarkResult 假数据"""
    from landmarker import LandmarkResult
    lm = LandmarkResult()
    lm.face_detected = detected
    lm.eye_distance = dist
    lm.eye_y = y
    lm.roll_deg = roll
    lm.yaw_ratio = yaw
    return lm


def feed_face(state, dist, y, roll=0.0, yaw=0.0):
    """向 SharedState 注入一帧有脸的关键点结果"""
    lm = make_landmark(dist, y, roll=roll, yaw=yaw, detected=True)
    with state.landmark_lock:
        state.landmark_result = lm
    return lm


def feed_no_face(state):
    """向 SharedState 注入一帧无脸结果"""
    lm = make_landmark(detected=False)
    with state.landmark_lock:
        state.landmark_result = lm
    return lm


@pytest.fixture
def analyzer_factory(clock):
    """
    工厂: 创建 (SharedState, PostureAnalyzer)。
    calibrated=True 时直接注入基准值并置于 MONITORING 状态，
    跳过 5 秒自动校准流程 (校准流程本身由专门用例覆盖)。
    """
    def _make(calibrated=True, D=100.0, Y=100.0, hermes=None):
        from main import SharedState, PostureAnalyzer, PostureState
        state = SharedState()
        analyzer = PostureAnalyzer(state, hermes=hermes)
        if calibrated:
            state.set_baseline(D, Y)
            analyzer.posture = PostureState.MONITORING
            state.posture_state = analyzer.posture
        return state, analyzer

    return _make
