# nodes/actions.py
import time

from core.event_bus import bus
from functions.func_logic import get_context_value
from nodes import register_node

try:
    import win32api
    import win32gui

    from functions.func_actions import (
        execute_background_click,
        execute_global_mouse_action,
        execute_mouse_wheel,
        execute_rapid_click,
    )
    from nodes.keyboard_backend import (
        execute_key_spec,
        execute_paste_text,
        execute_post_message_key_spec,
        execute_post_message_text,
        execute_type_string,
    )
except ImportError as e:
    print(f"⚠️ 警告: 动作底层库导入失败 ({e})")

# ==========================================
# 节点 1：物理点击 (支持前后台切换)
# ==========================================
click_schema = {
    "执行模式": ["前台物理(真实鼠标)", "后台静默(不抢鼠标)"],
    "点击按键": ["left", "right", "middle"],
    "点击动作": ["单击", "双击", "按下", "释放"],
    "操作前延迟(s)": "0.1",
}


@register_node(name="物理点击", category="动作", schema=click_schema)
def click_target(config, inputs):
    mode = config.get("执行模式", "前台物理(真实鼠标)")
    button = config.get("点击按键", "left")
    action_type = config.get("点击动作", "单击")
    delay = float(config.get("操作前延迟(s)", 0.1))

    x = inputs.get("target_x")
    y = inputs.get("target_y")
    hwnd = inputs.get("hwnd")  # 拿取上游视觉节点传下来的目标窗口句柄

    if x is None or y is None:
        raise Exception("❌ 未接收到绝对坐标！请确保该节点连接在『视觉寻图』节点之后。")

    time.sleep(delay)

    if "前台" in mode:
        bus.log_emitted.emit("INFO", "动作", f"🖱️ [前台] 移动物理鼠标至 ({x}, {y})")
        win32api.SetCursorPos((int(x), int(y)))
        time.sleep(0.05)
        success = execute_global_mouse_action(button, action_type, f"DAG_{button}")
    else:
        if not hwnd:
            raise Exception(
                "❌ 后台点击需要上游提供窗口句柄(hwnd)！请确保寻图节点成功传出了 hwnd。"
            )
        bus.log_emitted.emit("INFO", "动作", f"👻 [后台] 静默注入点击至句柄 {hwnd}")
        success = execute_background_click(
            hwnd, x, y, button, action_type, f"DAG_{button}"
        )

    if success:
        return {"status": "Success"}
    else:
        raise Exception("动作执行失败，请检查日志。")


# ==========================================
# 节点 2：连续物理点击 (狂暴连点器)
# ==========================================
rapid_click_schema = {
    "点击按键": ["left", "right"],
    "点击次数": "20",
    "点击间隔(s)": "0.05",
}


@register_node(name="连续物理点击", category="动作", schema=rapid_click_schema)
def rapid_click_target(config, inputs):
    button = config.get("点击按键", "left")
    count = int(config.get("点击次数", 20))
    interval = float(config.get("点击间隔(s)", 0.05))

    x = inputs.get("target_x")
    y = inputs.get("target_y")

    if x is not None and y is not None:
        bus.log_emitted.emit("INFO", "动作", f"🖱️ 移动鼠标至坐标 ({x}, {y}) 准备连点")
        win32api.SetCursorPos((int(x), int(y)))
        time.sleep(0.05)
    else:
        bus.log_emitted.emit(
            "WARN", "动作", "⚠️ 未收到绝对坐标，将在当前鼠标位置【原地连点】！"
        )

    bus.log_emitted.emit("INFO", "动作", f"🔫 开启狂暴连点：{button}键 {count}次...")

    success = execute_rapid_click(button, count, interval, "DAG_RapidClick")

    if success:
        return {"status": "Success"}
    else:
        raise Exception("连点执行失败或被中止。")


# ==========================================
# 节点 3：持续滚轮
# ==========================================
mouse_wheel_schema = {
    "__out_ports__": ["滚动完成"],
    "__out_descriptions__": {"滚动完成": "完成指定方向和时长的连续滚轮输入"},
    "滚动方向": ["向下", "向上"],
    "持续时长(s)": "1.0",
    "操作前延迟(s)": "0.2",
}


@register_node(name="持续滚轮", category="动作", schema=mouse_wheel_schema)
def mouse_wheel_action(config, inputs):
    direction = config.get("滚动方向", "向下")
    duration = float(config.get("持续时长(s)", 1.0))
    delay = float(config.get("操作前延迟(s)", 0.2))
    if duration <= 0:
        raise ValueError("持续滚轮的时长必须大于 0")

    time.sleep(delay)
    success = execute_mouse_wheel(direction, duration, "DAG_MouseWheel")
    if not success:
        raise Exception("持续滚轮执行失败或被中止")
    return {
        "status": "Success",
        "active_port": "滚动完成",
        "value": inputs.get("__value__", True),
    }


# ==========================================
# 节点 4：强制粘贴
# ==========================================
paste_schema = {"粘贴文本": "Hello World", "操作前延迟(s)": "0.5"}


@register_node(name="强制粘贴", category="动作", schema=paste_schema)
def paste_text(config, inputs):
    text = config.get("粘贴文本", "")
    delay = float(config.get("操作前延迟(s)", 0.5))
    hwnd = inputs.get("hwnd") or win32gui.GetForegroundWindow()

    time.sleep(delay)
    bus.log_emitted.emit("INFO", "动作", f"📋 准备粘贴文本: {text}")

    success = execute_paste_text(hwnd, text, "DAG_Paste")

    if success:
        return {"status": "Success"}
    else:
        raise Exception("剪贴板操作失败。")


# ==========================================
# 节点 5：键盘操作
# ==========================================
keyboard_schema = {
    "操作类型": ["敲击单键", "模拟打字(纯英文/数字)"],
    "输入方式": ["前台物理(SendInput)", "后台消息(PostMessage)"],
    "目标窗口标题(后台消息)": "鸣潮",
    # 保留旧字段名，避免已有工作流加载时丢失配置；该字段现在也支持 CTRL+S。
    "按键名(如 F/SPACE/ENTER) 或 文本": "F",
    "按压时长(s)": "0.05",
    "操作前延迟(s)": "0.2",
}


@register_node(name="键盘操作", category="动作", schema=keyboard_schema)
def keyboard_action(config, inputs):
    action_type = config.get("操作类型", "敲击单键")
    input_mode = config.get("输入方式", "前台物理(SendInput)")
    use_post_message = "PostMessage" in input_mode
    target = config.get("按键名(如 F/SPACE/ENTER) 或 文本", "F")
    duration = float(config.get("按压时长(s)", 0.05))
    delay = float(config.get("操作前延迟(s)", 0.2))

    hwnd = inputs.get("hwnd")

    if use_post_message and not hwnd:
        from functions.func_window import get_target_window

        window_title = str(config.get("目标窗口标题(后台消息)", "鸣潮")).strip()
        hwnd, _ = get_target_window(window_title)
        if not hwnd:
            raise Exception(f"❌ 未找到后台键盘目标窗口: {window_title}")

    time.sleep(delay)

    if action_type == "敲击单键":
        target = str(target).upper()
        mode_label = "后台消息" if use_post_message else "前台物理"
        bus.log_emitted.emit("INFO", "动作", f"⌨️ 准备通过{mode_label}敲击: [{target}]")

        if use_post_message:
            success = execute_post_message_key_spec(
                hwnd, target, duration, f"DAG_{target}"
            )
        else:
            # 物理输入仍保留旧行为：上游给出句柄时先激活目标窗口。
            if hwnd:
                from functions.func_window import force_activate_window

                if not force_activate_window(hwnd, "DAG_Keyboard"):
                    raise Exception("❌ 目标窗口激活失败，为避免误输入已取消键盘操作。")
                time.sleep(0.1)

            success = execute_key_spec(target, duration, f"DAG_{target}")

    else:
        bus.log_emitted.emit("INFO", "动作", f"⌨️ 准备像人一样打字: '{target}'")
        if use_post_message:
            success = execute_post_message_text(
                hwnd, target, 0.05, "DAG_BackgroundTypeString"
            )
        else:
            if hwnd:
                from functions.func_window import force_activate_window

                if not force_activate_window(hwnd, "DAG_Keyboard"):
                    raise Exception("❌ 目标窗口激活失败，为避免误输入已取消模拟打字。")
                time.sleep(0.1)

            success = execute_type_string(target, 0.05, "DAG_TypeString")

    if success:
        return {"status": "Success", "hwnd": hwnd}
    else:
        raise Exception("键盘操作执行失败。")


# ==========================================
# 节点 6：动态变量粘贴 (读取Context并执行物理/后台粘贴)
# ==========================================
dynamic_paste_schema = {
    "__out_ports__": ["已粘贴"],
    "__out_descriptions__": {"已粘贴": "原样转发已经粘贴的文本 value"},
    "__input_required__": True,
    "节点标签": "粘贴上下文变量",
    "读取变量名": "current_cdkey",
    "输入方式": ["前台物理(SendInput)", "后台消息(PostMessage)"],
    "目标窗口标题(后台消息)": "鸣潮",
    "操作前延迟(s)": "0.5",
}


@register_node(name="动态变量粘贴", category="动作", schema=dynamic_paste_schema)
def dynamic_paste_action(config, inputs):
    tag = config.get("节点标签", "动态粘贴")
    var_name = config.get("读取变量名", "current_cdkey")
    input_mode = config.get("输入方式", "前台物理(SendInput)")
    use_post_message = "PostMessage" in input_mode
    delay = float(config.get("操作前延迟(s)", 0.5))

    # 新工作流直接读取上游 value；保留变量读取作为旧图纸兼容路径。
    context = inputs.get("__global_context__", {})
    hwnd = inputs.get("hwnd")
    if use_post_message and not hwnd:
        from functions.func_window import get_target_window

        window_title = str(config.get("目标窗口标题(后台消息)", "鸣潮")).strip()
        hwnd, _ = get_target_window(window_title)
        if not hwnd:
            raise Exception(f"❌ 未找到后台粘贴目标窗口: {window_title}")
    elif not hwnd:
        hwnd = win32gui.GetForegroundWindow()

    incoming_value = inputs.get("__value__")
    text_to_paste = incoming_value if isinstance(incoming_value, str) else ""
    if not text_to_paste:
        text_to_paste = get_context_value(context, var_name, default="")

    if not text_to_paste:
        raise Exception(
            f"❌ 粘贴失败：上下文变量 [{var_name}] 为空或未找到！请检查前置节点。"
        )

    time.sleep(delay)
    bus.log_emitted.emit(
        "INFO",
        "动作",
        f"📋 [{tag}] 读取到变量 [{var_name}]，准备粘贴: {text_to_paste}",
    )

    if use_post_message:
        # Unreal 游戏会把后台 Ctrl+V 同时解释成字母 v 和多次粘贴。
        # 直接发送 WM_CHAR，确保兑换码中的每个字符只进入输入框一次。
        success = execute_post_message_text(
            hwnd,
            str(text_to_paste),
            0.02,
            f"DAG_DynamicPaste_{var_name}",
        )
    else:
        # 保持原有三参数调用，兼容旧工作流和外部扩展。
        success = execute_paste_text(
            hwnd, str(text_to_paste), f"DAG_DynamicPaste_{var_name}"
        )

    if success:
        return {
            "status": "Success",
            "active_port": "已粘贴",
            "value": str(text_to_paste),
            "hwnd": hwnd,
        }
    else:
        raise Exception(f"[{tag}] 剪贴板操作失败。")
