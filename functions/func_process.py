# functions/func_process.py
import os
import subprocess
import sys
import threading
from contextlib import contextmanager

from core.event_bus import bus

SHORT_NAME = "AEGIS_Process"
_launch_lock = threading.RLock()


def external_process_environment():
    """Keep AEGIS's Python/Qt and frozen DLL paths out of external apps."""
    env = dict(os.environ)
    for key in ("PYTHONHOME", "PYTHONPATH", "VIRTUAL_ENV", "QT_PLUGIN_PATH", "QT_QPA_PLATFORM",
                "QT_QPA_PLATFORM_PLUGIN_PATH", "QML2_IMPORT_PATH"):
        env.pop(key, None)
    bundle = getattr(sys, "_MEIPASS", "")
    if bundle:
        root = os.path.normcase(os.path.abspath(bundle))
        def bundled(value):
            path = os.path.normcase(os.path.abspath(value.strip('"')))
            return path == root or path.startswith(root + os.sep)
        env["PATH"] = os.pathsep.join(
            entry for entry in env.get("PATH", "").split(os.pathsep)
            if entry and not bundled(entry)
        )
        env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    return env


@contextmanager
def external_dll_search():
    """Windows children inherit SetDllDirectory; reset only while spawning."""
    with _launch_lock:
        if os.name != "nt" or not getattr(sys, "frozen", False):
            yield
            return
        import ctypes
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        get_directory = kernel32.GetDllDirectoryW
        get_directory.argtypes = [ctypes.c_uint32, ctypes.c_wchar_p]
        get_directory.restype = ctypes.c_uint32
        set_directory = kernel32.SetDllDirectoryW
        set_directory.argtypes = [ctypes.c_wchar_p]
        set_directory.restype = ctypes.c_bool
        size = get_directory(0, None)
        buffer = ctypes.create_unicode_buffer(size + 1)
        get_directory(len(buffer), buffer)
        previous = buffer.value
        if not set_directory(None):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            yield
        finally:
            if not set_directory(previous or None):
                raise ctypes.WinError(ctypes.get_last_error())


def log(msg, level="INFO"):
    if "成功" in msg:
        level = "SUCCESS"
    elif "失败" in msg or "异常" in msg:
        level = "WARN"
    bus.log_emitted.emit(level, "ProcessHAL", msg)


def _find_running_process_pid(executable_path: str):
    """Match the executable path; another Python installation is not a duplicate."""
    process_name = os.path.basename(executable_path).strip()
    if not process_name:
        return None
    try:
        from functions.func_okww import windows_process_inventory, _normalise_path
        expected = _normalise_path(os.path.abspath(executable_path))
        for process in windows_process_inventory():
            if process["name"].casefold() != process_name.casefold():
                continue
            actual = _normalise_path(process.get("executable_path"))
            if not actual or actual == expected:
                return int(process["pid"])
    except Exception as error:
        log(f"{SHORT_NAME}：检查重复进程失败，继续尝试启动: {error}", "WARN")
    return None


def execute_start_process(
    executable_path: str,
    arguments: str = "",
    working_dir: str = "",
    launch_if_running: bool = False,
):
    """
    硬核启动器：完美接管环境与参数
    """
    if not os.path.exists(executable_path):
        log(f"{SHORT_NAME}：找不到目标文件 -> {executable_path}", "ERROR")
        return False, None

    existing_pid = _find_running_process_pid(executable_path)
    if existing_pid and not launch_if_running:
        log(
            f"{SHORT_NAME}：目标程序已经在运行 (PID: {existing_pid})，已跳过重复启动"
        )
        return True, existing_pid
    if existing_pid:
        log(
            f"{SHORT_NAME}：目标程序已在运行 (PID: {existing_pid})，"
            "依配置再次调用程序以唤醒主窗口"
        )

    # [核心修复]：如果没有手动指定工作目录，自动将其设置为目标程序所在的文件夹
    # 这对于需要读取相对路径配置文件（如 .json）的 Python 脚本来说是救命的
    if not working_dir:
        working_dir = os.path.dirname(os.path.abspath(executable_path))

    # 组合命令：处理路径中可能带有空格的情况
    cmd = f'"{executable_path}" {arguments}'.strip()

    log(f"{SHORT_NAME}：准备启动命令 -> {cmd} | 工作目录: {working_dir}")

    try:
        # Spawn the executable itself so the returned PID and launch errors are real.
        with external_dll_search():
            process = subprocess.Popen(
                cmd,
                cwd=working_dir,
                shell=False,
                env=external_process_environment(),
                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
            )
        log(f"{SHORT_NAME}：进程启动成功 (PID: {process.pid})")
        return True, process.pid
    except Exception as e:
        log(f"{SHORT_NAME}：启动底层抛出异常: {e}", "ERROR")
        return False, None
