"""
上位机调试视图 — MJPEG 眼标注流 (始终开启)
============================================
浏览器访问 http://<board-ip>:8000/viewer 查看实时标注画面。

标注内容: 摄像头画面 + 双眼十字准星 + 眼距数值 + 人脸框
"""

import threading
import time
import logging
from typing import Optional

import cv2
import numpy as np

logger = logging.getLogger("guardian.debug_viewer")


# ============================================================
# 画面标注
# ============================================================

def annotate_frame(frame: np.ndarray, eye_distance: Optional[float],
                   eye_y: Optional[float], eye_positions: Optional[list],
                   face_detected: bool) -> np.ndarray:
    """空间域像素操作，标注眼睛位置和眼距"""
    annotated = frame.copy()

    if face_detected and eye_positions:
        lx, ly = eye_positions[0]
        rx, ry = eye_positions[1]

        # 眼睛十字
        cs = 12
        # 左眼
        cv2.line(annotated, (lx - cs, ly), (lx + cs, ly), (0, 255, 255), 2)
        cv2.line(annotated, (lx, ly - cs), (lx, ly + cs), (0, 255, 255), 2)
        cv2.circle(annotated, (lx, ly), 8, (0, 255, 0), 1)
        # 右眼
        cv2.line(annotated, (rx - cs, ry), (rx + cs, ry), (0, 255, 255), 2)
        cv2.line(annotated, (rx, ry - cs), (rx, ry + cs), (0, 255, 255), 2)
        cv2.circle(annotated, (rx, ry), 8, (0, 255, 0), 1)
        # 连线
        cv2.line(annotated, (lx, ly), (rx, ry), (255, 0, 255), 1)

        # 眼距数字
        mid_x, mid_y = (lx + rx) // 2, (ly + ry) // 2 - 15
        if eye_distance:
            cv2.putText(annotated, f"{eye_distance:.1f} px", (mid_x - 40, mid_y),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)

        # 人脸框
        ew = abs(rx - lx)
        fx, fy = max(0, min(lx, rx) - ew // 2), max(0, min(ly, ry) - ew)
        fw, fh = min(annotated.shape[1] - fx, ew * 2), min(annotated.shape[0] - fy, int(ew * 2.5))
        cv2.rectangle(annotated, (fx, fy), (fx + fw, fy + fh), (0, 255, 0), 1)

    # 状态标签
    status = "FACE OK" if face_detected else "NO FACE"
    color = (0, 255, 0) if face_detected else (0, 0, 255)
    cv2.putText(annotated, status, (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)

    if eye_distance:
        cv2.putText(annotated, f"Eye Distance: {eye_distance:.1f} px", (10, 55),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
    if eye_y:
        cv2.putText(annotated, f"Eye Y: {eye_y:.1f}", (10, 75),
                   cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)

    return annotated


# ============================================================
# MJPEG 流缓冲区 (线程安全)
# ============================================================

class MJPEGStream:
    def __init__(self):
        self._lock = threading.Lock()
        self._latest_jpeg: Optional[bytes] = None

    def update(self, jpeg_bytes: bytes):
        with self._lock:
            self._latest_jpeg = jpeg_bytes

    def get_latest(self) -> Optional[bytes]:
        with self._lock:
            return self._latest_jpeg

    @staticmethod
    def encode(frame: np.ndarray, quality: int = 55) -> bytes:
        _, jpeg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
        return jpeg.tobytes()


# 全局单例
_mjpeg_stream = MJPEGStream()


def init_debug_viewer(state):
    """初始化 (无按键，网页始终可访问)"""
    state.debug_active = True  # 始终开启
    state.eye_positions = None
    logger.info("调试视图已就绪 (http://<ip>:8000/viewer)")


def shutdown_debug_viewer():
    pass


def get_mjpeg_stream() -> MJPEGStream:
    return _mjpeg_stream


def process_debug_frame(state) -> Optional[bytes]:
    """生成标注帧 JPEG"""
    frame = state.get_raw_frame()
    if frame is None:
        return None

    eye_distance, eye_y, face_detected = state.get_inference()
    annotated = annotate_frame(frame, eye_distance, eye_y,
                               state.eye_positions, face_detected)
    jpeg = _mjpeg_stream.encode(annotated, quality=55)
    _mjpeg_stream.update(jpeg)
    return jpeg
