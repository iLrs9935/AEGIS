# nodes/system.py
import os
import time

from core.event_bus import bus

from . import register_node

try:
    from functions.func_process import execute_start_process
    from functions.func_system import (
        execute_delayed_hibernate,
        execute_self_destruct,
        execute_sleep,
    )
    from functions.func_window import (
        force_activate_window,
        get_target_window,
        kill_specific_processes,
        kill_windows_by_titles,
    )
except ImportError as e:
    print(f"⚠️ 警告: System 底层库导入失败 ({e})")

# ---------------------------------------------------------
# 节点 1：硬核启动器
# ---------------------------------------------------------
start_schema = {
    "程序路径": "$FILE$",
    "启动参数": "",
    "已运行时": ["跳过重复启动", "再次调用以唤醒窗口"],
    "等待启动(s)": "3.0",
    "工作目录": "",
    "OK-WW更新后恢复启动": ["否", "是"],
}


@register_node(name="启动程序", category="系统", schema=start_schema)
def start_program(config, inputs):
    path = config.get("程序路径", "")
    args = config.get("启动参数", "")
    launch_if_running = config.get("已运行时", "跳过重复启动") == "再次调用以唤醒窗口"
    delay = float(config.get("等待启动(s)", 3.0))
    working_dir = str(config.get("工作目录", "")).strip()

    if config.get("OK-WW更新后恢复启动") == "是":
        from nodes.okww import STATE_KEY
        import subprocess
        state = inputs.get("__global_context__", {}).get(STATE_KEY, {})
        if state.get("launch_worker_directly"):
            settings = state["settings"]
            script = settings["okww_main_script"]
            if not os.path.isfile(script):
                raise Exception(f"更新后的 OK-WW 主脚本不存在: {script}")
            path = settings["okww_worker_executable"]
            args = f'{subprocess.list2cmdline([script])} {args}'.strip()
            working_dir = os.path.dirname(os.path.abspath(script))
            bus.log_emitted.emit("INFO", "System", "更新已完成，使用 OK-WW 自带 Python 恢复每日任务参数。")

    if not path or path == "$FILE$":
        raise Exception("❌ 程序路径不能为空，请点击 [...] 选择文件！")
    bus.log_emitted.emit("INFO", "System", f"🚀 尝试拉起程序: {os.path.basename(path)}")

    # 调用底层火控 (不再传 cwd，底层会自动根据 path 提取绝对工作目录)
    launch_options = {"launch_if_running": launch_if_running}
    if working_dir:
        launch_options["working_dir"] = working_dir
    success, pid = execute_start_process(path, args, **launch_options)

    if success:
        if not execute_sleep(delay):
            return {"status": "Success", "pid": pid}
        return {"status": "Success", "pid": pid}
    else:
        if config.get("OK-WW更新后恢复启动") == "是":
            from nodes.okww import STATE_KEY
            state = inputs.get("__global_context__", {}).get(STATE_KEY)
            if isinstance(state, dict):
                state["launch_error"] = "OK-WW 程序启动失败，请检查路径或权限"
                return {"status": "Success", "pid": None}
        raise Exception("程序启动失败，请检查路径或权限。")


# ---------------------------------------------------------
# 节点 2：进程终结者
# ---------------------------------------------------------
close_schema = {
    "__out_ports__": ["已清理"],
    "节点标签": "清理现场",
    "目标模式": ["按窗口标题(智能关闭)", "按进程名称(强制猎杀)"],
    "目标名称(如 鸣潮 或 ok-ww.exe)": "鸣潮",
    "执行方式(针对窗口)": ["优雅关闭(发WM_CLOSE)", "强制终止(TaskKill)"],
}


@register_node(name="结束进程", category="系统", schema=close_schema)
def close_program(config, inputs):
    tag = config.get("节点标签", "结束进程")
    mode = config.get("目标模式", "按窗口标题(智能关闭)")
    target = config.get("目标名称(如 鸣潮 或 ok-ww.exe)", "").strip()
    action = config.get("执行方式(针对窗口)", "优雅关闭(发WM_CLOSE)")

    if not target:
        raise Exception(f"❌ [{tag}] 目标名称不能为空，请输入要关闭的标题或进程名！")

    try:
        # 假设这两个底层函数你已经在顶部 import 了
        if "进程名称" in mode:
            bus.log_emitted.emit(
                "INFO", "系统", f"[{tag}] 💀 准备强制猎杀进程: {target}"
            )
            kill_specific_processes([target])
        else:
            graceful = "优雅关闭" in action
            bus.log_emitted.emit(
                "INFO",
                "系统",
                f"[{tag}] 🛑 准备处理窗口: {target} (优雅关闭: {graceful})",
            )
            kill_windows_by_titles([target], graceful=graceful, protect_browser=True)

        bus.log_emitted.emit(
            "SUCCESS", "系统", f"[{tag}] ✅ 目标 [{target}] 已确认清理"
        )

    except Exception as e:
        # 就算杀进程报错了（比如权限不足、找不到进程），也不要崩溃，而是当做已经清理完毕
        bus.log_emitted.emit(
            "WARN", "系统", f"[{tag}] ⚠️ 清理时发生小插曲 (可能目标本就不存在): {e}"
        )

    # 稍微等一小会儿让系统缓一缓 (释放句柄等)
    import time

    time.sleep(1.0)

    # [核心修复 2]：指明走向，告诉引擎稳稳地走向下一个节点
    return {"status": "Success", "active_port": "已清理"}


# ---------------------------------------------------------
# 节点 3：S4 休眠（可取消，支持无人值守成功校验）
# ---------------------------------------------------------
sleep_schema = {
    "执行前倒计时(s)": "5",
    "执行动作": ["S4休眠并退出终端", "仅退出终端(不休眠)", "保留终端(不休眠)"],
    "休眠前校验": ["无需额外校验", "本次OK-WW成功且清理完成"],
}


@register_node(name="系统休眠", category="系统", schema=sleep_schema)
def s4_hibernate_and_exit(config, inputs):
    action = config.get("执行动作", "S4休眠并退出终端")

    if action not in sleep_schema["执行动作"]:
        bus.log_emitted.emit("ERROR", "System", "执行动作无效，已停止执行电源操作。")
        return {"status": "Error"}

    if action == "保留终端(不休眠)":
        bus.log_emitted.emit("WARN", "System", "本轮已停止，保留终端和日志，不执行休眠或退出。")
        return {"status": "Success", "value": inputs.get("__value__")}

    # The exit-only label also contains 休眠; power actions require exact matching.
    if action == "S4休眠并退出终端":
        from functions import func_system
        from nodes.okww import STATE_KEY, verify_power_ready

        context = inputs.get("__global_context__", {})
        policy = config.get("休眠前校验", "无需额外校验")
        if policy not in sleep_schema["休眠前校验"]:
            return {"status": "Error"}
        # Old daily files also require proof once OK-WW preflight has run.
        guarded = policy == "本次OK-WW成功且清理完成" or STATE_KEY in context
        if guarded:
            ready, reason = verify_power_ready(context)
            if not ready:
                bus.log_emitted.emit("ERROR", "System", f"已拦截休眠：{reason}")
                return {"status": "Error"}
        try:
            delay = int(config.get("执行前倒计时(s)", 5))
            if delay < 0:
                raise ValueError("negative delay")
        except (TypeError, ValueError):
            bus.log_emitted.emit("ERROR", "System", "休眠倒计时必须为非负整数。")
            return {"status": "Error"}
        bus.log_emitted.emit(
            "WARN",
            "System",
            f"休眠倒计时 {delay} 秒；点击停止可取消，终端将保持打开直到倒计时结束。",
        )

        if func_system.SAFE_POWER_MODE:
            bus.log_emitted.emit("WARN", "System", "安全验证模式：已拦截实际休眠和退出。")
            return {"status": "Success"}
        for remaining in range(delay, 0, -1):
            if remaining == delay or remaining <= 5 or remaining % 10 == 0:
                bus.log_emitted.emit("WARN", "System", f"距离休眠 {remaining} 秒，停止可取消。")
            if not execute_sleep(1):
                return {"status": "Cancelled"}
        if guarded:
            ready, reason = verify_power_ready(context)
            if not ready:
                bus.log_emitted.emit("ERROR", "System", f"倒计时结束后拦截休眠：{reason}")
                return {"status": "Error"}
        success = execute_delayed_hibernate(0)
        if not success:
            bus.log_emitted.emit("ERROR", "System", "休眠已取消或系统拒绝执行，保留终端。")
            return {"status": "Error"}
    else:
        bus.log_emitted.emit("WARN", "System", "👋 接收到退出指令，准备退出终端...")

    # 呼叫 HAL 层挂起一小会儿，确保 UI 日志渲染完毕
    if not execute_sleep(1.0):
        return {"status": "Cancelled"}

    bus.log_emitted.emit("INFO", "System", "正在退出 AEGIS 终端。")
    if not execute_sleep(0.5):
        return {"status": "Cancelled"}

    # ================= 终极自毁程序 =================
    # 呼叫 HAL 层执行物理拔管
    execute_self_destruct()

    # 因为进程已经被拔管，这行代码理论上永远不会被执行，但符合节点协议
    return {"status": "Success"}


# ---------------------------------------------------------
# 节点 4：蓝图跃迁引擎 (Blueprint Jumper)
# ---------------------------------------------------------
jump_schema = {
    "节点标签": "核心接管",
    "目标图纸路径": "$FILE$",
    "点火倒计时(s)": "1.0",
}


@register_node(name="运行新图纸", category="系统", schema=jump_schema)
def execute_blueprint_jump(config, inputs):
    tag = config.get("节点标签", "核心接管")
    path = config.get("目标图纸路径", "")
    delay = float(config.get("点火倒计时(s)", 1.0))

    if not path or path == "$FILE$":
        raise Exception(
            f"❌ [{tag}] 跃迁坐标缺失！请点击 [...] 选择要加载的 .json 图纸！"
        )
    if not os.path.exists(path):
        raise Exception(f"❌ [{tag}] 坐标解析失败，找不到实体文件: {path}")

    bus.log_emitted.emit(
        "WARN",
        "系统",
        f"[{tag}] 🌀 触发蓝图跃迁序列！引擎将在 {delay} 秒后被强制夺舍...",
    )
    execute_sleep(delay)

    try:
        bus.blueprint_jump_requested.emit(path)
    except AttributeError:
        raise Exception("总线拒绝访问。")

    bus.log_emitted.emit(
        "SUCCESS", "系统", f"[{tag}] ✨ 跃迁信号弹已升空，当前执行线程执行物理切断！"
    )
    return {"status": "Jump_Triggered", "active_port": None}


# ---------------------------------------------------------
# 节点 5：窗口强制唤醒 (Focus Overrider)
# ---------------------------------------------------------
activate_window_schema = {
    "__out_ports__": ["已唤醒(继续)", "未找到目标(阻断)"],
    "节点标签": "强制置顶",
    "目标窗口标题": "鸣潮",
    "操作前延迟(s)": "0.5",
    "操作后稳定延迟(s)": "1.0",
}


@register_node(name="唤醒并置顶窗口", category="系统", schema=activate_window_schema)
def activate_target_window(config, inputs):
    tag = config.get("节点标签", "强制置顶")
    target_title = config.get("目标窗口标题", "鸣潮").strip()
    delay_before = float(config.get("操作前延迟(s)", 0.5))
    delay_after = float(config.get("操作后稳定延迟(s)", 1.0))

    if not target_title:
        raise Exception(f"❌ [{tag}] 目标窗口标题不能为空！")

    # 执行前等待
    time.sleep(delay_before)
    bus.log_emitted.emit(
        "INFO", "System", f"[{tag}] 🔍 尝试寻获并唤醒窗口: '{target_title}'"
    )

    # 1. 调用底层寻获窗口
    hwnd, rect = get_target_window(target_title)

    if not hwnd:
        bus.log_emitted.emit(
            "WARN", "System", f"[{tag}] 👻 未能找到标题包含 '{target_title}' 的窗口"
        )
        return {"status": "Success", "active_port": "未找到目标(阻断)"}

    # 2. 呼叫底层执行强制暴力置顶
    try:
        # 因为你底层的 force_activate_window 已经自带了 log() 推送，这里只需调用即可
        success = force_activate_window(hwnd, f"DAG_{tag}")

        if success:
            bus.log_emitted.emit(
                "SUCCESS", "System", f"[{tag}] ✨ 夺权成功！窗口已锁定在前台。"
            )
        else:
            bus.log_emitted.emit(
                "WARN",
                "System",
                f"[{tag}] ⚠️ 激活指令已发送，但系统未能确认窗口是否绝对置顶。",
            )
    except Exception as e:
        bus.log_emitted.emit("ERROR", "System", f"[{tag}] ❌ 强制激活时遭到抵抗: {e}")

    # 给游戏引擎一点时间渲染画面，防止立刻寻图导致黑屏/灰屏
    time.sleep(delay_after)

    # 3. 核心：将句柄(hwnd)打包进 payload 传递给下游的视觉/动作节点
    return {
        "status": "Success",
        "active_port": "已唤醒(继续)",
        "hwnd": hwnd,  # 下游的 physical_click 或 find_target_image 可以直接用
        "target_title": target_title,
    }
