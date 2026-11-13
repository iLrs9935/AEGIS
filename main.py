# main.py
import argparse
import ctypes
import sys
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    pass

QApplication.setHighDpiScaleFactorRoundingPolicy(
    Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
)


def main():
    # 1. 解析启动指令
    parser = argparse.ArgumentParser(description="AEGIS 自动化控制终端")
    parser.add_argument("--file", type=str, help="启动时自动加载的图纸 (.json) 路径")
    parser.add_argument("--autorun", action="store_true", help="加载后是否自动开始执行")
    parser.add_argument("--safe-power", action="store_true", help="验证模式：拦截休眠和终端退出")
    parser.add_argument("--lang", choices=("en", "zh"), help="Interface language: en or zh")
    args, _ = parser.parse_known_args()

    # 2. 启动 Qt 应用
    app = QApplication(sys.argv)
    from ui.i18n import initialize_language
    initialize_language(args.lang)
    from core.run_log import RunLog
    from core.event_bus import bus
    from functions import func_system

    base = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).parent
    try:
        run_log = RunLog(base / 'logs')
    except OSError:
        import tempfile
        run_log = RunLog(Path(tempfile.gettempdir()) / 'AEGIS' / 'logs')
    func_system.SAFE_POWER_MODE = args.safe_power
    bus.log_emitted.emit('INFO', 'Startup', f'运行记录: {run_log.path}; safe_power={args.safe_power}')
    from ui.main_window import MainWindow

    # 3. 把指令传给主窗口
    window = MainWindow(init_file=args.file, autorun=args.autorun)
    window.show()
    result = app.exec()
    run_log.close()
    sys.exit(result)


if __name__ == "__main__":
    main()
