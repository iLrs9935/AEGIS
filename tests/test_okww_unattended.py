import json
import tempfile
import time
import unittest
import urllib.error
from datetime import datetime
from pathlib import Path
from unittest import mock

import networkx as nx

from core.engine import DAGEngine
from core.event_bus import bus
from functions.func_network import execute_reliable_bark_push
from functions.func_okww import (
    classify_log_update,
    extract_okww_session_pids,
    identify_okww_processes,
    read_appended_logs,
    session_owned_processes,
    snapshot_log_offsets,
)
from nodes import okww
from nodes import system as system_nodes
from nodes import NODE_REGISTRY


class OKWWProcessIdentityTests(unittest.TestCase):
    def test_only_exact_launcher_worker_and_game_are_selected(self):
        launcher = r"C:\Apps\ok-ww\ok-ww.exe"
        script = (
            r"C:\Apps\ok-ww\data\apps"
            r"\ok-ww\working\main.py"
        )
        processes = [
            {
                "pid": 1,
                "name": "ok-ww.exe",
                "executable_path": launcher,
                "command_line": f'"{launcher}" -t 1 -e',
                "creation_date": "A",
            },
            {
                "pid": 2,
                "name": "ok-ww.exe",
                "executable_path": r"D:\impostor\ok-ww.exe",
                "command_line": "",
                "creation_date": "B",
            },
            {
                "pid": 3,
                "name": "pythonw.exe",
                "executable_path": r"C:\Python\pythonw.exe",
                "command_line": f'pythonw.exe "{script}" -t 1 -e',
                "creation_date": "C",
            },
            {
                "pid": 4,
                "name": "Client-Win64-Shipping.exe",
                "executable_path": r"D:\Wuthering Waves\Client-Win64-Shipping.exe",
                "command_line": "",
                "creation_date": "D",
            },
            {
                "pid": 5,
                "name": "python.exe",
                "executable_path": r"C:\Python\python.exe",
                "command_line": f'python.exe -c "print(r\'{script}\')"',
                "creation_date": "E",
            },
        ]
        selected = identify_okww_processes(
            processes, launcher, script, "Client-Win64-Shipping.exe"
        )
        self.assertEqual({item["pid"] for item in selected}, {1, 3, 4})
        self.assertEqual(
            {item["role"] for item in selected},
            {"okww_launcher", "okww_worker", "game"},
        )

    def test_pid_reuse_is_not_treated_as_preexisting_identity(self):
        current = [{"pid": 9, "creation_date": "NEW"}]
        self.assertEqual(
            session_owned_processes(current, [(9, "OLD")]), current
        )
        self.assertEqual(session_owned_processes(current, [(9, "NEW")]), [])

    def test_hidden_launcher_path_is_treated_as_ambiguous_not_ignored(self):
        selected = identify_okww_processes(
            [
                {
                    "pid": 10,
                    "name": "ok-ww.exe",
                    "executable_path": "",
                    "command_line": "",
                    "creation_date": "A",
                }
            ],
            r"C:\Apps\ok-ww\ok-ww.exe",
            r"C:\Apps\ok-ww\data\apps\ok-ww\working\main.py",
            "Client-Win64-Shipping.exe",
        )
        self.assertEqual(selected[0]["role"], "okww_ambiguous")

    def test_real_okww_worker_command_line_is_selected(self):
        root = r"C:\Apps\ok-ww"
        script = root + r"\data\apps\ok-ww\working\main.py"
        worker = root + r"\data\apps\ok-ww\python\pythonw.exe"
        selected = identify_okww_processes(
            [
                {
                    "pid": 14668,
                    "name": "pythonw.exe",
                    "executable_path": worker,
                    "command_line": f'"{worker}" "{script}" -t 1 -e',
                    "creation_date": "A",
                }
            ],
            root + r"\ok-ww.exe",
            script,
            "Client-Win64-Shipping.exe",
            worker,
        )
        self.assertEqual([(item["pid"], item["role"]) for item in selected], [(14668, "okww_worker")])

    def test_exact_bundled_python_path_survives_hidden_command_line(self):
        worker = r"C:\Apps\ok-ww\data\apps\ok-ww\python\pythonw.exe"
        selected = identify_okww_processes(
            [{"pid": 28728, "name": "pythonw.exe", "executable_path": worker, "command_line": "", "creation_date": "A"}],
            r"C:\Apps\ok-ww\ok-ww.exe",
            r"C:\Apps\ok-ww\data\apps\ok-ww\working\main.py",
            "Client-Win64-Shipping.exe",
            worker,
        )
        self.assertEqual(selected[0]["role"], "okww_worker")


class OKWWLogTruthTests(unittest.TestCase):
    def test_worker_pid_is_recovered_from_real_launcher_log_shapes(self):
        text = (
            "Command spawned pid=14668 cmd_desc=pythonw.exe "
            "C:/Apps/ok-ww/data/apps/ok-ww/working/main.py\n"
            "ok:OK start id:ok-ww pid:28728\n"
        )
        self.assertEqual(extract_okww_session_pids(text), {14668, 28728})

    def test_stale_success_is_ignored_and_new_success_is_detected(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "app.2026-08-21"
            path.write_text(
                "Successfully Executed Task, Exiting Game and App!\n",
                encoding="utf-8",
            )
            offsets = snapshot_log_offsets(temp)
            self.assertEqual(read_appended_logs(temp, offsets), "")
            with path.open("a", encoding="utf-8") as handle:
                handle.write("Successfully Executed Task, Exiting Game and App!\n")
            event = classify_log_update(read_appended_logs(temp, offsets))
            self.assertEqual(event["state"], "success")

    def test_daily_exception_is_terminal_failure_with_detail(self):
        text = (
            "TaskExecutor:📅 Daily Task exception stopped Traceback\n"
            "ERROR [ok-ww]: ok.task.exceptions.WaitFailedException\n"
        )
        event = classify_log_update(text)
        self.assertEqual(event["state"], "failure")
        self.assertIn("WaitFailedException", event["summary"])

    def test_game_hot_update_is_expected_restart_not_failure(self):
        event = classify_log_update(
            "2026-08-23 19:16:24 INFO DailyTask:游戏更新成功, 游戏即将重启"
        )
        self.assertEqual(event["state"], "restart_required")
        self.assertIn("重启", event["summary"])

    def test_rotated_stale_success_is_filtered_by_attempt_time(self):
        text = (
            "2026-08-21 00:01:02,304 INFO TaskExecutor "
            "Successfully Executed Task, Exiting Game and App!\n"
            "2026-08-21 19:24:03,436 ERROR TaskExecutor "
            "TaskExecutor:📅 Daily Task exception stopped Traceback\n"
        )
        not_before = datetime.fromisoformat("2026-08-21 19:00:00").timestamp()
        event = classify_log_update(text, not_before=not_before)
        self.assertEqual(event["state"], "failure")

    def test_internal_ok_script_log_pattern_is_supported(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "ok-script.log"
            path.write_text("old", encoding="utf-8")
            offsets = snapshot_log_offsets(temp, ("ok-script*.log",))
            with path.open("a", encoding="utf-8") as handle:
                handle.write("\nSuccessfully Executed Task, Exiting Game and App!")
            event = classify_log_update(
                read_appended_logs(temp, offsets, ("ok-script*.log",))
            )
            self.assertEqual(event["state"], "success")

    def test_new_rotated_log_is_read_from_start(self):
        with tempfile.TemporaryDirectory() as temp:
            old = Path(temp) / "app.2026-08-21"
            old.write_text("old", encoding="utf-8")
            offsets = snapshot_log_offsets(temp)
            new = Path(temp) / "app.2026-08-22"
            new.write_text(
                "Successfully Executed Task, Exiting Game and App!",
                encoding="utf-8",
            )
            event = classify_log_update(read_appended_logs(temp, offsets))
            self.assertEqual(event["state"], "success")

    def test_truncated_log_resets_cursor_safely(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "app.2026-08-21"
            path.write_text("x" * 200, encoding="utf-8")
            offsets = snapshot_log_offsets(temp)
            path.write_text(
                "TaskExecutor:Daily Task exception stopped\n",
                encoding="utf-8",
            )
            event = classify_log_update(read_appended_logs(temp, offsets))
            self.assertEqual(event["state"], "failure")


class OKWWNodePolicyTests(unittest.TestCase):
    def test_logged_worker_pid_is_bound_to_creation_identity(self):
        settings = {
            "okww_executable": "ok-ww.exe",
            "okww_main_script": "main.py",
            "okww_worker_executable": "bundled-pythonw.exe",
            "game_process_name": "game.exe",
        }
        worker = {
            "pid": 14668,
            "name": "pythonw.exe",
            "executable_path": "",
            "command_line": "",
            "creation_date": "20260823191526.000000+480",
        }
        with mock.patch.object(okww, "windows_process_inventory", return_value=[worker]):
            selected = okww._relevant_processes(settings, {}, {14668})
            same = okww._relevant_processes(
                settings, {"14668": worker["creation_date"]}
            )
        self.assertEqual(selected[0]["role"], "okww_worker_log_pid")
        self.assertEqual(same[0]["role"], "okww_worker_log_pid")

        recycled = {**worker, "creation_date": "20260823201526.000000+480"}
        with mock.patch.object(okww, "windows_process_inventory", return_value=[recycled]):
            self.assertEqual(
                okww._relevant_processes(
                    settings, {"14668": worker["creation_date"]}
                ),
                [],
            )

    def test_preflight_refuses_to_take_over_existing_session(self):
        existing = [{"pid": 7, "role": "game", "creation_date": "A"}]
        with mock.patch.object(okww, "_relevant_processes", return_value=existing), mock.patch.object(
            okww, "snapshot_log_offsets", return_value={}
        ):
            result = okww.initialise_okww_monitor({}, {"__global_context__": {}})
        self.assertEqual(result["active_port"], "环境占用")
        self.assertEqual(result["value"]["state"], "environment_busy")

    def _monitor_state(self, attempt=1, max_attempts=3):
        now = time.monotonic()
        return {
            "attempt": attempt,
            "max_attempts": max_attempts,
            "attempt_started": now,
            "attempt_wall_started": time.time(),
            "workflow_started": now,
            "log_offsets": {},
            "saw_okww_process": True,
            "missing_since": None,
            "observed_worker_identities": {},
            "update_restart_count": 0,
            "max_update_restarts": 3,
            "settings": {
                "log_directory": "logs",
                "internal_log_directory": "internal-logs",
                "okww_executable": "ok-ww.exe",
                "okww_main_script": "main.py",
                "okww_worker_executable": "pythonw.exe",
                "game_process_name": "game.exe",
            },
        }

    def test_red_cross_exception_routes_to_retry(self):
        state = self._monitor_state(attempt=1, max_attempts=3)
        with mock.patch.object(
            okww,
            "read_appended_logs",
            return_value="TaskExecutor:Daily Task exception stopped",
        ), mock.patch.object(okww, "_relevant_processes", return_value=[]):
            result = okww.monitor_okww_task(
                {}, {"__global_context__": {okww.STATE_KEY: state}}
            )
        self.assertEqual(result["active_port"], "失败可重试")

    def test_hot_update_routes_to_restart_without_consuming_attempt(self):
        state = self._monitor_state(attempt=1, max_attempts=3)
        with mock.patch.object(
            okww,
            "read_appended_logs",
            side_effect=["游戏更新成功, 游戏即将重启", ""],
        ), mock.patch.object(okww, "_relevant_processes", return_value=[]):
            result = okww.monitor_okww_task(
                {}, {"__global_context__": {okww.STATE_KEY: state}}
            )
        self.assertEqual(result["active_port"], "更新后重启")
        self.assertEqual(result["value"]["attempt"], 1)
        self.assertTrue(state["preserve_attempt_number"])

    def test_expected_restart_reinitialises_same_attempt_number(self):
        context = {
            okww.STATE_KEY: {
                "attempt": 1,
                "workflow_started": time.monotonic(),
                "baseline_identities": [],
                "update_restart_count": 1,
                "preserve_attempt_number": True,
            }
        }
        with mock.patch.object(okww, "_relevant_processes", return_value=[]), mock.patch.object(
            okww, "snapshot_log_offsets", return_value={}
        ):
            result = okww.initialise_okww_monitor(
                {}, {"__global_context__": context}
            )
        self.assertEqual(result["value"]["attempt"], 1)
        self.assertEqual(context[okww.STATE_KEY]["update_restart_count"], 1)

    def test_last_red_cross_exception_routes_to_final_failure(self):
        state = self._monitor_state(attempt=3, max_attempts=3)
        with mock.patch.object(
            okww,
            "read_appended_logs",
            return_value="TaskExecutor:Daily Task exception stopped",
        ), mock.patch.object(okww, "_relevant_processes", return_value=[]):
            result = okww.monitor_okww_task(
                {}, {"__global_context__": {okww.STATE_KEY: state}}
            )
        self.assertEqual(result["active_port"], "最终失败")

    def test_success_marker_split_across_polls_is_not_lost(self):
        state = self._monitor_state(attempt=1, max_attempts=3)
        stamp = datetime.now().isoformat(sep=' ', timespec='milliseconds')
        state['attempt_wall_started'] -= 1
        state["log_tail"] = f"{stamp} INFO DailyTask:Daily Task Completed\n{stamp} INFO Successfully Executed Task, Exit"
        with mock.patch.object(
            okww,
            "read_appended_logs",
            return_value="ing Game and App!",
        ), mock.patch.object(okww, "_relevant_processes", return_value=[]):
            result = okww.monitor_okww_task(
                {}, {"__global_context__": {okww.STATE_KEY: state}}
            )
        self.assertEqual(result["active_port"], "成功")

    def test_exit_without_success_marker_is_failure(self):
        state = self._monitor_state(attempt=1, max_attempts=2)
        state["missing_since"] = time.monotonic() - 30
        with mock.patch.object(okww, "read_appended_logs", return_value=""), mock.patch.object(
            okww, "_relevant_processes", return_value=[]
        ):
            result = okww.monitor_okww_task(
                {"退出日志宽限(s)": "0"},
                {"__global_context__": {okww.STATE_KEY: state}},
            )
        self.assertEqual(result["active_port"], "失败可重试")
        self.assertIn("没有官方成功日志", result["value"]["summary"])

    def test_cleanup_targets_only_owned_exact_pid_and_verifies(self):
        owned = [{"pid": 88, "creation_date": "NEW", "role": "okww_worker"}]
        state = self._monitor_state()
        state["baseline_identities"] = []
        with mock.patch.object(okww, "_relevant_processes", return_value=owned), mock.patch.object(
            okww, "terminate_process_tree", return_value=True
        ) as terminate, mock.patch.object(
            okww, "wait_until_no_owned_processes", return_value=[]
        ):
            result = okww.cleanup_okww_session(
                {},
                {
                    "__global_context__": {okww.STATE_KEY: state},
                    "__value__": {"state": "success", "summary": "done"},
                },
            )
        terminate.assert_called_once_with(88)
        self.assertEqual(result["active_port"], "已清理")
        self.assertEqual(result["value"]["cleanup"], "verified")


class _Response:
    def __init__(self, status=200, payload=None):
        self.status = status
        self.payload = payload if payload is not None else {"code": 200}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class ReliableBarkTests(unittest.TestCase):
    def test_retries_until_server_confirms_api_success(self):
        calls = []

        def opener(request, **kwargs):
            calls.append(request)
            if len(calls) < 3:
                raise urllib.error.URLError("offline")
            return _Response()

        result = execute_reliable_bark_push(
            "https://api.day.app/test-key",
            "title",
            "body",
            attempts=3,
            retry_delay=0,
            opener=opener,
            sleeper=lambda _: None,
        )
        self.assertTrue(result["delivered"])
        self.assertEqual(len(calls), 3)

    def test_failed_message_is_queued_then_flushed_on_next_send(self):
        def offline(request, **kwargs):
            raise urllib.error.URLError("offline")

        with tempfile.TemporaryDirectory() as temp:
            first = execute_reliable_bark_push(
                "https://api.day.app/test-key",
                "first",
                "body",
                attempts=2,
                retry_delay=0,
                outbox_directory=temp,
                opener=offline,
                sleeper=lambda _: None,
            )
            self.assertTrue(first["queued"])
            self.assertEqual(len(list(Path(temp).glob("*.json"))), 1)

            calls = []

            def online(request, **kwargs):
                calls.append(request)
                return _Response()

            second = execute_reliable_bark_push(
                "https://api.day.app/test-key",
                "second",
                "body",
                attempts=1,
                outbox_directory=temp,
                opener=online,
                sleeper=lambda _: None,
            )
            self.assertTrue(second["delivered"])
            self.assertEqual(len(calls), 2)  # queued first, then current
            self.assertEqual(list(Path(temp).glob("*.json")), [])

    def test_http_200_with_bark_error_code_is_not_delivery(self):
        result = execute_reliable_bark_push(
            "https://api.day.app/test-key",
            "title",
            "body",
            attempts=1,
            opener=lambda request, **kwargs: _Response(payload={"code": 400}),
            sleeper=lambda _: None,
        )
        self.assertFalse(result["delivered"])

    def test_http_200_without_bark_confirmation_is_not_delivery(self):
        class EmptyResponse(_Response):
            def read(self):
                return b""

        result = execute_reliable_bark_push(
            "https://api.day.app/test-key",
            "title",
            "body",
            attempts=1,
            opener=lambda request, **kwargs: EmptyResponse(),
            sleeper=lambda _: None,
        )
        self.assertFalse(result["delivered"])


class DailyWorkflowPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "daily.json"
        cls.workflow = json.loads(path.read_text(encoding="utf-8"))

    def test_every_node_type_and_edge_is_valid(self):
        nodes = self.workflow["nodes"]
        ids = {item["id"] for item in nodes}
        self.assertEqual(len(ids), len(nodes))
        for item in nodes:
            self.assertIn(item["type"], NODE_REGISTRY)
        for edge in self.workflow["edges"]:
            self.assertIn(edge["src_id"], ids)
            self.assertIn(edge["tgt_id"], ids)
            source = next(item for item in nodes if item["id"] == edge["src_id"])
            self.assertIn(
                edge["src_port"], source["signal_config"]["outputs"]
            )

    def test_graph_has_one_start_and_only_intentional_feedback_edges(self):
        shadow = nx.MultiDiGraph()
        shadow.add_nodes_from(item["id"] for item in self.workflow["nodes"])
        feedback = []
        forward = []
        for edge in self.workflow["edges"]:
            key = shadow.add_edge(edge["src_id"], edge["tgt_id"])
            try:
                nx.find_cycle(shadow, orientation="original")
            except nx.NetworkXNoCycle:
                forward.append(edge)
            else:
                feedback.append(edge)
                shadow.remove_edge(edge["src_id"], edge["tgt_id"], key)

        starts = [node for node in shadow.nodes if shadow.in_degree(node) == 0]
        self.assertEqual(len(starts), 1)
        start_type = next(
            item["type"] for item in self.workflow["nodes"] if item["id"] == starts[0]
        )
        self.assertEqual(start_type, "OK-WW监控初始化")
        self.assertEqual(
            {
                (item["src_id"], item["src_port"], item["tgt_id"])
                for item in feedback
            },
            {
                (
                    next(
                        item["id"]
                        for item in self.workflow["nodes"]
                        if item["type"] == "信号分流器"
                    ),
                    "未找到",
                    next(
                        item["id"]
                        for item in self.workflow["nodes"]
                        if item["type"] == "OK-WW任务监控"
                    ),
                ),
                (
                    next(
                        item["id"]
                        for item in self.workflow["nodes"]
                        if item["type"] == "OK-WW任务监控"
                    ),
                    "运行中",
                    next(
                        item["id"]
                        for item in self.workflow["nodes"]
                        if item["type"] == "OK-WW任务监控"
                    ),
                ),
                (
                    next(item["id"] for item in self.workflow["nodes"] if item["name"] == "重试冷却 60 秒"),
                    "OUT",
                    starts[0],
                ),
                (
                    next(item["id"] for item in self.workflow["nodes"] if item["name"] == "更新后冷却 105 秒"),
                    "OUT",
                    starts[0],
                ),
            },
        )

    def test_monitor_starts_immediately_and_periodic_visual_check_is_preserved(self):
        nodes = {item["id"]: item for item in self.workflow["nodes"]}
        edges = {(e["src_id"], e["src_port"], e["tgt_id"]) for e in self.workflow["edges"]}
        start = next(item for item in nodes.values() if item["type"] == "启动程序")
        monitor = next(item for item in nodes.values() if item["type"] == "OK-WW任务监控")
        vision = next(item for item in nodes.values() if item["type"] == "视觉寻图")
        self.assertIn((start["id"], "OUT", monitor["id"]), edges)
        self.assertIn((monitor["id"], "检查更新界面", vision["id"]), edges)
        self.assertNotIn("等待游戏与更新界面", {item["name"] for item in nodes.values()})

    def test_all_custom_unattended_nodes_are_in_okww_category(self):
        custom_types = {"OK-WW监控初始化", "OK-WW任务监控", "OK-WW安全清理", "可靠Bark通知"}
        for node_type in custom_types:
            self.assertEqual(NODE_REGISTRY[node_type]["category"], "OK-WW")
        for item in self.workflow["nodes"]:
            if item["type"] in custom_types:
                self.assertEqual(item["category"], "OK-WW")

    def test_old_window_guessing_and_unverified_cleanup_are_gone(self):
        node_types = {item["type"] for item in self.workflow["nodes"]}
        self.assertNotIn("状态检测", node_types)
        self.assertNotIn("脉冲计时器", node_types)
        self.assertNotIn("结束进程", node_types)
        self.assertNotIn("Bark通知", node_types)
        self.assertIn("OK-WW任务监控", node_types)
        self.assertIn("OK-WW安全清理", node_types)
        self.assertIn("可靠Bark通知", node_types)

    def test_unsafe_or_unknown_cleanup_paths_never_hibernate(self):
        nodes = {item["name"]: item for item in self.workflow["nodes"]}
        guarded_exits = [
            "已有进程：保留终端",
            "更新清理失败：保留终端",
            "更新重启清理失败：保留终端",
            "成功清理失败：保留终端",
            "重试清理失败：保留终端",
            "最终清理失败：保留终端",
        ]
        for name in guarded_exits:
            self.assertEqual(
                nodes[name]["config"]["执行动作"], "保留终端(不休眠)"
            )

    def test_fault_injected_workflow_routes_reach_the_safe_terminal(self):
        node_map = {item["id"]: item for item in self.workflow["nodes"]}
        edges = [
            (
                edge["src_id"],
                edge["src_port"],
                edge["tgt_id"],
                edge["tgt_port"],
            )
            for edge in self.workflow["edges"]
        ]
        scenarios = {
            "success": "成功分支：休眠",
            "update": "更新分支：保留终端",
            "environment_busy": "已有进程：保留终端",
            "retry_then_success": "成功分支：休眠",
            "three_failures": "最终失败：保留终端",
            "success_cleanup_failure": "成功清理失败：保留终端",
            "retry_cleanup_failure": "重试清理失败：保留终端",
            "final_cleanup_failure": "最终清理失败：保留终端",
            "update_cleanup_failure": "更新清理失败：保留终端",
            "update_restart_then_success": "成功分支：休眠",
            "update_restart_cleanup_failure": "更新重启清理失败：保留终端",
        }

        class ImmediatePool:
            @staticmethod
            def start(worker):
                worker.run()

        original_funcs = {
            node_type: NODE_REGISTRY[node_type]["func"]
            for node_type in {item["type"] for item in node_map.values()}
        }
        try:
            for scenario, expected_terminal in scenarios.items():
                state = {"attempt": 0, "monitor_calls": 0, "executed": []}

                def fake_node(config, inputs, scenario=scenario, state=state):
                    item = node_map[inputs["__node_id__"]]
                    state["executed"].append(item["name"])
                    node_type = item["type"]
                    name = item["name"]
                    value = inputs.get("__value__")
                    if not isinstance(value, dict):
                        value = {}

                    if node_type == "系统休眠":
                        return original_funcs[node_type](config, inputs)

                    if node_type == "OK-WW监控初始化":
                        if state.pop("preserve_attempt", False):
                            pass
                        else:
                            state["attempt"] += 1
                        if scenario == "environment_busy":
                            return {
                                "status": "Success",
                                "active_port": "环境占用",
                                "value": {"state": "environment_busy"},
                            }
                        return {
                            "status": "Success",
                            "active_port": "允许启动",
                            "value": {"attempt": state["attempt"]},
                        }
                    if node_type == "视觉寻图":
                        return {
                            "status": "Success",
                            "value": {"found": scenario.startswith("update")},
                        }
                    if node_type == "信号分流器":
                        found = bool(inputs.get("found"))
                        return {
                            "status": "Success",
                            "active_port": "找到目标" if found else "未找到",
                            "value": {"found": found},
                        }
                    if node_type == "OK-WW任务监控":
                        state["monitor_calls"] += 1
                        if scenario in {"update", "update_cleanup_failure"} and state["monitor_calls"] == 1:
                            port = "检查更新界面"
                        elif scenario in {"update_restart_then_success", "update_restart_cleanup_failure"} and state["monitor_calls"] == 1:
                            state["preserve_attempt"] = True
                            port = "更新后重启"
                        elif scenario == "success" and state["monitor_calls"] == 1:
                            port = "运行中"
                        elif scenario in {
                            "retry_then_success",
                            "retry_cleanup_failure",
                        } and state["attempt"] == 1:
                            port = "失败可重试"
                        elif scenario in {
                            "three_failures",
                            "final_cleanup_failure",
                        }:
                            port = (
                                "失败可重试"
                                if state["attempt"] < 3
                                else "最终失败"
                            )
                        else:
                            port = "成功"
                        if port == '成功':
                            inputs['__global_context__'][okww.STATE_KEY] = {'terminal_state': 'success', 'cleanup_verified': False, 'settings': {}}
                        return {
                            "status": "Success",
                            "active_port": port,
                            "value": {"attempt": state["attempt"], "state": port},
                        }
                    if node_type == "OK-WW安全清理":
                        fail = (
                            (scenario == "success_cleanup_failure" and "成功分支" in name)
                            or (scenario == "retry_cleanup_failure" and "重试前" in name)
                            or (scenario == "final_cleanup_failure" and "最终失败" in name)
                            or (scenario == "update_cleanup_failure" and "更新分支" in name)
                            or (scenario == "update_restart_cleanup_failure" and "更新重启前" in name)
                        )
                        proof = inputs['__global_context__'].get(okww.STATE_KEY)
                        if proof is not None:
                            proof['cleanup_verified'] = not fail
                            inputs['__global_context__'][okww.STATE_KEY] = proof
                        return {
                            "status": "Success",
                            "active_port": "清理失败" if fail else "已清理",
                            "value": {**value, "cleanup": "failed" if fail else "verified"},
                        }
                    return {"status": "Success", "value": value or True}

                for node_type in original_funcs:
                    NODE_REGISTRY[node_type]["func"] = fake_node

                try:
                    bus.node_status_changed.disconnect()
                except TypeError:
                    pass
                engine = DAGEngine()
                engine.thread_pool = ImmediatePool()
                nodes_info = {
                    item_id: {
                        "name": item["type"],
                        "config": item["config"],
                        "signal_config": item["signal_config"],
                        "is_disabled": False,
                    }
                    for item_id, item in node_map.items()
                }
                engine.load_from_ui(nodes_info, edges)
                engine.authorize_execution(engine.review_execution().required)
                with mock.patch.object(
                    system_nodes, "execute_delayed_hibernate", return_value=True
                ) as hibernate, mock.patch.object(
                    system_nodes, "execute_self_destruct"
                ) as exit_terminal, mock.patch.object(
                    system_nodes, "execute_sleep", return_value=True
                ), mock.patch.object(
                    okww, '_relevant_processes', return_value=[]
                ):
                    self.assertTrue(engine.start_execution(), scenario)
                if "保留终端" in expected_terminal:
                    hibernate.assert_not_called()
                    exit_terminal.assert_not_called()
                else:
                    hibernate.assert_called_once_with(0)
                    exit_terminal.assert_called_once_with()
                self.assertFalse(engine.execution_failed, scenario)
                self.assertEqual(engine.active_nodes, set(), scenario)
                self.assertIn(expected_terminal, state["executed"], scenario)
                terminal_names = {
                    name for name in state["executed"] if "休眠" in name or "保留终端" in name
                }
                self.assertEqual(terminal_names, {expected_terminal}, scenario)
                try:
                    bus.node_status_changed.disconnect(engine._on_node_status_changed)
                except TypeError:
                    pass
        finally:
            for node_type, function in original_funcs.items():
                NODE_REGISTRY[node_type]["func"] = function


if __name__ == "__main__":
    unittest.main()
