"""
PFLD ONNX 模型 Benchmark + 关键点索引确认
============================================
独立脚本，不依赖项目其他模块。

验证:
  1. 模型输入/输出 shape
  2. 68 个关键点的分布（确认眼睛、鼻尖的索引）
  3. 推理速度 (100 帧)
"""
import sys
import os
import time
import numpy as np
import cv2

# 添加 src 目录到 path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import onnxruntime as ort

MODEL_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "models", "pfpld.onnx"
)

def main():
    print("=" * 60)
    print("PFLD ONNX Benchmark & Landmark Index Check")
    print("=" * 60)

    # ---- 1. 加载模型 ----
    print(f"\n[1] 加载模型: {MODEL_PATH}")
    session = ort.InferenceSession(MODEL_PATH)

    input_info = session.get_inputs()[0]
    print(f"  输入: name={input_info.name}, shape={input_info.shape}")
    for out in session.get_outputs():
        print(f"  输出: name={out.name}, shape={out.shape}")

    # ---- 2. 打开摄像头拍一张 ----
    print("\n[2] 打开摄像头...")
    # 自动查找 USB 摄像头 (跳过 Venus 编解码器)
    camera_idx = 2  # 通常是 /dev/video2
    for idx in [2, 3, 0, 1]:
        cap = cv2.VideoCapture(idx)
        if cap.isOpened():
            camera_idx = idx
            break
        cap.release()
    else:
        print("  ❌ 无法打开任何摄像头")
        return
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 360)
    # 丢弃前几帧（曝光调整）
    for _ in range(10):
        cap.read()
    ret, frame = cap.read()
    cap.release()

    if not ret:
        print("  ❌ 无法读取帧")
        return
    print(f"  帧尺寸: {frame.shape}")

    # ---- 3. 模拟人脸裁剪（画面中央 200×200） ----
    h, w = frame.shape[:2]
    margin = 20
    cx, cy = w // 2, h // 2
    crop_size = min(w, h) // 2
    x1 = max(0, cx - crop_size - margin)
    y1 = max(0, cy - crop_size - margin)
    x2 = min(w, cx + crop_size + margin)
    y2 = min(h, cy + crop_size + margin)
    face_crop = frame[y1:y2, x1:x2]

    if face_crop.size == 0:
        print("  ❌ 裁剪区域无效")
        return
    print(f"  人脸裁剪: ({x1},{y1}) → ({x2},{y2}), size={face_crop.shape}")

    # ---- 4. 预处理 ----
    H_TARGET, W_TARGET = 112, 112
    blob = cv2.resize(face_crop, (W_TARGET, H_TARGET))
    blob = cv2.cvtColor(blob, cv2.COLOR_BGR2RGB)
    blob = blob.astype(np.float32) / 255.0
    blob = blob.transpose(2, 0, 1)[np.newaxis, ...]  # [1, 3, 112, 112]
    print(f"  输入 blob shape: {blob.shape}, dtype: {blob.dtype}")

    # ---- 5. 推理 & 解析输出 ----
    print("\n[3] 推理:")
    input_name = session.get_inputs()[0].name
    results = session.run(None, {input_name: blob})

    # 输出 1: head pose (yaw, pitch, roll) in degrees or radians
    pose = results[0][0]  # [3]
    print(f"  Head Pose (raw): yaw={pose[0]:.1f}, pitch={pose[1]:.1f}, roll={pose[2]:.1f}")

    # 输出 2: landmarks [1, 196] → N × 2 坐标
    landms_raw = results[1][0]  # [196]
    n_landmarks = len(landms_raw) // 2
    landmarks = landms_raw.reshape(n_landmarks, 2)  # [N, 2]
    print(f"  Landmarks: {n_landmarks} 个点 ({len(landms_raw)} 个值)")
    print(f"  坐标范围: X=[{landmarks[:,0].min():.3f}, {landmarks[:,0].max():.3f}], "
          f"Y=[{landmarks[:,1].min():.3f}, {landmarks[:,1].max():.3f}]")

    # 坐标归一化 → 映射到裁剪图像素
    landmarks_px = landmarks.copy()
    landmarks_px[:, 0] *= face_crop.shape[1]
    landmarks_px[:, 1] *= face_crop.shape[0]

    # ---- 打印全部关键点分组 ----
    print(f"\n[4] 全部 {n_landmarks} 个关键点坐标 (像素):")
    pts_per_row = 10
    for i in range(0, n_landmarks, pts_per_row):
        row_pts = []
        for j in range(i, min(i + pts_per_row, n_landmarks)):
            x, y = landmarks_px[j]
            row_pts.append(f"{j:3d}:({x:5.0f},{y:5.0f})")
        print(f"  {'  '.join(row_pts)}")

    # ---- 找到眼睛和鼻尖的关键点 ----
    # 对于 98 点 WFLW 格式:
    #   60-67: 左眼 (8 点轮廓)
    #   68-75: 右眼 (8 点轮廓)
    #   54:    鼻尖
    # 对于 68 点 iBUG 格式:
    #   36-41: 左眼 (6 点)
    #   42-47: 右眼 (6 点)
    #   30 或 33: 鼻尖
    #
    # 我们通过 Y 坐标聚类来定位眼睛区域:
    # 最高(最小 Y)的两组点通常是眼睛和眉毛

    print(f"\n[5] 坐标分析:")
    # 找 Y 坐标最靠上的点 (脸的上半部分)
    sorted_by_y = np.argsort(landmarks_px[:, 1])  # 从小到大 (从上到下)
    top_indices = sorted_by_y[:20]  # 最靠上的 20 个点
    print(f"  最靠上的 20 个点 (按 Y 升序):")
    for idx in top_indices:
        x, y = landmarks_px[idx]
        print(f"    [{idx:3d}] ({x:5.0f}, {y:5.0f})")

    # ---- 额外: 眼睛中心与鼻尖 ----
    # 假设是 98 点 WFLW: 左眼=60-67, 右眼=68-75, 鼻尖=54
    # 假设是 68 点 iBUG: 左眼=36-41, 右眼=42-47, 鼻尖=33
    if n_landmarks == 98:
        LEFT_EYE = (60, 68)
        RIGHT_EYE = (68, 76)
        NOSE_TIP = 54
    elif n_landmarks == 68:
        LEFT_EYE = (36, 42)
        RIGHT_EYE = (42, 48)
        NOSE_TIP = 33
    else:
        # 根据坐标位置猜测
        LEFT_EYE = (36, 42)
        RIGHT_EYE = (42, 48)
        NOSE_TIP = 33
        print(f"\n  ⚠️  未知点数 {n_landmarks}，使用 iBUG 68 默认索引，请手动验证!")

    left_eye_center = landmarks_px[LEFT_EYE[0]:LEFT_EYE[1]].mean(axis=0)
    right_eye_center = landmarks_px[RIGHT_EYE[0]:RIGHT_EYE[1]].mean(axis=0)
    nose_tip = landmarks_px[NOSE_TIP]
    eye_dist = np.linalg.norm(right_eye_center - left_eye_center)
    roll_rad = np.arctan2(
        right_eye_center[1] - left_eye_center[1],
        right_eye_center[0] - left_eye_center[0]
    )
    roll_deg = np.degrees(roll_rad)
    # 侧脸: 鼻尖到两眼中心中点的水平偏移比
    eye_mid_x = (left_eye_center[0] + right_eye_center[0]) / 2
    yaw_ratio = abs(nose_tip[0] - eye_mid_x) / eye_dist if eye_dist > 0 else 0

    print(f"\n{'='*60}")
    print(f"[6] 派生指标 (使用索引: 左眼{LEFT_EYE}, 右眼{RIGHT_EYE}, 鼻尖{NOSE_TIP}):")
    print(f"  左眼中心: ({left_eye_center[0]:.1f}, {left_eye_center[1]:.1f})")
    print(f"  右眼中心: ({right_eye_center[0]:.1f}, {right_eye_center[1]:.1f})")
    print(f"  鼻尖:     ({nose_tip[0]:.1f}, {nose_tip[1]:.1f})")
    print(f"  眼距:     {eye_dist:.1f} px")
    print(f"  歪头角(计算):  {roll_deg:.1f}°")
    print(f"  歪头角(模型):  {pose[2]:.1f}°  ← 模型直接输出的 roll")
    print(f"  侧脸比:   {yaw_ratio:.3f} (<0.2=正面, >0.35=侧脸)")
    print(f"  模型 yaw: {pose[0]:.1f}°  模型 pitch: {pose[1]:.1f}°")

    # ---- 6. Benchmark: 100 帧 ----
    print(f"\n[7] Benchmark: 预热 20 次...")
    for _ in range(20):
        session.run(None, {input_name: blob})

    print("  计时 100 次推理...")
    t0 = time.perf_counter()
    for _ in range(100):
        session.run(None, {input_name: blob})
    elapsed = time.perf_counter() - t0

    fps = 100 / elapsed
    ms_per_frame = elapsed / 100 * 1000
    print(f"  100 帧: {elapsed:.2f}s → {fps:.0f} FPS → {ms_per_frame:.1f} ms/帧")
    print(f"\n{'='*60}")
    print("✅ Benchmark 完成")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
