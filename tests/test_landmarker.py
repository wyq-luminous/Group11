"""
FaceLandmarker (PFLD 98 点) 派生指标数学测试
==============================================
被测逻辑 (src/landmarker.py FaceLandmarker.detect):
  - MIN_EYE_DIST_PX=15 边界 (< 15 拒绝, == 15 接受)
  - roll_deg 计算与 [-90, 90] 归一化
  - yaw_ratio (鼻尖偏移比) 计算
  - 空/无效裁剪图容错

用 FakeNet 替换 cv2.dnn 网络, 直接构造归一化关键点输出,
从而精确控制眼睛/鼻尖坐标 (真实模型推理见 test_models_smoke.py)。
"""

import numpy as np
import pytest

from landmarker import (
    FaceLandmarker, LandmarkResult,
    LEFT_EYE_IDX, RIGHT_EYE_IDX, NOSE_TIP_IDX, MIN_EYE_DIST_PX,
)


class FakeNet:
    """模拟 cv2.dnn Net: forward 返回预设的 [pose, landms]"""

    def __init__(self, landmarks_98x2):
        self._landms = np.asarray(landmarks_98x2, dtype=np.float32).reshape(1, 196)
        self._pose = np.zeros((1, 3), dtype=np.float32)

    def setInput(self, blob):
        pass

    def forward(self, names):
        return [self._pose, self._landms]


def make_landmarker(left_eye, right_eye, nose=(0.5, 0.6)):
    """
    构造注入假网络的 FaceLandmarker。
    left_eye/right_eye/nose: 归一化坐标 (x, y), 眼轮廓 8 点全部置于同一坐标
    → 轮廓均值 (眼睛中心) 即该坐标, 便于精确断言。
    """
    landmarks = np.zeros((98, 2), dtype=np.float32)
    landmarks[LEFT_EYE_IDX] = left_eye
    landmarks[RIGHT_EYE_IDX] = right_eye
    landmarks[NOSE_TIP_IDX] = nose

    lmk = FaceLandmarker.__new__(FaceLandmarker)
    lmk.net = FakeNet(landmarks)
    lmk._input_name = "input"
    lmk._diag_cnt = 0
    return lmk


def make_crop(w=100, h=100):
    return np.full((h, w, 3), 128, dtype=np.uint8)


# ============================================================
# 输入容错
# ============================================================
class TestInputValidation:
    def test_none_crop_returns_no_face(self):
        lmk = make_landmarker((0.3, 0.4), (0.7, 0.4))
        result = lmk.detect(None)
        assert result.face_detected is False
        assert result.eye_distance is None

    def test_empty_crop_returns_no_face(self):
        lmk = make_landmarker((0.3, 0.4), (0.7, 0.4))
        result = lmk.detect(np.empty((0, 0, 3), dtype=np.uint8))
        assert result.face_detected is False

    def test_default_result_fields(self):
        """LandmarkResult 默认值: 供状态机安全读取"""
        r = LandmarkResult()
        assert r.face_detected is False
        assert r.eye_distance is None
        assert r.eye_y is None
        assert r.roll_deg == 0.0
        assert r.yaw_ratio == 0.0


# ============================================================
# 最小眼距边界 (15px)
# ============================================================
class TestMinEyeDistance:
    def test_distance_exactly_15px_accepted(self):
        """
        边界: 眼距 == 15.0px → 接受 (拒绝条件为严格 <)。
        坐标选用二进制可精确表示的值: 0.25 与 0.40625 (=13/32),
        差 0.15625 × 96px 裁剪宽 = 精确 15.0px。
        """
        lmk = make_landmarker((0.25, 0.5), (0.40625, 0.5))
        result = lmk.detect(make_crop(96, 96))
        assert result.face_detected is True
        assert result.eye_distance == pytest.approx(15.0)

    def test_distance_below_15px_rejected(self):
        """眼距 14.4px (< 15) → 判定为检测异常, face_detected=False"""
        lmk = make_landmarker((0.25, 0.5), (0.40, 0.5))  # 0.15 * 96 = 14.4
        result = lmk.detect(make_crop(96, 96))
        assert result.face_detected is False
        assert result.eye_distance is None

    def test_zero_distance_rejected(self):
        """双眼重合 (模型输出退化) → 拒绝"""
        lmk = make_landmarker((0.5, 0.5), (0.5, 0.5))
        result = lmk.detect(make_crop())
        assert result.face_detected is False


# ============================================================
# 眼距 / 眼Y 计算
# ============================================================
class TestEyeMetrics:
    def test_horizontal_eye_distance(self):
        """左(30,40) 右(70,40) @100px 裁剪 → 眼距 40, 眼Y 40"""
        lmk = make_landmarker((0.3, 0.4), (0.7, 0.4))
        result = lmk.detect(make_crop(100, 100))
        assert result.eye_distance == pytest.approx(40.0)
        assert result.eye_y == pytest.approx(40.0)

    def test_eye_y_is_mean_of_both(self):
        """两眼高度不同 → eye_y 为均值"""
        lmk = make_landmarker((0.3, 0.30), (0.7, 0.50))
        result = lmk.detect(make_crop(100, 100))
        assert result.eye_y == pytest.approx(40.0)

    def test_rectangular_crop_scales_axes_independently(self):
        """非正方形裁剪 (200x100): x 按宽、y 按高分别缩放"""
        lmk = make_landmarker((0.3, 0.4), (0.7, 0.4))
        result = lmk.detect(make_crop(200, 100))
        assert result.eye_distance == pytest.approx(80.0)  # 0.4 * 200
        assert result.eye_y == pytest.approx(40.0)          # 0.4 * 100


# ============================================================
# 歪头角 (roll) 与归一化
# ============================================================
class TestRollAngle:
    def test_level_eyes_zero_roll(self):
        lmk = make_landmarker((0.3, 0.4), (0.7, 0.4))
        result = lmk.detect(make_crop())
        assert result.roll_deg == pytest.approx(0.0, abs=1e-4)

    def test_positive_roll(self):
        """右眼低 10px, 水平距 40px → atan2(10,40) ≈ 14.04°"""
        lmk = make_landmarker((0.3, 0.4), (0.7, 0.5))
        result = lmk.detect(make_crop(100, 100))
        assert result.roll_deg == pytest.approx(np.degrees(np.arctan2(10, 40)), abs=0.1)

    def test_negative_roll(self):
        """右眼高 10px → 约 -14.04°"""
        lmk = make_landmarker((0.3, 0.5), (0.7, 0.4))
        result = lmk.detect(make_crop(100, 100))
        assert result.roll_deg == pytest.approx(-np.degrees(np.arctan2(10, 40)), abs=0.1)

    def test_roll_above_90_normalized(self):
        """
        左右眼标签互换 (模型输出镜像): 原始角 ≈ 166° → 归一化减 180 → ≈ -14°。
        保证 roll 始终落在 [-90, 90]。
        """
        lmk = make_landmarker((0.7, 0.4), (0.3, 0.5))  # dx<0 → atan2 落在第二象限
        result = lmk.detect(make_crop(100, 100))
        assert -90.0 <= result.roll_deg <= 90.0

    def test_roll_below_minus_90_normalized(self):
        lmk = make_landmarker((0.7, 0.5), (0.3, 0.4))  # 第三象限
        result = lmk.detect(make_crop(100, 100))
        assert -90.0 <= result.roll_deg <= 90.0


# ============================================================
# 侧脸比 (yaw_ratio)
# ============================================================
class TestYawRatio:
    def test_centered_nose_zero_yaw(self):
        """鼻尖在两眼中线上 → yaw_ratio = 0"""
        lmk = make_landmarker((0.3, 0.4), (0.7, 0.4), nose=(0.5, 0.6))
        result = lmk.detect(make_crop(100, 100))
        assert result.yaw_ratio == pytest.approx(0.0, abs=1e-4)

    def test_offset_nose_yaw_ratio(self):
        """鼻尖偏移 18px, 眼距 40px → yaw = 0.45 (> 0.35 会被门控丢弃)"""
        lmk = make_landmarker((0.3, 0.4), (0.7, 0.4), nose=(0.68, 0.6))
        result = lmk.detect(make_crop(100, 100))
        assert result.yaw_ratio == pytest.approx(0.45, abs=0.01)

    def test_yaw_ratio_is_absolute(self):
        """向左/向右偏移的 yaw_ratio 相同 (abs 语义)"""
        left = make_landmarker((0.3, 0.4), (0.7, 0.4), nose=(0.4, 0.6)).detect(make_crop())
        right = make_landmarker((0.3, 0.4), (0.7, 0.4), nose=(0.6, 0.6)).detect(make_crop())
        assert left.yaw_ratio == pytest.approx(right.yaw_ratio, abs=1e-4)
        assert left.yaw_ratio > 0


# ============================================================
# 输出坐标完整性 (供 debug_viewer 绘制)
# ============================================================
class TestOutputPoints:
    def test_eight_points_per_eye(self):
        lmk = make_landmarker((0.3, 0.4), (0.7, 0.4))
        result = lmk.detect(make_crop(100, 100))
        assert len(result.left_eye_pts) == 8
        assert len(result.right_eye_pts) == 8

    def test_nose_point_in_crop_coordinates(self):
        lmk = make_landmarker((0.3, 0.4), (0.7, 0.4), nose=(0.5, 0.6))
        result = lmk.detect(make_crop(100, 100))
        assert result.nose_pt == pytest.approx((50.0, 60.0))
