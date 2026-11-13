"""Dedicated unattended supervision nodes for OK-WW Daily Task."""

from __future__ import annotations

import os
import time
from pathlib import Path

from core.event_bus import bus
from functions.func_okww import (
    ProcessInspectionError,
    classify_log_update,
    extract_okww_session_pids,
    identify_okww_processes,
    launcher_update_state,
    process_identities,
    read_appended_logs,
    session_owned_processes,
    snapshot_log_offsets,
    terminate_process_tree,
    wait_until_no_owned_processes,
    windows_process_inventory,
)
from functions.func_system import execute_sleep

from . import register_node


STATE_KEY = "__okww_unattended_daily__"


def _int(config: dict, key: str, default: int, minimum: int = 0) -> int:
    try:
        return max(minimum, int(float(config.get(key, default))))
    except (TypeError, ValueError):
        return default


def _float(config: dict, key: str, default: float, minimum: float = 0.0) -> float:
    try:
        return max(minimum, float(config.get(key, default)))
    except (TypeError, ValueError):
        return default


def _default_executable() -> str:
    local_app_data = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    return str(local_app_data / "ok-ww" / "ok-ww.exe")


def _settings(config: dict) -> dict:
    executable = str(
        config.get("OK-WW程序路径") or _default_executable()
    ).strip()
    root = str(Path(executable).parent)
    return {
        "okww_executable": executable,
        "okww_main_script": str(
            config.get("OK-WW主脚本路径") or root + r"\data\apps\ok-ww\working\main.py"
        ).strip(),
        "okww_worker_executable": str(
            config.get("OK-WW Python路径") or root + r"\data\apps\ok-ww\python\pythonw.exe"
        ).strip(),
        "game_process_name": str(
            config.get("鸣潮进程名", "Client-Win64-Shipping.exe")
        ).strip(),
        "log_directory": str(
            config.get("OK-WW日志目录") or root + r"\logs"
        ).strip(),
        "internal_log_directory": str(
            config.get("OK-WW内部日志目录") or root + r"\data\apps\ok-ww\working\logs"
        ).strip(),
    }


def _relevant_processes(
    settings: dict,
    observed_worker_identities: dict[str, str] | None = None,
    candidate_worker_pids: set[int] | None = None,
) -> list[dict]:
    inventory = windows_process_inventory()
    selected = identify_okww_processes(
        inventory,
        settings["okww_executable"],
        settings["okww_main_script"],
        settings["game_process_name"],
        settings.get("okww_worker_executable", ""),
    )
    selected_pids = {item["pid"] for item in selected}
    observed = observed_worker_identities or {}
    candidates = set(candidate_worker_pids or set())
    for process in inventory:
        pid = int(process.get("pid", 0))
        creation_date = str(process.get("creation_date") or "")
        name = str(process.get("name") or "").casefold()
        known_identity = creation_date and observed.get(str(pid)) == creation_date
        new_logged_worker = (
            pid in candidates
            and creation_date
            and name in {"python.exe", "pythonw.exe"}
        )
        if (
            (known_identity or new_logged_worker)
            and pid not in selected_pids
        ):
            item = dict(process)
            item["role"] = "okww_worker_log_pid"
            selected.append(item)
    return selected


init_schema = {
    "__out_ports__": ["允许启动", "环境占用"],
    "节点标签": "OK-WW安全预检",
    "OK-WW程序路径": "",
    "OK-WW主脚本路径": "",
    "OK-WW Python路径": "",
    "OK-WW日志目录": "",
    "OK-WW内部日志目录": "",
    "鸣潮进程名": "Client-Win64-Shipping.exe",
    "最大尝试次数": "3",
    "最大更新重启次数": "3",
}


@register_node(name="OK-WW监控初始化", category="OK-WW", schema=init_schema)
def initialise_okww_monitor(config, inputs):
    """Fail closed if an existing/user-owned OK-WW or game session is found."""

    context = inputs.get("__global_context__", {})
    settings = _settings(config)
    state = context.get(STATE_KEY)

    try:
        relevant = _relevant_processes(settings)
        log_offsets = snapshot_log_offsets(settings["log_directory"])
        log_offsets.update(
            snapshot_log_offsets(
                settings["internal_log_directory"], ("ok-script*.log",)
            )
        )
    except (ProcessInspectionError, OSError) as exc:
        summary = f"安全预检失败，已禁止启动: {exc}"
        bus.log_emitted.emit("ERROR", "OK-WW监控", summary)
        return {
            "status": "Success",
            "active_port": "环境占用",
            "value": {"state": "preflight_failed", "summary": summary},
        }

    if relevant:
        roles = "、".join(sorted({item["role"] for item in relevant}))
        summary = f"发现预先存在的进程({roles})，为避免误杀已禁止启动"
        bus.log_emitted.emit("WARN", "OK-WW监控", summary)
        return {
            "status": "Success",
            "active_port": "环境占用",
            "value": {"state": "environment_busy", "summary": summary},
        }

    if not isinstance(state, dict):
        state = {
            "attempt": 0,
            "workflow_started": time.monotonic(),
            "baseline_identities": [],
            "update_restart_count": 0,
        }
        context[STATE_KEY] = state

    preserve_attempt = bool(state.pop("preserve_attempt_number", False))
    if not preserve_attempt:
        state["attempt"] = int(state.get("attempt", 0)) + 1
    state["max_attempts"] = _int(config, "最大尝试次数", 3, 1)
    state["max_update_restarts"] = _int(config, "最大更新重启次数", 3, 0)
    state["attempt_started"] = time.monotonic()
    state["attempt_wall_started"] = time.time()
    state["log_offsets"] = log_offsets
    state["log_tail"] = ""
    state["saw_okww_process"] = False
    state["missing_since"] = None
    state["saw_game_process"] = False
    state["game_missing_since"] = None
    state["launcher_update_phase"] = None
    state["launcher_update_finished_at"] = None
    state["saw_daily_activity"] = False
    state["last_failure"] = ""
    state["terminal_state"] = "running"
    state["cleanup_verified"] = False
    state["observed_worker_identities"] = {}
    state["poll_count"] = 0
    state["settings"] = settings

    attempt = state["attempt"]
    summary = f"安全预检通过，准备执行第 {attempt}/{state['max_attempts']} 次尝试"
    bus.log_emitted.emit("SUCCESS", "OK-WW监控", summary)
    return {
        "status": "Success",
        "active_port": "允许启动",
        "value": {
            "state": "ready",
            "attempt": attempt,
            "max_attempts": state["max_attempts"],
            "summary": summary,
        },
    }


monitor_schema = {
    "__out_ports__": [
        "运行中",
        "检查更新界面",
        "更新后重启",
        "成功",
        "失败可重试",
        "最终失败",
    ],
    "节点标签": "OK-WW每日任务监控",
    "轮询间隔(s)": "15",
    "启动宽限(s)": "180",
    "退出日志宽限(s)": "20",
    "单次超时(s)": "7200",
    "总超时(s)": "21600",
    "更新界面检查间隔(轮询次数)": "4",
    "启动器更新宽限(s)": "900",
    "更新后启动宽限(s)": "90",
    "游戏退出宽限(s)": "60",
}


def _terminal_result(state: dict, port: str, status: str, summary: str) -> dict:
    state["terminal_state"] = status
    state["cleanup_verified"] = False
    attempt = int(state.get("attempt", 0))
    max_attempts = int(state.get("max_attempts", 1))
    state["last_failure"] = (
        summary if status in {"retryable_failure", "final_failure"} else ""
    )
    return {
        "status": "Success",
        "active_port": port,
        "value": {
            "state": status,
            "attempt": attempt,
            "max_attempts": max_attempts,
            "summary": summary,
        },
    }


def _failure_result(state: dict, summary: str, force_final: bool = False) -> dict:
    attempt = int(state.get("attempt", 0))
    max_attempts = int(state.get("max_attempts", 1))
    retry = not force_final and attempt < max_attempts
    port = "失败可重试" if retry else "最终失败"
    status = "retryable_failure" if retry else "final_failure"
    level = "WARN" if retry else "ERROR"
    bus.log_emitted.emit(level, "OK-WW监控", summary)
    return _terminal_result(state, port, status, summary)


def _update_restart_result(state: dict, summary: str) -> dict:
    count = int(state.get("update_restart_count", 0)) + 1
    state["update_restart_count"] = count
    maximum = int(state.get("max_update_restarts", 3))
    if count > maximum:
        return _failure_result(state, "更新恢复重启次数超过上限", force_final=True)
    state["preserve_attempt_number"] = True
    summary = f"{summary}（第 {count}/{maximum} 次，不计失败）"
    bus.log_emitted.emit("INFO", "OK-WW监控", summary)
    return _terminal_result(state, "更新后重启", "update_restart", summary)


@register_node(name="OK-WW任务监控", category="OK-WW", schema=monitor_schema)
def monitor_okww_task(config, inputs):
    """Route only from official log truth, with crash and timeout fallbacks."""

    context = inputs.get("__global_context__", {})
    state = context.get(STATE_KEY)
    if not isinstance(state, dict):
        return _failure_result(
            {"attempt": 1, "max_attempts": 1},
            "监控状态丢失，已按最终失败处理",
            force_final=True,
        )

    settings = state["settings"]
    if state.get("launch_error"):
        return _failure_result(state, state.pop("launch_error"))
    try:
        launcher_logs = read_appended_logs(
            settings["log_directory"], state["log_offsets"]
        )
        new_logs = launcher_logs + read_appended_logs(
            settings["internal_log_directory"],
            state["log_offsets"],
            ("ok-script*.log",),
        )
        appended = state.get("log_tail", "") + new_logs
        candidate_pids = extract_okww_session_pids(new_logs)
        observed_identities = state.setdefault("observed_worker_identities", {})
        event = classify_log_update(
            appended, not_before=float(state.get("attempt_wall_started", 0))
        )
        state["log_tail"] = appended[-16000:]
        relevant = _relevant_processes(
            settings, observed_identities, candidate_pids
        )
        for process in relevant:
            if (
                int(process.get("pid", 0)) in candidate_pids
                and str(process.get("creation_date") or "")
            ):
                observed_identities[str(process["pid"])] = str(
                    process["creation_date"]
                )
    except (ProcessInspectionError, OSError) as exc:
        return _failure_result(state, f"监控读取失败: {exc}")

    if event and event["state"] == "success":
        summary = event["summary"]
        bus.log_emitted.emit("SUCCESS", "OK-WW监控", summary)
        return _terminal_result(state, "成功", "success", summary)
    if event and event["state"] == "failure":
        return _failure_result(state, event["summary"])
    if event and event["state"] == "restart_required":
        return _update_restart_result(state, event["summary"])

    now = time.monotonic()
    attempt_elapsed = now - float(state["attempt_started"])
    workflow_elapsed = now - float(state["workflow_started"])
    single_timeout = _float(config, "单次超时(s)", 7200.0, 1.0)
    total_timeout = _float(config, "总超时(s)", 21600.0, 1.0)
    if workflow_elapsed >= total_timeout:
        return _failure_result(state, "无人值守总时限已到", force_final=True)
    if attempt_elapsed >= single_timeout:
        return _failure_result(state, f"本次任务超过 {int(single_timeout)} 秒")

    phase = launcher_update_state(
        appended, float(state.get("attempt_wall_started", 0))
    )
    if phase and phase != state.get("launcher_update_phase"):
        state["launcher_update_phase"] = phase
        if phase == "completed":
            state["launcher_update_finished_at"] = now
        elif phase == "updating":
            state["launcher_update_finished_at"] = None
        elif phase == "failed":
            return _failure_result(state, "OK-WW 启动器自动更新失败")
    if "DailyTask:" in new_logs:
        state["saw_daily_activity"] = True

    # A launcher window alone cannot prove the Python task has started.
    worker_alive = any(
        item["role"]
        in {
            "okww_worker",
            "okww_worker_log_pid",
        }
        for item in relevant
    )
    updating = state.get("launcher_update_phase") == "updating"
    update_grace = _float(config, "启动器更新宽限(s)", 900.0, 1.0)
    if updating and attempt_elapsed >= update_grace:
        return _failure_result(state, "OK-WW 启动器更新超时，未确认更新完成")
    finished_at = state.get("launcher_update_finished_at")
    if (finished_at is not None
            and now - float(finished_at) >= _float(config, "更新后启动宽限(s)", 90.0, 1.0)
            and not state.get("saw_daily_activity")):
        state["launch_worker_directly"] = True
        return _update_restart_result(state, "OK-WW 已更新完成但每日任务未启动，清理后直接恢复 -t 1 -e")

    waiting_update_start = finished_at is not None and not state.get("saw_daily_activity")
    if worker_alive:
        state["saw_okww_process"] = True
        state["missing_since"] = None
    elif state.get("saw_okww_process") and not updating and not waiting_update_start:
        if state.get("missing_since") is None:
            state["missing_since"] = now
        exit_grace = _float(config, "退出日志宽限(s)", 20.0, 0.0)
        if now - float(state["missing_since"]) >= exit_grace:
            return _failure_result(state, "OK-WW 已退出，但没有官方成功日志")
    elif not updating and not waiting_update_start:
        startup_grace = _float(config, "启动宽限(s)", 180.0, 1.0)
        if attempt_elapsed >= startup_grace:
            return _failure_result(state, "启动宽限期内未发现 OK-WW 工作进程")

    game_alive = any(item["role"] == "game" for item in relevant)
    if game_alive:
        state["saw_game_process"] = True
        state["game_missing_since"] = None
    elif state.get("saw_game_process") and not updating:
        if state.get("game_missing_since") is None:
            state["game_missing_since"] = now
        if now - state["game_missing_since"] >= _float(config, "游戏退出宽限(s)", 60.0, 1.0):
            return _failure_result(state, "鸣潮进程已退出且没有成功日志，疑似崩溃；清理后重试")

    interval = _float(config, "轮询间隔(s)", 15.0, 0.1)
    identities = ', '.join(f"{p['role']} PID={p['pid']}" for p in relevant) or '未发现相关进程'
    bus.log_emitted.emit(
        "INFO",
        "OK-WW监控",
        f"第 {state['attempt']} 次，已等待 {attempt_elapsed:.0f} 秒；{identities}；{interval:g} 秒后复核",
    )
    execute_sleep(interval)
    state["poll_count"] = int(state.get("poll_count", 0)) + 1
    check_every = _int(config, "更新界面检查间隔(轮询次数)", 4, 1)
    active_port = (
        "检查更新界面"
        if game_alive and not updating and state["poll_count"] % check_every == 0
        else "运行中"
    )
    return {
        "status": "Success",
        "active_port": active_port,
        "value": {
            "state": "running",
            "attempt": state["attempt"],
            "max_attempts": state["max_attempts"],
            "summary": "OK-WW 每日任务运行中",
        },
    }


cleanup_schema = {
    "__out_ports__": ["已清理", "清理失败"],
    "节点标签": "OK-WW会话安全清理",
    "确认超时(s)": "20",
}


@register_node(name="OK-WW安全清理", category="OK-WW", schema=cleanup_schema)
def cleanup_okww_session(config, inputs):
    """Kill and verify only process identities created after preflight."""

    context = inputs.get("__global_context__", {})
    state = context.get(STATE_KEY)
    upstream = inputs.get("__value__")
    if not isinstance(upstream, dict):
        upstream = {}
    if not isinstance(state, dict):
        summary = "清理状态丢失，无法证明进程归属"
        bus.log_emitted.emit("ERROR", "OK-WW监控", summary)
        return {
            "status": "Success",
            "active_port": "清理失败",
            "value": {**upstream, "cleanup": "failed", "summary": summary},
        }

    state["cleanup_verified"] = False
    settings = state["settings"]
    baseline = state.get("baseline_identities", [])

    def inspect_owned() -> list[dict]:
        return session_owned_processes(
            _relevant_processes(
                settings, state.get("observed_worker_identities", {})
            ),
            baseline,
        )

    try:
        owned = inspect_owned()
        # Killing a launcher/worker tree often removes its game child too.  A
        # fresh inventory before every PID avoids targeting a recycled PID.
        for process in owned:
            current = {item["pid"]: item for item in inspect_owned()}
            candidate = current.get(process["pid"])
            if candidate and process_identities([candidate]) == process_identities(
                [process]
            ):
                terminate_process_tree(process["pid"])

        timeout = _float(config, "确认超时(s)", 20.0, 0.0)
        remaining = wait_until_no_owned_processes(
            inspect_owned, baseline_identities=[], timeout=timeout
        )
    except (ProcessInspectionError, OSError) as exc:
        remaining = [{"role": "inspection", "pid": -1}]
        inspection_error = str(exc)
    else:
        inspection_error = ""

    if remaining:
        roles = "、".join(sorted({item.get("role", "unknown") for item in remaining}))
        summary = f"安全清理未通过，仍有会话进程: {roles}"
        if inspection_error:
            summary += f" ({inspection_error})"
        bus.log_emitted.emit("ERROR", "OK-WW监控", summary)
        return {
            "status": "Success",
            "active_port": "清理失败",
            "value": {**upstream, "cleanup": "failed", "summary": summary},
        }

    summary = str(upstream.get("summary") or "OK-WW 本次会话已安全清理")
    state["cleanup_verified"] = True
    bus.log_emitted.emit("SUCCESS", "OK-WW监控", "本次会话进程已全部确认退出")
    return {
        "status": "Success",
        "active_port": "已清理",
        "value": {**upstream, "cleanup": "verified", "summary": summary},
    }


def verify_power_ready(context):
    """Use this run's internal state, never a configurable output label."""
    state = context.get(STATE_KEY)
    if not isinstance(state, dict) or state.get("terminal_state") != "success":
        return False, "没有本次每日任务的成功证据"
    if not state.get("cleanup_verified"):
        return False, "本次进程清理未通过复核"
    try:
        if _relevant_processes(state["settings"]):
            return False, "仍有或新出现了 OK-WW/游戏进程"
    except (ProcessInspectionError, OSError, KeyError) as exc:
        return False, f"无法安全复核进程: {exc}"
    return True, "本次成功且进程清理通过"
