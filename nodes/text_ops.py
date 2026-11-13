# nodes/text_ops.py
from core.event_bus import bus
from functions.func_logic import get_context_value, set_context_value
from functions.func_text import (  # 👈 补充引入
    format_simple_display,
    merge_strings,
)

from . import register_node

# ==========================================
# 1. 极简：纯文本输入框 (新增)
# ==========================================
simple_text_input_schema = {
    "__out_ports__": ["文本输出"],
    "节点标签": "文本输入",
    "文本内容": "$TEXTAREA$",  # 👈 魔法标识，UI会自动渲染成大输入框
    "存入变量名": "new_prompt",
}


@register_node(name="文本输入", category="文本", schema=simple_text_input_schema)
def node_simple_text_input(config, inputs):
    tag = config.get("节点标签", "文本输入")
    text = config.get("文本内容", "")
    out_var = config.get("存入变量名", "user_text_1").strip()

    context = inputs.get("__global_context__", {})
    set_context_value(context, out_var, text)

    bus.log_emitted.emit("INFO", "Text", f"[{tag}] 已注入纯文本：{text[:15]}...")
    return {"status": "Success", "active_port": "文本输出"}


# ==========================================
# 2. 多文本合并 (保留原样)
# ==========================================
text_merge_schema = {
    "__out_ports__": ["合并完成", "缺少变量"],
    "节点标签": "合并战术信息",
    "读取变量A": "system_prompt",
    "读取变量B": "enemy_info",
    "连接符": "\\n",
    "存入变量名": "new_prompt",
}


@register_node(name="多文本合并", category="文本", schema=text_merge_schema)
def node_text_merge(config, inputs):
    tag = config.get("节点标签", "文本合并")
    var_a = config.get("读取变量A", "").strip()
    var_b = config.get("读取变量B", "").strip()
    out_var = config.get("存入变量名", "merged_text").strip()

    context = inputs.get("__global_context__", {})
    text_a = get_context_value(context, var_a)
    text_b = get_context_value(context, var_b)

    if text_a is None or text_b is None:
        return {"status": "Success", "active_port": "缺少变量"}

    merged_text = merge_strings(text_a, text_b, config.get("连接符", "\\n"))

    set_context_value(context, out_var, merged_text)
    bus.log_emitted.emit("SUCCESS", "Text", f"[{tag}] 🔗 拼接成功 -> [{out_var}]")
    return {"status": "Success", "active_port": "合并完成"}


# ==========================================
# 4. 极简：纯文本只读展示板 (新增)
# ==========================================
simple_text_show_schema = {
    "__out_ports__": ["通过"],
    "节点标签": "只读展示板",
    "读取变量名": "ai_decision",
    "展示内容": "$TEXTAREA$",
}


@register_node(name="文本展示", category="文本", schema=simple_text_show_schema)
def node_simple_text_show(config, inputs):
    tag = config.get("节点标签", "文本展示")
    var_name = config.get("读取变量名", "").strip()

    context = inputs.get("__global_context__", {})
    raw_text = get_context_value(context, var_name)

    # 极简格式化打印
    clean_text = format_simple_display(raw_text)
    bus.log_emitted.emit("SUCCESS", "Text", f"[{tag}] -> {clean_text[:50]}...")

    # [核心：向 UI 画板发送文字更新信号]
    try:
        node_id = inputs.get("__node_id__")
        if node_id:
            bus.node_text_updated.emit(node_id, clean_text)
    except AttributeError:
        pass  # UI 未适配时静默跳过

    return {"status": "Success", "active_port": "通过"}
