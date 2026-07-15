"""
慧姿·智能坐姿守护系统 — 报警输出模块
==============================================
通过 Arduino Router Bridge (Unix Socket + MsgPack RPC)
控制板载资源:
  - 8×13 蓝色 LED 点阵 → 显示三角感叹号 ⚠️
  - RGB LED1 → 绿(正常) / 红(报警)

通信协议:
  Linux MPU ──msgpack──▶ /var/run/arduino-router.sock ──▶ STM32 MCU ──▶ LED Matrix
"""

import socket
import time
import logging

logger = logging.getLogger("guardian.alerter")

# Bridge socket 路径
BRIDGE_SOCK = "/var/run/arduino-router.sock"

# 矩阵尺寸 (UNO-Q 板载)
MATRIX_COLS = 13
MATRIX_ROWS = 8
MATRIX_PIXELS = MATRIX_COLS * MATRIX_ROWS  # 104

# RGB LED 路径 (Linux sysfs)
LED1_R = "/sys/class/leds/unoq:user-red1/brightness"
LED1_G = "/sys/class/leds/unoq:user-green1/brightness"
LED1_B = "/sys/class/leds/unoq:user-blue1/brightness"


# ============================================================
# 三角感叹号图案 (8×13 = 104 像素)
# ============================================================
# 等边三角形包裹感叹号
# ● = 亮 (255)   ○ = 灭 (0)
#
#    0 1 2 3 4 5 6 7 8 9 0 1 2
#   ┌─────────────────────────┐
# 0 │ ○ ○ ○ ○ ○ ○ ● ○ ○ ○ ○ ○ ○ │ 三角顶点
# 1 │ ○ ○ ○ ○ ○ ● ○ ● ○ ○ ○ ○ ○ │
# 2 │ ○ ○ ○ ○ ● ○ ○ ○ ● ○ ○ ○ ○ │
# 3 │ ○ ○ ○ ○ ● ○ ● ○ ● ○ ○ ○ ○ │ 感叹号竖线(嵌入三角)
# 4 │ ○ ○ ○ ● ○ ○ ● ○ ○ ● ○ ○ ○ │
# 5 │ ○ ○ ○ ● ○ ○ ● ○ ○ ● ○ ○ ○ │ 感叹号继续
# 6 │ ○ ○ ● ● ● ● ● ● ● ● ● ○ ○ │ 三角底边
# 7 │ ○ ○ ○ ○ ○ ○ ● ○ ○ ○ ○ ○ ○ │ 感叹号圆点
#   └─────────────────────────┘

_WARNING_PATTERN = bytearray([
    # Row 0
    0,0,0,0,0,0,255,0,0,0,0,0,0,
    # Row 1
    0,0,0,0,0,255,0,255,0,0,0,0,0,
    # Row 2
    0,0,0,0,255,0,0,0,255,0,0,0,0,
    # Row 3
    0,0,0,0,255,0,255,0,255,0,0,0,0,
    # Row 4
    0,0,0,255,0,0,255,0,0,255,0,0,0,
    # Row 5
    0,0,0,255,0,0,255,0,0,255,0,0,0,
    # Row 6
    0,0,255,255,255,255,255,255,255,255,255,0,0,
    # Row 7
    0,0,0,0,0,0,255,0,0,0,0,0,0,
])

# 正常状态图案: 对勾 ✓ 或简单的笑脸/圆点
_OK_PATTERN = bytearray([
    0,0,0,0,0,0,0,0,0,0,0,0,0,
    0,0,0,0,0,0,0,0,0,0,0,0,255,
    0,0,0,0,0,0,0,0,0,0,0,255,0,
    0,0,255,0,0,0,0,0,0,0,255,0,0,
    0,0,0,255,0,0,0,0,0,255,0,0,0,
    0,0,0,0,255,0,0,0,255,0,0,0,0,
    0,0,0,0,0,255,0,255,0,0,0,0,0,
    0,0,0,0,0,0,255,0,0,0,0,0,0,
])


# ============================================================
# Bridge 通信
# ============================================================

def _rpc_call(method: str, params: list | None = None, timeout: float = 3.0) -> dict:
    """
    通过 Unix Socket 向 STM32 MCU 发送 MsgPack RPC 调用。
    返回 MCU 的响应字典。
    """
    import msgpack

    req = [0, 1, method, params or []]
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(timeout)
        s.connect(BRIDGE_SOCK)
        s.sendall(msgpack.packb(req))

        data = s.recv(4096)
        s.close()

        if data:
            return {"ok": True, "response": msgpack.unpackb(data)}
        return {"ok": True, "response": None}
    except socket.timeout:
        return {"ok": False, "error": "Bridge timeout — MCU sketch 是否在运行?"}
    except FileNotFoundError:
        return {"ok": False, "error": f"Bridge socket 不存在: {BRIDGE_SOCK}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _sysfs_write(path: str, value: str) -> bool:
    """写入 sysfs LED 控制文件"""
    try:
        with open(path, "w") as f:
            f.write(str(value))
        return True
    except Exception:
        return False


# ============================================================
# Alerter 类
# ============================================================

class Alerter:
    """
    报警输出控制器。
    正常状态: 🟢 绿灯 + 点阵显示 ✓
    报警状态: 🔴 红灯 + 点阵显示 ⚠️ (三角感叹号) + 蜂鸣器间歇鸣叫
    """

    def __init__(self):
        self._is_alerting = False
        self._buzzer_on = False
        self._last_buzzer_toggle = 0.0
        self._buzzer_pattern = (0.15, 0.10)  # (on_sec, off_sec)

        # 蜂鸣器通过 MCU Bridge RPC 控制 (STM32 D2, LOW 触发)
        self._buzzer_rpc = True  # 使用 bridge RPC

        # ---- 清空矩阵，亮绿灯 ----
        self.clear()

    def _write_buzzer(self, on: bool):
        """控制蜂鸣器 (通过 STM32 Bridge RPC)"""
        if on:
            _rpc_call("buzzer_on")
        else:
            _rpc_call("buzzer_off")

    def _write_matrix(self, method: str):
        """调用 MCU RPC 显示预定图案"""
        result = _rpc_call(method)
        if not result.get("ok"):
            logger.debug(f"LED matrix RPC 失败 ({method}): {result.get('error', 'unknown')}")

    def _clear_matrix(self):
        """清空 LED 点阵"""
        _rpc_call("clear")

    def _set_rgb(self, r: int, g: int, b: int):
        """设置板载 RGB LED1"""
        _sysfs_write(LED1_R, str(r))
        _sysfs_write(LED1_G, str(g))
        _sysfs_write(LED1_B, str(b))

    # ---- 公开接口 (main.py 调用) ----

    def show_normal(self):
        """正常坐姿: 绿灯 + 点阵 ✓"""
        self._set_rgb(0, 1, 0)       # 绿灯亮
        self._write_matrix("ok")  # 对勾图案
        self._write_buzzer(False)
        self._is_alerting = False

    def show_warning(self):
        """
        报警: 红色 LED + 三角感叹号 ⚠️ + 蜂鸣器间歇鸣叫
        主循环定期调用此方法，蜂鸣器自动间歇切换。
        """
        self._set_rgb(1, 0, 0)           # 红灯亮
        self._write_matrix("warning")  # 三角感叹号
        self._is_alerting = True

        # 间歇蜂鸣
        now = time.time()
        on_time, off_time = self._buzzer_pattern
        threshold = on_time if self._buzzer_on else off_time

        if now - self._last_buzzer_toggle >= threshold:
            self._buzzer_on = not self._buzzer_on
            self._last_buzzer_toggle = now

        self._write_buzzer(self._buzzer_on)

    def clear(self):
        """清空所有输出 (蜂鸣器停 + 矩阵灭 + 绿灯)"""
        self._set_rgb(0, 1, 0)
        self._clear_matrix()
        self._write_buzzer(False)
        self._buzzer_on = False
        self._is_alerting = False

    def cleanup(self):
        """释放资源"""
        self.clear()
        logger.info("Alerter 资源已释放")
