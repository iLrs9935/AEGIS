# functions/func_vision.py
import ctypes
import os
import time

import cv2
import numpy as np
import pyautogui
import win32con
import win32gui
import win32ui
from PIL import Image as PILImage

from core.event_bus import bus

try:
    from functions.func_actions import stop_event
except ImportError:
    stop_event = None

# --- [系统解耦]: 尝试初始化 DXCAM ---
try:
    import dxcam

    camera = dxcam.create()
except ImportError:
    camera = None

# --- [依赖桥接]: 预留给 func_window.py 的强制激活函数 ---
try:
    from functions.func_window import force_activate_window
except ImportError:

    def force_activate_window(hwnd, name=""):
        return True


SHORT_NAME = "AEGIS_Vision"


def log(msg, level="INFO"):
    if "成功" in msg:
        level = "SUCCESS"
    elif "失败" in msg or "不足" in msg or "异常" in msg:
        level = "WARN"
    elif "彻底失败" in msg:
        level = "ERROR"

    bus.log_emitted.emit(level, "VisionHAL", msg)


def extract_target_by_strategy(
    result, confidence, tw, th, strategy="最高置信度", target_idx=1
):
    """核心黑魔法 V2：支持 2D 网格排序与严格模式防呆 (修复 numpy 线程崩溃 BUG)"""
    if result is None:
        return None, 0.0

    locations = np.where(result >= confidence)
    pts = list(zip(*locations[::-1]))
    if not pts:
        return None, 0.0

    matches = []
    for pt in pts:
        val = result[pt[1], pt[0]]
        is_overlap = False
        for i, m in enumerate(matches):
            if abs(pt[0] - m[0][0]) < tw * 0.5 and abs(pt[1] - m[0][1]) < th * 0.5:
                is_overlap = True
                if val > m[1]:
                    matches[i] = (pt, val)
                break
        if not is_overlap:
            matches.append((pt, val))

    if not matches:
        return None, 0.0

    # 防御序号小于1的非法输入
    target_idx = max(1, int(target_idx))
    if target_idx > len(matches):
        log(
            f"⚠️ 视觉目标数量不足！请求第 {target_idx} 个，但只识别到 {len(matches)} 个(置信度>{confidence})。触发防呆！",
            "WARN",
        )
        return None, 0.0

    if "从上到下" in strategy:
        matches.sort(key=lambda x: x[0][1])
    elif "从左到右" in strategy:
        matches.sort(key=lambda x: x[0][0])
    elif "网格阅读(Z字)" in strategy:
        row_tolerance = th * 0.5
        matches.sort(key=lambda x: (int(x[0][1] // row_tolerance), x[0][0]))
    else:
        matches.sort(key=lambda x: x[1], reverse=True)

    final_x = int(matches[target_idx - 1][0][0])
    final_y = int(matches[target_idx - 1][0][1])
    final_val = float(matches[target_idx - 1][1])

    return (final_x, final_y), final_val


def execute_template_match(
    hwnd,
    rect,
    pic_path: str,
    confidence: float = 0.75,
    grayscale: bool = True,
    is_background: bool = False,
    match_strategy: str = "最高置信度",
    target_index: int = 1,
    retry_count: int = 1,  # 新增参数: 重试次数
    retry_interval: float = 0.5,  # 新增参数: 重试间隔(秒)
):
    if not hwnd or not rect:
        log(f"{SHORT_NAME}：无效 hwnd 或 rect")
        return None, 0.0

    left, top, right, bottom = rect
    width = right - left
    height = bottom - top

    if width <= 0 or height <= 0:
        log(f"{SHORT_NAME}：窗口尺寸异常 {width}x{height}")
        return None, 0.0

    log(
        f"{SHORT_NAME}：窗口 rect: ({left},{top},{right},{bottom}) 尺寸 {width}x{height}"
    )

    # Borderless/full-screen games commonly report an invisible frame outside
    # the monitor (for example -16,-72,3856,2176 on a 3840x2160 display).
    # Screen-capture backends require a strictly valid on-screen rectangle.
    screen_width, screen_height = pyautogui.size()
    capture_left = max(0, left)
    capture_top = max(0, top)
    capture_right = min(screen_width, right)
    capture_bottom = min(screen_height, bottom)
    capture_width = capture_right - capture_left
    capture_height = capture_bottom - capture_top
    if capture_width <= 0 or capture_height <= 0:
        log(f"{SHORT_NAME}：窗口不在当前屏幕可捕获范围内", "ERROR")
        return None, 0.0
    if (capture_left, capture_top, capture_right, capture_bottom) != rect:
        log(
            f"{SHORT_NAME}：已将越界窗口裁剪为屏幕有效区域 "
            f"({capture_left},{capture_top},{capture_right},{capture_bottom})"
        )

    # 1. 拦截底层文件不存在的 IO 异常
    if not os.path.exists(pic_path):
        log(f"{SHORT_NAME}：⚠️ 致命错误，图片文件不存在: {pic_path}", "ERROR")
        # 返回 None, 0.0，使外层节点平滑走入“未找到”的分支
        return None, 0.0

    # 2. 增加 try-catch 拦截图片损坏或无读取权限等其他文件级异常
    try:
        if grayscale:
            template = cv2.imdecode(
                np.fromfile(pic_path, dtype=np.uint8), cv2.IMREAD_GRAYSCALE
            )
        else:
            template = cv2.imdecode(
                np.fromfile(pic_path, dtype=np.uint8), cv2.IMREAD_COLOR
            )
    except Exception as e:
        log(f"{SHORT_NAME}：⚠️ 读取图片文件时发生异常: {e}", "ERROR")
        return None, 0.0

    if template is None:
        log(f"{SHORT_NAME}：模板图像加载失败：{pic_path}", "ERROR")
        return None, 0.0

    def match_template(screenshot_cv):
        # Templates may be captured at 1080p/1440p while the live game runs at
        # 4K. Cover the common 100%/125%/150%/175%/200% UI scale factors, plus
        # smaller render scales, without multiplying the old search cost.
        scales = [1.0, 1.25, 1.5, 1.75, 2.0, 0.9, 0.8, 0.7, 0.6, 0.5]
        max_val_overall = 0.0
        best_loc = (0, 0)
        best_scale = 1.0
        best_resized_size = template.shape[:2]
        best_res = None

        for scale in scales:
            if stop_requested():
                break
            if scale <= 0:
                continue
            resized = (
                template
                if scale == 1.0
                else cv2.resize(template, None, fx=scale, fy=scale)
            )

            h, w = resized.shape[:2]
            if h > screenshot_cv.shape[0] or w > screenshot_cv.shape[1]:
                continue

            res = cv2.matchTemplate(screenshot_cv, resized, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(res)

            if max_val > max_val_overall:
                max_val_overall = max_val
                best_loc = max_loc
                best_scale = scale
                best_resized_size = (h, w)
                best_res = res
                if max_val >= confidence + 0.05:
                    break

        return best_res, max_val_overall, best_loc, best_scale, best_resized_size

    DEBUG_SAVE_SCREENSHOT = False

    def _debug_save_img(cv_img, method_name):
        if not DEBUG_SAVE_SCREENSHOT:
            return
        try:
            desktop = os.path.join(
                os.path.expanduser("~"), "Desktop", "debug_screenshots"
            )
            os.makedirs(desktop, exist_ok=True)
            from datetime import datetime

            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            pic_name = (
                os.path.basename(pic_path).replace(".png", "").replace(".jpg", "")
                if pic_path
                else "target"
            )
            filename = f"DEBUG_{SHORT_NAME}_{method_name}_{pic_name}_{ts}_val0.png"
            filepath = os.path.join(desktop, filename)
            save_img = (
                cv2.cvtColor(cv_img, cv2.COLOR_GRAY2BGR)
                if len(cv_img.shape) == 2
                else cv_img.copy()
            )
            cv2.imwrite(filepath, save_img)
            log(f"{SHORT_NAME}：【DEBUG】{method_name} 截图已保存 → {filename}")
        except Exception:
            pass

    global_max_val_best = 0.0

    def stop_requested():
        return bool(stop_event and stop_event.is_set())

    # 循环包裹整个捕获流程
    for attempt in range(retry_count):
        if stop_requested():
            log(f"{SHORT_NAME}：收到紧急刹车，视觉重试已立即终止", "WARN")
            return None, global_max_val_best
        if not win32gui.IsWindow(hwnd):
            log(f"{SHORT_NAME}：游戏窗口句柄已经失效，停止继续重试", "WARN")
            return None, global_max_val_best
        if attempt > 0:
            log(
                f"{SHORT_NAME}：准备第 {attempt + 1}/{retry_count} 次捕获重试，等待 {retry_interval}s..."
            )
            if stop_event and stop_event.wait(timeout=retry_interval):
                log(f"{SHORT_NAME}：收到紧急刹车，视觉等待已立即终止", "WARN")
                return None, global_max_val_best
            if not stop_event:
                time.sleep(retry_interval)

        max_val_best = 0.0

        try:
            # ============ 第一优先：pyautogui (仅限前台使用) ============
            if not is_background:
                log(f"{SHORT_NAME}：【优先】尝试 pyautogui 捕获 (Attempt {attempt+1})")
                try:
                    force_activate_window(hwnd, f"{SHORT_NAME}_pyautogui")
                    if stop_event and stop_event.wait(timeout=0.25):
                        return None, global_max_val_best
                    if not stop_event:
                        time.sleep(0.25)

                    screenshot_pil = pyautogui.screenshot(
                        region=(capture_left, capture_top, capture_width, capture_height)
                    )
                    screenshot_cv = cv2.cvtColor(
                        np.array(screenshot_pil), cv2.COLOR_RGB2BGR
                    )
                    if grayscale:
                        screenshot_cv = cv2.cvtColor(screenshot_cv, cv2.COLOR_BGR2GRAY)

                    best_res_py, max_val_py, _, _, (th, tw) = match_template(
                        screenshot_cv
                    )
                    max_val_best = max(max_val_best, max_val_py)

                    if max_val_py >= confidence:
                        best_loc, final_val = extract_target_by_strategy(
                            best_res_py,
                            confidence,
                            tw,
                            th,
                            match_strategy,
                            target_index,
                        )
                        if best_loc:
                            center_x = capture_left + best_loc[0] + tw // 2
                            center_y = capture_top + best_loc[1] + th // 2
                            log(
                                f"{SHORT_NAME}：pyautogui 匹配成功（置信度 {final_val:.3f}）"
                            )
                            return (center_x, center_y), final_val
                        else:
                            log(f"{SHORT_NAME}：pyautogui 目标数量不足")
                    else:
                        log(
                            f"{SHORT_NAME}：pyautogui 匹配置信度不足 ({max_val_py:.3f} < {confidence})"
                        )
                except Exception as e:
                    log(f"{SHORT_NAME}：pyautogui 捕获异常：{e}")
            else:
                log(
                    f"{SHORT_NAME}：👻 当前为后台静默模式，跳过 pyautogui 截屏与窗口激活。"
                )

            if stop_requested():
                return None, global_max_val_best

            # ============ 第二优先：PrintWindow + BitBlt ============
            log(f"{SHORT_NAME}：备选尝试 PrintWindow/BitBlt 捕获 (Attempt {attempt+1})")
            hdc = compatible_dc = bitmap_dc = bitmap = None
            try:
                hdc = win32gui.GetWindowDC(hwnd)
                compatible_dc = win32ui.CreateDCFromHandle(hdc)
                bitmap_dc = compatible_dc.CreateCompatibleDC()
                bitmap = win32ui.CreateBitmap()
                bitmap.CreateCompatibleBitmap(compatible_dc, width, height)
                bitmap_dc.SelectObject(bitmap)

                try:
                    pw_result = ctypes.windll.user32.PrintWindow(
                        hwnd, bitmap_dc.GetSafeHdc(), 0
                    )
                except Exception as e:
                    log(f"{SHORT_NAME}：PrintWindow 异常：{e}，fallback BitBlt")
                    pw_result = 0

                if pw_result == 0:
                    bitmap_dc.BitBlt(
                        (0, 0), (width, height), compatible_dc, (0, 0), win32con.SRCCOPY
                    )

                bmpinfo = bitmap.GetInfo()
                bmpstr = bitmap.GetBitmapBits(True)
                img = PILImage.frombuffer(
                    "RGB",
                    (bmpinfo["bmWidth"], bmpinfo["bmHeight"]),
                    bmpstr,
                    "raw",
                    "BGRX",
                    0,
                    1,
                )
                img_np = np.array(img)

                screenshot_cv_pw = (
                    cv2.cvtColor(img_np, cv2.COLOR_RGB2GRAY)
                    if grayscale
                    else cv2.cvtColor(img_np, cv2.COLOR_RGB2BGR)
                )
                _debug_save_img(screenshot_cv_pw, "printwindow")

                best_res_pw, max_val_pw, _, _, (th, tw) = match_template(
                    screenshot_cv_pw
                )
                max_val_best = max(max_val_best, max_val_pw)

                if max_val_pw >= confidence:
                    best_loc, final_val = extract_target_by_strategy(
                        best_res_pw, confidence, tw, th, match_strategy, target_index
                    )
                    if best_loc:
                        center_x = left + best_loc[0] + tw // 2
                        center_y = top + best_loc[1] + th // 2
                        log(
                            f"{SHORT_NAME}：PrintWindow/BitBlt 匹配成功（置信度 {final_val:.3f}）"
                        )
                        return (center_x, center_y), final_val
                    else:
                        log(f"{SHORT_NAME}：PrintWindow/BitBlt 目标数量不足")
                else:
                    log(
                        f"{SHORT_NAME}：PrintWindow/BitBlt 置信度不足（{max_val_pw:.3f}）"
                    )

            except Exception as e:
                log(f"{SHORT_NAME}：PrintWindow/BitBlt 完全异常：{e}")
            finally:
                if bitmap:
                    try:
                        win32gui.DeleteObject(bitmap.GetHandle())
                    except Exception:
                        pass
                if bitmap_dc:
                    try:
                        bitmap_dc.DeleteDC()
                    except Exception:
                        pass
                if compatible_dc:
                    try:
                        compatible_dc.DeleteDC()
                    except Exception:
                        pass
                if hdc:
                    try:
                        win32gui.ReleaseDC(hwnd, hdc)
                    except Exception:
                        pass

            if stop_requested():
                return None, global_max_val_best

            # ============ 第三优先：DXCAM ============
            log(f"{SHORT_NAME}：备选尝试 DXCAM (Attempt {attempt+1})")
            if camera:
                try:
                    frame = camera.grab(
                        region=(capture_left, capture_top, capture_right, capture_bottom)
                    )
                    if frame is not None:
                        screenshot_cv_dx = (
                            cv2.cvtColor(src=frame, code=cv2.COLOR_BGR2GRAY)
                            if grayscale
                            else frame.copy()
                        )
                        _debug_save_img(screenshot_cv_dx, "dxcam")

                        best_res_dx, max_val_dx, _, _, (th, tw) = match_template(
                            screenshot_cv_dx
                        )
                        max_val_best = max(max_val_best, max_val_dx)

                        if max_val_dx >= confidence:
                            best_loc, final_val = extract_target_by_strategy(
                                best_res_dx,
                                confidence,
                                tw,
                                th,
                                match_strategy,
                                target_index,
                            )
                            if best_loc:
                                center_x = capture_left + best_loc[0] + tw // 2
                                center_y = capture_top + best_loc[1] + th // 2
                                log(
                                    f"{SHORT_NAME}：DXCAM 匹配成功（置信度 {final_val:.3f}）"
                                )
                                return (center_x, center_y), final_val
                            else:
                                log(f"{SHORT_NAME}：DXCAM 目标数量不足")
                        else:
                            log(f"{SHORT_NAME}：DXCAM 置信度不足（{max_val_dx:.3f}）")
                    else:
                        log(f"{SHORT_NAME}：DXCAM 返回空帧")
                except Exception as e:
                    log(f"{SHORT_NAME}：DXCAM 异常：{e}")
            else:
                log(f"{SHORT_NAME}：DXCAM 未安装或初始化失败")

            # 单次迭代未命中目标，记录最高置信度用于最终兜底返回
            global_max_val_best = max(global_max_val_best, max_val_best)
            log(
                f"{SHORT_NAME}：第 {attempt + 1} 次重试中，所有捕获方案均未达标，当前轮次最高置信度 {max_val_best:.3f}",
                "WARN",
            )

        except Exception as e:
            log(f"{SHORT_NAME}：第 {attempt + 1} 次捕获彻底失败：{e}", "ERROR")

    # 循环走完（所有重试均结束）
    log(
        f"{SHORT_NAME}：经过 {retry_count} 次尝试，所有捕获方案均未达标，全局最高置信度 {global_max_val_best:.3f}",
        "WARN",
    )
    return None, global_max_val_best
