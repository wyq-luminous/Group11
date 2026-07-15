"""
慧姿·智能坐姿守护系统 — 全局配置文件
==============================================
所有可调参数集中于此。逻辑层代码严禁硬编码任何数值，
必须从此处 import 变量。
"""

import os

# ============================================================
# 项目根目录
# ============================================================
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ============================================================
# 摄像头参数 (USB Webcam via V4L2)
# ============================================================
CAMERA_INDEX = 0                  # /dev/video0
CAMERA_WIDTH = 640                # 采集分辨率宽度
CAMERA_HEIGHT = 360               # 采集分辨率高度
CAMERA_FPS = 30                   # 目标帧率
CAMERA_FOURCC = "MJPG"            # 压缩格式，避免 YUYV 占满 USB 带宽
CAMERA_BUFFERSIZE = 1             # V4L2 缓冲区大小（驱动可能忽略，由采集线程持续 drain 补偿）

# ============================================================
# AI 模型 (MoveNet Lightning ONNX)
# ============================================================
MODEL_PATH = os.path.join(PROJECT_ROOT, "models", "face_detection_yunet.onnx")
PFLD_MODEL_PATH = os.path.join(PROJECT_ROOT, "models", "pfpld.onnx")
MODEL_INPUT_SIZE_W = 320          # YuNet 输入宽度
MODEL_INPUT_SIZE_H = 240          # YuNet 输入高度

# 人脸检测置信度阈值：低于此值视为不可靠，丢弃该帧
MIN_KEYPOINT_CONFIDENCE = 0.6

# ============================================================
# 无感自动校准
# ============================================================
CALIBRATION_DURATION_SEC = 5.0    # 启动后自动采集的秒数
CALIBRATION_MIN_SAMPLES = 10      # 最少有效样本数（不足则延长采集）
CALIBRATION_COVER_SEC = 2.0       # 遮挡镜头触发重校准的持续秒数
CALIBRATION_RECAL_FEEDBACK_SEC = 1.0  # 重校准完成后 LED 确认闪烁秒数

# ============================================================
# 无人休眠
# ============================================================
UNATTENDED_TIMEOUT_SEC = 20.0      # 连续无脸多久进入休眠状态
UNATTENDED_WAKE_SEC = 3.0          # 连续有脸多久从休眠唤醒
UNATTENDED_INFERENCE_INTERVAL = 1.0  # 休眠时推理间隔（秒），省 CPU

# ============================================================
# 双指标复合判定阈值
# ============================================================
EYE_DISTANCE_RATIO_THRESHOLD = 1.2    # 眼距放大超过基准 1.2 倍 → 前倾
HEIGHT_DROP_THRESHOLD_PX = 25.0       # 眼睛 Y 坐标下降超过此像素值 → 低头
ALERT_PERSIST_SEC = 5.0               # 异常状态持续 5 秒才触发报警（时间滤波）
ALERT_COOLDOWN_SEC = 3.0              # 报警后姿势恢复需稳定 3 秒才解除

# ============================================================
# GPIO 引脚定义 (gpiod)
# ============================================================
# TODO: 硬件连线确定后修改为实际引脚号
GPIO_CHIP = 0                     # gpiochip0
GPIO_BUZZER_LINE = 17            # 蜂鸣器信号线
GPIO_LED_RED_LINE = 27           # 红色 LED 信号线
GPIO_LED_GREEN_LINE = 22         # 绿色 LED 信号线（正常状态指示）

# ============================================================
# 蜂鸣器 PWM 参数
# ============================================================
BUZZER_FREQUENCY_HZ = 2400       # 蜂鸣器频率
BUZZER_DUTY_CYCLE = 0.5          # 占空比 50%
BUZZER_PATTERN_ON_SEC = 0.15     # 间歇鸣叫：响
BUZZER_PATTERN_OFF_SEC = 0.10    # 间歇鸣叫：停

# ============================================================
# FastAPI 本地服务
# ============================================================
API_HOST = "0.0.0.0"             # 监听所有网络接口，局域网可访问
API_PORT = 8000

# ============================================================
# Haar Cascade 级联文件路径（OpenCV 内置）
# ============================================================
# opencv-python-headless 的 XML 级联文件可能不在 Python 包目录，
# 而在系统路径 /usr/share/opencv4/haarcascades/
import cv2
_sys_haar = "/usr/share/opencv4/haarcascades"
HAARCASCADE_DIR = _sys_haar if os.path.isdir(_sys_haar) else cv2.data.haarcascades

# ============================================================
# 日志
# ============================================================
LOG_DIR = os.path.join(PROJECT_ROOT, "logs")
LOG_LEVEL = "INFO"
