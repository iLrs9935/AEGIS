# core/hal.py
import ctypes
import time
from ctypes import wintypes


# --- [底层黑魔法 1]: 硬件级 ScanCode 穿透 ---
# C struct 定义 (完全对齐 Windows C++ API)
class KEYBDINPUT(ctypes.Structure):
    _fields_ = (
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", wintypes.ULONG),
    )


class INPUT(ctypes.Structure):
    class _INPUT(ctypes.Union):
        _fields_ = (
            ("ki", KEYBDINPUT),
            ("mi", ctypes.c_byte * 28),  # 占位 MouseInput
            ("hi", ctypes.c_byte * 32),
        )  # 占位 HardwareInput

    _anonymous_ = ("_input",)
    _fields_ = (("type", wintypes.DWORD), ("_input", _INPUT))


# Windows 常量
INPUT_KEYBOARD = 1
KEYEVENTF_SCANCODE = 0x0008
KEYEVENTF_KEYUP = 0x0002


# --- [底层黑魔法 2]: 自动降级截图路由 ---
class VisionCapture:
    """不挑游戏的万能截图引擎"""

    @classmethod
    def capture(cls) -> bool:
        """
        伪代码演示降级逻辑。
        真实业务中这里会返回 numpy array 供 OpenCV 使用。
        """
        from core.event_bus import bus

        # 尝试 1: WGC (Windows Graphics Capture) - 后台无感，Win10+
        if cls._try_wgc():
            bus.log_emitted.emit("INFO", "HAL", "📸 截图成功 (WGC 模式)")
            return True

        # 尝试 2: DXGI (DirectX 捕获) - 极速，适合全屏 3D 游戏
        if cls._try_dxgi():
            bus.log_emitted.emit("INFO", "HAL", "📸 截图成功 (DXGI 模式)")
            return True

        # 尝试 3: BitBlt (经典 GDI) - 兼容性最强底线
        if cls._try_bitblt():
            bus.log_emitted.emit("WARN", "HAL", "📸 截图成功 (BitBlt 降级模式)")
            return True

        bus.log_emitted.emit(
            "ERROR", "HAL", "❌ 所有截图通道均失败 (可能遭遇强黑屏保护)"
        )
        return False

    @staticmethod
    def _try_wgc() -> bool:
        # 这里预留 WinRT / winsdk 的调用逻辑
        return False  # 模拟 WGC 失败

    @staticmethod
    def _try_dxgi() -> bool:
        # 这里预留 d3dshot / DXGI 的调用逻辑
        return False  # 模拟 DXGI 失败

    @staticmethod
    def _try_bitblt() -> bool:
        # 这里预留 mss / win32gui 的调用逻辑
        return True  # 模拟 GDI 成功
