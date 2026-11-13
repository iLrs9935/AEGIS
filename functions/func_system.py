# functions/func_system.py
import os
import subprocess
import time

SAFE_POWER_MODE = False

try:
    from functions.func_actions import stop_event
except ImportError:
    stop_event = None


def execute_sleep(duration: float) -> bool:
    """
    [HAL] 线程挂起与时间线停滞 (已改造为可中断休眠)
    """
    try:
        if stop_event:
            is_interrupted = stop_event.wait(timeout=duration)
            if is_interrupted:
                print("🛑 沉睡被人工介入强制中断！")
                return False
        else:
            time.sleep(duration)
        return True
    except Exception as e:
        print(f"等待执行异常: {e}")
        return False


def execute_delayed_hibernate(delay_seconds: int) -> bool:
    """Keep the delay in-process so stopping/closing AEGIS cancels it."""
    if SAFE_POWER_MODE:
        return True
    try:
        if not execute_sleep(delay_seconds) or (stop_event and stop_event.is_set()):
            return False
        executable = os.path.join(os.environ.get('SystemRoot', r'C:\Windows'), 'System32', 'shutdown.exe')
        result = subprocess.run(
            [executable, '/h'], shell=False, capture_output=True, timeout=15,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
        )
        return result.returncode == 0
    except Exception as e:
        print(f"脱机休眠指令发送失败: {e}")
        return False


def execute_self_destruct() -> None:
    """
    [HAL] 物理切断主进程
    暴力拔管，无视所有 Python 线程锁和 Qt 框架事件循环
    """
    if SAFE_POWER_MODE:
        return
    try:
        os._exit(0)
    except Exception as e:
        print(f"自毁程序执行异常: {e}")
