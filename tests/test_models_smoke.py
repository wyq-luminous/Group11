"""
模型文件冒烟测试 (真实 ONNX, 无需摄像头/硬件)
==============================================
使用仓库内真实模型文件验证:
  - YuNet / PFLD 可被 OpenCV DNN 正常加载
  - 对合成图像推理不崩溃、输出结构正确
  - 空白图像 (无脸) → 正确返回"未检测到"

这层测试保证"模型文件损坏/格式不符/OpenCV 版本不兼容"
一类问题在部署到板子之前就能暴露。

注意: Windows 上 OpenCV 无法读取含非 ASCII 字符的路径,
因此先将模型复制到 pytest 临时目录 (纯 ASCII) 再加载。
板上项目路径为 ASCII, 无此问题。
"""

import os
import shutil

import numpy as np
import pytest

from config import MODEL_PATH, PFLD_MODEL_PATH

pytestmark = pytest.mark.skipif(
    not (os.path.exists(MODEL_PATH) and os.path.exists(PFLD_MODEL_PATH)),
    reason="模型文件缺失 (models/*.onnx)",
)


@pytest.fixture(scope="session")
def model_paths(tmp_path_factory):
    """复制模型到 ASCII 临时路径, 返回 (yunet_path, pfld_path)"""
    d = tmp_path_factory.mktemp("models")
    yunet = str(d / "face_detection_yunet.onnx")
    pfld = str(d / "pfpld.onnx")
    shutil.copyfile(MODEL_PATH, yunet)
    shutil.copyfile(PFLD_MODEL_PATH, pfld)
    return yunet, pfld


class TestYuNetModel:
    def test_model_file_size_sane(self):
        """YuNet 模型约 228KB; 明显偏小说明文件截断/损坏"""
        assert os.path.getsize(MODEL_PATH) > 100_000

    def test_engine_loads(self, model_paths):
        from main import YuNetEngine
        engine = YuNetEngine(model_paths[0])
        assert engine.detector is not None

    def test_blank_frame_no_face(self, model_paths):
        """纯灰图无脸 → (None, None, False), 不误检"""
        from main import YuNetEngine
        engine = YuNetEngine(model_paths[0])
        frame = np.full((360, 640, 3), 128, dtype=np.uint8)
        dist, eye_y, detected = engine.detect_eyes(frame)
        assert detected is False
        assert dist is None and eye_y is None

    def test_noise_frame_does_not_crash(self, model_paths):
        """随机噪声图 → 推理不崩溃 (结果无脸或低置信度均可接受)"""
        from main import YuNetEngine
        engine = YuNetEngine(model_paths[0])
        rng = np.random.default_rng(42)
        frame = rng.integers(0, 256, (360, 640, 3), dtype=np.uint8)
        engine.detect_eyes(frame)
        engine.detect_face_bbox(frame)

    def test_missing_model_raises(self, tmp_path):
        from main import YuNetEngine
        with pytest.raises(FileNotFoundError):
            YuNetEngine(str(tmp_path / "nonexistent.onnx"))


class TestPFLDModel:
    def test_model_file_size_sane(self):
        """PFLD 模型约 6.6MB"""
        assert os.path.getsize(PFLD_MODEL_PATH) > 1_000_000

    def test_landmarker_loads(self, model_paths):
        from landmarker import FaceLandmarker
        lmk = FaceLandmarker(model_paths[1])
        assert lmk.net is not None

    def test_inference_output_structure(self, model_paths):
        """
        对合成人脸区域推理: 输出必须是结构完整的 LandmarkResult。
        (合成图无真实人脸, 只验证输出协议, 不验证检测语义)
        """
        from landmarker import FaceLandmarker, LandmarkResult
        lmk = FaceLandmarker(model_paths[1])
        rng = np.random.default_rng(7)
        crop = rng.integers(0, 256, (160, 160, 3), dtype=np.uint8)
        result = lmk.detect(crop)
        assert isinstance(result, LandmarkResult)
        if result.face_detected:
            assert result.eye_distance >= 15.0     # MIN_EYE_DIST 门控生效
            assert -90.0 <= result.roll_deg <= 90.0
            assert result.yaw_ratio >= 0.0
            assert len(result.left_eye_pts) == 8
            assert len(result.right_eye_pts) == 8

    def test_tiny_crop_does_not_crash(self, model_paths):
        """极小裁剪图 (2x2) → 缩放到 112 后推理, 不崩溃"""
        from landmarker import FaceLandmarker
        lmk = FaceLandmarker(model_paths[1])
        crop = np.zeros((2, 2, 3), dtype=np.uint8)
        lmk.detect(crop)

    def test_missing_model_raises(self, tmp_path):
        from landmarker import FaceLandmarker
        with pytest.raises(FileNotFoundError):
            FaceLandmarker(str(tmp_path / "nonexistent.onnx"))
