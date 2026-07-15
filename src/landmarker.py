"""
慧姿·智能坐姿守护系统 — 人脸关键点定位模块
==============================================
基于 PFLD ONNX 模型 (98 点 WFLW 格式)，通过 OpenCV DNN 推理。

只提取坐姿判定所需的 17 个关键点:
  - 左眼轮廓 8 点 (索引 60-67)
  - 右眼轮廓 8 点 (索引 68-75)
  - 鼻尖     1 点 (索引 57)

派生指标:
  - eye_distance: 双眼中心间距 (像素)
  - eye_y:        双眼平均 Y 坐标
  - roll_deg:     歪头角度 (偏离水平面的角度)
  - yaw_ratio:    侧脸程度 (鼻尖偏离中线的比例)
"""

import os
import logging
import numpy as np
import cv2

logger = logging.getLogger("guardian.landmarker")

# WFLW 98 点格式中我们需要的索引
LEFT_EYE_IDX  = list(range(60, 68))   # 8 点左眼轮廓
RIGHT_EYE_IDX = list(range(68, 76))   # 8 点右眼轮廓
NOSE_TIP_IDX  = 57                     # 鼻尖

# 模型输入尺寸
MODEL_INPUT_SIZE = 112

# 质量门控
MIN_EYE_DIST_PX = 15.0   # 最小眼距，低于此值判定为检测异常


class LandmarkResult:
    """关键点检测结果"""
    __slots__ = (
        "face_detected", "eye_distance", "eye_y",
        "roll_deg", "yaw_ratio",
        "left_eye_pts", "right_eye_pts", "nose_pt",  # 供 debug_viewer 用
    )

    def __init__(self):
        self.face_detected = False
        self.eye_distance: float | None = None
        self.eye_y: float | None = None
        self.roll_deg: float = 0.0
        self.yaw_ratio: float = 0.0
        self.left_eye_pts: list = []
        self.right_eye_pts: list = []
        self.nose_pt: tuple = (0, 0)


class FaceLandmarker:
    """
    加载 PFLD ONNX，从人脸裁剪图中提取关键点。

    用法:
        landmarker = FaceLandmarker("models/pfpld.onnx")
        result = landmarker.detect(face_crop)  # face_crop: BGR numpy array
    """

    def __init__(self, model_path: str):
        if not os.path.exists(model_path):
            raise FileNotFoundError(f"PFLD 模型不存在: {model_path}")

        self.net = cv2.dnn.readNetFromONNX(model_path)
        # OpenCV DNN 后端优化: 尝试 OpenCL，回退到 CPU
        try:
            self.net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
            self.net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)
        except Exception:
            pass

        self._input_name = "input"
        self._diag_cnt = 0

        logger.info(f"FaceLandmarker: PFLD ONNX (98点 WFLW, {MODEL_INPUT_SIZE}×{MODEL_INPUT_SIZE})")

    def detect(self, face_crop: np.ndarray) -> LandmarkResult:
        """
        对裁剪后的人脸区域执行关键点检测。

        Args:
            face_crop: BGR 人脸裁剪图 (任意尺寸)

        Returns:
            LandmarkResult: 包含所有检测指标
        """
        result = LandmarkResult()

        if face_crop is None or face_crop.size == 0:
            return result

        h_crop, w_crop = face_crop.shape[:2]

        # ---- 预处理: 缩放 + RGB + 归一化 + NCHW ----
        blob = cv2.resize(face_crop, (MODEL_INPUT_SIZE, MODEL_INPUT_SIZE),
                          interpolation=cv2.INTER_AREA)
        blob = cv2.cvtColor(blob, cv2.COLOR_BGR2RGB)
        blob = blob.astype(np.float32) / 255.0
        # NCHW: (H, W, C) → (C, H, W) → (1, C, H, W)
        blob = blob.transpose(2, 0, 1)
        blob = np.expand_dims(blob, axis=0)

        # ---- 推理 ----
        self.net.setInput(blob)
        outputs = self.net.forward(["pose", "landms"])  # [pose(1,3), landms(1,196)]

        # ---- 解析 landmarks ----
        landms_raw = outputs[1][0]  # [196]
        landmarks = landms_raw.reshape(98, 2)  # 归一化坐标 [0,1]

        # ---- 提取关键点并映射回裁剪图坐标 ----
        left_pts = landmarks[LEFT_EYE_IDX]   # (8, 2)
        right_pts = landmarks[RIGHT_EYE_IDX]  # (8, 2)
        nose = landmarks[NOSE_TIP_IDX]        # (2,)

        # 归一化 → 像素
        left_pts_px = left_pts.copy()
        left_pts_px[:, 0] *= w_crop
        left_pts_px[:, 1] *= h_crop

        right_pts_px = right_pts.copy()
        right_pts_px[:, 0] *= w_crop
        right_pts_px[:, 1] *= h_crop

        nose_px = (float(nose[0] * w_crop), float(nose[1] * h_crop))

        # ---- 眼睛中心 ----
        left_center = left_pts_px.mean(axis=0)   # (x, y)
        right_center = right_pts_px.mean(axis=0)

        # ---- 眼距 ----
        eye_distance = float(np.linalg.norm(right_center - left_center))
        if eye_distance < MIN_EYE_DIST_PX:
            return result  # 异常检测，返回 face_detected=False

        eye_y = float((left_center[1] + right_center[1]) / 2.0)

        # ---- 歪头角 (Roll): 眼线偏离水平面的角度 ----
        roll_rad = np.arctan2(
            right_center[1] - left_center[1],
            right_center[0] - left_center[0]
        )
        roll_deg = float(np.degrees(roll_rad))
        # 归一化到 [-90, 90]
        if roll_deg > 90:
            roll_deg -= 180
        elif roll_deg < -90:
            roll_deg += 180

        # ---- 侧脸比 (Yaw): 鼻尖偏离两眼中线的比例 ----
        eye_mid_x = (left_center[0] + right_center[0]) / 2.0
        yaw_ratio = float(abs(nose_px[0] - eye_mid_x) / eye_distance)

        # ---- 组装结果 ----
        result.face_detected = True
        result.eye_distance = eye_distance
        result.eye_y = eye_y
        result.roll_deg = roll_deg
        result.yaw_ratio = yaw_ratio
        result.left_eye_pts = [(float(x), float(y)) for x, y in left_pts_px]
        result.right_eye_pts = [(float(x), float(y)) for x, y in right_pts_px]
        result.nose_pt = nose_px

        # 诊断日志 (每 60 帧一次)
        self._diag_cnt += 1
        if self._diag_cnt % 60 == 0:
            logger.info(
                f"[Landmark] 眼距={eye_distance:.1f}px 眼Y={eye_y:.1f} "
                f"歪头={roll_deg:.1f}° 侧脸比={yaw_ratio:.2f} "
                f"左眼=({left_center[0]:.0f},{left_center[1]:.0f}) "
                f"右眼=({right_center[0]:.0f},{right_center[1]:.0f})"
            )

        return result
