from core.context import mutate
# nodes/timers.py
import time

from core.event_bus import bus

from . import register_node

try:
    from functions.func_system import execute_sleep
except ImportError as e:
    print(f"⚠️ 警告: Timers 底层库导入失败 ({e})")

# ---------------------------------------------------------
# 强制等待
# ---------------------------------------------------------
wait_schema = {"等待时长(s)": "2.0"}


@register_node(name="等待时间", category="时间", schema=wait_schema)
def wait_node(config, inputs):
    duration = float(config.get("等待时长(s)", 2.0))
    bus.log_emitted.emit("INFO", "时间", f"⏳ 强制等待 {duration} 秒...")
    execute_sleep(duration)
    return {"status": "Success"}


# ---------------------------------------------------------
# 脉冲计时器 (增加标签识别版)
# ---------------------------------------------------------
timer_schema = {
    "__out_ports__": ["执行脉冲", "超时跳出"],
    "节点标签": "未命名计时器",  # <-- 新增：方便在 Log 里区分
    "监测间隔(s)": "30",
    "最大超时(s)": "3600",
}


@register_node(name="脉冲计时器", category="时间", schema=timer_schema)
def pulse_timer(config, inputs):
    # 1. 提取配置
    tag = config.get("节点标签", "未命名计时器")  # <-- 提取标签
    interval = float(config.get("监测间隔(s)", 30))
    max_time = float(config.get("最大超时(s)", 3600))

    # 2. 获取上下文和唯一标识
    context = inputs.get("__global_context__", {})
    node_id = inputs.get("__node_id__", "unknown")
    start_time_key = f"timer_start_{node_id}"

    now = time.time()
    def tick(data):
        start = data.setdefault(start_time_key, now)
        elapsed = now - start
        if elapsed >= max_time:
            data.pop(start_time_key, None)
        return elapsed
    elapsed = mutate(context, tick)
    if elapsed >= max_time:
        bus.log_emitted.emit("ERROR", "时间", f"[{tag}] 达到最大监测时间 ({max_time}s)")
        return {"status": "Success", "active_port": "超时跳出"}
    else:
        bus.log_emitted.emit(
            "WARN",
            "时间",
            f"[{tag}] ⏳ 挂机中({elapsed:.1f}s)，沉睡 {interval}s 后发射下一次脉冲",
        )
        # 调用底层的挂起函数
        from functions.func_system import execute_sleep  # 确保导入了正确的 sleep 函数

        execute_sleep(interval)
        return {"status": "Success", "active_port": "执行脉冲"}
