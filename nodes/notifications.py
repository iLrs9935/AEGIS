# nodes/notifications.py
from core.event_bus import bus
from core.config import application_directory, private_setting, resolve_config

from . import register_node

try:
    from functions.func_network import execute_bark_push, execute_reliable_bark_push
except ImportError:
    execute_bark_push = None  # 占位符，阻断 NameError 级联崩溃
    execute_reliable_bark_push = None

# ---------------------------------------------------------
# Bark 通知下发
# ---------------------------------------------------------
bark_schema = {
    "Bark推送地址": "",
    "通知标题": "AEGIS 任务指令",
    "通知内容": "自动化流程已执行完毕！",
}


@register_node(name="Bark通知", category="通知", schema=bark_schema)
def bark_notification(config, inputs):
    # 【新增防线】：如果在 exe 环境中底层库丢失，立刻在 UI 报警并安全退出
    if execute_bark_push is None:
        bus.log_emitted.emit(
            "ERROR", "通知", "❌ 底层网络模块(func_network)丢失，请检查打包配置！"
        )
        return {"status": "Error"}

    url = _bark_url(config)
    title = config.get("通知标题", "AEGIS")
    content = config.get("通知内容", "")

    if not url or "YOUR_KEY" in url:
        bus.log_emitted.emit("WARN", "通知", "⚠️ Bark 地址未配置或为默认值，跳过推送。")
        return {"status": "Success"}

    bus.log_emitted.emit("INFO", "通知", f"📱 正在呼叫远端设备: {title}")

    success = execute_bark_push(url, title, content)

    if success:
        bus.log_emitted.emit("SUCCESS", "通知", "✅ Bark 推送已成功送达终端！")
    else:
        bus.log_emitted.emit("ERROR", "通知", "❌ Bark 推送失败，请检查网络或配置。")

    return {"status": "Success"}


reliable_bark_schema = {
    "Bark推送地址": "",
    "通知标题模板": "AEGIS · {state}",
    "通知内容模板": "第 {attempt}/{max_attempts} 次：{summary}",
    "消息分组": "AEGIS无人值守",
    "通知级别": ["active", "timeSensitive", "critical", "passive"],
    "发送尝试次数": "3",
    "重试间隔(s)": "2",
    "请求超时(s)": "10",
    "离线队列目录": "自动(程序目录/alerts/pending)",
}


class _SafeFields(dict):
    def __missing__(self, key):
        return "{" + key + "}"


def _bark_url(config):
    configured = str(config.get("Bark推送地址", "")).strip()
    return resolve_config(configured) if configured else private_setting("AEGIS_BARK_URL").strip()


def _render(template: str, value: dict) -> str:
    try:
        return str(template).format_map(_SafeFields(value))
    except (ValueError, TypeError):
        return str(template)


def _number(config: dict, key: str, default, cast, minimum):
    try:
        return max(minimum, cast(config.get(key, default)))
    except (TypeError, ValueError):
        return default


@register_node(name="可靠Bark通知", category="OK-WW", schema=reliable_bark_schema)
def reliable_bark_notification(config, inputs):
    """Retry Bark and persist an atomic outbox item if delivery is unconfirmed."""

    if execute_reliable_bark_push is None:
        bus.log_emitted.emit(
            "ERROR", "通知", "可靠 Bark 模块缺失，通知无法发送或入队"
        )
        value = inputs.get("__value__")
        return {"status": "Success", "value": value or {}}

    value = inputs.get("__value__")
    if not isinstance(value, dict):
        value = {}
    fields = {
        "state": value.get("state", "notice"),
        "attempt": value.get("attempt", "-"),
        "max_attempts": value.get("max_attempts", "-"),
        "summary": value.get("summary", "AEGIS 无人值守状态更新"),
    }
    url = _bark_url(config)
    title = _render(config.get("通知标题模板", "AEGIS · {state}"), fields)
    content = _render(
        config.get("通知内容模板", "第 {attempt}/{max_attempts} 次：{summary}"),
        fields,
    )

    queue_directory = str(config.get("离线队列目录", "")).strip()
    if not queue_directory or queue_directory.startswith("自动("):
        queue_directory = str(application_directory() / "alerts" / "pending")

    if not url or "YOUR_KEY" in url:
        bus.log_emitted.emit("WARN", "通知", "Bark 地址未配置，本次远程通知已跳过")
        return {
            "status": "Success",
            "value": {**value, "notification": "not_configured"},
        }

    result = execute_reliable_bark_push(
        url,
        title,
        content,
        group=str(config.get("消息分组", "AEGIS无人值守")),
        level=str(config.get("通知级别", "active")),
        attempts=_number(config, "发送尝试次数", 3, int, 1),
        retry_delay=_number(config, "重试间隔(s)", 2.0, float, 0.0),
        timeout=_number(config, "请求超时(s)", 10.0, float, 1.0),
        outbox_directory=queue_directory,
    )

    if result["delivered"]:
        notification = "delivered"
        bus.log_emitted.emit("SUCCESS", "通知", "Bark 通知已得到服务端确认")
    elif result["queued"]:
        notification = "queued"
        bus.log_emitted.emit(
            "WARN", "通知", "Bark 暂未送达，通知已原子写入本地待发队列"
        )
    else:
        notification = "failed"
        bus.log_emitted.emit(
            "ERROR", "通知", "Bark 未送达且无法写入待发队列，请检查磁盘"
        )

    return {
        "status": "Success",
        "value": {**value, "notification": notification},
    }
