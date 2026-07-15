#!/usr/bin/env python3
"""Tkinter GUI for real-time elbow angle measurement — Workshop 5.

Stability & performance fixes:
- Forces camera to MJPG format to minimise USB 2.0 bandwidth (camera shares the
  same root hub as the Ethernet adapter; uncompressed YUYV would starve SSH).
- Inference runs in a background thread; tkinter is touched ONLY from the main
  thread (status updates go through a queue).
- Old PhotoImage references are explicitly deleted to avoid memory accumulation.
- Camera read failures trigger automatic reconnection instead of a crash.
"""

import cv2
import mediapipe as mp
import math
import os
import time
import threading
import queue
import tkinter as tk
from tkinter import ttk
from PIL import Image, ImageTk

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
# Camera discovery: we scan /dev/video* devices at startup AND periodically
# during runtime.  On the UNO-Q the SoC exposes two Qualcomm Venus codec
# devices (/dev/video0 = encoder, /dev/video1 = decoder) — those are NOT
# cameras and must be skipped.  Only devices whose V4L2 name does NOT contain
# "venus", "qcom", or "codec" are considered real cameras.
#
# When no camera is found the GUI still launches (so the user can see the
# status and connect a camera later); a background thread rescans every 5 s.
CAMERA_INDEX = None              # None = auto-detect; set to int for fixed index
CAMERA_RESCAN_INTERVAL = 5.0     # seconds between hotplug rescans
VALID_CAMERA_BLACKLIST = (       # case-insensitive substrings that mean "skip"
    "venus", "qcom", "codec", "decoder", "encoder",
)

# Capture at the smallest *native* MJPG resolution so the camera's onboard
# compressor kicks in (YUYV @ high res would flood the USB bus).
CAPTURE_WIDTH = 640
CAPTURE_HEIGHT = 360

# Downscale before inference — MediaPipe Lite on ARM is the bottleneck, not
# the camera.  A smaller frame means faster pixel-ops and less memory churn.
INFER_WIDTH = 320
INFER_HEIGHT = 240

MIN_DETECTION_CONF = 0.5
MIN_TRACKING_CONF = 0.5
VISIBILITY_THRESHOLD = 0.5       # below this → treat as occluded / hallucinated
PRESENCE_THRESHOLD = 0.5         # is the landmark in the frame at all?

GUI_WIDTH = 1200
GUI_HEIGHT = 700
RIGHT_PANEL_WIDTH = 350

ANGLE_FONT_SIZE = 64
LABEL_FONT_SIZE = 14

GUI_POLL_MS = 33          # ~30 fps GUI refresh
STATUS_QUEUE_SIZE = 20    # more than enough for status messages


# ---------------------------------------------------------------------------
# Body-only landmarks (exclude face indices 0-10)
# ---------------------------------------------------------------------------
# MediaPipe Pose has 33 landmarks.  0-10 = face (nose, eyes, ears, mouth).
# We only draw the body: shoulders → wrists, hips → ankles.
FACE_INDICES = frozenset(range(0, 11))   # 0–10 inclusive

# Pre-filter POSE_CONNECTIONS: keep only connections where BOTH ends are
# body landmarks.  Created once at import time.
def _build_body_connections(all_connections):
    """Return [(start, end), …] for connections that don't involve face."""
    body = []
    for a, b in all_connections:
        if a not in FACE_INDICES and b not in FACE_INDICES:
            body.append((a, b))
    return body


# ---------------------------------------------------------------------------
# Camera discovery helpers (module-level so the reconnect thread can use them)
# ---------------------------------------------------------------------------
def _get_v4l2_name(dev_path):
    """Read the V4L2 device name from sysfs.  Returns '' on failure."""
    try:
        name_path = os.path.join("/sys/class/video4linux",
                                 os.path.basename(dev_path), "name")
        with open(name_path) as fh:
            return fh.read().strip()
    except Exception:
        return ""


def _is_real_camera(idx):
    """Return True if /dev/video<idx> looks like a real camera.

    Opens the device via V4L2 to read the driver/card name and rejects
    devices whose name contains blacklisted substrings (codecs, etc.).
    """
    dev = f"/dev/video{idx}"
    if not os.path.exists(dev):
        return False
    name = _get_v4l2_name(dev).lower()
    if name:
        for bad in VALID_CAMERA_BLACKLIST:
            if bad in name:
                return False
    # Final sanity: try to open via OpenCV
    cap = cv2.VideoCapture(idx)
    if cap.isOpened():
        cap.release()
        return True
    return False


def find_camera_index():
    """Return the first real-camera index, or None if none found.

    Scans indices 0–15, skipping Qualcomm codec / Venus devices.
    When CAMERA_INDEX is explicitly set (not None) just verify that index.
    """
    if CAMERA_INDEX is not None:
        if _is_real_camera(CAMERA_INDEX):
            return CAMERA_INDEX
        return None

    for idx in range(16):
        if _is_real_camera(idx):
            return idx
    return None


# ---------------------------------------------------------------------------
# Angle helper
# ---------------------------------------------------------------------------
def calculate_angle(a, b, c):
    """Return ∠ABC in degrees (0–180).  b is the vertex."""
    ba = (a[0] - b[0], a[1] - b[1])
    bc = (c[0] - b[0], c[1] - b[1])
    dot = ba[0] * bc[0] + ba[1] * bc[1]
    mag_ba = math.hypot(*ba)
    mag_bc = math.hypot(*bc)
    if mag_ba < 1e-6 or mag_bc < 1e-6:
        return 0.0
    cos_angle = max(-1.0, min(1.0, dot / (mag_ba * mag_bc)))
    return math.degrees(math.acos(cos_angle))


_debug_last_log = 0.0   # timestamp of last debug print
_debug_frame_count = 0
_debug_has_pose = False
_debug_lm = None        # latest landmarks for detailed dump


def _debug_tick():
    """Print detection summary + landmark details once every 2 seconds."""
    global _debug_last_log, _debug_frame_count
    _debug_frame_count += 1
    now = time.time()
    if now - _debug_last_log < 2.0:
        return
    _debug_last_log = now
    fps = _debug_frame_count / 2.0
    print(f"[DEBUG] {fps:.0f} fps | pose={'YES' if _debug_has_pose else 'NO'}",
          flush=True)
    if _debug_has_pose and _debug_lm is not None:
        for side, indices in [("L", (11, 13, 15)), ("R", (12, 14, 16))]:
            vals = []
            for idx in indices:
                v = _debug_lm[idx].visibility
                p = _debug_lm[idx].presence
                vals.append(f"{idx}:v={v:.2f}/p={p:.2f}")
            dist = math.hypot(
                _debug_lm[indices[0]].x - _debug_lm[indices[2]].x,
                _debug_lm[indices[0]].y - _debug_lm[indices[2]].y)
            reliable = _arm_is_reliable(_debug_lm, *indices)
            print(f"  {side} | {' | '.join(vals)} | dist={dist:.4f} | ok={reliable}",
                  flush=True)
    _debug_frame_count = 0


def _arm_is_reliable(lm, shoulder_idx, elbow_idx, wrist_idx):
    """Return True if arm landmarks pass tiered visibility checks
    AND the three points are not degenerate.

    Wrists naturally have lower visibility than shoulders (smaller, faster).
    We use a relaxed threshold for wrists to avoid dropping real detections,
    while keeping shoulders/elbows strict to filter hallucinated limbs.

    NOTE: presence is intentionally NOT checked — MediaPipe Lite on ARM
    always reports presence=0.0 even for clearly-visible landmarks.
    """
    # Tiered visibility: shoulders & elbows must be well-visible;
    # wrists get a relaxed bar (they're smaller / move faster)
    if lm[shoulder_idx].visibility < 0.5:
        return False
    if lm[elbow_idx].visibility < 0.5:
        return False
    if lm[wrist_idx].visibility < 0.3:
        return False

    # Geometric sanity: shoulder–wrist distance must be non-trivial.
    # When the model hallucinates a limb, all three points cluster at
    # nearly the same location.
    sx, sy = lm[shoulder_idx].x, lm[shoulder_idx].y
    wx, wy = lm[wrist_idx].x, lm[wrist_idx].y
    if math.hypot(sx - wx, sy - wy) < 0.05:
        return False

    return True


def _draw_body_skeleton(frame, pose_landmarks, body_connections,
                        mp_drawing_styles):
    """Draw only the body skeleton (exclude face landmarks 0-10).

    Uses the same colour / thickness as MediaPipe's default style, but
    skips face landmarks so only the body skeleton is visible.
    """
    h, w = frame.shape[:2]

    # Collect which landmark indices are "body" (appear in body_connections)
    body_indices = set()
    for a, b in body_connections:
        body_indices.add(a)
        body_indices.add(b)

    # get_default_pose_landmarks_style() returns a dict[PoseLandmark, DrawingSpec]
    style_map = mp_drawing_styles.get_default_pose_landmarks_style()

    # ── Draw connections (lines between body landmarks) ──────────────────
    for start_idx, end_idx in body_connections:
        start_lm = pose_landmarks.landmark[start_idx]
        end_lm = pose_landmarks.landmark[end_idx]
        if start_lm.visibility < 0.5 or end_lm.visibility < 0.5:
            continue

        # Pick the connection colour from the *start* landmark's spec
        spec = style_map.get(start_idx)
        if spec is None:
            continue
        color = spec.color  # (B, G, R) tuple
        thickness = spec.thickness

        x1, y1 = int(start_lm.x * w), int(start_lm.y * h)
        x2, y2 = int(end_lm.x * w), int(end_lm.y * h)
        cv2.line(frame, (x1, y1), (x2, y2), color, thickness)

    # ── Draw landmark dots (body only — no face) ─────────────────────────
    for idx in sorted(body_indices):
        lm_i = pose_landmarks.landmark[idx]
        if lm_i.visibility < 0.5:
            continue
        spec = style_map.get(idx)
        if spec is None:
            continue
        cx, cy = int(lm_i.x * w), int(lm_i.y * h)
        cv2.circle(frame, (cx, cy),
                   spec.circle_radius, spec.color, spec.thickness)


# ---------------------------------------------------------------------------
# GUI Application
# ---------------------------------------------------------------------------
class AngleMeasurementApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Joint Angle Measurement - Workshop 5")
        self.root.geometry(f"{GUI_WIDTH}x{GUI_HEIGHT}")
        self.root.configure(bg="#1e1e1e")
        self.root.minsize(900, 550)

        # ---- State ----------------------------------------------------------
        self.running = False
        self.cap = None
        self._cam_index = None
        self.pose = None
        self._after_id = None

        # Tkinter image reference — hold ONE at a time, explicitly delete old
        self._tk_image = None

        self.left_angle = None
        self.right_angle = None
        self.fps = 0.0
        self._fps_time = time.time()
        self._fps_count = 0

        # Threading
        self._inference_thread = None
        self._capture_thread = None
        self._frame_queue = queue.Queue(maxsize=1)     # always keep latest frame
        self._status_queue = queue.Queue(maxsize=STATUS_QUEUE_SIZE)

        # Capture-thread state: always holds the freshest raw frame from camera.
        # The capture thread reads at camera rate (30 fps) so the V4L2 buffer
        # never accumulates stale frames.  Inference grabs a copy at its own
        # pace (~5 fps on ARM).
        self._raw_frame = None          # latest raw cv2 frame (BGR, mirrored)
        self._raw_lock = threading.Lock()

        # Latest inference result for async overlay
        self._latest_infer_frame = None  # inference-scale frame with skeleton drawn
        self._latest_left_angle = None
        self._latest_right_angle = None

        self._build_ui()
        self._init_mediapipe()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # Auto-start: begin scanning for camera as soon as the GUI paints
        self.root.after(500, self._on_start)

    # ========================================================================
    # UI
    # ========================================================================
    def _build_ui(self):
        # Main horizontal split with grid for proper resizing
        self.root.grid_rowconfigure(0, weight=1)
        self.root.grid_columnconfigure(0, weight=1)

        main = tk.Frame(self.root, bg="#1e1e1e")
        main.grid(row=0, column=0, sticky="nsew", padx=8, pady=(8, 2))
        main.grid_rowconfigure(0, weight=1)
        main.grid_columnconfigure(0, weight=1)    # camera  – expands
        main.grid_columnconfigure(1, weight=0)    # panel   – fixed width

        # ---- Left: camera feed ----------------------------------------------
        self.camera_label = tk.Label(
            main, bg="#000000",
            text="Press [Start] to open camera",
            fg="#555555", font=("Helvetica", 16),
        )
        self.camera_label.grid(row=0, column=0, sticky="nsew", padx=(0, 8))

        # ---- Right: angle panel ---------------------------------------------
        right = tk.Frame(main, bg="#2d2d2d", width=RIGHT_PANEL_WIDTH)
        right.grid(row=0, column=1, sticky="ns")
        right.grid_propagate(False)
        right.grid_rowconfigure(10, weight=1)

        r = 0
        tk.Label(right, text="Elbow Angle",
                 font=("Helvetica", 18, "bold"),
                 fg="#ffffff", bg="#2d2d2d").grid(row=r, column=0, pady=(20, 25), padx=20)
        r += 1

        tk.Label(right, text="Left (L-Elbow)",
                 font=("Helvetica", LABEL_FONT_SIZE),
                 fg="#aaaaaa", bg="#2d2d2d").grid(row=r, column=0)
        r += 1

        self.lbl_left = tk.Label(right, text="--.-", font=("Consolas", ANGLE_FONT_SIZE, "bold"),
                                 fg="#00ff88", bg="#2d2d2d")
        self.lbl_left.grid(row=r, column=0, pady=(0, 20))
        r += 1

        tk.Label(right, text="Right (R-Elbow)",
                 font=("Helvetica", LABEL_FONT_SIZE),
                 fg="#aaaaaa", bg="#2d2d2d").grid(row=r, column=0)
        r += 1

        self.lbl_right = tk.Label(right, text="--.-", font=("Consolas", ANGLE_FONT_SIZE, "bold"),
                                  fg="#00ff88", bg="#2d2d2d")
        self.lbl_right.grid(row=r, column=0, pady=(0, 20))
        r += 1

        ttk.Separator(right, orient=tk.HORIZONTAL).grid(
            row=r, column=0, sticky="ew", padx=25, pady=8)
        r += 1

        tk.Label(right, text="FPS",
                 font=("Helvetica", LABEL_FONT_SIZE),
                 fg="#aaaaaa", bg="#2d2d2d").grid(row=r, column=0)
        r += 1

        self.lbl_fps = tk.Label(right, text="0.0", font=("Consolas", 24, "bold"),
                                fg="#ffcc00", bg="#2d2d2d")
        self.lbl_fps.grid(row=r, column=0, pady=(0, 20))
        r += 1

        # Inference latency indicator
        tk.Label(right, text="Inference",
                 font=("Helvetica", LABEL_FONT_SIZE),
                 fg="#aaaaaa", bg="#2d2d2d").grid(row=r, column=0)
        r += 1

        self.lbl_infer = tk.Label(right, text="0 ms", font=("Consolas", 14),
                                  fg="#888888", bg="#2d2d2d")
        self.lbl_infer.grid(row=r, column=0, pady=(0, 15))
        r += 1

        # Chart placeholder
        chart = tk.Frame(right, bg="#3a3a3a", height=120)
        chart.grid(row=r, column=0, sticky="ew", padx=15, pady=(5, 5))
        chart.grid_propagate(False)
        tk.Label(chart, text="Angle curve (coming soon)",
                 font=("Helvetica", 12), fg="#666666", bg="#3a3a3a").pack(expand=True)

        # ---- Bottom: button bar ---------------------------------------------
        btn_frame = tk.Frame(self.root, bg="#1e1e1e")
        btn_frame.grid(row=1, column=0, sticky="ew", padx=8, pady=(2, 8))

        self.btn_start = tk.Button(
            btn_frame, text="Start", font=("Helvetica", 14, "bold"),
            bg="#28a745", fg="#ffffff", width=16, height=2, border=0,
            command=self._on_start,
        )
        self.btn_start.pack(side=tk.LEFT, padx=(0, 8))

        self.btn_pause = tk.Button(
            btn_frame, text="Pause", font=("Helvetica", 14, "bold"),
            bg="#ffc107", fg="#1e1e1e", width=16, height=2, border=0,
            state=tk.DISABLED, command=self._on_pause,
        )
        self.btn_pause.pack(side=tk.LEFT, padx=(0, 8))

        self.btn_screenshot = tk.Button(
            btn_frame, text="Screenshot", font=("Helvetica", 14, "bold"),
            bg="#17a2b8", fg="#ffffff", width=16, height=2, border=0,
            command=self._on_screenshot,
        )
        self.btn_screenshot.pack(side=tk.LEFT)

        self.status_var = tk.StringVar(value="Ready")
        tk.Label(self.root, textvariable=self.status_var,
                 font=("Helvetica", 10), fg="#888888", bg="#1e1e1e",
                 anchor=tk.W).grid(row=2, column=0, sticky="ew", padx=15, pady=(0, 5))

    # ========================================================================
    # Core
    # ========================================================================
    def _init_mediapipe(self):
        self.mp_pose = mp.solutions.pose
        self.mp_drawing = mp.solutions.drawing_utils
        self.mp_drawing_styles = mp.solutions.drawing_styles
        self.pose = self.mp_pose.Pose(
            static_image_mode=False,
            model_complexity=0,                  # 0 = Lite (much faster on ARM)
            smooth_landmarks=True,
            min_detection_confidence=MIN_DETECTION_CONF,
            min_tracking_confidence=MIN_TRACKING_CONF,
        )
        # Build body-only connection list (skip face landmarks 0-10)
        self._body_connections = _build_body_connections(
            self.mp_pose.POSE_CONNECTIONS)
        self._set_status("MediaPipe model loaded (Lite)")

    def _open_camera(self):
        """Open camera with explicit MJPG codec to keep USB bandwidth low.

        Uses find_camera_index() to skip Qualcomm codec devices.
        Returns (cap, actual_index) tuple or (None, None).
        """
        idx = find_camera_index()
        if idx is None:
            self._set_status("[Error] No USB camera found — plug one in & press Start")
            return None, None

        cap = cv2.VideoCapture(idx)
        if not cap.isOpened():
            self._set_status(f"[Error] /dev/video{idx} found but cannot open")
            return None, None

        # ── CRITICAL: force MJPG ────────────────────────────────────────
        # The camera and Ethernet dongle share the same USB 2.0 root hub.
        # YUYV (uncompressed) @ 640×360×30 fps ≈ 13.8 MB/s.
        # MJPG (compressed)   @ 640×360×30 fps ≈  2-3 MB/s.
        # Without this, SSH drops because the camera starves the network.
        mjpg = cv2.VideoWriter_fourcc(*"MJPG")
        cap.set(cv2.CAP_PROP_FOURCC, mjpg)

        cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAPTURE_WIDTH)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAPTURE_HEIGHT)
        cap.set(cv2.CAP_PROP_FPS, 30)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)     # keep latency low

        # Verify what we actually got
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        actual_fps = cap.get(cv2.CAP_PROP_FPS)
        fmt = int(cap.get(cv2.CAP_PROP_FOURCC))
        fmt_str = "".join(chr((fmt >> (8 * i)) & 0xFF) for i in range(4))

        # Warn if MJPG was rejected (camera fell back to YUYV)
        if fmt_str.strip() != "MJPG":
            self._set_status(
                f"Camera {idx}: {w}×{h} {fmt_str} (MJPG rejected! USB may be slow)")

        self._set_status(f"Camera {idx}: {w}×{h} {fmt_str} @ {actual_fps:.0f}fps — Ready")
        print(f"[INFO] Opened /dev/video{idx}: {w}×{h} {fmt_str} @ {actual_fps:.0f}fps")
        return cap, idx

    def _reopen_camera(self):
        """Attempt to re-open the camera after a read failure."""
        if self.cap is not None:
            try:
                self.cap.release()
            except Exception:
                pass
            self.cap = None
            self._cam_index = None
        time.sleep(0.5)
        self.cap, self._cam_index = self._open_camera()
        return self.cap is not None

    # ========================================================================
    # Thread-safe status updates
    # ========================================================================
    def _set_status(self, msg):
        """Callable from ANY thread — pushes to the status queue."""
        try:
            self._status_queue.put_nowait(msg)
        except queue.Full:
            pass  # drop stale status messages

    def _drain_status(self):
        """Called on the MAIN thread — apply pending status updates."""
        while True:
            try:
                msg = self._status_queue.get_nowait()
                self.status_var.set(msg)
            except queue.Empty:
                break

    # ========================================================================
    # Background capture thread — runs at camera rate, always keeps latest frame
    # ========================================================================
    def _capture_loop(self):
        """Runs in a daemon thread: reads frames as fast as the camera produces them.

        This is the KEY to low latency.  MediaPipe inference takes ~187 ms on
        ARM, but the camera produces a new frame every 33 ms (30 fps).  If we
        read + infer in a single thread the V4L2 buffer fills up with stale
        frames during inference, and the next read() returns the *oldest* one —
        adding ~150 ms of unnecessary lag.

        By reading continuously in a dedicated thread we always keep the
        *freshest* frame in ``_raw_frame``.  The inference thread grabs a copy
        at its own pace without ever touching the camera.
        """
        consecutive_failures = 0
        last_camera_scan = 0.0

        while self.running:
            # ── Hotplug: periodically rescan for camera ──────────────────
            if self.cap is None:
                now = time.time()
                if now - last_camera_scan > CAMERA_RESCAN_INTERVAL:
                    last_camera_scan = now
                    self._set_status("Scanning for camera...")
                    self.cap, self._cam_index = self._open_camera()
                    if self.cap is not None:
                        self._set_status(f"Camera connected! /dev/video{self._cam_index}")
                        consecutive_failures = 0
                time.sleep(0.5)
                continue

            # ── Read one frame (blocks ~33 ms @ 30 fps) ─────────────────
            ret, frame = self.cap.read()
            if not ret or frame is None:
                consecutive_failures += 1
                if consecutive_failures > 30:
                    self._set_status("[Error] Camera read failed — reconnecting...")
                    if not self._reopen_camera():
                        self._set_status("[Error] Camera lost — will keep scanning")
                        consecutive_failures = 0
                        last_camera_scan = 0
                time.sleep(0.01)
                continue
            consecutive_failures = 0

            # Mirror for natural selfie feel, then store as latest
            frame = cv2.flip(frame, 1)
            with self._raw_lock:
                self._raw_frame = frame

    # ========================================================================
    # Background inference thread — runs MediaPipe at its own pace
    # ========================================================================
    def _inference_loop(self):
        """Runs in a daemon thread: grabs latest frame → inference → push to queue.

        Does NOT touch the camera — frames come from the capture thread's
        ``_raw_frame`` (protected by ``_raw_lock``).  This way inference
        always works on the freshest frame the capture thread has read,
        not a stale frame from the V4L2 buffer.
        """
        global _debug_has_pose, _debug_lm
        self._set_status("Warming up inference (first frame is slow)...")
        infer_times = []   # rolling window for latency display
        last_raw = None    # skip if same frame as last cycle (capture is slower than inference)

        while self.running:
            # ── Grab latest frame from capture thread ────────────────────
            with self._raw_lock:
                raw = self._raw_frame
            if raw is None:
                time.sleep(0.005)
                continue
            if raw is last_raw:
                # Capture thread hasn't produced a new frame yet — brief
                # sleep to avoid busy-waiting at full CPU speed
                time.sleep(0.002)
                continue
            last_raw = raw

            # Downscale for inference
            infer_frame = cv2.resize(raw, (INFER_WIDTH, INFER_HEIGHT),
                                     interpolation=cv2.INTER_NEAREST)

            # ── Pose inference (the heavy part) ─────────────────────────
            t0 = time.time()
            rgb = cv2.cvtColor(infer_frame, cv2.COLOR_BGR2RGB)
            rgb.flags.writeable = False
            results = self.pose.process(rgb)
            rgb.flags.writeable = True
            infer_ms = (time.time() - t0) * 1000

            # Rolling average of last 10 inference times
            infer_times.append(infer_ms)
            if len(infer_times) > 10:
                infer_times.pop(0)
            self._last_infer_ms = sum(infer_times) / len(infer_times)

            # ── Angles ──────────────────────────────────────────────────
            h_i, w_i = infer_frame.shape[:2]
            left_angle = None
            right_angle = None

            # ── DEBUG: log detection status once per second ────────
            _debug_tick()

            if results.pose_landmarks:
                lm = results.pose_landmarks.landmark

                # ── Draw body-only skeleton (skip face landmarks 0-10) ──
                _draw_body_skeleton(
                    infer_frame, results.pose_landmarks,
                    self._body_connections, self.mp_drawing_styles,
                )

                _debug_has_pose = True
                _debug_lm = lm

                # ── Elbow angles ─────────────────────────────────────────
                # Left elbow:  shoulder(11) – elbow(13) – wrist(15)
                if _arm_is_reliable(lm, 11, 13, 15):
                    a = (lm[11].x * w_i, lm[11].y * h_i)
                    b = (lm[13].x * w_i, lm[13].y * h_i)
                    c = (lm[15].x * w_i, lm[15].y * h_i)
                    left_angle = calculate_angle(a, b, c)

                # Right elbow: shoulder(12) – elbow(14) – wrist(16)
                if _arm_is_reliable(lm, 12, 14, 16):
                    a = (lm[12].x * w_i, lm[12].y * h_i)
                    b = (lm[14].x * w_i, lm[14].y * h_i)
                    c = (lm[16].x * w_i, lm[16].y * h_i)
                    right_angle = calculate_angle(a, b, c)
            else:
                _debug_has_pose = False
                # No pose detected — show raw frame without overlay
                infer_frame = cv2.resize(raw, (INFER_WIDTH, INFER_HEIGHT),
                                         interpolation=cv2.INTER_NEAREST)

            # Push to GUI queue (drop old frame if GUI can't keep up)
            payload = (infer_frame, left_angle, right_angle)
            try:
                self._frame_queue.put_nowait(payload)
            except queue.Full:
                try:
                    self._frame_queue.get_nowait()
                except queue.Empty:
                    pass
                try:
                    self._frame_queue.put_nowait(payload)
                except queue.Full:
                    pass

    # ========================================================================
    # GUI poll  – called periodically by tkinter on the MAIN thread
    # ========================================================================
    def _poll_gui(self):
        """Check for new frames and status messages; update the GUI.

        Priority: inference result (with skeleton overlay) > raw capture frame.
        This keeps the video smooth at camera rate even when inference
        only runs at ~5 fps.
        """
        if not self.running:
            return

        # Drain pending status updates
        self._drain_status()

        # FPS (display-side counter — count every GUI poll, not just
        # inference frames, so the user sees the true display rate)
        self._fps_count += 1
        now = time.time()
        if now - self._fps_time >= 1.0:
            self.fps = self._fps_count / (now - self._fps_time)
            self._fps_time = now
            self._fps_count = 0

        try:
            frame, left_angle, right_angle = self._frame_queue.get_nowait()
            self.left_angle = left_angle
            self.right_angle = right_angle
            self._update_gui(frame)
        except queue.Empty:
            # No inference result ready — show raw capture frame for
            # smooth video (don't update angle labels, keep last known)
            with self._raw_lock:
                raw = self._raw_frame
            if raw is not None:
                # Downscale raw frame to inference size for consistent display
                raw_small = cv2.resize(raw, (INFER_WIDTH, INFER_HEIGHT),
                                       interpolation=cv2.INTER_NEAREST)
                self._update_gui(raw_small)

        self._after_id = self.root.after(GUI_POLL_MS, self._poll_gui)

    def _update_gui(self, cv_frame):
        """Resize frame to fill the Label, convert to ImageTk, update angles.

        Optimisations:
        - Label dimensions are cached (only re-read when the label is first
          shown or resized by the user).
        - The display canvas is pre-allocated and reused.
        """
        lbl_w = self.camera_label.winfo_width()
        lbl_h = self.camera_label.winfo_height()

        if lbl_w > 10 and lbl_h > 10:
            # Only recalculate scale + re-allocate canvas when size changes
            cached = getattr(self, "_last_lbl_size", None)
            if cached != (lbl_w, lbl_h):
                self._last_lbl_size = (lbl_w, lbl_h)
                h, w = cv_frame.shape[:2]
                scale = min(lbl_w / w, lbl_h / h)
                self._disp_w = int(w * scale)
                self._disp_h = int(h * scale)
                self._disp_x_off = (lbl_w - self._disp_w) // 2
                self._disp_y_off = (lbl_h - self._disp_h) // 2
                # Pre-allocate black canvas (reused every frame)
                self._canvas = Image.new("RGB", (lbl_w, lbl_h), color=(0, 0, 0))

            # Resize to display size; INTER_LINEAR is only marginally slower
            # than INTER_NEAREST but looks much better when upscaling
            resized = cv2.resize(cv_frame, (self._disp_w, self._disp_h),
                                 interpolation=cv2.INTER_NEAREST)

            # Reuse canvas (avoid allocating a new Image every frame)
            img = Image.fromarray(cv2.cvtColor(resized, cv2.COLOR_BGR2RGB))
            self._canvas.paste(img, (self._disp_x_off, self._disp_y_off))
            canvas = self._canvas
        else:
            # Label not yet laid out — use frame as-is
            canvas = Image.fromarray(cv2.cvtColor(cv_frame, cv2.COLOR_BGR2RGB))

        # ── Replace PhotoImage, explicitly deleting the old one ──────────
        new_tk_image = ImageTk.PhotoImage(canvas)
        old = self._tk_image
        self._tk_image = new_tk_image
        self.camera_label.configure(image=new_tk_image, text="")
        # Delete old reference AFTER configure to avoid flicker
        if old is not None:
            del old

        # ── Angle labels with colour coding ──────────────────────────────
        if self.left_angle is not None:
            self.lbl_left.configure(text=f"{self.left_angle:.1f}°",
                                    fg=self._angle_color(self.left_angle))
        else:
            self.lbl_left.configure(text="--.-°", fg="#555555")

        if self.right_angle is not None:
            self.lbl_right.configure(text=f"{self.right_angle:.1f}°",
                                     fg=self._angle_color(self.right_angle))
        else:
            self.lbl_right.configure(text="--.-°", fg="#555555")

        self.lbl_fps.configure(text=f"{self.fps:.1f}")

        # Inference latency
        ms = getattr(self, "_last_infer_ms", 0)
        self.lbl_infer.configure(
            text=f"{ms:.0f} ms",
            fg="#00ff88" if ms < 200 else "#ffcc00" if ms < 500 else "#ff4444")

    @staticmethod
    def _angle_color(angle):
        diff = abs(angle - 90.0)
        if diff < 30:
            return "#00ff88"       # green – healthy range
        elif diff < 60:
            return "#ffcc00"       # yellow – warning
        else:
            return "#ff4444"       # red – extreme

    # ========================================================================
    # Button actions
    # ========================================================================
    def _on_start(self):
        if self.running:
            return
        if self.cap is None:
            self.cap, self._cam_index = self._open_camera()
            # Even if no camera yet, enter "running" so the inference
            # loop keeps scanning for hotplug events.

        self.running = True
        self._fps_time = time.time()
        self._fps_count = 0
        self.btn_start.configure(state=tk.DISABLED)
        self.btn_pause.configure(state=tk.NORMAL)

        # Start capture thread first (reads frames at camera rate)
        self._capture_thread = threading.Thread(
            target=self._capture_loop, daemon=True
        )
        self._capture_thread.start()

        # Start inference thread (grabs frames from capture thread)
        self._inference_thread = threading.Thread(
            target=self._inference_loop, daemon=True
        )
        self._inference_thread.start()

        # Start GUI poll loop
        self._after_id = self.root.after(GUI_POLL_MS, self._poll_gui)

    def _on_pause(self):
        if not self.running:
            return
        self.running = False
        if self._after_id is not None:
            self.root.after_cancel(self._after_id)
            self._after_id = None
        self.btn_start.configure(state=tk.NORMAL)
        self.btn_pause.configure(state=tk.DISABLED)
        self._set_status("Paused")

    def _on_screenshot(self):
        if self._tk_image is None:
            self._set_status("No frame to capture")
            return
        filename = f"screenshot_{time.strftime('%Y%m%d_%H%M%S')}.png"
        try:
            img = ImageTk.getimage(self._tk_image)
            img.save(filename, "PNG")
            self._set_status(f"Saved: {filename}")
        except Exception as e:
            self._set_status(f"Screenshot failed: {e}")

    def _on_close(self):
        self.running = False
        if self._after_id is not None:
            self.root.after_cancel(self._after_id)
        # Brief wait for threads to notice self.running = False
        for t in (self._capture_thread, self._inference_thread):
            if t is not None and t.is_alive():
                t.join(timeout=1.0)
        if self.cap is not None:
            self.cap.release()
            self.cap = None
        if self.pose is not None:
            self.pose.close()
            self.pose = None
        self.root.destroy()


def main():
    root = tk.Tk()
    _app = AngleMeasurementApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
