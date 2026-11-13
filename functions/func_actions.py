# functions/func_actions.py
import ctypes
import threading
import time

import win32api
import win32clipboard
import win32con
import win32gui

from core.event_bus import bus
from functions.func_window import force_activate_window

SHORT_NAME = "AEGIS_Actions"


# --- C 语言结构体定义 (用于伪造底层硬件信号) ---
PUL = ctypes.POINTER(ctypes.c_ulong)


# --- [系统解耦]: 局部化原有的全局锁与事件 ---
hold_lock = threading.Lock()
hold_threads = {}
stop_event = threading.Event()


def log(msg, level="INFO"):
    """彩色日志桥接"""
    if "成功" in msg or "完成" in msg:
        level = "SUCCESS"
    elif "失败" in msg or "异常" in msg or "超时" in msg:
        level = "WARN"
    elif "彻底" in msg:
        level = "ERROR"
    bus.log_emitted.emit(level, "ActionHAL", msg)


# ==========================================
# 武器 1：全局鼠标操作
# ==========================================
def execute_global_mouse_action(button: str, action: str, name: str = "DAG_Mouse"):
    """原 backend_global_mouse_action"""
    log(f"全局鼠标操作：在当前位置执行 {button} {action} [{name}]")
    flags_down = {
        "left": win32con.MOUSEEVENTF_LEFTDOWN,
        "right": win32con.MOUSEEVENTF_RIGHTDOWN,
        "middle": win32con.MOUSEEVENTF_MIDDLEDOWN,
    }
    flags_up = {
        "left": win32con.MOUSEEVENTF_LEFTUP,
        "right": win32con.MOUSEEVENTF_RIGHTUP,
        "middle": win32con.MOUSEEVENTF_MIDDLEUP,
    }
    down_flag = flags_down.get(button.lower(), win32con.MOUSEEVENTF_LEFTDOWN)
    up_flag = flags_up.get(button.lower(), win32con.MOUSEEVENTF_LEFTUP)

    try:
        if action == "单击":
            win32api.mouse_event(down_flag, 0, 0, 0, 0)
            time.sleep(0.05)
            win32api.mouse_event(up_flag, 0, 0, 0, 0)
        elif action == "双击":
            win32api.mouse_event(down_flag, 0, 0, 0, 0)
            time.sleep(0.05)
            win32api.mouse_event(up_flag, 0, 0, 0, 0)
            time.sleep(0.05)
            win32api.mouse_event(down_flag, 0, 0, 0, 0)
            time.sleep(0.05)
            win32api.mouse_event(up_flag, 0, 0, 0, 0)
        elif action == "按下":
            win32api.mouse_event(down_flag, 0, 0, 0, 0)
        elif action == "释放":
            win32api.mouse_event(up_flag, 0, 0, 0, 0)
        log(f"[{name}] 全局鼠标操作成功")
        return True
    except Exception as e:
        log(f"[{name}] 全局鼠标操作失败: {e}")
        return False


def execute_mouse_wheel(direction: str, duration: float, name: str = "DAG_Wheel"):
    """原 backend_global_mouse_wheel_continuous"""
    log(f"全局鼠标滚轮：持续 {direction} 滚动 {duration:.1f} 秒 [{name}]")
    delta_per_tick = 120 if direction == "向上" else -120
    tick_interval = 0.05
    total_ticks = int(duration / tick_interval)
    try:
        for _ in range(total_ticks):
            if stop_event.is_set():
                return False
            win32api.mouse_event(win32con.MOUSEEVENTF_WHEEL, 0, 0, delta_per_tick, 0)
            time.sleep(tick_interval)

        remaining = duration - (total_ticks * tick_interval)
        if remaining > 0:
            # ====== 修改：将 time.sleep 替换为 wait ======
            stop_event.wait(timeout=remaining)
            # ============================================

        log(f"[{name}] 持续滚轮操作完成")
        return True
    except Exception as e:
        log(f"[{name}] 持续滚轮操作失败: {e}", "ERROR")
        return False


# functions/func_actions.py 追加这段代码
def execute_background_click(
    hwnd, x, y, button: str, action: str, name: str = "DAG_BgClick"
):
    """
    真·后台静默点击：通过 PostMessage 直接向窗口句柄发送信号，绝不干扰真实鼠标！
    x, y: 视觉节点传来的绝对屏幕坐标
    """
    if not hwnd or not win32gui.IsWindow(hwnd):
        log(f"[{name}] 后台点击失败：无效的窗口句柄 {hwnd}", "ERROR")
        return False

    log(f"后台操作：准备向句柄 {hwnd} 发送 {button} {action}")

    try:
        # 【核心黑魔法 1：坐标系降维转换】将屏幕绝对坐标，转换为该窗口内部的相对坐标！
        client_point = win32gui.ScreenToClient(hwnd, (int(x), int(y)))
        cx, cy = client_point
        lparam = win32api.MAKELONG(cx, cy)  # 组合为 Windows 消息能看懂的指针参数

        # 匹配按键消息码
        if button.lower() == "left":
            msg_down, msg_up = win32con.WM_LBUTTONDOWN, win32con.WM_LBUTTONUP
            wparam = win32con.MK_LBUTTON
        elif button.lower() == "right":
            msg_down, msg_up = win32con.WM_RBUTTONDOWN, win32con.WM_RBUTTONUP
            wparam = win32con.MK_RBUTTON
        else:
            msg_down, msg_up = win32con.WM_MBUTTONDOWN, win32con.WM_MBUTTONUP
            wparam = win32con.MK_MBUTTON

        # 【核心黑魔法 2：静默消息注入】
        if action == "单击":
            win32api.PostMessage(hwnd, msg_down, wparam, lparam)
            time.sleep(0.05)  # 模拟按压时长
            win32api.PostMessage(hwnd, msg_up, 0, lparam)
        elif action == "双击":
            win32api.PostMessage(hwnd, msg_down, wparam, lparam)
            time.sleep(0.05)
            win32api.PostMessage(hwnd, msg_up, 0, lparam)
            time.sleep(0.05)
            win32api.PostMessage(hwnd, msg_down, wparam, lparam)
            time.sleep(0.05)
            win32api.PostMessage(hwnd, msg_up, 0, lparam)
        elif action == "按下":
            win32api.PostMessage(hwnd, msg_down, wparam, lparam)
        elif action == "释放":
            win32api.PostMessage(hwnd, msg_up, 0, lparam)

        log(f"[{name}] 后台点击执行成功！相对坐标: ({cx}, {cy})")
        return True
    except Exception as e:
        log(f"[{name}] 后台点击异常: {e}", "ERROR")
        return False


# ==========================================
# 武器 3：狂暴连点器
# ==========================================
def execute_rapid_click(
    button: str, count: int, interval: float, name: str = "DAG_RapidClick"
):
    """
    狂暴连点器 (不受 DAG 开销限制的极速底层点击)
    """
    log(f"🔫 执行物理连点：{button} 键 {count} 次，间隔 {interval}s")

    flags_down = {
        "left": win32con.MOUSEEVENTF_LEFTDOWN,
        "right": win32con.MOUSEEVENTF_RIGHTDOWN,
    }
    flags_up = {
        "left": win32con.MOUSEEVENTF_LEFTUP,
        "right": win32con.MOUSEEVENTF_RIGHTUP,
    }

    down_flag = flags_down.get(button.lower(), win32con.MOUSEEVENTF_LEFTDOWN)
    up_flag = flags_up.get(button.lower(), win32con.MOUSEEVENTF_LEFTUP)

    try:
        for i in range(count):
            # 极速响应中止指令（防失控安全锁）
            if stop_event.is_set():
                log(f"[{name}] ⚠️ 连点被强制中止！", "WARN")
                return False

            win32api.mouse_event(down_flag, 0, 0, 0, 0)
            time.sleep(0.01)  # 模拟人类微小的按压时间
            win32api.mouse_event(up_flag, 0, 0, 0, 0)

            if i < count - 1:
                time.sleep(interval)

        log(f"[{name}] ✅ 连点执行完毕")
        return True
    except Exception as e:
        log(f"[{name}] 连点异常: {e}", "ERROR")
        return False
