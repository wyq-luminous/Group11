"""
慧姿·智能坐姿守护系统 — 主入口
==============================================
四线程架构：
  1. FastAPI 线程 — 非阻塞监听，接收前端基准值注入
  2. 采集线程    — 30fps 持续清空 V4L2 缓冲区
  3. 推理线程    — 人脸/眼睛检测 → 眼距 & 高度计算
  4. 主线程      — 状态机判定 + GPIO 报警

当前推理引擎: OpenCV Haar Cascade（内置，零额外依赖）
可替换为: ONNX Runtime + face_landmark（高精度 468 关键点）
"""

import sys
import os
import time
import threading
import queue
import signal
import logging
from pathlib import Path

import cv2
import numpy as np
import asyncio

# 添加 src 目录到 path，确保能 import config
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from alerter import Alerter
from landmarker import FaceLandmarker, LandmarkResult
import debug_viewer
from config import (
    # 摄像头
    CAMERA_INDEX, CAMERA_WIDTH, CAMERA_HEIGHT, CAMERA_FPS, CAMERA_FOURCC, CAMERA_BUFFERSIZE,
    # 模型
    MODEL_PATH, PFLD_MODEL_PATH,
    # 推理
    MIN_KEYPOINT_CONFIDENCE,
    # 校准
    CALIBRATION_DURATION_SEC, CALIBRATION_MIN_SAMPLES,
    CALIBRATION_COVER_SEC, CALIBRATION_RECAL_FEEDBACK_SEC,
    # 阈值
    EYE_DISTANCE_RATIO_THRESHOLD, HEIGHT_DROP_THRESHOLD_PX,
    ALERT_PERSIST_SEC, ALERT_COOLDOWN_SEC,
    # GPIO
    GPIO_CHIP, GPIO_BUZZER_LINE, GPIO_LED_RED_LINE, GPIO_LED_GREEN_LINE,
    BUZZER_FREQUENCY_HZ, BUZZER_DUTY_CYCLE,
    BUZZER_PATTERN_ON_SEC, BUZZER_PATTERN_OFF_SEC,
    # API
    API_HOST, API_PORT,
    # 日志
    LOG_DIR, LOG_LEVEL,
)

# ============================================================
# 日志配置
# ============================================================
os.makedirs(LOG_DIR, exist_ok=True)
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format="%(asctime)s [%(threadName)-10s] %(levelname)s: %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(LOG_DIR, "guardian.log")),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger("guardian")


# ============================================================
# 共享状态容器（线程安全）
# ============================================================
class SharedState:
    """所有线程间的数据交换通过此类完成，Lock 保护避免竞态"""

    def __init__(self):
        # ---- 系统控制 ----
        self.running = True
        self.posture_state: str = "CALIBRATING"  # 当前 FSM 状态名（供 API 读取）

        # ---- 采集 → 推理 ----
        self.raw_lock = threading.Lock()
        self.raw_frame: np.ndarray | None = None

        # ---- 推理 → 状态机 ----
        self.inference_lock = threading.Lock()
        self.eye_distance: float | None = None     # 当前双眼像素距离
        self.eye_y: float | None = None             # 当前眼睛 Y 轴均值
        self.face_detected: bool = False            # 当前帧是否检测到人脸
        self.inference_timestamp: float = 0.0       # 推理完成时间戳

        # ---- PFLD 关键点（替代上述粗粒度数据） ----
        self.landmark_lock = threading.Lock()
        self.landmark_result: LandmarkResult | None = None
        self.eye_positions: list | None = None       # 供 debug_viewer 绘制

        # ---- 基准值（校准/动态注入） ----
        self.calibration_lock = threading.Lock()
        self.D_normal: float | None = None          # 基准眼距
        self.Y_normal: float | None = None          # 基准眼睛高度
        self.is_calibrated: bool = False
        self.calibration_samples: list = []         # [(distance, y), ...]

        # ---- 报警状态 ----
        self.alert_lock = threading.Lock()
        self.is_alerting: bool = False
        self.bad_posture_start: float | None = None  # 不良坐姿起始时间戳
        self.good_posture_start: float | None = None  # 恢复坐姿起始时间戳

        # ---- 遮挡追踪（无感校准触发） ----
        self.cover_lock = threading.Lock()
        self.no_face_start: float | None = None   # 无人脸开始时间戳
        self.pending_recal: bool = False          # 人脸恢复后需重新校准

    def stop(self):
        """通知所有线程停止"""
        self.running = False

    # ---- 采集接口 ----
    def set_raw_frame(self, frame: np.ndarray):
        with self.raw_lock:
            self.raw_frame = frame

    def get_raw_frame(self) -> np.ndarray | None:
        with self.raw_lock:
            return self.raw_frame.copy() if self.raw_frame is not None else None

    # ---- 推理结果接口 ----
    def update_inference(self, eye_distance: float, eye_y: float, face_detected: bool):
        with self.inference_lock:
            self.eye_distance = eye_distance
            self.eye_y = eye_y
            self.face_detected = face_detected
            self.inference_timestamp = time.time()

    def get_inference(self) -> tuple[float | None, float | None, bool]:
        with self.inference_lock:
            return self.eye_distance, self.eye_y, self.face_detected

    def update_landmark(self, result: LandmarkResult, eye_positions: list | None = None):
        """写入 PFLD 关键点检测结果，同时同步旧字段供校准兼容"""
        with self.landmark_lock:
            self.landmark_result = result
            if eye_positions is not None:
                self.eye_positions = eye_positions
        with self.inference_lock:
            self.eye_distance = result.eye_distance
            self.eye_y = result.eye_y
            self.face_detected = result.face_detected
            self.inference_timestamp = time.time()

    def get_landmark(self) -> LandmarkResult | None:
        with self.landmark_lock:
            return self.landmark_result

    # ---- 校准接口 ----
    def set_baseline(self, d_normal: float, y_normal: float):
        """外部 API 注入基准值，覆盖自动校准结果"""
        with self.calibration_lock:
            self.D_normal = d_normal
            self.Y_normal = y_normal
            self.is_calibrated = True
            self.calibration_samples.clear()
            logger.info(f"基准值已从 API 注入: D_normal={d_normal:.2f}px, Y_normal={y_normal:.2f}px")

    def add_calibration_sample(self, distance: float, y: float):
        with self.calibration_lock:
            self.calibration_samples.append((distance, y))

    def finalize_calibration(self):
        """自动校准完成：取中位数作为基准（抗野值）"""
        with self.calibration_lock:
            if len(self.calibration_samples) < CALIBRATION_MIN_SAMPLES:
                return False
            arr = np.array(self.calibration_samples)
            self.D_normal = float(np.median(arr[:, 0]))
            self.Y_normal = float(np.median(arr[:, 1]))
            self.is_calibrated = True
            self.calibration_samples.clear()
            logger.info(f"自动校准完成: D_normal={self.D_normal:.2f}px, Y_normal={self.Y_normal:.2f}px")
            return True

    def get_baseline(self) -> tuple[float | None, float | None, bool]:
        with self.calibration_lock:
            return self.D_normal, self.Y_normal, self.is_calibrated

    # ---- 报警状态接口 ----
    def set_alerting(self, alerting: bool):
        with self.alert_lock:
            self.is_alerting = alerting

    # ---- 遮挡追踪接口（无感校准触发） ----
    def mark_no_face(self, ts: float):
        """记录无人脸开始时间（仅首次）"""
        with self.cover_lock:
            if self.no_face_start is None:
                self.no_face_start = ts

    def mark_face_restored(self) -> float | None:
        """人脸恢复，返回遮挡持续秒数；若未在遮挡状态返回 None"""
        with self.cover_lock:
            if self.no_face_start is not None:
                duration = time.time() - self.no_face_start
                self.no_face_start = None
                return duration
            return None

    def get_no_face_duration(self, now: float) -> float:
        """返回当前无脸持续秒数"""
        with self.cover_lock:
            if self.no_face_start is None:
                return 0.0
            return now - self.no_face_start


# ============================================================
# 1. 采集线程
# ============================================================
def _find_usb_camera() -> int:
    """
    查找 USB 摄像头的 /dev/video 索引，跳过 Qualcomm Venus 编解码器设备。
    返回设备索引，未找到则返回 -1。
    """
    import subprocess
    try:
        result = subprocess.run(
            ["v4l2-ctl", "--list-devices"], capture_output=True, text=True, timeout=5
        )
        lines = result.stdout.split("\n")
        current_is_camera = False
        for line in lines:
            line = line.strip()
            if "venus" in line.lower() or "video-codec" in line.lower():
                current_is_camera = False
                continue
            if "usb" in line.lower() or "camera" in line.lower() or "webcam" in line.lower():
                current_is_camera = True
                continue
            if current_is_camera and line.startswith("/dev/video"):
                idx_str = line.replace("/dev/video", "")
                return int(idx_str)
    except Exception:
        pass

    # 回退：逐个尝试 /dev/video0-9，跳过已知的 Venus 设备
    for i in range(10):
        dev = f"/dev/video{i}"
        if not os.path.exists(dev):
            continue
        try:
            result = subprocess.run(
                ["v4l2-ctl", "-d", dev, "--all"], capture_output=True, text=True, timeout=3
            )
            if "qcom-venus" in result.stdout.lower() or "venus" in result.stdout.lower():
                continue  # 跳过 Venus 编解码器
        except Exception:
            continue
        return i

    return -1


def capture_loop(state: SharedState):
    """持续以 30fps 读取摄像头，始终持有最新帧，清空 V4L2 FIFO 缓冲区"""
    logger.info("采集线程启动")

    # ---- 查找真实摄像头（跳过 Venus 编解码器） ----
    camera_idx = _find_usb_camera()
    if camera_idx < 0:
        logger.warning("未找到 USB 摄像头，尝试默认 /dev/video0")
        camera_idx = CAMERA_INDEX

    cap = cv2.VideoCapture(camera_idx)
    if not cap.isOpened():
        logger.error(f"无法打开摄像头 /dev/video{camera_idx}")
        logger.info("系统将以无摄像头模式运行（仅 API 可用）")
        # 不停止系统，API 仍然可用
        return

    # 摄像头参数配置
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*CAMERA_FOURCC))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAMERA_WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAMERA_HEIGHT)
    cap.set(cv2.CAP_PROP_FPS, CAMERA_FPS)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, CAMERA_BUFFERSIZE)

    actual_w = cap.get(cv2.CAP_PROP_FRAME_WIDTH)
    actual_h = cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
    actual_fps = cap.get(cv2.CAP_PROP_FPS)
    logger.info(f"摄像头已打开: {actual_w:.0f}x{actual_h:.0f} @ {actual_fps:.0f}fps (FourCC={CAMERA_FOURCC})")

    consecutive_failures = 0
    MAX_FAILURES = 30  # 连续失败阈值，触发自动重连

    while state.running:
        ret, frame = cap.read()
        if not ret:
            consecutive_failures += 1
            if consecutive_failures >= MAX_FAILURES:
                logger.warning(f"摄像头连续 {MAX_FAILURES} 次读取失败，尝试重连...")
                cap.release()
                time.sleep(1.0)
                cap = cv2.VideoCapture(CAMERA_INDEX)
                cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*CAMERA_FOURCC))
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAMERA_WIDTH)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAMERA_HEIGHT)
                cap.set(cv2.CAP_PROP_FPS, CAMERA_FPS)
                consecutive_failures = 0
            time.sleep(0.01)
            continue

        consecutive_failures = 0

        # 水平镜像（用户体验：画面不自拍反）
        frame = cv2.flip(frame, 1)

        # 存入共享状态（始终覆盖，只有最新帧）
        state.set_raw_frame(frame)

    cap.release()
    logger.info("采集线程已退出")


# ============================================================
# 2. 推理线程
# ============================================================
class InferenceEngine:
    """
    推理引擎基类 — 可插拔设计。
    当前实现: OpenCV Haar Cascade（内置，零额外依赖）
    未来替换: ONNX Runtime + face_landmark（高精度 468 关键点）
    """

    def detect_eyes(self, frame: np.ndarray) -> tuple[float | None, float | None, bool]:
        """
        检测双眼位置，返回 (eye_distance_px, eye_y_avg, face_detected)。
        子类必须实现此方法。
        """
        raise NotImplementedError


class YuNetEngine(InferenceEngine):
    """
    基于 OpenCV FaceDetectorYN (YuNet) 的 DNN 人脸+关键点检测。
    直接输出 5 点人脸关键点（左右眼、鼻尖、左右嘴角），无需额外眼睛检测步骤。

    YuNet 输出格式 (每张人脸 15 个值):
      [0..3]:  bbox x, y, w, h
      [4..5]:  right_eye_x, right_eye_y
      [6..7]:  left_eye_x, left_eye_y
      [8..9]:  nose_x, nose_y
      [10..11]: right_mouth_x, right_mouth_y
      [12..13]: left_mouth_x, left_mouth_y
      [14]:    confidence score
    """

    # YuNet 模型内部输入分辨率
    INPUT_W = 320
    INPUT_H = 240
    SCORE_THRESHOLD = 0.6
    NMS_THRESHOLD = 0.3

    def __init__(self, model_path: str):
        if not os.path.exists(model_path):
            raise FileNotFoundError(f"YuNet 模型不存在: {model_path}")

        self.detector = cv2.FaceDetectorYN_create(
            model_path, "",
            (self.INPUT_W, self.INPUT_H),
            self.SCORE_THRESHOLD,
            self.NMS_THRESHOLD,
            5000,  # top_k
        )
        self.detector.setInputSize((self.INPUT_W, self.INPUT_H))
        self.last_eye_positions = None  # 供调试视图用
        logger.info(f"推理引擎: YuNet DNN (face_detection_yunet.onnx, {self.INPUT_W}x{self.INPUT_H})")

    def detect_eyes(self, frame: np.ndarray) -> tuple[float | None, float | None, bool]:
        """
        空间域预处理 + DNN 推理：
        1. 缩放至 320x240（减少像素计算量）
        2. YuNet 推理 → 人脸框 + 5 点关键点
        3. 取置信度最高的人脸 → 提取左右眼坐标
        4. 计算眼距 & 平均 Y 坐标
        """
        h, w = frame.shape[:2]

        # ---- Step 1: 空间域缩放（INTER_AREA 适合缩小，无频域操作） ----
        resized = cv2.resize(frame, (self.INPUT_W, self.INPUT_H), interpolation=cv2.INTER_AREA)

        # ---- Step 2: YuNet DNN 推理 ----
        self.detector.setInputSize((self.INPUT_W, self.INPUT_H))
        faces = self.detector.detect(resized)

        if faces[1] is None or len(faces[1]) == 0:
            return None, None, False

        # ---- Step 3: 取置信度最高的人脸 ----
        face = faces[1][0]
        score = face[14]
        if score < self.SCORE_THRESHOLD:
            return None, None, False

        # ---- Step 4: 关键点坐标映射回原始分辨率 ----
        scale_x = w / self.INPUT_W
        scale_y = h / self.INPUT_H

        # YuNet 关键点索引: 4,5=右眼  6,7=左眼
        rx = float(face[4] * scale_x)   # right_eye_x
        ry = float(face[5] * scale_y)   # right_eye_y
        lx = float(face[6] * scale_x)   # left_eye_x
        ly = float(face[7] * scale_y)   # left_eye_y

        # ---- Step 5: 空间域眼距计算（欧氏距离） ----
        eye_distance = float(np.linalg.norm(np.array([rx - lx, ry - ly])))
        eye_y = float((ly + ry) / 2.0)

        # 保存眼睛位置供调试视图标注
        self.last_eye_positions = [(int(lx), int(ly)), (int(rx), int(ry))]

        return eye_distance, eye_y, True

    def detect_face_bbox(self, frame: np.ndarray) -> tuple | None:
        """
        仅检测人脸边界框（供 PFLD 级联使用）。
        返回 (x, y, w, h, confidence) 或 None。
        坐标已映射回原始分辨率，带 15% 边距。
        """
        h, w = frame.shape[:2]

        resized = cv2.resize(frame, (self.INPUT_W, self.INPUT_H), interpolation=cv2.INTER_AREA)
        self.detector.setInputSize((self.INPUT_W, self.INPUT_H))
        faces = self.detector.detect(resized)

        if faces[1] is None or len(faces[1]) == 0:
            return None

        face = faces[1][0]
        score = face[14]
        if score < self.SCORE_THRESHOLD:
            return None

        scale_x = w / self.INPUT_W
        scale_y = h / self.INPUT_H

        bx = float(face[0] * scale_x)
        by = float(face[1] * scale_y)
        bw = float(face[2] * scale_x)
        bh = float(face[3] * scale_y)

        # 扩展 15% 边距，确保眼睛/鼻尖不贴边
        margin_x = bw * 0.15
        margin_y = bh * 0.15
        bx = max(0, bx - margin_x)
        by = max(0, by - margin_y)
        bw = min(w - bx, bw + margin_x * 2)
        bh = min(h - by, bh + margin_y * 2)

        return (int(bx), int(by), int(bw), int(bh), float(score))


def inference_loop(state: SharedState):
    """
    推理线程主循环 (YuNet 检测人脸 → PFLD 精确定位关键点):
    - 从 shared_state 获取最新帧
    - YuNet 检测人脸边界框
    - PFLD 在裁剪区域精确定位 98 个关键点
    - 提取 17 个坐姿相关点 + 派生指标 → 写入 SharedState
    """
    logger.info("推理线程启动")

    # ---- 初始化 YuNet 人脸检测器 ----
    engine = None
    if os.path.exists(MODEL_PATH):
        try:
            engine = YuNetEngine(MODEL_PATH)
        except Exception as e:
            logger.warning(f"YuNet 初始化失败: {e}")
    else:
        logger.warning(f"模型文件缺失: {MODEL_PATH}")

    if engine is None:
        logger.error("无可用的推理引擎，推理线程退出")
        return

    # ---- 初始化 PFLD 关键点定位器 ----
    landmarker = None
    if os.path.exists(PFLD_MODEL_PATH):
        try:
            landmarker = FaceLandmarker(PFLD_MODEL_PATH)
        except Exception as e:
            logger.warning(f"PFLD 初始化失败: {e}")
    else:
        logger.warning(f"PFLD 模型缺失: {PFLD_MODEL_PATH}")

    if landmarker is None:
        logger.error("无可用的关键点定位器，回退到 YuNet 粗检测模式")
        # 回退：仍然用旧的 detect_eyes
        last_frame_id = None
        inference_count = 0
        t_start = time.time()
        while state.running:
            frame = state.get_raw_frame()
            if frame is None:
                time.sleep(0.002)
                continue
            frame_id = id(frame)
            if frame_id == last_frame_id:
                time.sleep(0.002)
                continue
            last_frame_id = frame_id
            try:
                eye_distance, eye_y, face_detected = engine.detect_eyes(frame)
            except Exception as e:
                logger.error(f"推理异常: {e}")
                time.sleep(0.01)
                continue
            state.update_inference(eye_distance, eye_y, face_detected)
            state.eye_positions = engine.last_eye_positions
            inference_count += 1
            debug_viewer.process_debug_frame(state)
        elapsed = time.time() - t_start
        logger.info(f"推理线程已退出 ({inference_count} 次推理, {inference_count/elapsed:.1f} fps)")
        return

    last_frame_id = None
    inference_count = 0
    t_start = time.time()

    while state.running:
        frame = state.get_raw_frame()
        if frame is None:
            time.sleep(0.002)
            continue

        frame_id = id(frame)
        if frame_id == last_frame_id:
            time.sleep(0.002)
            continue
        last_frame_id = frame_id

        try:
            # ---- Stage 1: YuNet 检测人脸框 ----
            bbox = engine.detect_face_bbox(frame)

            if bbox is not None:
                x, y, w_box, h_box, conf = bbox

                # 边界安全检查
                x = max(0, x)
                y = max(0, y)
                w_box = min(frame.shape[1] - x, w_box)
                h_box = min(frame.shape[0] - y, h_box)

                if w_box > 20 and h_box > 20:
                    face_crop = frame[y:y + h_box, x:x + w_box]

                    # ---- Stage 2: PFLD 精确定位 ----
                    result = landmarker.detect(face_crop)

                    if result.face_detected:
                        # 映射关键点坐标回原始帧
                        left_full = [(px + x, py + y) for px, py in result.left_eye_pts]
                        right_full = [(px + x, py + y) for px, py in result.right_eye_pts]
                        nose_full = (result.nose_pt[0] + x, result.nose_pt[1] + y)
                        result.nose_pt = nose_full

                        state.update_landmark(result, eye_positions=(left_full, right_full))
                        inference_count += 1
                        debug_viewer.process_debug_frame(state)
                        continue

                # 裁剪无效或 PFLD 未检测到关键点
                state.update_landmark(LandmarkResult(), eye_positions=None)

            else:
                # YuNet 未检测到人脸
                state.update_landmark(LandmarkResult(), eye_positions=None)

        except Exception as e:
            logger.error(f"推理异常: {e}", exc_info=True)
            time.sleep(0.01)
            continue

        inference_count += 1
        debug_viewer.process_debug_frame(state)

    elapsed = time.time() - t_start
    fps = inference_count / elapsed if elapsed > 0 else 0
    logger.info(f"推理线程已退出 ({inference_count} 次推理, {fps:.1f} fps)")


# ============================================================
# 3. 状态机
# ============================================================
class PostureState:
    CALIBRATING = "CALIBRATING"   # 自动校准中
    MONITORING = "MONITORING"     # 正常监控
    ALERTING = "ALERTING"         # 报警中
    WAITING_COOLDOWN = "COOLDOWN" # 报警后恢复等待


class PostureAnalyzer:
    """
    坐姿分析状态机：
    - CALIBRATING: 采集 N 秒样本 → 计算基准值
    - MONITORING:  检查双指标 → 不良坐姿累计 5 秒 → ALERTING
    - ALERTING:    持续报警 → 坐姿恢复稳定 3 秒 → MONITORING
    """

    def __init__(self, state: SharedState):
        self.state = state
        self.posture = PostureState.CALIBRATING
        self.state.posture_state = self.posture
        self.calibration_start = time.time()
        self.inference_ts = 0.0  # 上次推理时间戳
        self._last_eye_dist: float | None = None  # 帧间跳变检测

    def tick(self) -> bool:
        """
        每次主循环调用，返回是否应触发报警。

        判定流水线:
          1. 无人脸 → _handle_no_face (遮挡追踪)
          2. 侧脸(yaw>0.35) → 丢弃帧，冻结计时器
          3. 帧间跳变(>30%) → 丢弃帧，冻结计时器
          4. 正常 → 三指标判定 (前倾/低头/歪头)
        """
        # 读取 PFLD 关键点结果
        lm = self.state.get_landmark()
        now = time.time()

        # 兼容回退: 若无 landmark 数据则用旧接口
        if lm is None:
            eye_distance, eye_y, face_detected = self.state.get_inference()
        else:
            eye_distance = lm.eye_distance
            eye_y = lm.eye_y
            face_detected = lm.face_detected

        if not face_detected or eye_distance is None or eye_y is None:
            self._last_eye_dist = None
            return self._handle_no_face(now)

        # 人脸存在 — 清除遮挡计时，检查是否需要重校准
        self.state.mark_face_restored()
        if self.state.pending_recal:
            self._start_recalibration(now)
            self._last_eye_dist = None

        # ---- 质量门控 (仅 MONITORING/ALERTING 状态下生效) ----
        if lm is not None and self.posture in (PostureState.MONITORING, PostureState.ALERTING):
            # 侧脸: 丢弃帧，冻结计时器
            if lm.yaw_ratio > 0.35:
                return self.state.is_alerting

            # 帧间眼距跳变 > 30%: 丢弃帧，冻结计时器
            if self._last_eye_dist is not None and self._last_eye_dist > 0:
                jump = abs(eye_distance - self._last_eye_dist) / self._last_eye_dist
                if jump > 0.30:
                    self._last_eye_dist = eye_distance
                    return self.state.is_alerting

        self._last_eye_dist = eye_distance

        if self.posture == PostureState.CALIBRATING:
            return self._handle_calibrating(eye_distance, eye_y, now)

        elif self.posture == PostureState.MONITORING:
            return self._handle_monitoring(eye_distance, eye_y, now, lm)

        elif self.posture == PostureState.ALERTING:
            return self._handle_alerting(eye_distance, eye_y, now, lm)

        elif self.posture == PostureState.WAITING_COOLDOWN:
            self.posture = PostureState.MONITORING
            self.state.posture_state = self.posture
            return False

        return False

    def _handle_calibrating(self, d: float, y: float, now: float) -> bool:
        """校准阶段：收集样本"""
        self.state.add_calibration_sample(d, y)
        elapsed = now - self.calibration_start

        if elapsed >= CALIBRATION_DURATION_SEC:
            if self.state.finalize_calibration():
                self.posture = PostureState.MONITORING
                self.state.posture_state = self.posture
                logger.info(f"校准完成，进入监控状态")
            else:
                logger.warning(f"校准样本不足 ({len(self.state.calibration_samples)}), 延长采集...")
                self.calibration_start = now  # 延长采集

        return False  # 校准期间不报警

    def _is_bad_posture(self, d: float, y: float,
                        roll_deg: float = 0.0) -> tuple[bool, str]:
        """
        三指标复合判定（空间域）:
          - 前倾: 眼距比率 > 1.2
          - 低头: 当前眼Y − 基准眼Y > 25px (正值=眼睛比基准低)
          - 歪头: |眼线倾角| > 12°
        """
        D_n, Y_n, calibrated = self.state.get_baseline()
        if not calibrated or D_n is None or Y_n is None:
            return False, ""

        ratio = d / D_n
        drop = y - Y_n   # 修复: 低头时 y > Y_n → 正值

        reasons = []
        if ratio > EYE_DISTANCE_RATIO_THRESHOLD:
            reasons.append(f"前倾(眼距比={ratio:.2f})")
        if drop > HEIGHT_DROP_THRESHOLD_PX:
            reasons.append(f"低头(高度降={drop:.1f}px)")
        if abs(roll_deg) > 12.0:
            reasons.append(f"歪头(倾角={roll_deg:.1f}°)")

        return len(reasons) > 0, " | ".join(reasons)

    def _handle_monitoring(self, d: float, y: float, now: float,
                           lm=None) -> bool:
        """监控阶段：检测不良坐姿并累计时长"""
        roll = lm.roll_deg if lm else 0.0
        is_bad, reason = self._is_bad_posture(d, y, roll)

        if is_bad:
            if self.state.bad_posture_start is None:
                self.state.bad_posture_start = now
            elapsed_bad = now - self.state.bad_posture_start

            if elapsed_bad >= ALERT_PERSIST_SEC:
                self.posture = PostureState.ALERTING
                self.state.posture_state = self.posture
                self.state.set_alerting(True)
                logger.warning(f"⚠ 触发报警！{reason} | 持续 {elapsed_bad:.1f}s")
                return True
        else:
            if self.state.bad_posture_start is not None:
                self.state.bad_posture_start = None

        return False

    def _handle_alerting(self, d: float, y: float, now: float,
                         lm=None) -> bool:
        """报警阶段：检查是否恢复"""
        roll = lm.roll_deg if lm else 0.0
        is_bad, _ = self._is_bad_posture(d, y, roll)

        if not is_bad:
            if self.state.good_posture_start is None:
                self.state.good_posture_start = now
            elapsed_good = now - self.state.good_posture_start

            if elapsed_good >= ALERT_COOLDOWN_SEC:
                self.posture = PostureState.MONITORING
                self.state.posture_state = self.posture
                self.state.set_alerting(False)
                self.state.bad_posture_start = None
                self.state.good_posture_start = None
                logger.info(f"✓ 坐姿恢复，解除报警")
                return False
        else:
            self.state.good_posture_start = None

        return True  # 继续报警

    def _handle_no_face(self, now: float) -> bool:
        """
        无脸帧处理：追踪遮挡时长以触发重校准。
        仅在 MONITORING 状态下检测遮挡（校准/报警期间不触发）。
        """
        self.state.mark_no_face(now)
        duration = self.state.get_no_face_duration(now)

        if self.posture == PostureState.MONITORING:
            if duration >= CALIBRATION_COVER_SEC and not self.state.pending_recal:
                self.state.pending_recal = True
                logger.info(f"🔁 检测到遮挡 {duration:.1f}s ≥ {CALIBRATION_COVER_SEC}s，"
                            f"人脸恢复后将重新校准")

        return self.state.is_alerting

    def _start_recalibration(self, now: float):
        """人脸恢复后，重置校准数据并切入 CALIBRATING 状态"""
        with self.state.calibration_lock:
            self.state.calibration_samples.clear()
        self.calibration_start = now
        self.posture = PostureState.CALIBRATING
        self.state.posture_state = self.posture
        self.state.pending_recal = False
        logger.info("🔄 开始重校准（遮挡触发）...")


# ============================================================
# 4. 报警输出（由 alerter.py 实现）
# ============================================================
# Alerter 类已从 alerter 模块导入，提供:
#   alerter.show_normal()   — 绿灯 + 点阵 ✓
#   alerter.show_warning()  — 红灯 + 点阵 ⚠️ 三角感叹号 + 蜂鸣器
#   alerter.clear()         — 清空所有输出
#   alerter.cleanup()       — 释放硬件资源
#
# 通过 Arduino Router Bridge (Unix Socket + MsgPack RPC)
# 与 STM32 MCU 通信，控制板载 8×13 LED 点阵和 RGB LED。


# ============================================================
# 5. FastAPI 服务
# ============================================================
def _create_fastapi_app(state: SharedState):
    """创建 FastAPI 应用实例"""
    from fastapi import FastAPI
    from pydantic import BaseModel

    app = FastAPI(
        title="SmartPosture Guardian",
        description="慧姿·智能坐姿守护系统 — 本地 API",
        version="0.1.0",
    )

    class CalibrationRequest(BaseModel):
        user_D_normal: float
        user_Y_normal: float

    class StatusResponse(BaseModel):
        is_calibrated: bool
        D_normal: float | None
        Y_normal: float | None
        is_alerting: bool
        state: str
        posture_state: str

    @app.post("/api/v1/calibration")
    async def set_calibration(req: CalibrationRequest):
        """接收前端注入的用户专属基准值"""
        if req.user_D_normal <= 0 or req.user_Y_normal <= 0:
            return {"status": "error", "message": "基准值必须大于 0"}

        state.set_baseline(req.user_D_normal, req.user_Y_normal)
        return {
            "status": "ok",
            "D_normal": req.user_D_normal,
            "Y_normal": req.user_Y_normal,
        }

    @app.get("/api/v1/status")
    async def get_status():
        """返回系统运行状态"""
        d, y, calibrated = state.get_baseline()
        return StatusResponse(
            is_calibrated=calibrated,
            D_normal=d,
            Y_normal=y,
            is_alerting=state.is_alerting,
            state="running" if state.running else "stopped",
            posture_state=state.posture_state,
        )

    @app.get("/api/v1/health")
    async def health():
        return {"status": "ok"}

    # ---- 调试上位机: 标注眼距的 MJPEG 视频流 ----
    from fastapi.responses import StreamingResponse, HTMLResponse

    @app.get("/viewer", response_class=HTMLResponse)
    async def viewer_page():
        """调试上位机 HTML 页面: 实时摄像头画面 + 眼睛标注 + 眼距"""
        return HTMLResponse("""
<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>SmartPosture Guardian - Debug Viewer</title>
<style>
  body { margin:0; background:#111; color:#fff; font-family:monospace; text-align:center; }
  img { max-width:100%; border:2px solid #333; margin-top:10px; }
  h2 { margin:10px 0 0 0; color:#0af; }
  p { color:#888; margin:5px; }
  .warning { color:#f44; animation:blink 1s infinite; }
  @keyframes blink { 50%{opacity:0.5;} }
</style>
</head>
<body>
  <h2>SmartPosture Guardian</h2>
  <p>实时眼距检测 · 调试视图</p>
  <p class="warning">按板载 Volume Up 键切换显示</p>
  <img src="/stream" alt="MJPEG Stream" id="stream">
  <script>
    // 自动重连
    const img = document.getElementById('stream');
    img.onerror = function() { setTimeout(() => { img.src = '/stream?' + Date.now(); }, 1000); };
  </script>
</body>
</html>""")

    @app.get("/stream")
    async def mjpeg_stream():
        """MJPEG 视频流: 实时摄像头画面 + 眼睛标注 + 眼距数值"""
        stream = debug_viewer.get_mjpeg_stream()

        async def generate():
            while True:
                jpeg = stream.get_latest()
                if jpeg is not None:
                    yield (b"--frame\r\n"
                           b"Content-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n")
                await asyncio.sleep(0.05)  # ~20 fps max

        return StreamingResponse(
            generate(),
            media_type="multipart/x-mixed-replace; boundary=frame",
            headers={"Cache-Control": "no-cache"}
        )

    return app


def api_server_thread(state: SharedState):
    """FastAPI 服务线程"""
    import uvicorn
    app = _create_fastapi_app(state)
    config = uvicorn.Config(
        app, host=API_HOST, port=API_PORT,
        log_level="warning", access_log=False
    )
    server = uvicorn.Server(config)
    logger.info(f"API 服务已启动: http://{API_HOST}:{API_PORT}")
    server.run()
    logger.info("API 服务已退出")


# ============================================================
# 6. 主函数
# ============================================================
def main():
    logger.info("=" * 50)
    logger.info("慧姿·智能坐姿守护系统 启动中...")
    logger.info("=" * 50)

    state = SharedState()

    # ---- 初始化调试视图 (按钮 + MJPEG 流) ----
    debug_viewer.init_debug_viewer(state)

    # ---- 信号处理：优雅退出 ----
    def graceful_shutdown(signum, frame):
        logger.info(f"收到信号 {signum}，正在退出...")
        state.stop()

    signal.signal(signal.SIGINT, graceful_shutdown)
    signal.signal(signal.SIGTERM, graceful_shutdown)

    # ---- 启动工作线程 ----
    threads = [
        threading.Thread(target=api_server_thread, args=(state,), name="API", daemon=True),
        threading.Thread(target=capture_loop, args=(state,), name="Capture", daemon=True),
        threading.Thread(target=inference_loop, args=(state,), name="Inference", daemon=True),
    ]

    for t in threads:
        t.start()
        time.sleep(0.1)  # 错开启动，日志可读

    # ---- 主线程：状态机 + 报警 ----
    analyzer = PostureAnalyzer(state)
    alerter = Alerter()

    logger.info("进入主循环（状态机 + 报警控制）")

    try:
        while state.running:
            loop_start = time.time()

            # 执行状态机判定
            should_alert = analyzer.tick()

            # 控制报警硬件（按状态区分反馈）
            if analyzer.posture == PostureState.CALIBRATING:
                alerter.show_calibrating()
            elif should_alert:
                alerter.show_warning()
            else:
                alerter.show_normal()

            # 每秒输出一次状态摘要
            elapsed = time.time() - loop_start
            sleep_time = max(0.0, 0.05 - elapsed)  # 目标 20Hz 循环
            time.sleep(sleep_time)

    except KeyboardInterrupt:
        logger.info("收到键盘中断")
    finally:
        state.stop()
        debug_viewer.shutdown_debug_viewer()
        alerter.cleanup()
        for t in threads:
            t.join(timeout=2.0)
        logger.info("系统已退出")


if __name__ == "__main__":
    main()
