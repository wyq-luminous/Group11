"""
YuNetEngine 多人脸选脸 & 边界框裁剪测试
==============================================
被测逻辑 (src/main.py YuNetEngine.detect_face_bbox / detect_eyes):
  - 置信度阈值 0.6 边界 (>= 接受)
  - 多人脸: 最大脸优先; 面积差 < 20% 且有历史位置 → 位置连续性裁决
  - bbox 15% 边距扩展后在画面边缘的钳位 (不越界)
  - detect_eyes 眼距/眼Y 的缩放映射

使用 FakeDetector 替换 cv2.FaceDetectorYN, 直接构造 YuNet 输出矩阵
(N,15): [x,y,w,h, re_x,re_y, le_x,le_y, nose_x,nose_y, rm_x,rm_y, lm_x,lm_y, conf]
坐标均在模型输入空间 (320x240); 测试帧为 640x360 → scale_x=2.0, scale_y=1.5。
"""

import numpy as np
import pytest

from main import YuNetEngine

FRAME_W, FRAME_H = 640, 360
SCALE_X = FRAME_W / YuNetEngine.INPUT_W   # 2.0
SCALE_Y = FRAME_H / YuNetEngine.INPUT_H   # 1.5


class FakeDetector:
    """模拟 cv2.FaceDetectorYN 的最小接口"""

    def __init__(self, faces):
        # faces: list[list[15]] 或 None
        self._faces = np.array(faces, dtype=np.float32) if faces else None

    def setInputSize(self, size):
        pass

    def detect(self, img):
        return (None, self._faces)


def make_face(x, y, w, h, conf, re=(0, 0), le=(0, 0)):
    """构造一行 YuNet 输出 (模型输入空间坐标)"""
    return [x, y, w, h, re[0], re[1], le[0], le[1], 0, 0, 0, 0, 0, 0, conf]


def make_engine(faces):
    """跳过模型加载, 注入假检测器"""
    engine = YuNetEngine.__new__(YuNetEngine)
    engine.detector = FakeDetector(faces)
    engine.last_eye_positions = None
    return engine


@pytest.fixture
def frame():
    return np.zeros((FRAME_H, FRAME_W, 3), dtype=np.uint8)


# ============================================================
# 置信度阈值边界 (0.6)
# ============================================================
class TestConfidenceThreshold:
    def test_no_faces_returns_none(self, frame):
        engine = make_engine(None)
        assert engine.detect_face_bbox(frame) is None

    def test_confidence_below_threshold_rejected(self, frame):
        """边界: conf = 0.599 → 拒绝"""
        engine = make_engine([make_face(100, 80, 60, 60, 0.599)])
        assert engine.detect_face_bbox(frame) is None

    def test_confidence_exactly_at_threshold_accepted(self, frame):
        """边界: conf == 0.6 → 接受 (过滤条件为 >=)"""
        engine = make_engine([make_face(100, 80, 60, 60, 0.6)])
        assert engine.detect_face_bbox(frame) is not None

    def test_all_faces_below_threshold_returns_none(self, frame):
        engine = make_engine([
            make_face(50, 50, 40, 40, 0.3),
            make_face(150, 80, 60, 60, 0.5),
        ])
        assert engine.detect_face_bbox(frame) is None


# ============================================================
# 多人脸选脸策略
# ============================================================
class TestMultiFaceSelection:
    def test_single_face_selected(self, frame):
        engine = make_engine([make_face(100, 80, 60, 60, 0.9)])
        bbox = engine.detect_face_bbox(frame)
        assert bbox is not None

    def test_largest_face_wins_without_history(self, frame):
        """无历史位置 → 面积最大的脸胜出"""
        engine = make_engine([
            make_face(10, 10, 30, 30, 0.9),      # 小脸 (远处路人)
            make_face(150, 80, 80, 80, 0.9),     # 大脸 (使用者)
        ])
        bbox = engine.detect_face_bbox(frame, last_center=None)
        # 大脸中心 (150+40)*2=380 附近; 验证选中的是大脸
        x, y, w, h, conf = bbox
        assert w > 100 * SCALE_X  # 80px 模型空间 → >160px 帧空间 (含边距)

    def test_area_diff_exactly_20_percent_uses_largest(self, frame):
        """
        边界: 面积差恰好 20% → 不算"接近", 仍选最大脸
        (条件为 (A-B)/A < 0.20, 严格小于)
        大脸 100x100=10000, 小脸 √8000≈89.44… 改用 100x80=8000 → 差 20% 整。
        """
        big = make_face(200, 100, 100, 100, 0.9)     # 面积 10000
        small = make_face(10, 10, 100, 80, 0.9)      # 面积 8000
        engine = make_engine([small, big])
        # 历史位置紧贴小脸中心 → 若走连续性裁决会选小脸
        last_center = ((10 + 50) * SCALE_X, (10 + 40) * SCALE_Y)
        bbox = engine.detect_face_bbox(frame, last_center=last_center)
        x, _, _, _, _ = bbox
        assert x > 100 * SCALE_X  # 选中的是右侧大脸 (x≈200*2 减边距)

    def test_area_diff_below_20_percent_uses_position_continuity(self, frame):
        """面积差 19% (< 20%) 且有历史位置 → 位置连续性裁决, 选离历史更近的脸"""
        big = make_face(200, 100, 100, 100, 0.9)     # 面积 10000, 右侧
        near = make_face(10, 10, 90, 90, 0.9)        # 面积 8100 (差 19%), 左上
        engine = make_engine([near, big])
        last_center = (55 * SCALE_X, 55 * SCALE_Y)   # 靠近左上脸的原空间中心
        bbox = engine.detect_face_bbox(frame, last_center=last_center)
        x, _, _, _, _ = bbox
        assert x < 100  # 选中的是左上脸 (x≈10*2 减边距 → 接近 0)

    def test_area_diff_below_20_percent_without_history_uses_largest(self, frame):
        """面积接近但无历史位置 → 回退最大脸策略"""
        big = make_face(200, 100, 100, 100, 0.9)
        near = make_face(10, 10, 90, 90, 0.9)
        engine = make_engine([near, big])
        bbox = engine.detect_face_bbox(frame, last_center=None)
        x, _, _, _, _ = bbox
        assert x > 100 * SCALE_X


# ============================================================
# bbox 边距扩展与画面边缘钳位
# ============================================================
class TestBboxClamping:
    def test_face_at_origin_clamped_to_zero(self, frame):
        """人脸贴左上角 → 15% 边距扩展后 x/y 钳位到 0, 不为负"""
        engine = make_engine([make_face(0, 0, 60, 60, 0.9)])
        x, y, w, h, _ = engine.detect_face_bbox(frame)
        assert x >= 0
        assert y >= 0

    def test_face_at_bottom_right_clamped_inside(self, frame):
        """人脸贴右下角 → 扩展后 bbox 不超出帧边界"""
        engine = make_engine([make_face(260, 180, 60, 60, 0.9)])  # 恰好顶到 320x240 边缘
        x, y, w, h, _ = engine.detect_face_bbox(frame)
        assert x + w <= FRAME_W
        assert y + h <= FRAME_H

    def test_bbox_scaled_to_frame_space(self, frame):
        """坐标映射: 模型空间 (320x240) → 帧空间 (640x360)"""
        engine = make_engine([make_face(100, 80, 60, 60, 0.9)])
        x, y, w, h, _ = engine.detect_face_bbox(frame)
        # 中心点不受边距影响: (100+30)*2=260, (80+30)*1.5=165
        assert x + w / 2 == pytest.approx(260, abs=2)
        assert y + h / 2 == pytest.approx(165, abs=2)

    def test_margin_is_15_percent(self, frame):
        """边距量化验证: w 扩展约 30% (两侧各 15%)"""
        engine = make_engine([make_face(100, 80, 60, 60, 0.9)])
        _, _, w, _, _ = engine.detect_face_bbox(frame)
        assert w == pytest.approx(60 * 1.3 * SCALE_X, abs=2)


# ============================================================
# detect_eyes 缩放映射与眼距计算
# ============================================================
class TestDetectEyes:
    def test_no_face_returns_none_tuple(self, frame):
        engine = make_engine(None)
        assert engine.detect_eyes(frame) == (None, None, False)

    def test_low_confidence_returns_none_tuple(self, frame):
        engine = make_engine([make_face(100, 80, 60, 60, 0.5, re=(160, 100), le=(120, 100))])
        assert engine.detect_eyes(frame) == (None, None, False)

    def test_eye_distance_and_y_scaled(self, frame):
        """
        模型空间: 左眼(120,100) 右眼(160,100) → 帧空间 (240,150)/(320,150)
        眼距 = 80px, 眼Y = 150
        """
        engine = make_engine([make_face(100, 80, 60, 60, 0.9,
                                        re=(160, 100), le=(120, 100))])
        dist, eye_y, detected = engine.detect_eyes(frame)
        assert detected
        assert dist == pytest.approx(80.0)
        assert eye_y == pytest.approx(150.0)

    def test_diagonal_eye_distance_euclidean(self, frame):
        """歪头时眼距为欧氏距离: dx=40*2=80, dy=20*1.5=30 → √(80²+30²)"""
        engine = make_engine([make_face(100, 80, 60, 60, 0.9,
                                        re=(160, 120), le=(120, 100))])
        dist, eye_y, _ = engine.detect_eyes(frame)
        assert dist == pytest.approx((80**2 + 30**2) ** 0.5)
        assert eye_y == pytest.approx((100 * 1.5 + 120 * 1.5) / 2)
