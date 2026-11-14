from core.context import snapshot, mutate
# nodes/ai.py
from core.event_bus import bus
from functions.func_ai import generate_chat, load_model, unload_model
from functions.func_logic import get_context_value, set_context_value
from functions.func_memory import vault  # 👈 引入底层记忆武器库

from . import register_node

# ==========================================
# 1. 引擎管理：加载大模型
# ==========================================
load_schema = {
    "__out_ports__": ["加载成功", "加载失败"],
    "节点标签": "启动战术大脑",
    "模型路径": "$FILE$",
    "GPU层数": "35",
}


@register_node(name="加载大模型", category="AI核心", schema=load_schema)
def node_load_llm(config, inputs):
    success = load_model(config.get("模型路径"), config.get("GPU层数"))
    return {"status": "Success", "active_port": "加载成功" if success else "加载失败"}


# ==========================================
# 2. 引擎管理：卸载大模型 (释放显存)
# ==========================================
unload_schema = {
    "__out_ports__": ["已释放"],
    "节点标签": "休眠战术大脑",
}


@register_node(name="卸载大模型", category="AI核心", schema=unload_schema)
def node_unload_llm(config, inputs):
    unload_model()
    return {"status": "Success", "active_port": "已释放"}


# ==========================================
# 3. 数据处理：构建提示词 (旧版遗留，适配非Chat模型)
# ==========================================
prompt_schema = {
    "__out_ports__": ["构建完成"],
    "节点标签": "战术分析 Prompt",
    "系统指令": "你是一个冷酷的战术AI，只回答指令。",
    "动态内容": "当前血量：{hp}，怪物：{enemy}。请决策。",
    "输出变量名": "final_prompt",
}


@register_node(name="构建提示词", category="AI核心", schema=prompt_schema)
def node_build_prompt(config, inputs):
    context = inputs.get("__global_context__", {})
    sys_prompt = config.get("系统指令", "")
    raw_content = config.get("动态内容", "")
    out_var = config.get("输出变量名", "final_prompt")

    try:
        user_content = raw_content.format(**snapshot(context))
    except KeyError as e:
        user_content = raw_content
        bus.log_emitted.emit("WARN", "AI_Node", f"提示词缺少上下文变量: {e}")

    full_prompt = f"System: {sys_prompt}\nUser: {user_content}\nAssistant:"
    set_context_value(context, out_var, full_prompt)
    return {"status": "Success", "active_port": "构建完成"}


# ==========================================
# 4. 执行机构：大模型推理
# ==========================================
infer_schema = {
    "__out_ports__": ["推理完成", "推理报错"],
    "节点标签": "执行战术推理",
    "读取Prompt变量": "messages_array",
    "最大生成长度": "1024",
    "存入结果变量": "ai_decision",
}


@register_node(name="大模型推理", category="AI核心", schema=infer_schema)
def node_llm_inference(config, inputs):
    context = inputs.get("__global_context__", {})
    prompt_var = config.get("读取Prompt变量", "final_prompt")
    out_var = config.get("存入结果变量", "ai_decision")

    prompt = get_context_value(context, prompt_var)
    if not prompt:
        bus.log_emitted.emit("ERROR", "AI_Node", "找不到 Prompt！")
        return {"status": "Success", "active_port": "推理报错"}

    try:
        bus.log_emitted.emit("INFO", "AI_Node", "🧠 正在演算战术 (Chat模式)...")
        result = generate_chat(prompt, max_tokens=config.get("最大生成长度", 1024))
        set_context_value(context, out_var, result)
        bus.log_emitted.emit("SUCCESS", "AI_Node", f"💡 演算完毕，已写入 [{out_var}]")
        return {"status": "Success", "active_port": "推理完成"}
    except Exception as e:
        bus.log_emitted.emit("ERROR", "AI_Node", f"💥 推理崩溃: {e}")
        return {"status": "Success", "active_port": "推理报错"}


# ==========================================
# 5. 记忆流：加载历史并追加新问题 (加入滑动窗口截断机制)
# ==========================================
load_chat_schema = {
    "__out_ports__": ["组装完成"],
    "节点标签": "提取长期记忆",
    "记忆键名": "chat_history",
    "读取用户输入变量": "new_prompt",
    "最大上下文条数": "20",  # 👈 新增：限制最大消息数量 (含 System 和当前新问题)
    "存入对话组变量": "messages_array",
}


@register_node(name="加载并组装对话", category="AI核心", schema=load_chat_schema)
def node_load_chat(config, inputs):
    vault_key = config.get("记忆键名", "chat_history").strip()
    user_var = config.get("读取用户输入变量", "new_prompt").strip()
    out_var = config.get("存入对话组变量", "messages_array").strip()

    # 获取最大限制，默认20条
    try:
        max_msgs = int(config.get("最大上下文条数", "20"))
    except ValueError:
        max_msgs = 20

    context = inputs.get("__global_context__", {})
    user_text = get_context_value(context, user_var) or "..."

    # 1. 调用底层 Func 读取 SQLite
    history = vault.read(vault_key)
    if not isinstance(history, list):
        history = []

    # =========================================================
    # 2. 核心：上下文滑动窗口截断逻辑
    # =========================================================
    # 我们需要预留 1 个位置给马上要塞进去的新问题 (user_text)
    limit = max(1, max_msgs - 1)

    if len(history) > limit:
        # 保护机制：如果第一条是系统设定 (system prompt)，绝对不能被裁掉
        if len(history) > 0 and history[0].get("role") == "system":
            system_prompt = history[0]
            # 截取末尾的老旧记忆 (腾出1个位置给 system_prompt)
            keep_count = limit - 1
            keep_history = history[-keep_count:] if keep_count > 0 else []
            history = [system_prompt] + keep_history
        else:
            # 没有系统设定，直接切除开头的旧记忆
            history = history[-limit:]

    # 3. 追加当前的新问题
    history.append({"role": "user", "content": user_text})

    # 4. 更新到节点图上下文
    set_context_value(context, out_var, history)

    bus.log_emitted.emit(
        "INFO",
        "Memory",
        f"📂 对话已就绪，当前共 {len(history)} 条记录 (上限: {max_msgs}条)。",
    )
    return {"status": "Success", "active_port": "组装完成"}


# ==========================================
# 6. 记忆流：追加并封存记忆 (从 chat_memory 迁移并瘦身)
# ==========================================
save_chat_schema = {
    "__out_ports__": ["保存完成"],
    "节点标签": "刻入长期记忆",
    "记忆键名": "chat_history",
    "读取对话组变量": "messages_array",
    "读取AI回复变量": "ai_decision",
}


@register_node(name="追加并保存对话", category="AI核心", schema=save_chat_schema)
def node_save_chat(config, inputs):
    vault_key = config.get("记忆键名", "chat_history").strip()
    array_var = config.get("读取对话组变量", "messages_array").strip()
    ai_var = config.get("读取AI回复变量", "ai_decision").strip()
    context = inputs.get("__global_context__", {})

    def append_reply(data):
        history = data.get(array_var)
        ai_text = data.get(ai_var)
        if isinstance(history, list) and ai_text:
            history.append({"role": "assistant", "content": ai_text})
            return list(history)
        return None
    history = mutate(context, append_reply)
    if history is not None:

        # 调用底层 Func (vault.write) 写入 SQLite
        vault.write(vault_key, history)
        bus.log_emitted.emit("SUCCESS", "Memory", "💾 AI 完整记忆轮回已更新至数据库。")

    return {"status": "Success", "active_port": "保存完成"}
