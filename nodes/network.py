from typing import Any

from core.event_bus import bus
from nodes import register_node

web_crawler_schema: dict[str, Any] = {
    "__out_ports__": ["有待兑换", "没有待兑换"],
    "__out_descriptions__": {
        "有待兑换": "输出尚未确认处理的兑换码数组",
        "没有待兑换": "账本中没有待处理兑换码，流程可直接结束",
    },
    "节点标签": "网页正则嗅探",
    "目标URL": "",
    "触发关键词(可不填)": "兑换码",
    "正则特征": r"\b(?!USER)(?=[A-Z0-9]{8,20}\b)(?=[A-Z0-9]*[A-Z])[A-Z0-9]{8,20}\b",
    "最大下潜页数": "10",
    "记忆账本键名": "mingchao_cdkeys",
    "结果存入全局变量": "cdkeys_array",
}


@register_node(name="通用网页嗅探", category="网络与侦察", schema=web_crawler_schema)
def fetch_web_data(config, inputs):
    tag = config.get("节点标签", "网页嗅探")
    url = config.get("目标URL", "")
    keywords = config.get("触发关键词(可不填)", "")
    regex = config.get("正则特征", "")
    max_scroll = int(config.get("最大下潜页数", 10))
    ledger_key = config.get("记忆账本键名", "mingchao_cdkeys").strip()

    # 获取 UI 上用户填写的变量名
    output_var_name = config.get("结果存入全局变量", "cdkeys_array").strip()

    if not url or not regex or not output_var_name or not ledger_key:
        raise Exception("目标 URL、正则特征、账本键名和兼容变量名均不可为空")

    bus.log_emitted.emit("INFO", "Network", f"🕸️ 锁定目标 [{url}]，开始静默嗅探...")

    from functions.func_crawler import hal_scrape_cdkeys

    try:
        new_keys = hal_scrape_cdkeys(
            url=url,
            keywords_str=keywords,
            regex_pattern=regex,
            max_scroll=max_scroll,
            ledger_key=ledger_key,
        )

        if new_keys and len(new_keys) > 0:
            bus.log_emitted.emit(
                "SUCCESS", "Network", f"[{tag}] 🎯 共提取 {len(new_keys)} 条数据"
            )

            # 【优雅的上下文注入】根据 UI 面板上指定的变量名，把数组存进去
            context = inputs.get("__global_context__", {})
            context[output_var_name] = new_keys

            return {
                "status": "Success",
                "active_port": "有待兑换",
                "value": new_keys,
            }
        else:
            bus.log_emitted.emit(
                "WARN", "Network", f"[{tag}] 👻 未发现符合正则的新数据"
            )
            return {
                "status": "Success",
                "active_port": "没有待兑换",
                "value": [],
            }

    except Exception as e:
        bus.log_emitted.emit("ERROR", "Network", f"[{tag}] ❌ 嗅探失败: {str(e)}")
        raise


redeem_result_schema: dict[str, Any] = {
    "__out_ports__": ["继续下一个"],
    "__out_descriptions__": {"继续下一个": "当前兑换码已提交账本，可继续取下一条"},
    "节点标签": "提交兑换结果",
    "记忆账本键名": "mingchao_cdkeys",
    "当前兑换码兼容变量": "current_cdkey",
    "处理结果": ["兑换成功", "已使用", "无效兑换码", "已使用/已失效", "已提交待人工确认"],
}


@register_node(name="记录兑换码结果", category="网络与侦察", schema=redeem_result_schema)
def record_redeem_result(config, inputs):
    tag = config.get("节点标签", "提交兑换结果")
    ledger_key = config.get("记忆账本键名", "mingchao_cdkeys").strip()
    result = config.get("处理结果", "兑换成功")
    value = inputs.get("__value__")

    code = value if isinstance(value, str) else ""
    if not code:
        context = inputs.get("__global_context__", {})
        variable_name = config.get("当前兑换码兼容变量", "current_cdkey")
        code = context.get(variable_name, "")
    code = str(code or "").strip().upper()
    if not code:
        raise ValueError("没有收到可记录的兑换码 value")

    from functions.func_crawler import mark_cdkey_processed

    mark_cdkey_processed(code, result=result, ledger_key=ledger_key)
    bus.log_emitted.emit(
        "SUCCESS", "Network", f"[{tag}] {code} 已记入账本：{result}"
    )
    return {
        "status": "Success",
        "active_port": "继续下一个",
        "value": code,
    }
