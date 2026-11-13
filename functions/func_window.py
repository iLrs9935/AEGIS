# functions/func_window.py
import os
import re
import subprocess
import sys
import time

import win32api
import win32con
import win32gui
import win32process

from core.event_bus import bus

SHORT_NAME = "AEGIS_Sys"


def log(msg, level="INFO"):
    """将底层的 log 直接推送到 UI 的极客控制台"""
    if "成功" in msg or "找到" in msg or "✅" in msg:
        level = "SUCCESS"
    elif "失败" in msg or "异常" in msg or "未找到" in msg or "⚠️" in msg:
        level = "WARN"
    elif "❌" in msg or "出错" in msg:
        level = "ERROR"

    bus.log_emitted.emit(level, "WindowHAL", msg)


# ==========================================
# 核心功能：窗口句柄与激活 (原 backend.py & utils.py)
# ==========================================


def force_activate_window(hwnd, name=""):
    """Win11 专用：强制激活窗口（已彻底清理 Alt 残留）"""
    if not hwnd or not win32gui.IsWindow(hwnd):
        log(f"{name}：无效句柄，跳过激活")
        return False

    cur_thread = win32api.GetCurrentThreadId()
    fg_thread = target_thread = 0
    attached = False
    success = False

    try:
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        win32gui.ShowWindow(hwnd, win32con.SW_SHOW)
        time.sleep(0.05)

        # 线程附加
        fg_hwnd = win32gui.GetForegroundWindow()
        if fg_hwnd:
            fg_thread = win32process.GetWindowThreadProcessId(fg_hwnd)[0]
        target_thread = win32process.GetWindowThreadProcessId(hwnd)[0]

        if fg_thread and fg_thread != target_thread and fg_thread != 0:
            win32process.AttachThreadInput(fg_thread, target_thread, True)
            attached = True
        if cur_thread != target_thread and cur_thread != 0:
            win32process.AttachThreadInput(cur_thread, target_thread, True)
            attached = True

        # 多重置顶激活
        for _ in range(3):
            win32gui.SetWindowPos(
                hwnd,
                win32con.HWND_TOPMOST,
                0,
                0,
                0,
                0,
                win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_SHOWWINDOW,
            )
            win32gui.SetWindowPos(
                hwnd,
                win32con.HWND_NOTOPMOST,
                0,
                0,
                0,
                0,
                win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_SHOWWINDOW,
            )
            win32gui.BringWindowToTop(hwnd)
            win32gui.SetForegroundWindow(hwnd)
            time.sleep(0.08)

        # 【终极清理】强制释放所有修饰键，杜绝残留
        time.sleep(0.05)
        for vk in [
            win32con.VK_MENU,
            win32con.VK_CONTROL,
            win32con.VK_SHIFT,
            win32con.VK_LCONTROL,
            win32con.VK_RCONTROL,
            win32con.VK_LSHIFT,
            win32con.VK_RSHIFT,
            win32con.VK_LMENU,
            win32con.VK_RMENU,
            0x5B,
            0x5C,  # WIN 键
        ]:
            win32api.keybd_event(vk, 0, win32con.KEYEVENTF_KEYUP, 0)
            time.sleep(0.01)

        # 假鼠标移动兜底
        x, y = win32api.GetCursorPos()
        win32api.SetCursorPos((x + 1, y))
        win32api.SetCursorPos((x, y))

        success = win32gui.GetForegroundWindow() == hwnd
        if success:
            log(f"{name}：窗口强制激活成功 ✅")
        else:
            log(f"{name}：激活失败（仍未前台）")
        return success

    except Exception as e:
        log(f"{name}：force_activate_window 异常: {e}")
        return False
    finally:
        if attached:
            try:
                if fg_thread and fg_thread != 0:
                    win32process.AttachThreadInput(fg_thread, target_thread, False)
                if cur_thread and cur_thread != target_thread and cur_thread != 0:
                    win32process.AttachThreadInput(cur_thread, target_thread, False)
            except Exception:
                pass


def get_target_window(title_keyword):
    """获取包含关键词的可见窗口（取标题最长者）"""
    windows = []

    def enum_handler(hwnd, _):
        if win32gui.IsWindowVisible(hwnd):
            title = win32gui.GetWindowText(hwnd)
            if title_keyword and title_keyword.lower() in title.lower():
                windows.append((hwnd, title))

    win32gui.EnumWindows(enum_handler, None)

    if not windows:
        return None, None

    target_hwnd, target_title = max(windows, key=lambda x: len(x[1]))
    try:
        rect = win32gui.GetWindowRect(target_hwnd)
        log(f"{SHORT_NAME}：找到目标窗口 → {target_title}")
        return target_hwnd, rect
    except Exception as e:
        log(f"{SHORT_NAME}：获取窗口位置失败: {e}")
        return None, None


# ==========================================
# 扩展功能：进程与资源管理 (原 utils.py)
# ==========================================


def is_process_running(process_name):
    if not process_name:
        return False
    try:
        result = subprocess.run(
            ["tasklist", "/nh", "/fi", f"imagename eq {process_name}"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return process_name.lower() in result.stdout.lower()
    except Exception as e:
        log(f"{SHORT_NAME}：检查进程 {process_name} 失败: {e}")
        return False


def kill_specific_processes(names):
    valid_names = [name for name in names if name]
    if not valid_names:
        return
    cmd = ["taskkill", "/F", "/T"]
    for name in valid_names:
        cmd.extend(["/IM", name])
    try:
        subprocess.run(cmd, capture_output=True, timeout=8)
        log(f"{SHORT_NAME}：已批量强制结束进程 {valid_names}")
    except Exception as e:
        log(f"{SHORT_NAME}：批量结束进程出错: {e}")


def close_windows_by_titles(titles):
    if not titles:
        return
    count = 0

    def enum_handler(hwnd, _):
        nonlocal count
        if win32gui.IsWindowVisible(hwnd):
            title = win32gui.GetWindowText(hwnd).lower()
            for kw in (k.lower() for k in titles):
                if kw in title:
                    win32api.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
                    count += 1
                    log(f"{SHORT_NAME}：发送关闭消息 → {win32gui.GetWindowText(hwnd)}")
                    break

    win32gui.EnumWindows(enum_handler, None)
    if count:
        time.sleep(0.8)


def kill_windows_by_titles(
    titles, use_regex=False, graceful=True, protect_browser=True
):
    if not titles:
        log(f"{SHORT_NAME}：关闭失败 - titles 参数为空！")
        return

    pids = set()
    target_hwnds = []
    matched_titles = []
    compiled_regexes, plain_keywords, suffix_keywords = [], [], []

    for keyword in titles:
        kw = keyword.lower().strip()
        if kw.startswith("."):
            suffix_keywords.append(kw)
        elif use_regex:
            try:
                compiled_regexes.append(re.compile(kw, re.IGNORECASE))
            except re.error as e:
                log(f"{SHORT_NAME}：正则编译失败忽略 '{kw}': {e}")
        else:
            plain_keywords.append(kw)

    browser_keywords = [
        "google chrome",
        "microsoft edge",
        "chrome",
        "edge",
        "- google",
        "- microsoft",
    ]

    def is_browser(title):
        return any(bk in title.lower() for bk in browser_keywords)

    def enum_handler(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return
        title = win32gui.GetWindowText(hwnd)
        if not title:
            return

        t_lower = title.lower()
        if protect_browser and is_browser(title):
            return

        match = False
        if any(t_lower.endswith(s) for s in suffix_keywords):
            match = True
        elif any(k in t_lower for k in plain_keywords):
            match = True
        elif use_regex and any(r.search(t_lower) for r in compiled_regexes):
            match = True

        if match:
            matched_titles.append(title)
            target_hwnds.append(hwnd)
            try:
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                if pid > 0:
                    pids.add(pid)
            except Exception:
                pass

    win32gui.EnumWindows(enum_handler, None)
    log(
        f"{SHORT_NAME}：关闭扫描完成 → 找到 {len(matched_titles)} 个匹配窗口，{len(pids)} 个 PID"
    )

    if not pids:
        log(f"{SHORT_NAME}：⚠️ 未找到匹配进程！当前关键词：{titles}")
        return

    if graceful:
        log(f"{SHORT_NAME}：执行优雅关闭...")
        for hwnd in target_hwnds:
            try:
                win32api.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
            except Exception:
                pass
        time.sleep(1.5)

    for pid in pids:
        try:
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/F", "/T"],
                capture_output=True,
                timeout=8,
            )
            log(f"{SHORT_NAME}：✅ 强制终止 PID {pid} 成功")
        except Exception as e:
            log(f"{SHORT_NAME}：❌ 终止 PID {pid} 失败: {e}")


def _get_hwnds_by_pids(pids):
    hwnds = []

    def callback(hwnd, _):
        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
            if pid in pids and win32gui.IsWindowVisible(hwnd):
                hwnds.append(hwnd)
        except Exception:
            pass
        return True

    win32gui.EnumWindows(callback, None)
    return hwnds


def resource_path(relative_path):
    base_path = getattr(sys, "_MEIPASS", os.path.abspath("."))
    return os.path.join(base_path, relative_path)
