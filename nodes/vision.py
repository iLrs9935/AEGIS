# nodes/vision.py
from typing import Any
import sys

from core.event_bus import bus
from nodes import register_node  # 仅保留这一个正常的导入！

vision_schema: dict[str, Any] = {
    "__out_ports__": ["OUT"],
    "__out_descriptions__": {"OUT": "寻图结果：found、坐标、置信度"},
    "执行模式": ["前台(拉起窗口)", "后台(静默寻图)"],
    "节点标签": "未命名检测",
    "窗口标题": "明日方舟",
    "图片路径": "$FILE$",
    "置信度": "0.75",
    "灰度匹配": ["是", "否"],
    "匹配策略": ["最高置信度", "从上到下(Y轴)", "从左到右(X轴)", "网格阅读(Z字)"],
    "目标序号(第几个)": "1",
    "重试次数": "5",  # UI已暴露
    "重试间隔(s)": "1.0",  # UI已暴露
}


@register_node(name="视觉寻图", category="视觉", schema=vision_schema)
def find_target_image(config, inputs):
    window_title = config.get("窗口标题", "")
    tag = config.get("节点标签", "未命名寻图")
    pic_path = config.get("图片路径", "")

    # ======== [终极解禁：相对路径动态解析] ========
    import os

    if pic_path and pic_path != "$FILE$":
        if getattr(sys, "frozen", False):
            app_base_dir = os.path.dirname(sys.executable)
        else:
            app_base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

        # 相对资源一律以源码根目录或 EXE 所在目录为基准，避免任务计划
        # 程序从 System32 启动时因 cwd 不同而丢图。
        if not os.path.isabs(pic_path):
            candidates = [
                os.path.join(app_base_dir, pic_path),
                os.path.join(getattr(sys, "_MEIPASS", app_base_dir), pic_path),
                os.path.join(os.getcwd(), pic_path),
            ]
            pic_path = next(
                (os.path.abspath(path) for path in candidates if os.path.exists(path)),
                os.path.abspath(candidates[0]),
            )
        # 兜底：如果绝对路径不存在，尝试强行切成相对路径再找一遍（防止带了 E盘 的老数据）
        if not os.path.exists(pic_path):
            # 提取 "data/images/..." 之后的部分
            parts = pic_path.replace("\\", "/").split("/data/")
            if len(parts) > 1:
                fallback_path = os.path.join(os.getcwd(), "data", parts[-1])
                if os.path.exists(fallback_path):
                    pic_path = fallback_path
    # ============================================
    conf = float(config.get("置信度", 0.75))
    grayscale = config.get("灰度匹配", "是") == "是"
    mode = config.get("执行模式", "前台(拉起窗口)")
    match_strategy = config.get("匹配策略", "最高置信度")
    target_index = int(config.get("目标序号(第几个)", 1))

    # [新增]: 提取 UI 配置中的重试参数，并做类型转换和兜底
    retry_count = int(config.get("重试次数", 5))
    retry_interval = float(config.get("重试间隔(s)", 1.0))

    is_bg = "后台" in mode

    if not pic_path or pic_path == "$FILE$":
        raise Exception("❌ 请点击 [...] 选择目标图片路径！")

    bus.log_emitted.emit(
        "INFO",
        "Vision",
        f"👁️ 锁定窗口 [{window_title}]，准备寻图 ({mode})，重试配置: {retry_count}次/{retry_interval}s",
    )

    from functions.func_vision import execute_template_match
    from functions.func_window import get_target_window

    hwnd, rect = get_target_window(window_title)
    if not hwnd:
        bus.log_emitted.emit(
            "WARN", "Vision", f"⚠️ 未找到标题包含 '{window_title}' 的窗口！"
        )
        return {
            "status": "Success",
            "active_port": "OUT",
            "value": {"found": False, "reason": "window_not_found"},
        }

    pos, max_val = execute_template_match(
        hwnd=hwnd,
        rect=rect,
        pic_path=pic_path,
        confidence=conf,
        grayscale=grayscale,
        is_background=is_bg,
        match_strategy=match_strategy,
        target_index=target_index,
        retry_count=retry_count,  # [新增]: 传入重试次数
        retry_interval=retry_interval,  # [新增]: 传入重试间隔
    )

    if pos is not None and max_val >= conf:
        bus.log_emitted.emit(
            "SUCCESS",
            "Vision",
            f"[{tag}] 🎯 分支：【找到目标】 (置信度: {max_val:.3f}, 坐标: {pos})",
        )
        return {
            "status": "Success",
            "active_port": "OUT",
            "value": {
                "found": True,
                "target_x": pos[0],
                "target_y": pos[1],
                "hwnd": hwnd,
                "confidence": max_val,
            },
            "target_x": pos[0],
            "target_y": pos[1],
            "hwnd": hwnd,
        }
    else:
        bus.log_emitted.emit(
            "WARN", "Vision", f"[{tag}] 👻 分支：【未找到】 (最高置信度: {max_val:.3f})"
        )
        return {
            "status": "Success",
            "active_port": "OUT",
            "value": {
                "found": False,
                "confidence": max_val,
                "reason": "not_found",
            },
        }
