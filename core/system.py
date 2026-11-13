# core/system.py
import os
import subprocess
from datetime import datetime, timedelta

from .event_bus import bus


class SystemDaemon:
    """系统级幽灵守护引擎"""

    TASK_NAME = "AEGIS_RTC_Wakeup"

    @classmethod
    def set_rtc_wakeup(cls, target_time: datetime):
        """
        写入硬件级定时唤醒任务。
        需要管理员权限，并确保控制面板中 "允许唤醒定时器" 已开启。
        """
        time_str = target_time.strftime("%H:%M")
        date_str = target_time.strftime("%m/%d/%Y")

        # 构造 schtasks 命令，/rl highest 请求最高权限
        cmd = [
            "schtasks",
            "/Create",
            "/TN",
            cls.TASK_NAME,
            "/TR",
            "cmd.exe /c echo AEGIS Waking Up...",  # 唤醒后执行的动作，这里随便填个 echo 即可，重点是唤醒
            "/SC",
            "ONCE",
            "/ST",
            time_str,
            "/SD",
            date_str,
            "/RL",
            "HIGHEST",
            "/F",  # 强制覆盖同名任务
        ]

        try:
            # CREATE_NO_WINDOW 避免弹出黑框
            subprocess.run(cmd, check=True, creationflags=subprocess.CREATE_NO_WINDOW)
            bus.log_emitted.emit(
                "SUCCESS",
                "System",
                f"🔋 RTC 唤醒定时器已成功注入 BIOS，目标时间: {time_str}",
            )
        except subprocess.CalledProcessError as e:
            bus.log_emitted.emit(
                "ERROR",
                "System",
                f"❌ RTC 定时器注入失败，请检查是否以管理员权限运行！错误码: {e.returncode}",
            )

    @classmethod
    def execute_s4_hibernate(cls):
        """
        执行系统级 S4 休眠。
        数据将写入 hiberfil.sys 并彻底断电。
        """
        bus.log_emitted.emit("WARN", "System", "💤 系统即将进入 S4 休眠，准备断电...")
        # 延迟 2 秒让 UI 把日志画完
        import time

        time.sleep(2)

        # 调用 Windows 电源管理 API 进行休眠 (S4)
        # /h 表示 hibernate
        os.system("shutdown /h")

    @classmethod
    def schedule_daily_loop(cls, execute_hour: int, execute_minute: int):
        """
        计算明天特定时间的 datetime，并挂载 RTC 唤醒
        """
        now = datetime.now()
        target = now.replace(
            hour=execute_hour, minute=execute_minute, second=0, microsecond=0
        )

        # 如果设定的时间在今天已经过去了，就定在明天的这个时间
        if target <= now:
            target += timedelta(days=1)

        cls.set_rtc_wakeup(target)
        cls.execute_s4_hibernate()
