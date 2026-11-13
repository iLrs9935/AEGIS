# nodes/triggers.py
from core.event_bus import bus

from . import register_node

try:
    from functions.func_window import get_target_window, is_process_running
except ImportError as e:
    print(f"⚠️ 警告: Triggers 底层库导入失败 ({e})")

# ---------------------------------------------------------
# 状态检测 (增加标签识别与显式分支 Log)
# ---------------------------------------------------------
check_schema = {
    "__out_ports__": ["已运行", "未运行"],
    "节点标签": "未命名检测",
    "检测模式": ["按窗口标题", "按进程名称(如 ok-ww.exe)"],
    "目标名称": "鸣潮",
}


@register_node(name="状态检测", category="触发", schema=check_schema)
def check_program_status(config, inputs):
    tag = config.get("节点标签", "状态检测")  # 提取标签
    mode = config.get("检测模式", "按窗口标题")
    target = config.get("目标名称", "").strip()

    if not target:
        raise Exception(f"❌ [{tag}] 目标名称不能为空！")

    is_running = False
    hwnd = None

    if "进程名称" in mode:
        bus.log_emitted.emit("INFO", "触发", f"[{tag}] 🔍 正在静默扫描进程树: {target}")
        is_running = is_process_running(target)
    else:
        bus.log_emitted.emit(
            "INFO", "触发", f"[{tag}] 🔍 正在扫描前台可视窗口: {target}"
        )
        hwnd, _ = get_target_window(target)
        is_running = hwnd is not None

    # 显式输出分支 Log
    if is_running:
        bus.log_emitted.emit(
            "SUCCESS", "触发", f"[{tag}] ✅ 分支：【已运行】 (确认目标: {target})"
        )
        result = {
            "status": "Success",
            "active_port": "已运行",
            "value": {"running": True, "hwnd": hwnd},
        }
        if hwnd:
            result["hwnd"] = hwnd
        return result
    else:
        bus.log_emitted.emit(
            "WARN", "触发", f"[{tag}] 🪹 分支：【未运行】 (未发现目标: {target})"
        )
        return {
            "status": "Success",
            "active_port": "未运行",
            "value": {"running": False, "hwnd": None},
        }
