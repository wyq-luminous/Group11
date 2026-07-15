#!/usr/bin/env python3
"""Real-time pose detection using MediaPipe Pose — 33 landmarks + FPS display."""

import cv2
import mediapipe as mp
import math
import time
import sys

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
CAMERA_INDEX = 0          # /dev/video0
FRAME_WIDTH = 1280
FRAME_HEIGHT = 720
MIN_DETECTION_CONF = 0.5
MIN_TRACKING_CONF = 0.5

# Drawing style
LANDMARK_RADIUS = 4
LANDMARK_COLOR = (0, 255, 0)       # green dots
CONNECTION_COLOR = (0, 255, 255)   # yellow lines
CONNECTION_THICKNESS = 2

# FPS display position
FPS_POS = (10, 35)
FPS_COLOR = (0, 255, 0)
FPS_FONT = cv2.FONT_HERSHEY_SIMPLEX
FPS_SCALE = 1.0
FPS_THICKNESS = 2


def calculate_angle(a, b, c):
    """Return the angle ∠ABC in degrees (0–180).

    a, b, c are each (x, y) tuples.  b is the vertex.
    Uses:  angle = arccos( (ba · bc) / (|ba| * |bc|) ) * 180 / π
    """
    ba = (a[0] - b[0], a[1] - b[1])
    bc = (c[0] - b[0], c[1] - b[1])

    dot = ba[0] * bc[0] + ba[1] * bc[1]
    mag_ba = math.hypot(ba[0], ba[1])
    mag_bc = math.hypot(bc[0], bc[1])

    if mag_ba < 1e-6 or mag_bc < 1e-6:
        return 0.0  # degenerate – two points coincide

    # Clamp to [-1, 1] to avoid domain errors from floating-point drift
    cos_angle = max(-1.0, min(1.0, dot / (mag_ba * mag_bc)))
    return math.degrees(math.acos(cos_angle))


def main():
    # -- 1. Initialise MediaPipe Pose ---------------------------------------
    mp_pose = mp.solutions.pose
    mp_drawing = mp.solutions.drawing_utils
    mp_drawing_styles = mp.solutions.drawing_styles

    pose = mp_pose.Pose(
        static_image_mode=False,
        model_complexity=1,                 # 0=Lite, 1=Full, 2=Heavy
        smooth_landmarks=True,
        min_detection_confidence=MIN_DETECTION_CONF,
        min_tracking_confidence=MIN_TRACKING_CONF,
    )

    # -- 2. Open camera -----------------------------------------------------
    cap = cv2.VideoCapture(CAMERA_INDEX)
    if not cap.isOpened():
        print(f"[ERROR] Cannot open camera index {CAMERA_INDEX}")
        sys.exit(1)

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, FRAME_WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_HEIGHT)

    actual_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    actual_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    print(f"Camera: {actual_w}x{actual_h}")
    print("Press 'q' to quit | Press 's' to save a screenshot")

    # FPS calculation
    prev_time = 0
    frame_count = 0
    fps = 0.0

    has_gui = _check_gui()
    print(f"GUI mode: {has_gui}")
    sys.stdout.flush()

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                print("[WARN] Empty frame, retrying...")
                time.sleep(0.01)
                continue

            # Mirror for natural selfie feel
            frame = cv2.flip(frame, 1)

            # -- 3. MediaPipe inference -------------------------------------
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            frame_rgb.flags.writeable = False
            results = pose.process(frame_rgb)
            frame_rgb.flags.writeable = True

            # -- 4. Draw landmarks & connections ----------------------------
            if results.pose_landmarks:
                # MediaPipe built-in drawing: 33 landmarks + 35 connections
                mp_drawing.draw_landmarks(
                    frame,
                    results.pose_landmarks,
                    mp_pose.POSE_CONNECTIONS,
                    landmark_drawing_spec=mp_drawing_styles.get_default_pose_landmarks_style(),
                )

            # -- 5. FPS -----------------------------------------------------
            now = time.time()
            frame_count += 1
            if now - prev_time >= 0.5:
                fps = frame_count / (now - prev_time)
                prev_time = now
                frame_count = 0

            cv2.putText(
                frame, f"FPS: {fps:.1f}", FPS_POS,
                FPS_FONT, FPS_SCALE, FPS_COLOR, FPS_THICKNESS,
            )

            # -- Elbow angles ------------------------------------------------
            left_angle = None
            right_angle = None

            if results.pose_landmarks:
                h, w = frame.shape[:2]
                lm = results.pose_landmarks.landmark

                # Left  elbow:  shoulder(11) – elbow(13) – wrist(15)
                if all(lm[i].visibility > 0.0 for i in (11, 13, 15)):
                    a_left = (lm[11].x * w, lm[11].y * h)
                    b_left = (lm[13].x * w, lm[13].y * h)
                    c_left = (lm[15].x * w, lm[15].y * h)
                    left_angle = calculate_angle(a_left, b_left, c_left)

                # Right elbow:  shoulder(12) – elbow(14) – wrist(16)
                if all(lm[i].visibility > 0.0 for i in (12, 14, 16)):
                    a_right = (lm[12].x * w, lm[12].y * h)
                    b_right = (lm[14].x * w, lm[14].y * h)
                    c_right = (lm[16].x * w, lm[16].y * h)
                    right_angle = calculate_angle(a_right, b_right, c_right)

                # Overlay on frame (left side, below FPS)
                y_off = 70
                if left_angle is not None:
                    cv2.putText(frame, f"L-Elbow: {left_angle:6.1f} deg",
                                (10, y_off), FPS_FONT, FPS_SCALE, (0, 255, 0), FPS_THICKNESS)
                    y_off += 35
                if right_angle is not None:
                    cv2.putText(frame, f"R-Elbow: {right_angle:6.1f} deg",
                                (10, y_off), FPS_FONT, FPS_SCALE, (0, 255, 0), FPS_THICKNESS)

            # -- Display -------------------------------------------------
            if has_gui:
                cv2.imshow("Pose Detection (q=quit)", frame)
                key = cv2.waitKey(1) & 0xFF
                if key == ord('q'):
                    break
                if key == ord('s'):
                    filename = f"screenshot_{time.strftime('%Y%m%d_%H%M%S')}.jpg"
                    cv2.imwrite(filename, frame)
                    print(f"Saved: {filename}")
            else:
                # headless fallback: print stats periodically
                if frame_count == 1:  # once per 0.5 s (first after fps update)
                    status = "POSE DETECTED" if results.pose_landmarks else "no pose"
                    parts = [f"[{fps:.1f} fps]", status]
                    if left_angle is not None:
                        parts.append(f"L={left_angle:.0f}")
                    if right_angle is not None:
                        parts.append(f"R={right_angle:.0f}")
                    msg = " | ".join(parts) + "     "
                    print(f"\r{msg}", end="", flush=True)

    except KeyboardInterrupt:
        pass
    finally:
        cap.release()
        pose.close()
        if has_gui:
            cv2.destroyAllWindows()
        print("\nDone.")


def _check_gui():
    """Return True if we can open GUI windows."""
    try:
        cv2.namedWindow("_test", cv2.WINDOW_AUTOSIZE)
        cv2.destroyWindow("_test")
        return True
    except cv2.error:
        return False


if __name__ == "__main__":
    main()
