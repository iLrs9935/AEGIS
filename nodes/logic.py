from core.context import mutate
# nodes/logic.py
from core.event_bus import bus
from core.signals import parse_signal_value
from functions.func_logic import (
    check_logic_and,
    check_logic_or,
    get_context_value,
    set_context_value,
)

from . import register_node

# ==========================================
# 1. 信号暂存器 (Buffer) - 记事本
# ==========================================
buffer_schema = {
    "__out_ports__": ["继续"],
    "节点标签": "记录状态",
    "变量名": "ww_done",
    "写入值": ["True", "False"],
}


@register_node(name="信号暂存器", category="逻辑", schema=buffer_schema)
def signal_buffer(config, inputs):
    tag = config.get("节点标签", "暂存器")
    var_name = config.get("变量名", "temp_sig")
    val = config.get("写入值") == "True"

    context = inputs.get("__global_context__", {})
    set_context_value(context, var_name, val)

    bus.log_emitted.emit("INFO", "Logic", f"[{tag}] 📝 变量 [{var_name}] 已存入: {val}")
    return {"status": "Success", "active_port": "继续"}


# ==========================================
# 2. 逻辑中继器 (Relay) - 条件开关
# ==========================================
relay_schema = {
    "__out_ports__": ["通过", "阻断"],
    "节点标签": "条件闸门",
    "控制变量名": "ww_done",
    "通过条件": ["True", "False"],
}


@register_node(name="信号中继器", category="逻辑", schema=relay_schema)
def signal_relay(config, inputs):
    tag = config.get("节点标签", "中继器")
    ctrl_var = config.get("控制变量名", "")
    condition = config.get("通过条件") == "True"

    context = inputs.get("__global_context__", {})
    current_val = get_context_value(context, ctrl_var, default=False)

    if current_val == condition:
        bus.log_emitted.emit(
            "SUCCESS", "Logic", f"[{tag}] 🟢 分支：【通过】 (变量 {ctrl_var} 符合条件)"
        )
        return {"status": "Success", "active_port": "通过"}
    else:
        bus.log_emitted.emit(
            "WARN", "Logic", f"[{tag}] 🔴 分支：【阻断】 (变量 {ctrl_var} 不符条件)"
        )
        return {"status": "Success", "active_port": "阻断"}


# ==========================================
# 3. 逻辑与门 (AND) - 必须全员到齐
# ==========================================
and_gate_schema = {
    "__out_ports__": ["全选通", "等待中"],
    "节点标签": "必须都完成",
    "检测信号列表": "ww_done,ark_done",  # 逗号分隔
}


@register_node(name="逻辑与门", category="逻辑", schema=and_gate_schema)
def logic_and_node(config, inputs):
    tag = config.get("节点标签", "与门")
    keys = config.get("检测信号列表", "").split(",")

    context = inputs.get("__global_context__", {})
    is_all_done = check_logic_and(context, keys)

    if is_all_done:
        bus.log_emitted.emit(
            "SUCCESS", "Logic", f"[{tag}] 🎉 分支：【全选通】 (所有指定信号均为True)"
        )
        return {"status": "Success", "active_port": "全选通"}
    else:
        bus.log_emitted.emit(
            "INFO", "Logic", f"[{tag}] ⏳ 分支：【等待中】 (部分信号未准备好)"
        )
        return {"status": "Success", "active_port": "等待中"}


# ==========================================
# 4. 逻辑或门 (OR) - 只要有人出列就行
# ==========================================
or_gate_schema = {
    "__out_ports__": ["有选通", "全无信号"],
    "节点标签": "任意完成即可",
    "检测信号列表": "ww_done,ark_done",  # 逗号分隔
}


@register_node(name="逻辑或门", category="逻辑", schema=or_gate_schema)
def logic_or_node(config, inputs):
    tag = config.get("节点标签", "或门")
    keys = config.get("检测信号列表", "").split(",")

    context = inputs.get("__global_context__", {})
    is_any_done = check_logic_or(context, keys)

    if is_any_done:
        bus.log_emitted.emit(
            "SUCCESS", "Logic", f"[{tag}] ⚡ 分支：【有选通】 (检测到至少一个True信号)"
        )
        return {"status": "Success", "active_port": "有选通"}
    else:
        bus.log_emitted.emit(
            "INFO", "Logic", f"[{tag}] 🕳️ 分支：【全无信号】 (指定信号全为False或空)"
        )
        return {"status": "Success", "active_port": "全无信号"}


# ==========================================
# 5. 逻辑非门 (NOT) - 专门抬杠
# ==========================================
not_gate_schema = {
    "__out_ports__": ["无信号(通过)", "有信号(阻断)"],
    "节点标签": "非门拦截",
    "检测变量名": "bark_sent",
}


@register_node(name="逻辑非门", category="逻辑", schema=not_gate_schema)
def logic_not_node(config, inputs):
    tag = config.get("节点标签", "非门")
    key = config.get("检测变量名", "")

    context = inputs.get("__global_context__", {})
    # 如果没这个变量，或者变量是 False，非门就放行
    current_val = get_context_value(context, key, default=False)

    if not current_val:
        bus.log_emitted.emit(
            "SUCCESS", "Logic", f"[{tag}] 🟢 分支：【无信号(通过)】 (没检测到 {key})"
        )
        return {"status": "Success", "active_port": "无信号(通过)"}
    else:
        bus.log_emitted.emit(
            "WARN", "Logic", f"[{tag}] 🛑 分支：【有信号(阻断)】 ({key} 已存在，拦截)"
        )
        return {"status": "Success", "active_port": "有信号(阻断)"}


# nodes/logic.py (追加以下代码)

# ==========================================
# 6. 数组遍历器 (Iterator) - 循环拆包
# ==========================================
iterator_schema = {
    "__out_ports__": ["弹出元素(继续)", "队列为空(完成)"],
    "__out_descriptions__": {
        "弹出元素(继续)": "直接输出当前数组元素作为 value",
        "队列为空(完成)": "所有元素均已取出，结束循环",
    },
    "__input_required__": True,
    "节点标签": "数组遍历",
    "目标数组变量名": "cdkeys_array",  # 假设上游爬虫把数组存到了这个变量
    "当前元素存入变量": "current_cdkey",  # 弹出的单个码存到这个变量
}


@register_node(name="数组遍历器", category="逻辑", schema=iterator_schema)
def logic_iterator_node(config, inputs):
    tag = config.get("节点标签", "遍历器")
    arr_var = config.get("目标数组变量名", "cdkeys_array")
    out_var = config.get("当前元素存入变量", "current_cdkey")

    context = inputs.get("__global_context__", {})

    node_id = inputs.get("__node_id__", "iterator")
    runtime_queue_key = f"__iterator_queue__:{node_id}"
    incoming_value = inputs.get("__value__")

    def take(data):
        if isinstance(incoming_value, (list, tuple)):
            data[runtime_queue_key] = list(incoming_value)
        elif runtime_queue_key not in data:
            legacy = data.get(arr_var, [])
            data[runtime_queue_key] = list(legacy) if isinstance(legacy, list) else []
        queue = data[runtime_queue_key]
        if not isinstance(queue, list) or not queue:
            return False, None, 0
        item = queue.pop(0)
        data[arr_var] = list(queue)
        data[out_var] = item
        return True, item, len(queue)

    available, popped_item, remaining = mutate(context, take)
    if not available:
        bus.log_emitted.emit("WARN", "Logic", f"[{tag}] 队列 [{arr_var}] 已耗尽")
        return {"status": "Success", "active_port": "队列为空(完成)"}

    bus.log_emitted.emit(
        "SUCCESS",
        "Logic",
        f"[{tag}] 🔄 成功弹出元素: '{popped_item}' (剩余 {remaining} 个)",
    )
    return {
        "status": "Success",
        "active_port": "弹出元素(继续)",
        "value": popped_item,
    }


# ==========================================
# 7. 数据分流器 - single value / configurable output rules
# ==========================================
signal_router_schema = {
    "__out_ports__": ["True", "False"],
    "__dynamic_router__": True,
    "__input_required__": True,
    "节点标签": "数据分流",
    "输入选择": ["最后一个", "第一个"],
    "匹配模式": ["首个匹配", "全部匹配"],
    "路由规则": {
        "$widget": "route_rules",
        "default": [
            {"port": "True", "path": "", "operator": "等于", "target": "true"},
            {"port": "False", "path": "", "operator": "等于", "target": "false"},
        ],
    },
    "未匹配时": ["终止工作流", "走默认出口"],
    "默认出口名称": "默认",
}


_MISSING = object()


def _extract_route_value(value, path):
    path = str(path or "").strip()
    if path in {"", "value", "$value"}:
        return value
    current = value
    for part in path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
            continue
        if isinstance(current, (list, tuple)):
            try:
                current = current[int(part)]
                continue
            except (ValueError, IndexError):
                pass
        return _MISSING
    return current


def _compare_route_value(actual, expected, operator):
    if operator == "存在":
        return actual is not _MISSING
    if operator == "不存在":
        return actual is _MISSING
    if actual is _MISSING:
        raise ValueError("路由规则引用了不存在的字段")
    both_numbers = (
        not isinstance(actual, bool)
        and not isinstance(expected, bool)
        and isinstance(actual, (int, float))
        and isinstance(expected, (int, float))
    )
    if operator == "等于":
        return (both_numbers or type(actual) is type(expected)) and actual == expected
    if operator == "不等于":
        return not ((both_numbers or type(actual) is type(expected)) and actual == expected)
    if operator == "包含":
        try:
            return expected in actual
        except TypeError as exc:
            raise ValueError("“包含”只能用于文本、数组或对象") from exc
    if isinstance(actual, bool) or isinstance(expected, bool):
        raise ValueError(f"“{operator}”不能比较布尔值")
    if not (
        isinstance(actual, (int, float)) and isinstance(expected, (int, float))
    ) and type(actual) is not type(expected):
        raise ValueError(f"“{operator}”两侧的数据类型不一致")
    operations = {
        "大于": lambda left, right: left > right,
        "大于等于": lambda left, right: left >= right,
        "小于": lambda left, right: left < right,
        "小于等于": lambda left, right: left <= right,
    }
    if operator not in operations:
        raise ValueError(f"未知比较方式：{operator}")
    try:
        return operations[operator](actual, expected)
    except TypeError as exc:
        raise ValueError(f"“{operator}”无法比较当前 value") from exc


@register_node(name="信号分流器", category="逻辑", schema=signal_router_schema)
def signal_router_node(config, inputs):
    tag = config.get("节点标签", "数据分流")
    envelopes = inputs.get("__signals__", [])
    if not envelopes:
        raise ValueError("数据分流器没有收到上游 value")
    envelope = envelopes[0] if config.get("输入选择") == "第一个" else envelopes[-1]
    value = envelope.get("value")
    rules = config.get("路由规则", [])
    if not isinstance(rules, list) or not rules:
        raise ValueError("数据分流器没有配置任何路由规则")

    active_ports = []
    matched_rules = []
    for rule in rules:
        if not isinstance(rule, dict):
            raise ValueError("路由规则格式不正确")
        port = str(rule.get("port", "")).strip()
        if not port:
            raise ValueError("路由规则缺少输出端口名称")
        operator = str(rule.get("operator", "等于"))
        actual = _extract_route_value(value, rule.get("path", ""))
        expected = parse_signal_value(rule.get("target", ""))
        if _compare_route_value(actual, expected, operator):
            if port not in active_ports:
                active_ports.append(port)
            matched_rules.append(port)
            if config.get("匹配模式", "首个匹配") == "首个匹配":
                break

    if not active_ports:
        if config.get("未匹配时", "终止工作流") == "走默认出口":
            active_ports = [str(config.get("默认出口名称", "默认")).strip() or "默认"]
        else:
            raise ValueError(f"[{tag}] value 没有命中任何路由规则：{value!r}")

    bus.log_emitted.emit(
        "SUCCESS",
        "Logic",
        f"[{tag}] value={value!r}，分流至：{', '.join(active_ports)}",
    )
    return {
        "status": "Success",
        "active_ports": active_ports,
        "value": value,
    }
