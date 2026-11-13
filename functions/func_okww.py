"""Fail-safe helpers for supervising one OK-WW Daily Task attempt.

The public functions in this module intentionally do not depend on Qt.  That
makes the process/log rules testable without launching either OK-WW or the
game.  A run is successful only after OK-Script's own terminal success marker
has been appended to the launcher log.
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable


SUCCESS_MARKER = "Successfully Executed Task, Exiting Game and App!"
# ok-script 3.x translates DailyTask's completion message into the UI language.
# Match the exact task logger and message, not other tasks or partial progress.
DAILY_COMPLETION_PATTERN = re.compile(
    r"(?m)(?<![\w.])DailyTask:(?:Daily Task Completed|每日任务已完成)[ \t]*\r?$"
)
UPDATE_RESTART_MARKER = "游戏更新成功, 游戏即将重启"
FAILURE_MARKERS = (
    "Daily Task exception stopped",
    "TaskExecutor:TaskDisabledException, continue <src.task.DailyTask.DailyTask",
)


class ProcessInspectionError(RuntimeError):
    """Raised when Windows process ownership cannot be inspected safely."""


def _normalise_path(value: str | None) -> str:
    if not value:
        return ""
    normalised = os.path.normcase(os.path.normpath(value or ""))
    if normalised.startswith("\\\\?\\"):
        normalised = normalised[4:]
    return normalised


def _command_tokens(command_line: str | None) -> list[str]:
    """Split a Windows command line without accepting incidental substrings."""

    value = str(command_line or "").strip()
    if not value:
        return []
    try:
        import ctypes

        argc = ctypes.c_int()
        command_to_argv = ctypes.windll.shell32.CommandLineToArgvW
        command_to_argv.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_int)]
        command_to_argv.restype = ctypes.POINTER(ctypes.c_wchar_p)
        argv = command_to_argv(value, ctypes.byref(argc))
        if not argv:
            return []
        try:
            return [argv[index] for index in range(argc.value)]
        finally:
            local_free = ctypes.windll.kernel32.LocalFree
            local_free.argtypes = [ctypes.c_void_p]
            local_free.restype = ctypes.c_void_p
            local_free(argv)
    except (AttributeError, OSError, ValueError):
        return [token.strip('"') for token in shlex.split(value, posix=False)]


def _identity(process: dict) -> tuple[int, str]:
    return int(process["pid"]), str(process.get("creation_date") or "")


def windows_process_inventory() -> list[dict]:
    """Return the fields needed to identify an OK-WW session using WMI.

    WMI is used instead of window titles so tray/background processes remain
    visible.  COM is initialised here because nodes run on Qt worker threads.
    """

    try:
        import pythoncom
        import win32com.client
    except ImportError as exc:  # pragma: no cover - packaging guard
        raise ProcessInspectionError("缺少 Windows WMI 组件") from exc

    pythoncom.CoInitialize()
    service = None
    rows = None
    row = None
    try:
        service = win32com.client.GetObject(
            r"winmgmts:{impersonationLevel=impersonate}!\\.\root\cimv2"
        )
        rows = service.ExecQuery(
            "SELECT ProcessId, ParentProcessId, Name, ExecutablePath, "
            "CommandLine, CreationDate FROM Win32_Process"
        )
        result = []
        for row in rows:
            try:
                result.append(
                    {
                        "pid": int(row.ProcessId),
                        "parent_pid": int(row.ParentProcessId or 0),
                        "name": str(row.Name or ""),
                        "executable_path": str(row.ExecutablePath or ""),
                        "command_line": str(row.CommandLine or ""),
                        "creation_date": str(row.CreationDate or ""),
                    }
                )
            except (AttributeError, TypeError, ValueError):
                continue
        return result
    except Exception as exc:
        raise ProcessInspectionError(f"WMI 进程查询失败: {exc}") from exc
    finally:
        row = None
        rows = None
        service = None
        pythoncom.CoUninitialize()


def identify_okww_processes(
    processes: Iterable[dict],
    okww_executable: str,
    okww_main_script: str,
    game_process_name: str,
    okww_worker_executable: str = "",
) -> list[dict]:
    """Select only the exact launcher, worker and game process identities."""

    expected_launcher = _normalise_path(okww_executable)
    expected_script = _normalise_path(okww_main_script)
    expected_worker = _normalise_path(okww_worker_executable)
    expected_game = (game_process_name or "").casefold()
    matches = []

    for process in processes:
        name = str(process.get("name") or "")
        executable = _normalise_path(process.get("executable_path"))
        command_tokens = {
            _normalise_path(token) for token in _command_tokens(process.get("command_line"))
        }
        role = None

        if expected_launcher and executable == expected_launcher:
            role = "okww_launcher"
        elif name.casefold() == "ok-ww.exe" and not executable:
            # Elevated processes may hide ExecutablePath from a lower-integrity
            # WMI caller.  Treat that uncertainty as relevant so preflight
            # fails closed instead of launching a duplicate instance.
            role = "okww_ambiguous"
        elif (
            (expected_worker and executable == expected_worker)
            or (
                expected_script
                and name.casefold() in {"python.exe", "pythonw.exe"}
                and expected_script in command_tokens
            )
        ):
            role = "okww_worker"
        elif expected_game and name.casefold() == expected_game:
            role = "game"

        if role:
            selected = dict(process)
            selected["role"] = role
            matches.append(selected)

    return matches


def extract_okww_session_pids(text: str) -> set[int]:
    """Extract worker PIDs that OK-WW itself reports for the current run."""

    pids: set[int] = set()
    patterns = (
        r"Command spawned pid=(\d+)[^\r\n]*(?:working[\\/]+main\.py|cmd_desc=ok-ww)",
        r"ok:OK start id:[^\r\n]*?\bpid:(\d+)\b",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            try:
                pid = int(match.group(1))
            except (TypeError, ValueError):
                continue
            if pid > 0:
                pids.add(pid)
    return pids


def process_identities(processes: Iterable[dict]) -> set[tuple[int, str]]:
    return {_identity(process) for process in processes}


def session_owned_processes(
    processes: Iterable[dict], baseline_identities: Iterable[tuple[int, str]]
) -> list[dict]:
    """Exclude every process identity that existed before this workflow."""

    baseline = {
        (int(identity[0]), str(identity[1])) for identity in baseline_identities
    }
    return [process for process in processes if _identity(process) not in baseline]


def _matching_log_paths(directory: Path, patterns: Iterable[str]) -> list[Path]:
    paths = {
        path.resolve()
        for pattern in patterns
        for path in directory.glob(pattern)
        if path.is_file()
    }
    return sorted(paths, key=lambda path: (path.stat().st_mtime_ns, path.name))


def snapshot_log_offsets(
    log_directory: str, patterns: Iterable[str] = ("app.*",)
) -> dict[str, int]:
    directory = Path(log_directory)
    if not directory.is_dir():
        raise FileNotFoundError(f"OK-WW 日志目录不存在: {directory}")
    return {
        str(path): path.stat().st_size
        for path in _matching_log_paths(directory, patterns)
    }


def read_appended_logs(
    log_directory: str,
    offsets: dict[str, int],
    patterns: Iterable[str] = ("app.*",),
) -> str:
    """Read only bytes appended after the attempt baseline, across rotations."""

    directory = Path(log_directory)
    if not directory.is_dir():
        raise FileNotFoundError(f"OK-WW 日志目录不存在: {directory}")

    chunks: list[bytes] = []
    paths = _matching_log_paths(directory, patterns)
    for path in paths:
        key = str(path.resolve())
        size = path.stat().st_size
        start = int(offsets.get(key, 0))
        if start < 0 or start > size:  # log was replaced or truncated
            start = 0
        if size > start:
            with path.open("rb") as handle:
                handle.seek(start)
                chunks.append(handle.read())
        offsets[key] = size

    return b"\n".join(chunks).decode("utf-8", errors="replace")


def _failure_summary(text: str, marker_index: int) -> str:
    tail = text[marker_index : marker_index + 12000]
    candidates = []
    for raw_line in tail.splitlines()[1:]:
        line = raw_line.rsplit("[ok-ww]:", 1)[-1].strip()
        if not line:
            continue
        if re.search(r"(?:Exception|Error)(?::|\s|$)", line):
            candidates.append(line)
    if candidates:
        detail = candidates[-1]
        detail = re.sub(r"^\d{4}-\d\d-\d\d .*? (?:ERROR|INFO) \S+ ", "", detail)
        return detail[:300]
    return "OK-WW 每日任务报告异常"


def _event_timestamp(text: str, index: int) -> float | None:
    line_start = text.rfind("\n", 0, index) + 1
    line = text[line_start : text.find("\n", index) if "\n" in text[index:] else None]
    match = re.match(r"(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d(?:[.,]\d+)?)", line)
    if not match:
        return None
    raw = match.group(1).replace(",", ".")
    try:
        return datetime.fromisoformat(raw).timestamp()
    except ValueError:
        return None


def launcher_update_state(text: str, not_before: float) -> str | None:
    """Read timestamped PyAppify update transitions, never app.json snapshots."""
    state = None
    for match in re.finditer(r"(?m)^.*$", text):
        stamp = _event_timestamp(text, match.start())
        if stamp is None or stamp < not_before:
            continue
        line = match.group()
        if re.search(r"Auto Update to version .* success\.|Updated ok-ww to version ", line):
            state = "completed"
        elif re.search(r"Updating ok-ww to version |开始自动更新", line):
            state = "updating"
        elif re.search(r"Auto [Uu]pdate.*(?:failed|error)|Failed to update ok-ww", line):
            state = "failed"
    return state


def classify_log_update(text: str, not_before: float | None = None) -> dict | None:
    """Return the first decisive event in newly appended log text."""

    events: list[tuple[int, str, str]] = []
    daily_times = [
        _event_timestamp(text, item.start())
        for item in DAILY_COMPLETION_PATTERN.finditer(text)
    ]
    for match in re.finditer(re.escape(SUCCESS_MARKER), text):
        event_time = _event_timestamp(text, match.start())
        # A generic executor exit may belong to another task or a rotated log.
        # In supervised runs require both timestamped DailyTask completion and
        # the executor success marker, from this attempt, in that order.
        confirmed = event_time is not None and any(
            stamp is not None and not_before <= stamp <= event_time
            for stamp in daily_times
        ) if not_before is not None else True
        if confirmed and (not_before is None or event_time >= not_before):
            events.append(
                (match.start(), "success", "OK-WW 每日任务已确认完成")
            )
    for marker in FAILURE_MARKERS:
        for match in re.finditer(re.escape(marker), text):
            event_time = _event_timestamp(text, match.start())
            if not_before is None or event_time is None or event_time >= not_before:
                events.append(
                    (
                        match.start(),
                        "failure",
                        _failure_summary(text, match.start()),
                    )
                )
    for match in re.finditer(re.escape(UPDATE_RESTART_MARKER), text):
        event_time = _event_timestamp(text, match.start())
        if not_before is None or event_time is None or event_time >= not_before:
            events.append(
                (
                    match.start(),
                    "restart_required",
                    "游戏热更新完成，准备重启 OK-WW",
                )
            )
    if not events:
        return None
    _, state, summary = min(events, key=lambda item: item[0])
    return {"state": state, "summary": summary}


def terminate_process_tree(pid: int, timeout: float = 15.0) -> bool:
    """Terminate exactly one identified session tree with Windows taskkill."""

    try:
        result = subprocess.run(
            ["taskkill", "/PID", str(int(pid)), "/T", "/F"],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        # 128/255 are commonly returned when the target already disappeared.
        return result.returncode in {0, 128, 255}
    except (OSError, subprocess.SubprocessError, ValueError):
        return False


def wait_until_no_owned_processes(
    inspect: Callable[[], list[dict]],
    baseline_identities: Iterable[tuple[int, str]],
    timeout: float,
    interval: float = 0.5,
) -> list[dict]:
    deadline = time.monotonic() + max(0.0, timeout)
    while True:
        remaining = session_owned_processes(inspect(), baseline_identities)
        if not remaining or time.monotonic() >= deadline:
            return remaining
        time.sleep(max(0.05, interval))
