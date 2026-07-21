"""
FastAPI 接口边界条件测试
==============================================
使用 fastapi.testclient (无需真实网络/设备) 测试:
  - POST /api/v1/calibration: 基准值必须严格 > 0
  - GET  /api/v1/status: 状态一致性
  - GET  /api/v1/health
"""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def app_client():
    from main import SharedState, _create_fastapi_app
    state = SharedState()
    app = _create_fastapi_app(state)
    return state, TestClient(app)


# ============================================================
# POST /api/v1/calibration
# ============================================================
class TestCalibrationEndpoint:
    URL = "/api/v1/calibration"

    def test_valid_values_accepted(self, app_client):
        state, client = app_client
        r = client.post(self.URL, json={"user_D_normal": 62.5, "user_Y_normal": 180.0})
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert body["D_normal"] == 62.5
        assert body["Y_normal"] == 180.0
        # 注入立即生效
        d, y, calibrated = state.get_baseline()
        assert (d, y, calibrated) == (62.5, 180.0, True)

    def test_zero_d_normal_rejected(self, app_client):
        """边界: D_normal == 0 → 拒绝 (严格 > 0)"""
        state, client = app_client
        r = client.post(self.URL, json={"user_D_normal": 0, "user_Y_normal": 180.0})
        assert r.json()["status"] == "error"
        assert state.is_calibrated is False

    def test_zero_y_normal_rejected(self, app_client):
        """边界: Y_normal == 0 → 拒绝"""
        state, client = app_client
        r = client.post(self.URL, json={"user_D_normal": 62.5, "user_Y_normal": 0})
        assert r.json()["status"] == "error"
        assert state.is_calibrated is False

    def test_negative_values_rejected(self, app_client):
        state, client = app_client
        r = client.post(self.URL, json={"user_D_normal": -62.5, "user_Y_normal": -180.0})
        assert r.json()["status"] == "error"
        assert state.is_calibrated is False

    def test_smallest_positive_value_accepted(self, app_client):
        """边界: 极小正数 (1e-9) 仍 > 0 → 当前实现接受。
        若未来加入合理范围校验 (如 10~300px), 此用例需更新。"""
        state, client = app_client
        r = client.post(self.URL, json={"user_D_normal": 1e-9, "user_Y_normal": 1e-9})
        assert r.json()["status"] == "ok"
        assert state.is_calibrated is True

    def test_missing_field_returns_422(self, app_client):
        """缺少必填字段 → pydantic 422 校验错误"""
        _, client = app_client
        r = client.post(self.URL, json={"user_D_normal": 62.5})
        assert r.status_code == 422

    def test_non_numeric_returns_422(self, app_client):
        """非数值类型 → 422"""
        _, client = app_client
        r = client.post(self.URL, json={"user_D_normal": "abc", "user_Y_normal": 180.0})
        assert r.status_code == 422

    def test_empty_body_returns_422(self, app_client):
        _, client = app_client
        r = client.post(self.URL, json={})
        assert r.status_code == 422

    def test_numeric_string_coerced_by_pydantic(self, app_client):
        """pydantic 宽松模式: 数字字符串 "62.5" 会被转为 float 接受"""
        state, client = app_client
        r = client.post(self.URL, json={"user_D_normal": "62.5", "user_Y_normal": "180"})
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    def test_reinjection_overrides_previous(self, app_client):
        """重复注入 → 后者覆盖前者 (用户换人/换座场景)"""
        state, client = app_client
        client.post(self.URL, json={"user_D_normal": 60.0, "user_Y_normal": 170.0})
        client.post(self.URL, json={"user_D_normal": 80.0, "user_Y_normal": 190.0})
        d, y, _ = state.get_baseline()
        assert (d, y) == (80.0, 190.0)


# ============================================================
# GET /api/v1/status
# ============================================================
class TestStatusEndpoint:
    URL = "/api/v1/status"

    def test_initial_status_uncalibrated(self, app_client):
        _, client = app_client
        body = client.get(self.URL).json()
        assert body["is_calibrated"] is False
        assert body["D_normal"] is None
        assert body["Y_normal"] is None
        assert body["is_alerting"] is False
        assert body["state"] == "running"
        assert body["posture_state"] == "CALIBRATING"

    def test_status_reflects_baseline_injection(self, app_client):
        state, client = app_client
        state.set_baseline(62.5, 180.0)
        body = client.get(self.URL).json()
        assert body["is_calibrated"] is True
        assert body["D_normal"] == 62.5
        assert body["Y_normal"] == 180.0

    def test_status_reflects_alerting_flag(self, app_client):
        state, client = app_client
        state.set_alerting(True)
        assert client.get(self.URL).json()["is_alerting"] is True
        state.set_alerting(False)
        assert client.get(self.URL).json()["is_alerting"] is False

    def test_status_reflects_stopped_state(self, app_client):
        state, client = app_client
        state.stop()
        assert client.get(self.URL).json()["state"] == "stopped"

    def test_status_reflects_posture_state(self, app_client):
        state, client = app_client
        state.posture_state = "UNATTENDED"
        assert client.get(self.URL).json()["posture_state"] == "UNATTENDED"


# ============================================================
# GET /api/v1/health
# ============================================================
class TestHealthEndpoint:
    def test_health_ok(self, app_client):
        _, client = app_client
        r = client.get("/api/v1/health")
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}


# ============================================================
# GET /viewer
# ============================================================
class TestViewerPage:
    def test_viewer_returns_html(self, app_client):
        _, client = app_client
        r = client.get("/viewer")
        assert r.status_code == 200
        assert "text/html" in r.headers["content-type"]
        assert "/stream" in r.text  # 页面内嵌 MJPEG 流地址
