"""Windows keyboard input backend used by the keyboard action node.

This module keeps all key-down/key-up handling paired and uses the real Win32
INPUT layout on both 32-bit and 64-bit Python.  It deliberately exposes small
helpers so the behavior can be tested without injecting real keyboard input.
"""

import ctypes
import threading
from ctypes import wintypes

import win32api
import win32clipboard
import win32con
import win32gui

from core.event_bus import bus


# ctypes.wintypes does not expose ULONG_PTR, while WPARAM has the same width.
ULONG_PTR = wintypes.WPARAM


class MouseInput(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class KeyBdInput(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class HardwareInput(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class InputUnion(ctypes.Union):
    _fields_ = [
        ("mi", MouseInput),
        ("ki", KeyBdInput),
        ("hi", HardwareInput),
    ]


class Input(ctypes.Structure):
    _anonymous_ = ("value",)
    _fields_ = [("type", wintypes.DWORD), ("value", InputUnion)]


INPUT_KEYBOARD = 1
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_SCANCODE = 0x0008
MAPVK_VK_TO_VSC = 0
MAPVK_VK_TO_VSC_EX = 4

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_send_input_api = _user32.SendInput
_send_input_api.argtypes = (wintypes.UINT, ctypes.POINTER(Input), ctypes.c_int)
_send_input_api.restype = wintypes.UINT
_map_virtual_key_api = _user32.MapVirtualKeyW
_map_virtual_key_api.argtypes = (wintypes.UINT, wintypes.UINT)
_map_virtual_key_api.restype = wintypes.UINT

# This is shared with the older action backend, so the UI's emergency stop also
# interrupts a long key hold or a string currently being typed.
try:
    from functions.func_actions import hold_lock, stop_event
except ImportError:
    stop_event = threading.Event()
    hold_lock = threading.Lock()


KEY_MAP = {
    "BACKSPACE": 0x08,
    "TAB": 0x09,
    "ENTER": 0x0D,
    "SHIFT": 0x10,
    "CTRL": 0x11,
    "ALT": 0x12,
    "PAUSE": 0x13,
    "CAPSLOCK": 0x14,
    "ESC": 0x1B,
    "SPACE": 0x20,
    "PAGEUP": 0x21,
    "PAGEDOWN": 0x22,
    "END": 0x23,
    "HOME": 0x24,
    "LEFT": 0x25,
    "UP": 0x26,
    "RIGHT": 0x27,
    "DOWN": 0x28,
    "PRINTSCREEN": 0x2C,
    "INSERT": 0x2D,
    "DELETE": 0x2E,
    "WIN": 0x5B,
}
KEY_MAP.update({chr(code): code for code in range(ord("A"), ord("Z") + 1)})
KEY_MAP.update({chr(code): code for code in range(ord("0"), ord("9") + 1)})
KEY_MAP.update({f"F{number}": 0x6F + number for number in range(1, 25)})

KEY_ALIASES = {
    "RETURN": "ENTER",
    "ESCAPE": "ESC",
    "CONTROL": "CTRL",
    "MENU": "ALT",
    "WINDOWS": "WIN",
    "BACK": "BACKSPACE",
    "DEL": "DELETE",
    "INS": "INSERT",
    "PGUP": "PAGEUP",
    "PGDN": "PAGEDOWN",
    "ARROWUP": "UP",
    "ARROWDOWN": "DOWN",
    "ARROWLEFT": "LEFT",
    "ARROWRIGHT": "RIGHT",
}

MODIFIER_VKS = {0x10, 0x11, 0x12, 0x5B, 0x5C}
EXTENDED_VKS = {
    0x21,  # PAGEUP
    0x22,  # PAGEDOWN
    0x23,  # END
    0x24,  # HOME
    0x25,  # LEFT
    0x26,  # UP
    0x27,  # RIGHT
    0x28,  # DOWN
    0x2C,  # PRINTSCREEN
    0x2D,  # INSERT
    0x2E,  # DELETE
    0x5B,  # LWIN
    0x5C,  # RWIN
    0x6F,  # NUMPAD DIVIDE
    0x90,  # NUMLOCK
}


def _log(message, level="INFO"):
    bus.log_emitted.emit(level, "KeyboardHAL", message)


def resolve_key_code(key_name: str) -> int:
    """Resolve a human-readable key name to a Windows virtual-key code."""
    normalized = str(key_name).strip().upper()
    normalized = KEY_ALIASES.get(normalized, normalized)
    vk_code = KEY_MAP.get(normalized)
    if vk_code is not None:
        return vk_code

    if len(normalized) == 1:
        mapped = win32api.VkKeyScan(normalized)
        if mapped != -1:
            return mapped & 0xFF

    raise ValueError(f"无法识别的按键: {key_name}")


def _vk_to_scan_code(vk_code: int):
    """Return ``(scan_code, is_extended)`` for a virtual-key code."""
    mapped = int(_map_virtual_key_api(vk_code, MAPVK_VK_TO_VSC_EX))
    if not mapped:
        mapped = int(_map_virtual_key_api(vk_code, MAPVK_VK_TO_VSC))
    if not mapped:
        raise ValueError(f"虚拟键码无法转换为扫描码: {vk_code}")

    prefix = mapped & 0xFF00
    is_extended = prefix in (0xE000, 0xE100) or vk_code in EXTENDED_VKS
    return mapped & 0xFF, is_extended


def _build_input(vk_code: int, key_up: bool = False) -> Input:
    """Build one INPUT value without sending it; useful for validation/tests."""
    scan_code, is_extended = _vk_to_scan_code(vk_code)
    flags = KEYEVENTF_SCANCODE
    if is_extended:
        flags |= KEYEVENTF_EXTENDEDKEY
    if key_up:
        flags |= KEYEVENTF_KEYUP

    event = Input(type=INPUT_KEYBOARD)
    event.ki = KeyBdInput(0, scan_code, flags, 0, 0)
    return event


def _send_vk_event(vk_code: int, key_up: bool = False):
    event = _build_input(vk_code, key_up)
    sent = _send_input_api(1, ctypes.byref(event), ctypes.sizeof(Input))
    if sent != 1:
        error_code = ctypes.get_last_error()
        raise OSError(error_code, f"SendInput 发送失败 (WinError {error_code})")


def _execute_key_chord(
    vk_code: int,
    modifiers=(),
    duration: float = 0.05,
    name: str = "DAG_Key",
):
    """Press a chord and always release it in reverse order."""
    if stop_event.is_set():
        return False

    pressed = []
    interrupted = False
    try:
        for modifier in modifiers:
            _send_vk_event(modifier)
            pressed.append(modifier)

        _send_vk_event(vk_code)
        pressed.append(vk_code)
        interrupted = stop_event.wait(timeout=max(0.0, float(duration)))
        return not interrupted
    except Exception as error:
        _log(f"[{name}] 键盘输入失败: {error}", "ERROR")
        return False
    finally:
        for pressed_vk in reversed(pressed):
            try:
                _send_vk_event(pressed_vk, key_up=True)
            except Exception as release_error:
                _log(f"[{name}] 释放按键失败: {release_error}", "ERROR")


def execute_hardware_key(vk_code: int, duration: float = 0.05, name="DAG_Key"):
    """Send one key through Win32 SendInput using its hardware scan code."""
    _log(f"准备敲击按键 [VK: {vk_code}]，按压 {duration}s")
    success = _execute_key_chord(vk_code, duration=duration, name=name)
    if success:
        _log(f"[{name}] 按键执行成功", "SUCCESS")
    return success


def execute_key_spec(key_spec: str, duration: float = 0.05, name="DAG_Key"):
    """Execute a key or a chord such as ``CTRL+SHIFT+S``."""
    parts = [part.strip() for part in str(key_spec).split("+") if part.strip()]
    if not parts:
        _log(f"[{name}] 按键名称为空", "ERROR")
        return False

    try:
        key_codes = [resolve_key_code(part) for part in parts]
    except ValueError as error:
        _log(f"[{name}] {error}", "ERROR")
        return False

    if len(key_codes) == 1:
        return execute_hardware_key(key_codes[0], duration, name)

    modifiers = key_codes[:-1]
    if any(vk not in MODIFIER_VKS for vk in modifiers):
        _log(f"[{name}] 组合键中除最后一项外只能使用 Ctrl/Shift/Alt/Win", "ERROR")
        return False

    _log(f"准备敲击组合键 [{key_spec}]，按压 {duration}s")
    success = _execute_key_chord(key_codes[-1], modifiers, duration, name)
    if success:
        _log(f"[{name}] 组合键执行成功", "SUCCESS")
    return success


def _resolve_post_message_hwnd(hwnd):
    """Validate a window handle and prefer its top-level owner window."""
    try:
        target_hwnd = int(hwnd)
    except (TypeError, ValueError):
        raise ValueError("后台键盘输入需要有效的目标窗口句柄")

    if not target_hwnd or not win32gui.IsWindow(target_hwnd):
        raise ValueError(f"目标窗口句柄已经失效: {hwnd}")

    try:
        root_hwnd = win32gui.GetAncestor(
            target_hwnd, getattr(win32con, "GA_ROOT", 2)
        )
        if root_hwnd and win32gui.IsWindow(root_hwnd):
            target_hwnd = root_hwnd
    except Exception:
        # 部分老版本 pywin32 没有 GetAncestor；原句柄仍然可以使用。
        pass
    return target_hwnd


def _post_message_activate(hwnd):
    """Use the same lightweight activation message as OK-WW's backend."""
    win32gui.PostMessage(hwnd, win32con.WM_ACTIVATE, win32con.WA_ACTIVE, 0)


def _make_post_message_lparam(vk_code: int, key_up: bool = False) -> int:
    """Build the Win32 keyboard lParam used by OK-WW PostMessage input."""
    scan_code = int(win32api.MapVirtualKey(vk_code, MAPVK_VK_TO_VSC))
    if not scan_code:
        raise ValueError(f"虚拟键码无法转换为扫描码: {vk_code}")

    lparam = (scan_code << 16) | 1
    if key_up:
        lparam |= (1 << 30) | (1 << 31)
    return lparam


def _post_vk_event(hwnd, vk_code: int, key_up: bool = False):
    message = win32con.WM_KEYUP if key_up else win32con.WM_KEYDOWN
    win32gui.PostMessage(
        hwnd,
        message,
        vk_code,
        _make_post_message_lparam(vk_code, key_up),
    )


def execute_post_message_key_spec(
    hwnd,
    key_spec: str,
    duration: float = 0.05,
    name="DAG_BackgroundKey",
):
    """Send a key/chord to a window without forcing it into the foreground.

    This mirrors OK-WW's PostMessage interaction method: WM_ACTIVATE followed by
    WM_KEYDOWN/WM_KEYUP whose lParam includes the mapped hardware scan code.
    """
    parts = [part.strip() for part in str(key_spec).split("+") if part.strip()]
    if not parts:
        _log(f"[{name}] 按键名称为空", "ERROR")
        return False

    try:
        target_hwnd = _resolve_post_message_hwnd(hwnd)
        key_codes = [resolve_key_code(part) for part in parts]
    except (TypeError, ValueError) as error:
        _log(f"[{name}] {error}", "ERROR")
        return False

    modifiers = key_codes[:-1]
    if any(vk not in MODIFIER_VKS for vk in modifiers):
        _log(
            f"[{name}] 组合键中除最后一项外只能使用 Ctrl/Shift/Alt/Win",
            "ERROR",
        )
        return False
    if stop_event.is_set():
        return False

    pressed = []
    interrupted = False
    try:
        _post_message_activate(target_hwnd)
        for modifier in modifiers:
            _post_vk_event(target_hwnd, modifier)
            pressed.append(modifier)

        _post_vk_event(target_hwnd, key_codes[-1])
        pressed.append(key_codes[-1])
        interrupted = stop_event.wait(timeout=max(0.0, float(duration)))
        if not interrupted:
            _log(
                f"[{name}] 后台按键 [{key_spec}] 已发送到窗口 {target_hwnd}",
                "SUCCESS",
            )
        return not interrupted
    except Exception as error:
        _log(f"[{name}] 后台键盘输入失败: {error}", "ERROR")
        return False
    finally:
        for pressed_vk in reversed(pressed):
            try:
                _post_vk_event(target_hwnd, pressed_vk, key_up=True)
            except Exception as release_error:
                _log(f"[{name}] 后台释放按键失败: {release_error}", "ERROR")


def execute_post_message_text(
    hwnd,
    text: str,
    interval: float = 0.05,
    name="DAG_BackgroundType",
):
    """Send text as WM_CHAR messages to a background window."""
    try:
        target_hwnd = _resolve_post_message_hwnd(hwnd)
        _post_message_activate(target_hwnd)
        normalized_text = str(text).replace("\r\n", "\n").replace("\r", "\n")
        for index, char in enumerate(normalized_text):
            if stop_event.is_set():
                return False
            win32gui.PostMessage(target_hwnd, win32con.WM_CHAR, ord(char), 1)
            if index < len(normalized_text) - 1 and stop_event.wait(
                timeout=max(0.0, float(interval))
            ):
                return False
        _log(f"[{name}] 后台文本已发送到窗口 {target_hwnd}", "SUCCESS")
        return True
    except Exception as error:
        _log(f"[{name}] 后台文本输入失败: {error}", "ERROR")
        return False


def _char_to_keystroke(char: str):
    """Resolve a character plus the modifier bits returned by VkKeyScan."""
    if char == "\n":
        return win32con.VK_RETURN, []
    if char == "\t":
        return win32con.VK_TAB, []

    mapped = win32api.VkKeyScan(char)
    if mapped == -1:
        raise ValueError(f"当前键盘布局无法输入字符 {char!r}，请改用粘贴节点")

    vk_code = mapped & 0xFF
    shift_state = (mapped >> 8) & 0xFF

    # VkKeyScan does not account for the current CapsLock state.
    if (
        char.isascii()
        and char.isalpha()
        and (win32api.GetKeyState(win32con.VK_CAPITAL) & 1)
    ):
        shift_state ^= 0x01

    modifiers = []
    if shift_state & 0x01:
        modifiers.append(win32con.VK_SHIFT)
    if shift_state & 0x02:
        modifiers.append(win32con.VK_CONTROL)
    if shift_state & 0x04:
        modifiers.append(win32con.VK_MENU)
    return vk_code, modifiers


def execute_type_string(text: str, interval: float = 0.05, name="DAG_Type"):
    """Type Latin text with correct case, punctuation, tabs and newlines."""
    normalized_text = str(text).replace("\r\n", "\n").replace("\r", "\n")
    _log(f"准备模拟打字（{len(normalized_text)} 个字符）")

    try:
        for index, char in enumerate(normalized_text):
            if stop_event.is_set():
                return False

            vk_code, modifiers = _char_to_keystroke(char)
            if not _execute_key_chord(
                vk_code,
                modifiers,
                duration=0.02,
                name=f"{name}_{index}",
            ):
                return False

            if index < len(normalized_text) - 1 and stop_event.wait(
                timeout=max(0.0, float(interval))
            ):
                return False
        return True
    except Exception as error:
        _log(f"[{name}] 模拟打字失败: {error}", "ERROR")
        return False


def _read_clipboard_text():
    opened = False
    try:
        win32clipboard.OpenClipboard()
        opened = True
        if win32clipboard.IsClipboardFormatAvailable(win32con.CF_UNICODETEXT):
            return win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT)
        return None
    finally:
        if opened:
            win32clipboard.CloseClipboard()


def _write_clipboard_text(text: str):
    opened = False
    try:
        win32clipboard.OpenClipboard()
        opened = True
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardData(win32con.CF_UNICODETEXT, str(text))
    finally:
        if opened:
            win32clipboard.CloseClipboard()


def execute_paste_text(
    hwnd,
    text: str,
    name="DAG_Paste",
    retries: int = 3,
    use_post_message: bool = False,
):
    """Paste Unicode text while guaranteeing that Ctrl and V are released."""
    if not text:
        return True
    if not hwnd:
        _log(f"[{name}] 没有可接收粘贴的窗口", "ERROR")
        return False

    if use_post_message:
        try:
            hwnd = _resolve_post_message_hwnd(hwnd)
        except ValueError as error:
            _log(f"[{name}] {error}", "ERROR")
            return False
    else:
        from functions.func_window import force_activate_window

    old_text = None
    try:
        with hold_lock:
            old_text = _read_clipboard_text()
    except Exception as error:
        _log(f"[{name}] 读取原剪贴板失败，将继续尝试粘贴: {error}", "WARN")

    success = False
    try:
        for attempt in range(1, max(1, int(retries)) + 1):
            if stop_event.is_set():
                break
            try:
                with hold_lock:
                    _write_clipboard_text(text)

                if use_post_message:
                    paste_success = execute_post_message_key_spec(
                        hwnd, "CTRL+V", duration=0.05, name=name
                    )
                else:
                    if not force_activate_window(hwnd, name):
                        raise RuntimeError("目标窗口激活失败")
                    if stop_event.wait(timeout=0.15):
                        break
                    paste_success = execute_key_spec(
                        "CTRL+V", duration=0.05, name=name
                    )
                if not paste_success:
                    raise RuntimeError("Ctrl+V 发送失败")

                # 给目标窗口留出读取剪贴板的时间，再恢复用户原内容。
                stop_event.wait(timeout=0.15)
                success = True
                _log(f"[{name}] 剪贴板方式粘贴成功", "SUCCESS")
                break
            except Exception as error:
                _log(f"[{name}] 粘贴失败（{error}），重试 {attempt}/{retries}", "WARN")
                if stop_event.wait(timeout=0.5):
                    break
    finally:
        if old_text is not None:
            try:
                with hold_lock:
                    _write_clipboard_text(old_text)
            except Exception as error:
                _log(f"[{name}] 恢复原剪贴板失败: {error}", "WARN")

    return success
