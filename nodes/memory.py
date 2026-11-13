# nodes/memory.py
from core.event_bus import bus

from . import register_node

try:
    from functions.func_memory import vault
except ImportError as e:
    print(f"⚠️ 警告: Memory 底层库导入失败 ({e})")

# ---------------------------------------------------------
# 节点 1：写入记忆 (Data Injector)
# ---------------------------------------------------------
write_schema = {
    "__out_ports__": ["已写入"],
    "记忆键名 (Key)": "llm_context",
    "要写入的值 (可接线)": "",
}


@register_node(name="写入记忆", category="记忆", schema=write_schema)
def memory_write_node(config, inputs):
    key = config.get("记忆键名 (Key)", "").strip()

    # 动态数据覆盖：优先用连线传来的数据，其次用面板手填的数据
    val = inputs.get("要写入的值 (可接线)")
    if val is None:
        val = config.get("要写入的值 (可接线)", "")

    if not key:
        raise Exception("❌ 无法写入：记忆键名(Key)不能为空！")

    success = vault.write(key, val)
    if success:
        bus.log_emitted.emit("INFO", "Memory", f"💾 数据已持久化至磁道 -> [Key: {key}]")
        return {"status": "Success", "active_port": "已写入", "当前值": val}
    else:
        raise Exception("❌ 写入失败，底层保险库拒绝访问。")


# ---------------------------------------------------------
# 节点 2：提取记忆 (Data Extractor)
# ---------------------------------------------------------
read_schema = {
    "__out_ports__": ["提取成功", "无此记忆"],
    "记忆键名 (Key)": "llm_context",
}


@register_node(name="读取记忆", category="记忆", schema=read_schema)
def memory_read_node(config, inputs):
    key = config.get("记忆键名 (Key)", "").strip()
    if not key:
        raise Exception("❌ 无法读取：记忆键名(Key)不能为空！")

    val = vault.read(key)

    if val is not None:
        bus.log_emitted.emit("SUCCESS", "Memory", f"📂 提取记忆成功 -> [Key: {key}]")
        return {"status": "Success", "active_port": "提取成功", "提取的值": val}
    else:
        bus.log_emitted.emit(
            "WARN", "Memory", f"⚠️ 记忆保险库中未找到记录 -> [Key: {key}]"
        )
        return {"status": "Success", "active_port": "无此记忆", "提取的值": None}


# ---------------------------------------------------------
# 节点 3：神经擦除 (Memory Eraser)
# ---------------------------------------------------------
delete_schema = {
    "__out_ports__": ["已清理"],
    "目标键名 (输入 * 擦除全部)": "llm_context",
}


@register_node(name="删除记忆", category="记忆", schema=delete_schema)
def memory_delete_node(config, inputs):
    key = config.get("目标键名 (输入 * 擦除全部)", "").strip()

    if not key:
        raise Exception("❌ 目标键名不能为空！")

    if key == "*":
        vault.wipe_all()
        bus.log_emitted.emit(
            "ERROR", "Memory", "💥 警告：执行格式化指令！系统全盘记忆已彻底粉碎。"
        )
    else:
        vault.delete(key)
        bus.log_emitted.emit("INFO", "Memory", f"🗑️ 记忆簇已定点擦除 -> [Key: {key}]")

    return {"status": "Success", "active_port": "已清理"}
