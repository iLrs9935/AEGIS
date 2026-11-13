from PyQt6.QtCore import QObject, pyqtSignal


class _EventBus(QObject):
    """
    AEGIS 全局事件总线
    使用 Python 模块级单例机制，严禁重写 __new__ 破坏 QObject 生命周期。
    """

    # --- 节点与 DAG 生命周期信号 ---
    node_status_changed = pyqtSignal(str, str, str)
    dag_completed = pyqtSignal(str, bool)

    # --- 系统与日志信号 ---
    log_emitted = pyqtSignal(str, str, str)
    system_event = pyqtSignal(str, dict)

    # 最高权限 - 蓝图跃迁请求信号，参数为 (目标图纸绝对/相对路径)
    blueprint_jump_requested = pyqtSignal(str)

    # 节点内部文本显示更新信号
    # 参数 1: node_id (节点的唯一标识符)
    # 参数 2: display_text (需要展示在节点上的字符串)
    node_text_updated = pyqtSignal(str, str)


# 唯一合法的全局句柄！
# 其他任何模块必须且只能使用：from core.event_bus import bus
bus = _EventBus()
