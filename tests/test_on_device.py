"""
UNO-Q 板上集成测试 (需要真实硬件)
==============================================
运行方式 (在板子上):
    pytest tests/test_on_device.py -m device -v

覆盖:
  - USB 摄像头: 打开 / 采帧 / 分辨率 / 帧率
  - Bridge RPC: socket 存在性 + LED 点阵 / 蜂鸣器往返调用
  - PFLD 推理延迟基准 (目标 < 100ms/帧)
  - 端到端: 主服务 API 可达性 (需 main.py 已在运行)

默认 (无 -m device) 这些用例全部跳过, 保证 PC 上纯逻辑测试可独立运行。
"""

import os
import time

import numpy as np
import pytest

pytestmark = pytest.mark.device

BRIDGE_SOCK = "/var/run/arduino-router.sock"


# ============================================================
# USB 摄像头
# ============================================================
class TestCameraDevice:
    @pytest.fixture(scope="class")
    def cap(self):
        import cv2
        from main import _find_usb_camera
        from config import (CAMERA_FOURCC, CAMERA_WIDTH, CAMERA_HEIGHT,
                            CAMERA_FPS, CAMERA_BUFFERSIZE)
        idx = _find_usb_camera()
        if idx < 0:
            pytest.skip("未找到 USB 摄像头")
        cap = cv2.VideoCapture(idx)
        if not cap.isOpened():
            pytest.skip(f"/dev/video{idx} 打不开")
        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*CAMERA_FOURCC))
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAMERA_WIDTH)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAMERA_HEIGHT)
        cap.set(cv2.CAP_PROP_FPS, CAMERA_FPS)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, CAMERA_BUFFERSIZE)
        yield cap
        cap.release()

    def test_camera_reads_frame(self, cap):
        ret, frame = cap.read()
        assert ret, "摄像头读帧失败"
        assert frame is not None and frame.size > 0

    def test_frame_resolution(self, cap):
        from config import CAMERA_WIDTH, CAMERA_HEIGHT
        ret, frame = cap.read()
        assert ret
        h, w = frame.shape[:2]
        assert (w, h) == (CAMERA_WIDTH, CAMERA_HEIGHT), \
            f"实际分辨率 {w}x{h} 与配置 {CAMERA_WIDTH}x{CAMERA_HEIGHT} 不符"

    def test_sustained_capture_rate(self, cap):
        """连续采集 60 帧, 实测帧率应 >= 15fps (30fps 目标的容错下限)"""
        for _ in range(5):   # 预热, 排空缓冲
            cap.read()
        t0 = time.time()
        ok = 0
        for _ in range(60):
            ret, _ = cap.read()
            ok += int(ret)
        elapsed = time.time() - t0
        fps = ok / elapsed
        assert ok >= 55, f"60 帧中仅 {ok} 帧成功"
        assert fps >= 15.0, f"实测帧率 {fps:.1f}fps 过低"


# ============================================================
# Bridge RPC (STM32 MCU)
# ============================================================
class TestBridgeRPC:
    @pytest.fixture(autouse=True)
    def require_socket(self):
        if not os.path.exists(BRIDGE_SOCK):
            pytest.skip(f"Bridge socket 不存在: {BRIDGE_SOCK} "
                        "(检查 arduino-app-cli app start user:posture_alerter)")

    def test_clear_rpc_roundtrip(self):
        from alerter import _rpc_call
        result = _rpc_call("clear")
        assert result["ok"], f"clear RPC 失败: {result.get('error')}"

    def test_matrix_patterns(self):
        """依次显示 ok → warning → clear, 每个图案人工目视确认 1 秒"""
        from alerter import _rpc_call
        for method in ("ok", "warning", "clear"):
            result = _rpc_call(method)
            assert result["ok"], f"{method} RPC 失败: {result.get('error')}"
            time.sleep(1.0)

    def test_buzzer_beep(self):
        """蜂鸣器响 0.2s 后关闭 (人工听觉确认)"""
        from alerter import _rpc_call
        assert _rpc_call("buzzer_on")["ok"]
        time.sleep(0.2)
        result = _rpc_call("buzzer_off")
        assert result["ok"], "buzzer_off 失败 — 若蜂鸣器持续响请手动断电!"

    def test_rpc_latency(self):
        """单次 RPC 往返延迟 < 100ms (主循环 20Hz 的预算约束)"""
        from alerter import _rpc_call
        t0 = time.time()
        _rpc_call("clear")
        latency = time.time() - t0
        assert latency < 0.1, f"RPC 延迟 {latency*1000:.0f}ms 超预算"


# ============================================================
# 推理性能基准
# ============================================================
class TestInferenceLatency:
    def test_pfld_latency_budget(self):
        """PFLD 单帧推理平均延迟 < 100ms (板上 CPU)"""
        from config import PFLD_MODEL_PATH
        from landmarker import FaceLandmarker
        lmk = FaceLandmarker(PFLD_MODEL_PATH)
        crop = np.full((160, 160, 3), 128, dtype=np.uint8)
        lmk.detect(crop)  # 预热
        t0 = time.time()
        n = 20
        for _ in range(n):
            lmk.detect(crop)
        avg = (time.time() - t0) / n
        assert avg < 0.1, f"PFLD 平均 {avg*1000:.1f}ms/帧, 超出 100ms 预算"

    def test_yunet_latency_budget(self):
        """YuNet 单帧检测平均延迟 < 100ms"""
        from config import MODEL_PATH
        from main import YuNetEngine
        engine = YuNetEngine(MODEL_PATH)
        frame = np.full((360, 640, 3), 128, dtype=np.uint8)
        engine.detect_eyes(frame)  # 预热
        t0 = time.time()
        n = 20
        for _ in range(n):
            engine.detect_eyes(frame)
        avg = (time.time() - t0) / n
        assert avg < 0.1, f"YuNet 平均 {avg*1000:.1f}ms/帧"


# ============================================================
# 端到端 API (需 main.py 已在运行, 如 systemd 服务)
# ============================================================
class TestLiveAPI:
    BASE = "http://127.0.0.1:8000"

    @pytest.fixture(autouse=True)
    def require_service(self):
        import requests
        try:
            requests.get(f"{self.BASE}/api/v1/health", timeout=2)
        except requests.ConnectionError:
            pytest.skip("主服务未运行 (systemctl start smartposture-guardian)")

    def test_health(self):
        import requests
        r = requests.get(f"{self.BASE}/api/v1/health", timeout=2)
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}

    def test_status_schema(self):
        import requests
        body = requests.get(f"{self.BASE}/api/v1/status", timeout=2).json()
        for key in ("is_calibrated", "D_normal", "Y_normal",
                    "is_alerting", "state", "posture_state"):
            assert key in body
        assert body["state"] == "running"

    def test_calibration_injection_roundtrip(self):
        """注入基准值 → status 立即反映 (注意: 会覆盖当前校准, 测试后需重校准)"""
        import requests
        r = requests.post(f"{self.BASE}/api/v1/calibration",
                          json={"user_D_normal": 62.5, "user_Y_normal": 180.0},
                          timeout=2)
        assert r.json()["status"] == "ok"
        body = requests.get(f"{self.BASE}/api/v1/status", timeout=2).json()
        assert body["D_normal"] == 62.5
        assert body["is_calibrated"] is True

    def test_calibration_rejects_zero(self):
        import requests
        r = requests.post(f"{self.BASE}/api/v1/calibration",
                          json={"user_D_normal": 0, "user_Y_normal": 0},
                          timeout=2)
        assert r.json()["status"] == "error"

    def test_stream_endpoint_serves_mjpeg(self):
        import requests
        r = requests.get(f"{self.BASE}/stream", timeout=3, stream=True)
        assert r.status_code == 200
        assert "multipart/x-mixed-replace" in r.headers["content-type"]
        r.close()
